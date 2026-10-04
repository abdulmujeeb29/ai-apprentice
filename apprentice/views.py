import json
import logging
import re
import threading
import time

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import elevenlabs as el
from . import prompts
from .llm import LLMError, call_json
from .models import Decision, Event, Session, Utterance, WorkMap
from .policy import Candidate, Moment, decide, phase_gap

logger = logging.getLogger("apprentice")

# ---------------------------------------------------------------- helpers

_SECRET_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b(sk|pk|rk|xi|ghp|gho|AKIA)[_-]?[A-Za-z0-9]{12,}\b"), "[key]"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}\b"), "[secret]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[number]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    (re.compile(r"\b(postgres|mysql|redis|mongodb)(\+\w+)?://\S+"), "[database url]"),
]


_PROTOCOL = re.compile(r"^\s*\[(ASK|DEBRIEF|OFF|ON|OPEN|SCREEN|COACH|GUARDRAIL|CHECK)\]")
_AUDIO_TAG = re.compile(r"\[[a-z][a-z' -]{0,30}\]\s*", re.I)


def clean_message(text: str) -> str:
    """Drop app protocol echoes; strip Eleven v3 expressive tags like [curious]."""
    if not text or _PROTOCOL.match(text):
        return ""
    return re.sub(r"\s{2,}", " ", _AUDIO_TAG.sub("", text)).strip()


def scrub(text: str) -> str:
    """Remove personal data and secrets before anything is stored."""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _transcript(session: Session, limit: int = 200) -> str:
    rows = list(session.utterances.all())[-limit:]
    who = {"user": "Expert" if session.kind == Session.CAPTURE else "New hire", "agent": "Agent"}
    return "\n".join(f"{who.get(u.role, u.role)}: {u.text}" for u in rows) or "(no conversation)"


def _events(session: Session, limit: int = 120) -> str:
    rows = list(session.events.all())[-limit:]
    t0 = rows[0].at if rows else 0
    return "\n".join(f"[{int(e.at - t0):>4}s] ({e.phase}) {e.text}" for e in rows) or "(no screen events)"


def _phase_view(session: Session) -> list[dict]:
    """The learning rail: each phase with its four checklist scores."""
    out = []
    for pid, name in prompts.PHASES:
        scores = session.coverage.get(pid, {})
        out.append({"id": pid, "name": name, "scores": {k: round(float(scores.get(k, 0)), 2)
                                                         for k in ("what", "why", "vs_manual", "risk")}})
    return out


# ------------------------------------------------- background assessor (off the critical path)

_assess_lock = threading.Lock()
_assess_inflight: set = set()
_assess_dirty: set = set()


def _assess(session_id):
    try:
        while True:
            with _assess_lock:
                _assess_dirty.discard(session_id)
            session = Session.objects.get(pk=session_id)
            user = (f"Screen events:\n{_events(session)}\n\nConversation:\n{_transcript(session)}\n\n"
                    f"Previous coverage (only raise scores the evidence supports):\n{json.dumps(session.coverage)}")
            out = call_json(prompts.COVERAGE_SYSTEM, user, effort="low", timeout=45)
            cov = out.get("coverage") or {}
            merged = dict(session.coverage)
            for pid, scores in cov.items():
                if pid not in prompts.PHASE_IDS or not isinstance(scores, dict):
                    continue
                prev = merged.get(pid, {})
                merged[pid] = {k: max(float(prev.get(k, 0)), min(max(float(scores.get(k, 0) or 0), 0), 1))
                               for k in ("what", "why", "vs_manual", "risk")}
            Session.objects.filter(pk=session_id).update(coverage=merged)
            with _assess_lock:
                if session_id not in _assess_dirty:
                    _assess_inflight.discard(session_id)
                    return
    except Exception as e:  # noqa: BLE001 - keep previous scores, never break the session
        logger.warning("assessor failed for %s: %s", session_id, e)
        with _assess_lock:
            _assess_inflight.discard(session_id)


def refresh_coverage(session_id):
    """Single-flight refresh; if more evidence arrives mid-run, run once more after."""
    with _assess_lock:
        _assess_dirty.add(session_id)
        if session_id in _assess_inflight:
            return
        _assess_inflight.add(session_id)
    threading.Thread(target=_assess, args=(session_id,), daemon=True).start()


