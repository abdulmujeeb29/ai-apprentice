"""When should the apprentice speak? A pure, utility-based decision.

Ported from Hiwaar's stage controller: no clock reads, no I/O, everything is passed in,
and the Decision carries the math so every choice can be logged and tuned.

Actions:
  ask   - nudge the voice agent to ask one question now
  wait  - stay quiet; the moment or the topic is not good enough yet
  save  - the topic is worth asking but the moment never came; keep it for the debrief
"""
from dataclasses import asdict, dataclass, field

CHECKLIST = ("what", "why", "vs_manual", "risk")

# How good a moment is to speak, by what the expert appears to be doing on screen.
MOMENT = {"waiting": 1.0, "idle": 0.8, "reading": 0.45, "clicking": 0.2, "typing": 0.0}
# Cost of interrupting each activity.
INTERRUPT = {"waiting": 0.0, "idle": 0.05, "reading": 0.2, "clicking": 0.4, "typing": 1.0}


@dataclass(frozen=True)
class Weights:
    w_gap: float = 1.0
    w_moment: float = 0.6
    w_transition: float = 0.25
    w_interrupt: float = 0.7
    w_budget: float = 0.5
    ask_threshold: float = 0.75
    min_silence_s: float = 2.2      # nobody has spoken for this long
    min_gap_s: float = 40.0         # between two live questions
    max_live_questions: int = 6     # the rest waits for the debrief
    stale_s: float = 150.0          # a topic this old with no moment goes to the debrief


@dataclass
class Moment:
    now: float
    activity: str                 # waiting | idle | reading | clicking | typing
    silence_s: float              # since the expert or the agent last spoke
    agent_speaking: bool
    phase_changed: bool           # the screen just moved to a new deploy phase
    questions_asked: int
    last_question_at: float


@dataclass
class Candidate:
    event_id: int
    text: str
    phase: str
    judgment: float
    at: float


@dataclass
class Decision:
    action: str
    reason: str
    event_id: int | None = None
    utility: float = 0.0
    terms: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


def phase_gap(coverage: dict, phase: str) -> tuple[float, list[str]]:
    """1 - mean coverage of the phase checklist, plus which items are still missing."""
    scores = coverage.get(phase, {}) if coverage else {}
    missing = [k for k in CHECKLIST if float(scores.get(k, 0.0)) < 0.6]
    mean = sum(min(float(scores.get(k, 0.0)), 1.0) for k in CHECKLIST) / len(CHECKLIST)
    return 1.0 - mean, missing


def decide(m: Moment, candidates: list[Candidate], coverage: dict, w: Weights = Weights()) -> Decision:
    # Hard gates first: never talk over anyone, never exceed the budget.
    if m.agent_speaking:
        return Decision("wait", "agent_speaking")
    if m.silence_s < w.min_silence_s:
        return Decision("wait", "someone_talking", terms={"silence_s": round(m.silence_s, 1)})
    if not candidates:
        return Decision("wait", "nothing_to_ask")

    budget_left = w.max_live_questions - m.questions_asked
    since_last = m.now - m.last_question_at if m.last_question_at else 1e9

    best = None
    for c in candidates:
        gap, missing = phase_gap(coverage, c.phase)
        value = w.w_gap * gap * c.judgment
        moment = w.w_moment * MOMENT.get(m.activity, 0.3) + (w.w_transition if m.phase_changed else 0.0)
        cost = w.w_interrupt * INTERRUPT.get(m.activity, 0.3) + w.w_budget * (m.questions_asked / w.max_live_questions)
        u = value + moment - cost
        terms = {"gap": round(gap, 2), "missing": missing, "judgment": round(c.judgment, 2),
                 "moment": round(moment, 2), "cost": round(cost, 2), "activity": m.activity}
        if best is None or u > best[0]:
            best = (u, c, terms)

    u, c, terms = best
    stale = (m.now - c.at) > w.stale_s
    if budget_left <= 0:
        return Decision("save", "budget_spent", c.event_id, u, terms)
    if since_last < w.min_gap_s:
        if stale:
            return Decision("save", "stale_no_moment", c.event_id, u, terms)
        return Decision("wait", "too_soon", c.event_id, u, {**terms, "since_last": round(since_last)})
    if u >= w.ask_threshold:
        return Decision("ask", "utility", c.event_id, u, terms)
    if stale:
        return Decision("save", "stale_no_moment", c.event_id, u, terms)
    return Decision("wait", "low_utility", c.event_id, u, terms)
