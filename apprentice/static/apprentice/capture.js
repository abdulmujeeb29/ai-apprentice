import { Orb, Voice, ScreenWatcher, api, toast, speakText, revealPage, setPill, scanPulse,
  addFeedItem, addTranscript, animate, reduceMotion } from "./core.js";

const boot = JSON.parse(document.getElementById("boot").textContent);
const $ = (id) => document.getElementById(id);
const gsap = window.gsap;
const SID = boot.session;
const PHASE_NAMES = Object.fromEntries(boot.phases.map((p) => [p.id, p.name]));
const ACTIVITY = { waiting: "waiting on the build", idle: "paused", reading: "reading", clicking: "clicking", typing: "typing" };

const orb = new Orb($("orb"));
let voice, screen;
let off = false;
let started = 0;
let stage = "idle"; // idle | live | debrief | mapping
let questions = 0;

revealPage();

// ------------------------------------------------------------ status

function status(kind, text) { setPill($("status"), kind, text); }
setInterval(() => {
  if (!started) return;
  const s = Math.floor((Date.now() - started) / 1000);
  $("clock").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}, 500);

function state(unchangedS = 0) {
  return {
    silence_s: voice ? voice.silenceSeconds : 0,
    agent_speaking: voice ? voice.agentSpeaking : false,
    unchanged_s: unchangedS,
    off,
  };
}

// ------------------------------------------------------------ learning rail

let lastPhase = "";
function renderRail(phases, current) {
  for (const p of phases || []) {
    const row = document.querySelector(`.phase[data-phase="${p.id}"]`);
    if (!row) continue;
    const vals = ["what", "why", "vs_manual", "risk"].map((k) => p.scores[k] || 0);
    row.querySelectorAll(".dots i").forEach((dot, i) => {
      const was = dot.className;
      dot.className = vals[i] >= 0.6 ? "on" : vals[i] >= 0.3 ? "half" : "";
      if (dot.className && dot.className !== was && !reduceMotion) {
        animate(dot, { scale: [1.9, 1] }, { type: "spring", stiffness: 420, damping: 18 });
      }
    });
    row.classList.toggle("done", vals.every((v) => v >= 0.6));
  }
  if (current && current !== lastPhase) {
    document.querySelectorAll(".phase").forEach((r) => r.classList.toggle("current", r.dataset.phase === current));
    const row = document.querySelector(`.phase[data-phase="${current}"]`);
    if (row && !reduceMotion) animate(row, { x: [-6, 0] }, { duration: 0.4 });
    lastPhase = current;
  }
}

// ------------------------------------------------------------ voice events

function onMessage(role, text) {
  addTranscript($("transcript"), role, text, { user: "You", agent: "Sidecar" });
  if (!off) api(`/api/s/${SID}/utterance`, { role, text }).catch(() => {});
  if (role === "agent") {
    $("whoLabel").textContent = "Sidecar";
    speakText($("utter"), text);
  } else if (text.split(" ").length > 3) {
    $("whoLabel").textContent = "You";
    speakText($("utter"), text, { user: true });
  }
}

function onMode(mode) {
  if (off) return;
  if (mode === "speaking") status("speaking", "Speaking");
  else status("live", "Listening");
}

function askFlash() {
  if (reduceMotion || !gsap) return;
  gsap.fromTo($("askFlash"), { opacity: 0 }, { opacity: 1, duration: 0.35, yoyo: true, repeat: 1, ease: "power2.out" });
}

// ------------------------------------------------------------ server round trips

function handleDecision(res) {
  if (res.phases) renderRail(res.phases, res.phase || lastPhase);
  if (res.nudge && stage === "live") {
    voice.say(res.nudge);
    questions += 1;
    $("qCount").textContent = `${questions} question${questions === 1 ? "" : "s"}`;
    askFlash();
    const tag = document.querySelector(".feed-item");
    if (tag) tag.classList.add("asked");
  }
}

async function onFrame(image, unchangedS) {
  if (off || stage !== "live") return;
  scanPulse($("scan"));
  let res;
  try {
    res = await api(`/api/s/${SID}/frame`, { image, state: state(unchangedS) });
  } catch (e) {
    console.warn(e);
    return;
  }
  if (res.skipped) return;
  if (res.screen) $("screenNow").textContent = res.screen;
  if (res.phase) $("phaseName").textContent = PHASE_NAMES[res.phase] || res.phase;
  if (res.activity) $("activity").textContent = ACTIVITY[res.activity] || res.activity;
  for (const ev of res.events || []) {
    addFeedItem($("feed"), { tag: PHASE_NAMES[ev.phase] || "screen", text: ev.text, hi: ev.judgment >= 0.6 });
  }
  if (res.events?.length) {
    const txt = res.events.map((e) => e.text).join("; ");
    voice.context(`[SCREEN] Phase: ${PHASE_NAMES[res.phase] || "unknown"}. ${txt}. The expert is ${ACTIVITY[res.activity] || "working"}.`);
  } else if (res.phase_changed) {
    voice.context(`[SCREEN] The expert moved to: ${PHASE_NAMES[res.phase]}.`);
  }
  handleDecision(res);
}