# ---------------------------------------------------------------- map rendering

def map_to_text(data: dict) -> str:
    """Compact plain-text Work Map for the tutor's prompt."""
    lines = [f"Task: {data.get('title', '')}", f"Goal: {data.get('goal', '')}", data.get("summary", ""), ""]
    for p in data.get("phases", []):
        lines.append(f"## {p.get('name')} ({p.get('id')})")
        for s in p.get("steps", []):
            lines.append(f"- Do: {s.get('action')} | Why: {s.get('why')}")
        if p.get("platform_does"):
            lines.append(f"- Thales Ops does: {p['platform_does']} | By hand: {p.get('manual_equivalent', '')}")
        for c in p.get("concepts", []):
            lines.append(f"- Concept {c.get('name')}: {c.get('plain')}")
        for r in p.get("decision_rules", []):
            lines.append(f"- Rule: {r}")
        for x in p.get("exceptions", []):
            lines.append(f"- Exception: {x}")
        for g in p.get("guardrails", []):
            lines.append(f"- GUARDRAIL ({g.get('severity')}): {g.get('rule')} because {g.get('why')}")
        lines.append("")
    for g in data.get("global_guardrails", []):
        lines.append(f"GUARDRAIL ({g.get('severity')}): {g.get('rule')} because {g.get('why')}")
    return "\n".join(lines)


def all_guardrails(data: dict) -> list[dict]:
    out = list(data.get("global_guardrails", []))
    for p in data.get("phases", []):
        out.extend(p.get("guardrails", []))
    return out


