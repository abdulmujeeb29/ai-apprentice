import { revealPage, countUp, reduceMotion } from "./core.js";

const data = JSON.parse(document.getElementById("mapData").textContent) || {};
const phases = data.phases || [];
const gsap = window.gsap;
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Title: line-by-line reveal, the italic-free serif arriving like speech.
if (!reduceMotion && gsap && window.SplitText) {
  gsap.registerPlugin(window.SplitText);
  const split = new window.SplitText("#mapTitle", { type: "words" });
  gsap.from(split.words, { opacity: 0, y: 30, filter: "blur(8px)", duration: 0.9, ease: "expo.out", stagger: 0.05 });
}
revealPage();
document.querySelectorAll("[data-count]").forEach((el) => countUp(el, Number(el.dataset.count), 1.6));

function render(i) {
  const p = phases[i];
  if (!p) return;
  const steps = (p.steps || []).map((s) => `
    <li><div><strong>${esc(s.action)}</strong><div class="why">${esc(s.why)}</div>
    ${s.evidence ? `<div class="quote">“${esc(s.evidence)}”</div>` : ""}</div></li>`).join("");
  const concepts = (p.concepts || []).map((c) => `<span class="chip"><b>${esc(c.name)}</b> · ${esc(c.plain)}</span>`).join("");
  const rules = (p.decision_rules || []).map((r) => `<span class="chip">${esc(r)}</span>`).join("");
  const exc = (p.exceptions || []).map((r) => `<span class="chip">${esc(r)}</span>`).join("");
  const covered = (t) => (t && !/^not covered/i.test(t) ? t : "");
  const platform = covered(p.platform_does), manual = covered(p.manual_equivalent);
  const guards = (p.guardrails || []).map((g) => `
    <div class="guard ${g.severity === "stop" ? "" : "warn"}"><span class="sev">${g.severity === "stop" ? "STOP" : "WARN"}</span>
    <div>${esc(g.rule)}<div class="why">${esc(g.why)}</div></div></div>`).join("");
  $("#detail").innerHTML = `
    <span class="label">Phase ${i + 1} of ${phases.length}</span>
    <h2>${esc(p.name)}</h2>
    <ol class="steps">${steps || '<li><div class="why">No steps recorded.</div></li>'}</ol>
    ${platform || manual ? `<div class="grid2">
      ${platform ? `<div class="box platform"><span class="label">Thales Ops does this for you</span><p>${esc(platform)}</p></div>` : ""}
      ${manual ? `<div class="box"><span class="label">By hand, you would</span><p>${esc(manual)}</p></div>` : ""}</div>` : ""}
    ${concepts ? `<div class="label sub-h">The idea behind it</div><div class="chips">${concepts}</div>` : ""}
    ${rules ? `<div class="label sub-h">Decision rules</div><div class="chips">${rules}</div>` : ""}
    ${exc ? `<div class="label sub-h">Exceptions</div><div class="chips">${exc}</div>` : ""}
    ${guards ? `<div class="label sub-h">Guardrails</div>${guards}` : ""}`;
  if (!reduceMotion && gsap) {
    gsap.fromTo("#detail > *", { opacity: 0, y: 16 }, { opacity: 1, y: 0, stagger: 0.05, duration: 0.6, ease: "expo.out" });
  }
  document.querySelectorAll(".path-node").forEach((n) => n.classList.toggle("active", Number(n.dataset.i) === i));
}

// The connecting path between phase bubbles, drawn in on load.
function drawPath() {
  const nav = $("#path"), svg = $("#pathSvg"), line = $("#pathLine");
  if (!nav || !svg) return;
  const box = nav.getBoundingClientRect();
  svg.setAttribute("width", box.width); svg.setAttribute("height", box.height);
  const pts = [...nav.querySelectorAll(".bubble")].map((b) => {
    const r = b.getBoundingClientRect();
    return [r.left - box.left + r.width / 2, r.top - box.top + r.height / 2];
  });
  if (pts.length < 2) return;
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let k = 1; k < pts.length; k++) {
    const [x0, y0] = pts[k - 1], [x1, y1] = pts[k];
    const my = (y0 + y1) / 2;
    d += ` C${x0 + 14},${my} ${x1 - 14},${my} ${x1},${y1}`;
  }
  line.setAttribute("d", d);
  const len = line.getTotalLength();
  line.style.strokeDasharray = len;
  if (reduceMotion || !gsap) { line.style.strokeDashoffset = 0; return; }
  gsap.fromTo(line, { strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.8, ease: "power2.inOut", delay: 0.3 });
  gsap.from(".path-node", { opacity: 0, x: -14, stagger: 0.1, duration: 0.6, ease: "expo.out", delay: 0.2 });
}

document.querySelectorAll(".path-node").forEach((n) => n.addEventListener("click", () => render(Number(n.dataset.i))));
if (phases.length) { render(0); requestAnimationFrame(drawPath); window.addEventListener("resize", () => {
  const line = $("#pathLine"); if (line) { line.style.strokeDasharray = "none"; } drawPath(); }); }
