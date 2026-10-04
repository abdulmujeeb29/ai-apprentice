// Shared engine for the capture and teach pages: voice, screen, orb, motion helpers.
import { Conversation } from "https://cdn.jsdelivr.net/npm/@elevenlabs/client@1.26.0/+esm";
import { animate, stagger } from "https://cdn.jsdelivr.net/npm/motion@12.43.0/+esm";

export { animate, stagger };
export const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Messages the app sends to the agent; never show or store them if echoed back.
const PROTOCOL = /^\s*\[(ASK|DEBRIEF|OFF|ON|OPEN|SCREEN|COACH|GUARDRAIL|CHECK)\]/;
// Eleven v3 expressive audio tags like [curious] or [warm]: spoken as tone, not as words.
const AUDIO_TAG = /\[[a-z][a-z' -]{0,30}\]\s*/gi;

/** Returns display text, or "" for app protocol messages. */
export function cleanMessage(text) {
  if (!text || PROTOCOL.test(text)) return "";
  return text.replace(AUDIO_TAG, "").replace(/\s{2,}/g, " ").trim();
}
const gsap = window.gsap;

// ------------------------------------------------------------------ http

export async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export function toast(msg, kind = "") {
  const wrap = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  wrap.appendChild(el);
  animate(el, { opacity: [0, 1], y: [16, 0] }, { duration: 0.35, ease: [0.16, 1, 0.3, 1] });
  setTimeout(() => animate(el, { opacity: 0, y: 8 }, { duration: 0.3 }).then(() => el.remove()), 4200);
}

// ------------------------------------------------------------------ text motion

/** Reveal a line word by word, like speech arriving. */
export function speakText(el, text, { user = false } = {}) {
  el.classList.toggle("user", user);
  el.innerHTML = "";
  const words = text.split(/(\s+)/).filter(Boolean);
  const spans = words.map((w) => {
    const s = document.createElement("span");
    s.className = "w";
    s.textContent = w;
    el.appendChild(s);
    return s;
  });
  if (reduceMotion || !gsap) return;
  gsap.fromTo(spans, { opacity: 0, y: 14, filter: "blur(6px)" },
    { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.55, ease: "power3.out", stagger: Math.min(0.06, 2.2 / spans.length) });
}

export function countUp(el, to, duration = 1.4) {
  if (reduceMotion || !gsap) { el.textContent = to; return; }
  const o = { v: 0 };
  gsap.to(o, { v: to, duration, ease: "expo.out", onUpdate: () => { el.textContent = Math.round(o.v); } });
}

export function revealPage(root = document) {
  if (reduceMotion || !gsap) return;
  const items = root.querySelectorAll("[data-reveal]");
  gsap.fromTo(items, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.9, ease: "expo.out", stagger: 0.07, clearProps: "transform" });
}

// ------------------------------------------------------------------ orb

/** A living orb that breathes when idle and ripples with real audio volume. */
export class Orb {
  constructor(canvas, { color = [242, 169, 59], userColor = [242, 237, 228] } = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.color = color;
    this.userColor = userColor;
    this.level = 0;       // agent output volume 0..1
    this.userLevel = 0;   // mic volume 0..1
    this.mode = "idle";   // idle | listening | speaking | thinking
    this.t = 0;
    this.resize();
    window.addEventListener("resize", () => this.resize());
    const loop = () => { this.draw(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }
  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = this.c.getBoundingClientRect();
    this.c.width = r.width * dpr; this.c.height = r.height * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = r.width; this.h = r.height;
  }
  draw() {
    const { ctx, w, h } = this;
    this.t += reduceMotion ? 0.002 : 0.016;
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    const base = Math.min(w, h) * 0.27;
    const speaking = this.mode === "speaking";
    const energy = speaking ? this.level : this.userLevel * 0.7;
    const [r, g, b] = speaking || this.mode !== "listening" ? this.color : this.color;

    // glow
    const glowR = base * (1.9 + energy * 0.9);
    const glow = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, glowR);
    glow.addColorStop(0, `rgba(${r},${g},${b},${0.28 + energy * 0.35})`);
    glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(cx, cy, glowR, 0, Math.PI * 2); ctx.fill();

    // rings that ripple out while the agent speaks
    for (let i = 0; i < 3; i++) {
      const p = (this.t * 0.35 + i / 3) % 1;
      const rr = base * (1 + p * 0.9);
      ctx.strokeStyle = `rgba(${r},${g},${b},${(1 - p) * (speaking ? 0.35 : 0.08)})`;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.stroke();
    }

    // body: a soft blob whose edge moves with the voice
    const pts = 96;
    ctx.beginPath();
    for (let i = 0; i <= pts; i++) {
      const a = (i / pts) * Math.PI * 2;
      const breath = Math.sin(this.t * 1.1) * 0.03;
      const wobble = Math.sin(a * 3 + this.t * 2.1) * 0.035 + Math.sin(a * 5 - this.t * 2.7) * 0.025;
      const voice = Math.sin(a * 7 + this.t * 9) * energy * 0.12 + Math.sin(a * 4 - this.t * 6) * energy * 0.08;
      const rad = base * (1 + breath + wobble * (0.6 + energy) + voice);
      const x = cx + Math.cos(a) * rad, y = cy + Math.sin(a) * rad;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    const body = ctx.createRadialGradient(cx - base * 0.35, cy - base * 0.4, base * 0.1, cx, cy, base * 1.15);
    body.addColorStop(0, "rgba(255,236,200,0.95)");
    body.addColorStop(0.35, `rgba(${r},${g},${b},0.95)`);
    body.addColorStop(1, `rgba(${Math.round(r * 0.35)},${Math.round(g * 0.3)},${Math.round(b * 0.2)},0.95)`);
    ctx.fillStyle = body;
    ctx.fill();

    // user voice: an ivory ring that follows the mic
    if (this.userLevel > 0.02 && !speaking) {
      const [ur, ug, ub] = this.userColor;
      ctx.strokeStyle = `rgba(${ur},${ug},${ub},${Math.min(0.6, this.userLevel * 2)})`;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(cx, cy, base * (1.22 + this.userLevel * 0.5), 0, Math.PI * 2); ctx.stroke();
    }
  }
}

// ------------------------------------------------------------------ voice

/**
 * Wraps an ElevenAgents conversation. Tracks who is talking so the policy
 * never interrupts anyone.
 */
export class Voice {
  constructor({ role, dynamicVariables, onMessage, onMode, onStatus, onError, orb }) {
    Object.assign(this, { role, dynamicVariables, onMessage, onMode, onStatus, onError, orb });
    this.conv = null;
    this.mode = "idle";
    this.lastVoiceAt = performance.now();
    this._poll = null;
  }

  async start() {
    // Ask for the mic first so a refusal gets a clear message.
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach((t) => t.stop());
    } catch {
      throw new Error("Microphone access was blocked. Allow the mic in the address bar and try again.");
    }
    const { signed_url } = await api(`/api/agent/${this.role}/signed-url`);
    this.conv = await Conversation.startSession({
      signedUrl: signed_url,
      connectionType: "websocket",
      dynamicVariables: this.dynamicVariables || undefined,
      onMessage: ({ source, message }) => {
        const text = cleanMessage(message);
        this.lastVoiceAt = performance.now();
        if (!text || text === "...") return;
        this.onMessage?.(source === "user" ? "user" : "agent", text);
      },
      onModeChange: ({ mode }) => {
        this.mode = mode;
        if (this.orb) this.orb.mode = mode;
        this.lastVoiceAt = performance.now();
        this.onMode?.(mode);
      },
      onStatusChange: ({ status }) => this.onStatus?.(status),
      onError: (e) => this.onError?.(e),
      onDisconnect: () => this.onStatus?.("disconnected"),
    });
    this._poll = setInterval(() => this._levels(), 80);
  }

  async _levels() {
    if (!this.conv) return;
    try {
      const out = await this.conv.getOutputVolume();
      const inp = await this.conv.getInputVolume();
      if (this.orb) { this.orb.level = this.orb.level * 0.6 + out * 0.4 * 2.2; this.orb.userLevel = this.orb.userLevel * 0.6 + inp * 0.4 * 2.2; }
      if (inp > 0.06 || out > 0.03) this.lastVoiceAt = performance.now();
    } catch { /* not ready yet */ }
  }

  get agentSpeaking() { return this.mode === "speaking"; }
  get silenceSeconds() { return (performance.now() - this.lastVoiceAt) / 1000; }

  context(text) { try { this.conv?.sendContextualUpdate(text); } catch (e) { console.warn(e); } }
  say(text) { try { this.conv?.sendUserMessage(text); this.lastVoiceAt = performance.now(); } catch (e) { console.warn(e); } }
  mute(on) { try { this.conv?.setMicMuted(on); } catch { /* older sdk */ } }

  async stop() {
    clearInterval(this._poll);
    try { await this.conv?.endSession(); } catch { /* already closed */ }
    this.conv = null;
  }
}

// ------------------------------------------------------------------ screen

/**
 * Shares a screen and sends a frame only when it changes (or the server needs a
 * decision tick). One request in flight at a time, so the vision model is never
 * flooded and frames never pile up.
 */
export class ScreenWatcher {
  constructor({ video, onFrame, onTick, onEnded, intervalMs = 1500 }) {
    Object.assign(this, { video, onFrame, onTick, onEnded, intervalMs });
    this.stream = null;
    this.busy = false;
    this.prev = null;
    this.lastChangeAt = performance.now();
    this.lastSentAt = 0;
    this.lastTickAt = 0;
    this.paused = false;
    this.small = document.createElement("canvas");
    this.small.width = 64; this.small.height = 36;
    this.big = document.createElement("canvas");
  }

  async start() {
    try {
      this.stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
    } catch {
      throw new Error("Screen sharing was cancelled. Click Start again and pick the Thales Ops tab or window.");
    }
    this.video.srcObject = this.stream;
    await this.video.play().catch(() => {});
    this.stream.getVideoTracks()[0].addEventListener("ended", () => { this.stop(); this.onEnded?.(); });
    this.timer = setInterval(() => this._loop(), this.intervalMs);
  }

  stop() {
    clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }

  _diff() {
    const ctx = this.small.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(this.video, 0, 0, 64, 36);
    const d = ctx.getImageData(0, 0, 64, 36).data;
    const gray = new Uint8Array(64 * 36);
    for (let i = 0; i < gray.length; i++) gray[i] = (d[i * 4] * 3 + d[i * 4 + 1] * 6 + d[i * 4 + 2]) / 10;
    let diff = 255;
    if (this.prev) {
      let sum = 0;
      for (let i = 0; i < gray.length; i++) sum += Math.abs(gray[i] - this.prev[i]);
      diff = sum / gray.length;
    }
    this.prev = gray;
    return diff;
  }

  _encode() {
    const vw = this.video.videoWidth, vh = this.video.videoHeight;
    const scale = Math.min(1, 1280 / vw);
    this.big.width = Math.round(vw * scale); this.big.height = Math.round(vh * scale);
    this.big.getContext("2d").drawImage(this.video, 0, 0, this.big.width, this.big.height);
    return this.big.toDataURL("image/jpeg", 0.72);
  }

  async _loop() {
    if (!this.stream || this.busy || this.paused || !this.video.videoWidth) return;
    const now = performance.now();
    const changed = this._diff() > 1.6;
    if (changed) this.lastChangeAt = now;
    const unchangedS = (now - this.lastChangeAt) / 1000;
    this.busy = true;
    try {
      // Send a frame when the screen changed, or every 12s so slow progress (builds) is seen.
      if (changed || now - this.lastSentAt > 12000) {
        this.lastSentAt = now;
        await this.onFrame?.(this._encode(), unchangedS);
      } else if (now - this.lastTickAt > 2500) {
        this.lastTickAt = now;
        await this.onTick?.(unchangedS);
      }
    } catch (e) {
      console.warn("screen loop", e);
    } finally {
      this.busy = false;
    }
  }
}

// ------------------------------------------------------------------ ui bits

export function setPill(el, kind, text) {
  el.className = `pill ${kind}`;
  el.innerHTML = `<span class="dot"></span>${text}`;
}

export function scanPulse(scanEl) {
  if (reduceMotion || !gsap || !scanEl) return;
  gsap.fromTo(scanEl, { top: "-40%", opacity: 1 }, { top: "100%", opacity: 0.2, duration: 1.1, ease: "power2.inOut" });
}

export function addFeedItem(feed, { tag, text, hi = false, asked = false }, max = 9) {
  feed.querySelector(".empty")?.remove();
  const el = document.createElement("div");
  el.className = `feed-item${hi ? " hi" : ""}${asked ? " asked" : ""}`;
  el.innerHTML = `<span class="tag"></span><span class="t"></span>`;
  el.querySelector(".tag").textContent = tag;
  el.querySelector(".t").textContent = text;
  feed.prepend(el);
  animate(el, { opacity: [0, 1], x: [-18, 0], scale: [0.98, 1] }, { duration: 0.5, ease: [0.16, 1, 0.3, 1] });
  while (feed.children.length > max) feed.lastElementChild.remove();
}

export function addTranscript(box, role, text, labels) {
  box.querySelector(".empty")?.remove();
  const el = document.createElement("div");
  el.className = `line ${role}`;
  el.innerHTML = `<span class="r"></span><span class="x"></span>`;
  el.querySelector(".r").textContent = labels[role] || role;
  el.querySelector(".x").textContent = text;
  box.appendChild(el);
  animate(el, { opacity: [0, 1], y: [8, 0] }, { duration: 0.35 });
  box.scrollTop = box.scrollHeight;
}
