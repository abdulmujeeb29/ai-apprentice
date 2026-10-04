import { Orb, Voice, ScreenWatcher, api, toast, speakText, revealPage, setPill, scanPulse,
  addTranscript, animate, countUp, reduceMotion } from "./core.js";

const boot = JSON.parse(document.getElementById("boot").textContent);
const mapPhases = JSON.parse(document.getElementById("mapPhases").textContent) || [];
const byId = Object.fromEntries(mapPhases.map((p) => [p.id, p]));
const $ = (id) => document.getElementById(id);
const gsap = window.gsap;
const SID = boot.session;

const orb = new Orb($("orb"), { color: [79, 214, 167] });
let voice, screen;
let stage = "idle";
let current = "";

revealPage();
const status = (k, t) => setPill($("status"), k, t);
const state = (u = 0) => ({ silence_s: voice?.silenceSeconds ?? 0, agent_speaking: voice?.agentSpeaking ?? false, unchanged_s: u });

function setPhase(pid) {
  if (!pid || pid === current) return;
  const rows = [...document.querySelectorAll(".phase")];
  const idx = rows.findIndex((r) => r.dataset.phase === pid);
  rows.forEach((r, i) => { r.classList.toggle("current", i === idx); r.classList.toggle("done", idx > -1 && i < idx); });
  current = pid;
  const p = byId[pid];
  if (p) {
    $("coachTitle").textContent = p.name;
    const concept = (p.concepts || [])[0];
    $("coachText").textContent = concept ? `${concept.name}: ${concept.plain}` : (p.platform_does || "");
    if (!reduceMotion && gsap) gsap.fromTo("#coach", { y: 10, opacity: 0.4 }, { y: 0, opacity: 1, duration: 0.6, ease: "expo.out" });
  }
}