def map_to_agent_md(wm: WorkMap) -> str:
    d = wm.data
    lines = [f"# Agent procedure: {d.get('title', wm.title)}", "",
             f"Goal: {d.get('goal', '')}", "",
             "Follow these steps in order. Before every step, check its guardrails. "
             "If a STOP guardrail would be broken, do not continue: stop and ask a human.", ""]
    for i, p in enumerate(d.get("phases", []), 1):
        lines.append(f"## {i}. {p.get('name')}")
        for s in p.get("steps", []):
            lines.append(f"- {s.get('action')}  _(why: {s.get('why')})_")
        for r in p.get("decision_rules", []):
            lines.append(f"- Decision rule: {r}")
        for x in p.get("exceptions", []):
            lines.append(f"- Exception: {x}")
        for g in p.get("guardrails", []):
            tag = "STOP" if g.get("severity") == "stop" else "WARN"
            lines.append(f"- **{tag}:** {g.get('rule')} ({g.get('why')})")
        lines.append("")
    if d.get("global_guardrails"):
        lines.append("## Always")
        for g in d["global_guardrails"]:
            tag = "STOP" if g.get("severity") == "stop" else "WARN"
            lines.append(f"- **{tag}:** {g.get('rule')} ({g.get('why')})")
    lines += ["", "## Escalate to a human when",
              "- a STOP guardrail would be broken",
              "- the situation matches none of the steps or exceptions above"]
    for q in d.get("open_questions", []):
        lines.append(f"- unresolved: {q}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- pages

def healthz(request):
    return JsonResponse({"ok": True})


def home(request):
    maps = WorkMap.objects.order_by("-created")[:12]
    sessions = Session.objects.filter(kind=Session.CAPTURE).order_by("-created")[:6]
    return render(request, "apprentice/home.html", {"maps": maps, "sessions": sessions})


@require_POST
@csrf_exempt
def capture_new(request):
    s = Session.objects.create(kind=Session.CAPTURE)
    return redirect("capture", session_id=s.id)


def capture(request, session_id):
    s = get_object_or_404(Session, pk=session_id, kind=Session.CAPTURE)
    return render(request, "apprentice/capture.html", {
        "session": s, "phases": prompts.PHASES,
        "boot": {"session": str(s.id), "kind": "capture", "role": "interviewer",
                 "phases": _phase_view(s)},
    })


def map_view(request, map_id):
    wm = get_object_or_404(WorkMap, pk=map_id)
    src = getattr(wm, "source_session", None)
    return render(request, "apprentice/map.html", {
        "wm": wm, "data": wm.data,
        "stats": {
            "events": src.events.count() if src else 0,
            "questions": src.questions_asked if src else 0,
            "phases": len(wm.data.get("phases", [])),
            "guardrails": len(all_guardrails(wm.data)),
        },
    })


def map_json(request, map_id):
    wm = get_object_or_404(WorkMap, pk=map_id)
    resp = JsonResponse(wm.data, json_dumps_params={"indent": 2})
    resp["Content-Disposition"] = f'attachment; filename="work-map-{wm.id}.json"'
    return resp


def map_agent(request, map_id):
    wm = get_object_or_404(WorkMap, pk=map_id)
    return HttpResponse(map_to_agent_md(wm), content_type="text/markdown; charset=utf-8")


def teach(request, map_id):
    wm = get_object_or_404(WorkMap, pk=map_id)
    s = Session.objects.create(kind=Session.TEACH, work_map=wm, title=f"Teach: {wm.title}")
    check = wm.data.get("check_scenario") or {}
    return render(request, "apprentice/teach.html", {
        "session": s, "wm": wm, "phases": prompts.PHASES,
        "boot": {
            "session": str(s.id), "kind": "teach", "role": "tutor",
            "dynamicVariables": {
                "work_map": map_to_text(wm.data),
                "check_scenario": f"{check.get('situation', '')} Expected: {check.get('expected', '')}",
            },
            "mapPhases": [p.get("id") for p in wm.data.get("phases", [])],
        },
    })


# ---------------------------------------------------------------- API

@require_GET
def signed_url(request, role):
    agent_id = {"interviewer": settings.INTERVIEWER_AGENT_ID, "tutor": settings.TUTOR_AGENT_ID}.get(role)
    if not agent_id:
        raise Http404
    try:
        return JsonResponse({"signed_url": el.signed_url(agent_id)})
    except el.ElevenLabsError as e:
        logger.error("signed url: %s", e)
        return JsonResponse({"error": "Could not reach ElevenLabs. Check the API key and try again."}, status=502)


def _moment(session: Session, state: dict, activity: str, phase_changed: bool) -> Moment:
    return Moment(
        now=time.time(),
        activity=activity,
        silence_s=float(state.get("silence_s", 0) or 0),
        agent_speaking=bool(state.get("agent_speaking")),
        phase_changed=phase_changed,
        questions_asked=session.questions_asked,
        last_question_at=session.last_question_at,
    )


def _opening(session: Session, state: dict, flags: dict) -> str | None:
    """First thing the agent says once it can see the screen. Returns the nudge once."""
    if flags.get("opened") or not session.screen or state.get("agent_speaking"):
        return None
    if float(state.get("silence_s", 0) or 0) < 1.5:
        return None
    flags["opened"] = True
    if session.kind == Session.CAPTURE:
        return (f"[OPEN] You can now see the expert's screen: {session.screen} "
                "React naturally in one short sentence to what you see, then ask them for the one-line idea of "
                "what this platform does for them before they start. Do not describe the screen in detail.")
    wm = session.work_map.data if session.work_map else {}
    return (f"[OPEN] You can now see the new hire's screen: {session.screen} "
            f"Orient them in two short sentences: where they are, what Thales Ops is for "
            f"({wm.get('goal', 'deploying apps')}), and the first thing to do. Then let them drive.")


def _capture_decision(session: Session, state: dict, activity: str, phase_changed: bool) -> dict:
    """Run the policy for a capture session; returns {decision, nudge}."""
    if state.get("off"):
        return {"decision": {"action": "wait", "reason": "off_the_record"}, "nudge": None}
    flags = dict(session.debrief)
    opening = _opening(session, state, flags)
    if opening:
        Session.objects.filter(pk=session.pk).update(debrief=flags)
        session.debrief = flags
        return {"decision": {"action": "ask", "reason": "opening"}, "nudge": opening}
    recent = session.events.filter(asked=False, judgment__gte=0.4, at__gte=time.time() - 300).order_by("-at")[:8]
    cands = [Candidate(e.id, e.text, e.phase, e.judgment, e.at) for e in recent]
    m = _moment(session, state, activity, phase_changed)
    d = decide(m, cands, session.coverage)
    Decision.objects.create(session=session, at=m.now, action=d.action, reason=d.reason,
                            data={"utility": round(d.utility, 3), **d.terms, "event_id": d.event_id})
    nudge = None
    if d.action in ("ask", "save") and d.event_id:
        ev = Event.objects.get(pk=d.event_id)
        Event.objects.filter(pk=ev.pk).update(asked=True)
        if d.action == "ask":
            _, missing = phase_gap(session.coverage, ev.phase)
            # Focus on the single most valuable gap; "what" is usually visible on screen already.
            focus = next((k for k in ("why", "vs_manual", "risk", "what") if k in missing), "why")
            missing_txt = {"what": "what they did here", "why": "why they did it this way",
                           "vs_manual": "what Thales Ops did here that would be manual work without it",
                           "risk": "what can go wrong here, or what they would never do"}[focus]
            moment = {"waiting": "while the build runs", "idle": "they paused",
                      "reading": "they are reading"}.get(activity, "they paused")
            nudge = (f"[ASK] Natural moment ({moment}). Phase: {prompts.PHASE_NAMES.get(ev.phase, ev.phase)}. "
                     f"Worth asking about: \"{ev.text}\". Learn {missing_txt}. "
                     f"Ask ONE short natural question.")
            Session.objects.filter(pk=session.pk).update(
                questions_asked=session.questions_asked + 1, last_question_at=time.time())
    return {"decision": {"action": d.action, "reason": d.reason, "utility": round(d.utility, 2), "terms": d.terms},
            "nudge": nudge}


def _covered(text) -> str:
    text = str(text or "").strip()
    return "" if not text or text.lower().startswith("not covered") else text


def _teach_decision(session: Session, state: dict, violation: dict | None) -> dict:
    nudge, kind, alert = None, None, None
    flags = dict(session.result)
    opening = _opening(session, state, flags) if not violation else None
    if opening:
        session.result = flags
        session.save(update_fields=["result"])
        return {"nudge": opening, "nudge_kind": "coach", "alert": None}
    if violation and violation.get("guardrail"):
        recent = session.result.get("flagged", {})
        key = violation["guardrail"][:80]
        if time.time() - recent.get(key, 0) > 60:
            recent[key] = time.time()
            session.result = {**session.result, "flagged": recent,
                              "violations": session.result.get("violations", []) + [violation]}
            session.save(update_fields=["result"])
            what = str(violation.get("what_happened", "")).rstrip(". ")
            rule = str(violation["guardrail"]).rstrip(". ")
            nudge, kind = (f"[GUARDRAIL] On screen: {what}. Expert's rule: {rule}. Stop them now, kindly."), "guardrail"
            alert = rule
    if not nudge and not state.get("agent_speaking") and float(state.get("silence_s", 0) or 0) > 2.5:
        phase = session.phase
        mp = {p.get("id"): p for p in (session.work_map.data.get("phases", []) if session.work_map else [])}
        if phase in mp and phase not in session.coached_phases:
            p = mp[phase]
            session.coached_phases = session.coached_phases + [phase]
            session.save(update_fields=["coached_phases"])
            concept = (p.get("concepts") or [{}])[0]
            parts = [f"[COACH] The new hire is now at: {p.get('name')}."]
            if concept.get("plain"):
                parts.append(f"Key idea: {concept['plain']}")
            if _covered(p.get("platform_does")):
                parts.append(f"Thales Ops does: {p['platform_does']}")
            if _covered(p.get("manual_equivalent")):
                parts.append(f"By hand: {p['manual_equivalent']}")
            nudge, kind = " ".join(parts), "coach"
    return {"nudge": nudge, "nudge_kind": kind, "alert": alert}


@csrf_exempt
@require_POST
def frame(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    body = _body(request)
    state = body.get("state") or {}
    image = body.get("image") or ""
    if state.get("off"):
        return JsonResponse({"skipped": "off_the_record"})
    if not image.startswith("data:image/"):
        return JsonResponse({"error": "image must be a data URL"}, status=400)

    system = prompts.VISION_SYSTEM
    if session.kind == Session.TEACH and session.work_map:
        wmd = session.work_map.data
        rules = "\n".join(f"- {g.get('rule')} (why: {g.get('why', '')})" for g in all_guardrails(wmd)) or "- (none)"
        exceptions = "\n".join(f"- {x}" for p in wmd.get("phases", []) for x in p.get("exceptions", [])) or "- (none)"
        system += prompts.VISION_TEACH_ADDENDUM.format(guardrails=rules, exceptions=exceptions)
    recent = "\n".join(f"- {e.text}" for e in list(session.events.order_by("-at")[:6])[::-1]) or "(none)"
    user = (f"Previous screen: {session.screen or '(first frame)'}\nPrevious phase: {session.phase or '(none)'}\n"
            f"Recent events:\n{recent}\n\nDescribe the current screen and what changed.")
    try:
        out = call_json(system, user, image_data_url=image, effort="low", timeout=40)
    except LLMError as e:
        logger.warning("vision failed: %s", e)
        return JsonResponse({"error": "vision_unavailable"}, status=503)

    now = time.time()
    phase = out.get("phase") if out.get("phase") in prompts.PHASE_IDS else ""
    phase_changed = bool(phase) and phase != session.phase
    activity = out.get("activity") if out.get("activity") in ("typing", "clicking", "reading", "waiting", "idle") else "reading"
    new_events = []
    for ev in (out.get("events") or [])[:4]:
        text = scrub(str(ev.get("text", "")).strip())[:200]
        if not text:
            continue
        try:
            j = min(max(float(ev.get("judgment", 0.3)), 0.0), 1.0)
        except (TypeError, ValueError):
            j = 0.3
        e = Event.objects.create(session=session, at=now, phase=phase or session.phase, text=text, judgment=j)
        new_events.append({"id": e.id, "text": text, "judgment": j, "phase": e.phase})
    session.screen = scrub(str(out.get("screen", ""))[:400])
    session.activity = activity
    if phase:
        session.phase = phase
    session.save(update_fields=["screen", "phase", "activity"])

    resp = {"screen": session.screen, "phase": session.phase, "phase_changed": phase_changed,
            "activity": activity, "events": new_events}
    if session.kind == Session.CAPTURE:
        if new_events:
            refresh_coverage(session.id)
        resp.update(_capture_decision(session, state, activity, phase_changed))
        resp["phases"] = _phase_view(Session.objects.get(pk=session.pk))
    else:
        violation = out.get("violation") if isinstance(out.get("violation"), dict) else None
        resp.update(_teach_decision(session, state, violation))
    return JsonResponse(resp)


@csrf_exempt
@require_POST
def tick(request, session_id):
    """Screen unchanged: re-run the decision with the last known activity, no vision call."""
    session = get_object_or_404(Session, pk=session_id)
    state = _body(request).get("state") or {}
    if session.kind == Session.CAPTURE:
        activity = session.activity or "idle"
        # A screen that stopped changing for a while is an idle screen.
        if float(state.get("unchanged_s", 0) or 0) > 6 and activity in ("clicking", "typing"):
            activity = "idle"
        out = _capture_decision(session, state, activity, False)
        out["phases"] = _phase_view(Session.objects.get(pk=session.pk))
        return JsonResponse(out)
    return JsonResponse(_teach_decision(session, state, None))


@csrf_exempt
@require_POST
def utterance(request, session_id):
    session = get_object_or_404(Session, pk=session_id)
    body = _body(request)
    role = body.get("role") if body.get("role") in ("user", "agent") else None
    text = scrub(clean_message(str(body.get("text", ""))))[:2000]
    if not role or not text or text == "...":
        return JsonResponse({"ok": False})
    Utterance.objects.create(session=session, at=time.time(), role=role, text=text)
    if session.kind == Session.CAPTURE and role == "user":
        refresh_coverage(session.id)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def debrief(request, session_id):
    session = get_object_or_404(Session, pk=session_id, kind=Session.CAPTURE)
    saved = [e.text for e in session.events.filter(asked=True).order_by("-judgment")[:6]]
    user = (f"Screen events:\n{_events(session)}\n\nConversation so far:\n{_transcript(session)}\n\n"
            f"Coverage per phase (0-1):\n{json.dumps(session.coverage)}\n\n"
            f"Actions the apprentice noticed but may not have asked about:\n" + "\n".join(f"- {t}" for t in saved))
    try:
        out = call_json(prompts.DEBRIEF_SYSTEM, user, effort="medium", timeout=90)
    except LLMError as e:
        logger.error("debrief failed: %s", e)
        return JsonResponse({"error": "Could not prepare the debrief. Try again."}, status=503)
    qs = [str(q) for q in (out.get("open_questions") or [])][:5]
    teach_back = str(out.get("teach_back", ""))
    session.debrief = {**session.debrief, "open_questions": qs, "teach_back": teach_back}
    session.save(update_fields=["debrief"])
    numbered = " ".join(f"{i}) {q}" for i, q in enumerate(qs, 1))
    nudge = ("[DEBRIEF] The expert has finished the task. Thank them in one short sentence. "
             f"Then ask these questions ONE AT A TIME, waiting for each answer: {numbered} "
             "After the last answer, explain the whole process back in plain words, in under 45 seconds, "
             f"based on this draft (correct it with what they just told you): {teach_back} "
             "End with: \"Is that how it works?\" If they correct you, restate the corrected part and ask again.")
    return JsonResponse({"open_questions": qs, "teach_back": teach_back, "nudge": nudge})


@csrf_exempt
@require_POST
def build_map(request, session_id):
    session = get_object_or_404(Session, pk=session_id, kind=Session.CAPTURE)
    user = (f"Screen events:\n{_events(session, 400)}\n\nFull conversation (interview, debrief and confirmation):\n"
            f"{_transcript(session, 400)}\n\nCoverage per phase:\n{json.dumps(session.coverage)}")
    try:
        data = call_json(prompts.WORKMAP_SYSTEM, user, effort="medium", timeout=150, retries=1)
    except LLMError as e:
        logger.error("work map failed: %s", e)
        return JsonResponse({"error": "Could not build the Work Map. Try again."}, status=503)
    data["phases"] = [p for p in data.get("phases", []) if isinstance(p, dict)]
    order = {pid: i for i, pid in enumerate(prompts.PHASE_IDS)}
    data["phases"].sort(key=lambda p: order.get(p.get("id"), 99))
    title = str(data.get("title") or "Deploy an app on Thales Ops")[:200]
    if session.produced_map:
        wm = session.produced_map
        wm.title, wm.data = title, data
        wm.save()
    else:
        wm = WorkMap.objects.create(title=title, data=data)
        session.produced_map = wm
        session.save(update_fields=["produced_map"])
    return JsonResponse({"map_id": str(wm.id), "url": f"/map/{wm.id}/"})


@csrf_exempt
@require_POST
def grade(request, session_id):
    session = get_object_or_404(Session, pk=session_id, kind=Session.TEACH)
    wm = session.work_map
    user = (f"Work Map:\n{map_to_text(wm.data) if wm else '(none)'}\n\nNew hire's screen events:\n{_events(session)}\n\n"
            f"Guardrail interventions by the tutor:\n{json.dumps(session.result.get('violations', []))}\n\n"
            f"Conversation:\n{_transcript(session)}")
    try:
        out = call_json(prompts.GRADE_SYSTEM, user, effort="medium", timeout=90)
    except LLMError as e:
        logger.error("grade failed: %s", e)
        return JsonResponse({"error": "Could not grade the session. Try again."}, status=503)
    try:
        out["score"] = int(min(max(float(out.get("score", 0)), 0), 100))
    except (TypeError, ValueError):
        out["score"] = 0
    session.result = {**session.result, "grade": out}
    session.save(update_fields=["result"])
    return JsonResponse(out)


@require_GET
def session_debug(request, session_id):
    """Decision log, for tuning the policy from real sessions."""
    s = get_object_or_404(Session, pk=session_id)
    return JsonResponse({
        "phase": s.phase, "coverage": s.coverage, "questions_asked": s.questions_asked,
        "events": [{"phase": e.phase, "text": e.text, "judgment": e.judgment, "asked": e.asked} for e in s.events.all()],
        "decisions": [{"action": d.action, "reason": d.reason, **d.data} for d in s.decisions.all()[:500]],
        "utterances": [{"role": u.role, "text": u.text} for u in s.utterances.all()],
    }, json_dumps_params={"indent": 2})