async function onTick(unchangedS) {
  if (off || stage !== "live") return;
  try { handleDecision(await api(`/api/s/${SID}/tick`, { state: state(unchangedS) })); } catch { /* next tick */ }
}

// ------------------------------------------------------------ flow

async function start() {
  const btn = $("startBtn");
  btn.disabled = true; btn.querySelector(".spin").hidden = false;
  try {
    screen = new ScreenWatcher({ video: $("video"), onFrame, onTick, onEnded: () => toast("Screen sharing stopped. Click “I'm done” to debrief.") });
    await screen.start();
    voice = new Voice({
      role: "interviewer", orb, onMessage, onMode,
      onStatus: (s) => { if (s === "disconnected" && stage !== "mapping") status("", "Disconnected"); },
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
  started = Date.now();
  status("live", "Listening");
  const hero = $("startHero");
  const show = () => {
    hero.hidden = true;
    for (const id of ["screenCard", "voiceStage", "transcript"]) $(id).hidden = false;
    if (!reduceMotion && gsap) gsap.fromTo(["#screenCard", "#voiceStage", "#transcript"], { opacity: 0, y: 26 }, { opacity: 1, y: 0, stagger: 0.08, duration: 0.8, ease: "expo.out" });
  };
  if (reduceMotion || !gsap) show(); else gsap.to(hero, { opacity: 0, y: -16, duration: 0.35, onComplete: show });
  $("offBtn").disabled = false; $("doneBtn").disabled = false;
}

function toggleOff() {
  off = !off;
  const b = $("offBtn");
  b.textContent = off ? "Back on the record" : "Off the record";
  b.className = off ? "btn btn-danger btn-sm" : "btn btn-ghost btn-sm";
  screen.paused = off;
  if (off) {
    voice.context("[OFF] The expert went off the record. Do not ask anything and do not use what is said now.");
    status("off", "Off the record");
    toast("Off the record: nothing you say or show is saved.");
  } else {
    voice.context("[ON] The expert is back on the record.");
    status("live", "Listening");
  }
  if (!reduceMotion && gsap) gsap.to("#voiceStage, #screenCard", { opacity: off ? 0.45 : 1, duration: 0.4 });
}

async function done() {
  if (off) toggleOff();
  stage = "debrief";
  const b = $("doneBtn");
  b.disabled = true; b.textContent = "Preparing debrief…";
  screen.paused = true;
  try {
    const res = await api(`/api/s/${SID}/debrief`, {});
    const list = $("debriefList");
    list.innerHTML = "";
    for (const q of res.open_questions) { const li = document.createElement("li"); li.textContent = q; list.appendChild(li); }
    $("debriefBox").hidden = false;
    if (!reduceMotion && gsap) {
      gsap.fromTo("#debriefBox", { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.7, ease: "expo.out" });
      gsap.fromTo("#debriefList li", { opacity: 0, x: -12 }, { opacity: 1, x: 0, stagger: 0.12, delay: 0.2, duration: 0.6, ease: "power3.out" });
    }
    voice.say(res.nudge);
    $("hint").textContent = "Debrief: answer its questions, then confirm its summary. Then build the Work Map.";
    b.textContent = "Debriefing";
    const mb = $("mapBtn");
    mb.hidden = false;
    animate(mb, { opacity: [0, 1], y: [10, 0] }, { duration: 0.5 });
  } catch (e) {
    toast(e.message, "error");
    b.disabled = false; b.textContent = "I'm done";
    stage = "live"; screen.paused = false;
  }
}

async function buildMap() {
  stage = "mapping";
  const mb = $("mapBtn");
  mb.disabled = true; mb.querySelector(".spin").hidden = false;
  const ov = $("mapping");
  ov.hidden = false;
  let tl;
  if (!reduceMotion && gsap) {
    gsap.fromTo(ov, { opacity: 0 }, { opacity: 1, duration: 0.4 });
    gsap.fromTo("#mapping h2", { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.9, ease: "expo.out", delay: 0.1 });
    tl = gsap.timeline({ repeat: -1 }).to(".mapping-rail i", { backgroundColor: "#f2a93b", stagger: 0.18, duration: 0.3 })
      .to(".mapping-rail i", { backgroundColor: "#25211c", stagger: 0.18, duration: 0.3 }, "+=0.2");
  }
  try {
    const res = await api(`/api/s/${SID}/workmap`, {});
    screen?.stop();
    await voice?.stop();
    window.location.href = res.url;
  } catch (e) {
    tl?.kill();
    ov.hidden = true;
    mb.disabled = false; mb.querySelector(".spin").hidden = true;
    stage = "debrief";
    toast(e.message, "error");
  }
}

$("startBtn").addEventListener("click", start);
$("offBtn").addEventListener("click", toggleOff);
$("doneBtn").addEventListener("click", done);
$("mapBtn").addEventListener("click", buildMap);
window.addEventListener("beforeunload", () => { screen?.stop(); voice?.stop(); });