function guardrailAlert(alert) {
  const el = $("alert");
  const a = typeof alert === "string" ? { rule: alert } : (alert || {});
  $("alertText").textContent = a.rule || "This breaks one of the expert's rules.";
  $("alertQuote").textContent = a.quote ? `“${a.quote}” the expert` : "";
  const m = a.moment;
  $("alertMoment").innerHTML = m && m.keyframe
    ? `<img src="${m.keyframe}" alt="The expert's screen at ${m.time}"><div class="label" style="margin-top:6px">Expert at ${m.time}</div>` : "";
  el.style.display = "block";
  if (reduceMotion || !gsap) { setTimeout(() => (el.style.display = "none"), 9000); return; }
  gsap.timeline()
    .fromTo(el, { opacity: 0, y: -20, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(1.6)" })
    .to(el, { x: -8, duration: 0.06, repeat: 5, yoyo: true, ease: "none" })
    .to(el, { x: 0, duration: 0.06 })
    .to(el, { opacity: 0, y: -12, duration: 0.5, delay: 8.5, onComplete: () => (el.style.display = "none") });
}

function onMessage(role, text) {
  addTranscript($("transcript"), role, text, { user: "You", agent: "Tutor" });
  api(`/api/s/${SID}/utterance`, { role, text }).catch(() => {});
  if (role === "agent") { $("whoLabel").textContent = "Tutor"; speakText($("utter"), text); }
  else if (text.split(" ").length > 3) { $("whoLabel").textContent = "You"; speakText($("utter"), text, { user: true }); }
}

function handle(res) {
  if (!res?.nudge || stage !== "live") return;
  voice.say(res.nudge);
  if (res.nudge_kind === "guardrail") {
    guardrailAlert(res.alert);
  } else if (!reduceMotion && gsap) {
    gsap.fromTo($("askFlash"), { opacity: 0 }, { opacity: 1, duration: 0.35, yoyo: true, repeat: 1 });
  }
}

async function onFrame(image, u) {
  if (stage !== "live") return;
  scanPulse($("scan"));
  let res;
  try { res = await api(`/api/s/${SID}/frame`, { image, state: state(u) }); } catch { return; }
  if (res.screen) $("screenNow").textContent = res.screen;
  if (res.phase) { $("phaseName").textContent = byId[res.phase]?.name || res.phase; setPhase(res.phase); }
  if (res.events?.length) voice.context(`[SCREEN] ${res.events.map((e) => e.text).join("; ")}.`);
  handle(res);
}

async function onTick(u) {
  if (stage !== "live") return;
  try { handle(await api(`/api/s/${SID}/tick`, { state: state(u) })); } catch { /* next tick */ }
}

async function start() {
  const btn = $("startBtn");
  btn.disabled = true; btn.querySelector(".spin").hidden = false;
  try {
    screen = new ScreenWatcher({ video: $("video"), onFrame, onTick, onEnded: () => toast("Screen sharing stopped.") });
    await screen.start();
    voice = new Voice({
      role: "tutor", orb, dynamicVariables: boot.dynamicVariables, onMessage,
      onMode: (m) => status(m === "speaking" ? "speaking" : "live", m === "speaking" ? "Speaking" : "Listening"),
      onError: (e) => toast(`Voice error: ${e?.message || e}`, "error"),
    });
    await voice.start();
  } catch (e) {
    screen?.stop(); await voice?.stop();
    btn.disabled = false; btn.querySelector(".spin").hidden = true;
    toast(e.message, "error");
    return;
  }
  stage = "live";
  status("live", "Listening");
  const show = () => {
    $("startHero").hidden = true;
    for (const id of ["screenCard", "voiceStage", "transcript"]) $(id).hidden = false;
    if (!reduceMotion && gsap) gsap.fromTo(["#screenCard", "#voiceStage", "#transcript"], { opacity: 0, y: 26 }, { opacity: 1, y: 0, stagger: 0.08, duration: 0.8, ease: "expo.out" });
  };
  if (reduceMotion || !gsap) show(); else gsap.to("#startHero", { opacity: 0, y: -16, duration: 0.35, onComplete: show });
  $("checkBtn").disabled = false;
}

function check() {
  stage = "check";
  screen.paused = true;
  voice.say("[CHECK] The new hire says the deploy is done. Give them the check scenario now and wait for their answer.");
  $("checkBtn").disabled = true;
  $("checkBtn").textContent = "Answer the tutor's question";
  $("coachTitle").textContent = "Final check";
  $("coachText").textContent = "Answer out loud. Then see how you did.";
  const g = $("gradeBtn");
  g.hidden = false;
  animate(g, { opacity: [0, 1], y: [10, 0] }, { duration: 0.5 });
}

async function grade() {
  const g = $("gradeBtn");
  g.disabled = true; g.querySelector(".spin").hidden = false;
  try {
    const res = await api(`/api/s/${SID}/grade`, {});
    screen?.stop(); await voice?.stop();
    status("", "Session ended");
    $("verdict").textContent = res.verdict || "";
    const ul = $("resultList");
    ul.innerHTML = "";
    for (const r of res.guardrails_respected || []) ul.insertAdjacentHTML("beforeend", `<li>✓ ${escapeHtml(r)}</li>`);
    for (const r of res.guardrails_broken || []) ul.insertAdjacentHTML("beforeend", `<li style="color:var(--danger)">✗ ${escapeHtml(r)}</li>`);
    if (res.check_passed !== null && res.check_passed !== undefined) {
      ul.insertAdjacentHTML("beforeend", `<li>${res.check_passed ? "✓ Handled a new case on their own" : "✗ New case not handled yet"}</li>`);
    }
    const lists = [["Mastered", res.mastered], ["Practice next", res.practice_next]];
    for (const [title, items] of lists) {
      if (!items || !items.length) continue;
      ul.insertAdjacentHTML("beforeend", `<h4>${title}</h4>`);
      for (const it of items) ul.insertAdjacentHTML("beforeend", `<li>${escapeHtml(it)}</li>`);
    }
    $("result").hidden = false;
    const score = res.score || 0;
    const arc = $("ringArc");
    if (!reduceMotion && gsap) {
      gsap.fromTo("#result", { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.7, ease: "expo.out" });
      gsap.to(arc, { attr: { "stroke-dashoffset": 326.7 * (1 - score / 100) }, duration: 1.6, ease: "expo.out", delay: 0.2 });
    } else {
      arc.setAttribute("stroke-dashoffset", 326.7 * (1 - score / 100));
    }
    countUp($("ringNum"), score, 1.6);
    $("result").scrollIntoView({ behavior: "smooth", block: "center" });
    g.hidden = true;
  } catch (e) {
    toast(e.message, "error");
    g.disabled = false; g.querySelector(".spin").hidden = true;
  }
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

$("startBtn").addEventListener("click", start);
$("checkBtn").addEventListener("click", check);
$("gradeBtn").addEventListener("click", grade);
window.addEventListener("beforeunload", () => { screen?.stop(); voice?.stop(); });
