// Boot, hash router, one delegated click handler, settings in localStorage.
import { html, fmtDay, ago, scanAlerts } from "./lib.js";
import { eventSheet } from "./cards.js";
import * as V from "./views.js";

const DEFAULTS = { window: "24h", relative: true, sigma: 2.5, pricePct: 3, volX: 2,
  cats: ["results", "management_change", "M&A", "fund_raise", "litigation", "pledging", "credit_rating"] };
const store = {
  get(k, d) { try { const v = localStorage.getItem("finn." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("finn." + k, JSON.stringify(v)); } catch { /* private mode / full */ } },
};

const state = {
  settings: { ...DEFAULTS, ...store.get("settings", {}) },
  lastSeen: store.get("lastSeen", 0),
  meta: null, events: null, prices: null, symbols: null,
  dossiers: {}, research: {}, showHidden: false, speaking: false, openThread: null, sheet: null, windowTouched: false,
};
state.nameOf = (t) => state.meta?.portfolio?.find((c) => c.t === t)?.name || state.dossiers[t]?.name || t;
const seenAtBoot = state.lastSeen;
const ctx = {
  nameOf: state.nameOf,
  isNew: (e) => seenAtBoot && new Date(e.ts).getTime() > seenAtBoot,
  researchReady: (t) => (state.meta?.research_ready || []).includes(t) || !!state.dossiers[t],
};

const $ = (s) => document.querySelector(s);
const getJSON = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))));

async function load() {
  const [meta, ev, pr] = await Promise.allSettled([getJSON("data/meta.json"), getJSON("data/events.json"), getJSON("data/prices.json")]);
  state.meta = meta.value || { portfolio: [], research_ready: [], status: {} };
  state.events = ev.value?.events || [];
  state.prices = pr.value || null;
  state.loadError = [meta, ev, pr].some((x) => x.status === "rejected");
  render();
  getJSON("data/symbols.json").then((s) => { state.symbols = s; if (route().tab === "research" && !route().t) render(); }).catch(() => {});
}

// ------------------------------------------------------------------ routing
function route() {
  const [, tab = "today", t, th] = (location.hash || "#/today").split("/");
  return { tab, t: t ? decodeURIComponent(t).toUpperCase() : null, th };
}

function freshness() {
  const st = state.meta?.status || {};
  const bad = Object.entries(st).filter(([, v]) => !v.ok).map(([k]) => k);
  const p = state.prices?.dates;
  return html`<div class="fresh">
    ${p?.length ? html`<span>Prices: ${fmtDay(p.at(-1))} close</span>` : ""}
    ${st.filings ? html`<span>· Filings ${ago(st.filings.at)}</span>` : ""}
    ${bad.length ? html`<span class="bad">· ${bad.join(", ")} failed last run, showing last good data</span>` : ""}
    ${state.loadError && !p ? html`<span class="bad">Data not built yet. The pipeline hasn't run.</span>` : ""}
  </div>`;
}

function render() {
  const r = route();
  let body;
  if (r.tab === "alerts") body = V.alerts(state);
  else if (r.tab === "research") body = r.t ? researchView(r.t) : V.researchHome(state);
  else body = V.today(state, ctx);
  const d = new Date();
  const nAct = (state.events || []).filter((e) => e.tier === "act" && ctx.isNew(e)).length;
  $("#app").innerHTML = html`
    <header class="mast"><h1>FINN</h1><div class="dateline">${d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" })}<br>${state.meta?.portfolio?.length || 18} holdings · NSE</div></header>
    ${freshness()}
    <main>${body}</main>`.toString();
  $("#tabs").innerHTML = html`<nav>
    <a href="#/today" class="${r.tab === "today" ? "on" : ""}"><b>Today</b>filings${nAct ? html`<span class="badge">${nAct}</span>` : ""}</a>
    <a href="#/alerts" class="${r.tab === "alerts" ? "on" : ""}"><b>Alerts</b>thresholds</a>
    <a href="#/research" class="${r.tab === "research" ? "on" : ""}"><b>Research</b>promises</a></nav>`.toString();
  renderSheet();
  if (r.th) { const el = document.getElementById(r.th); if (el) { state.openThread = r.th; el.scrollIntoView({ block: "center" }); } }
}

function renderSheet() {
  let el = $("#sheet");
  if (!state.sheet) { if (el) el.remove(); document.body.style.overflow = ""; return; }
  if (!el) { el = document.createElement("div"); el.id = "sheet"; document.body.appendChild(el); }
  const e = (state.events || []).find((x) => x.id === state.sheet);
  el.innerHTML = e ? html`<div class="scrim" data-act="closeSheet"><div class="sheet" data-stop="1"><div class="grab"></div>
    <button class="close" data-act="closeSheet">Close</button>${eventSheet(e, ctx)}</div></div>`.toString() : "";
  document.body.style.overflow = "hidden";
}

// ----------------------------------------------------------------- research
function researchView(t) {
  if (state.dossiers[t]) return V.dossier(state.dossiers[t], state);
  const r = state.research[t];
  if (!r) { startResearch(t); return V.researchLoading(t, { started: Date.now() }, state); }
  if (r.error) return html`<div class="dossier-h"><div class="co">${state.nameOf(t)}<small>${t}</small></div></div>${V.recentFor(t, state)}
    <div class="note">${r.error}</div><button class="listen" data-act="retry" data-t="${t}">Try again</button>`;
  return V.researchLoading(t, r, state);
}

async function startResearch(t) {
  if (state.research[t]?.running) return;
  state.research[t] = { running: true, started: Date.now() };
  const cached = store.get("r." + t, null);
  try {
    let d = null;
    if ((state.meta?.research_ready || []).includes(t)) d = await getJSON(`data/research/${t}.json`).catch(() => null);
    if (!d && cached && Date.now() - new Date(cached.generated_at) < 3 * 864e5) d = cached;
    if (!d) {
      const tick = setInterval(() => route().t === t && !state.dossiers[t] && render(), 1000);
      try {
        const res = await fetch(`api/research?t=${encodeURIComponent(t)}`);
        const j = await res.json().catch(() => ({ error: `Server error ${res.status}` }));
        if (!res.ok || j.error) throw new Error(j.error || `Server error ${res.status}`);
        d = j;
        store.set("r." + t, d);
      } finally { clearInterval(tick); }
    }
    state.dossiers[t] = d;
  } catch (e) {
    state.research[t] = { error: `Couldn't build research for ${t}: ${e.message}. Check the symbol, or try again in a minute.` };
  }
  if (route().t === t) render();
}

// ------------------------------------------------------------------- listen
function briefScript() {
  const { win, evs } = V.todayEvents(state);
  const spoken = (t) => state.meta?.portfolio?.find((c) => c.t === t)?.spoken || state.nameOf(t);
  const say = (v) => (v == null ? "" : `${v < 0 ? "down" : "up"} ${Math.abs(v).toFixed(1)} percent`);
  const crore = (v) => `${Math.round(v).toLocaleString("en-IN")} crore rupees`;
  const act = evs.filter((e) => e.tier === "act").sort((a, b) => b.score - a.score);
  const know = evs.filter((e) => e.tier === "know");
  const hidden = evs.filter((e) => e.tier === "hidden").reduce((s, e) => s + e.filings.length, 0);
  const lines = [`${V.windowLabel(state, win)}. ${act.length ? `${act.length} thing${act.length > 1 ? "s" : ""} need${act.length > 1 ? "" : "s"} you.` : "Nothing needs you."}`];
  for (const e of act.slice(0, 5)) {
    const c = e.card;
    if (c?.type === "results") {
      const rev = c.rows.find((r) => r.k === "Revenue"), pat = c.rows.find((r) => r.k === "PAT");
      lines.push(`${spoken(e.ticker)} reported results. Revenue ${rev ? crore(rev.v) : ""}, ${say(rev?.yoy)} year on year. Profit after tax ${say(pat?.yoy)} year on year.`);
    } else if (c?.type === "mgmt") {
      const p = c.people[0];
      lines.push(`${spoken(e.ticker)}: ${p.name}, ${p.role}, ${p.change}.${p.profile ? " " + p.profile : ""}`);
    } else lines.push(`${spoken(e.ticker)}: ${e.oneliner || e.title}.`);
  }
  if (know.length) lines.push(`Also worth knowing: ${know.slice(0, 4).map((e) => `${spoken(e.ticker)}, ${(e.oneliner || e.title).split(/[.;]/)[0]}`).join(". ")}.`);
  const p = state.prices;
  if (p) {
    const moves = scanAlerts(p, state.settings, p.dates.length - 1);
    if (moves.length) lines.push(`Unusual moves last session: ${moves.slice(0, 3).map((x) => `${spoken(x.t)} ${x.price ? say(x.ret) : ""}${x.vol ? ` on ${x.volx.toFixed(1)} times normal volume` : ""}`).join(", ")}.`);
  }
  lines.push(`${hidden} routine filings were hidden. That's your brief.`);
  return lines.map((l) => l.replace(/₹/g, "rupees ").replace(/\bcr\b/g, "crore").replace(/\s+/g, " ").trim());
}

function toggleListen() {
  const synth = window.speechSynthesis;
  if (!synth) { alertLine("Your browser can't read aloud."); return; }
  if (state.speaking) { synth.cancel(); state.speaking = false; captions(null); render(); return; }
  const lines = briefScript();
  const voices = synth.getVoices();
  const voice = voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang?.startsWith("en-GB")) || voices.find((v) => v.lang?.startsWith("en"));
  state.speaking = true; render();
  lines.forEach((text, i) => {
    const u = new SpeechSynthesisUtterance(text);
    if (voice) u.voice = voice;
    u.rate = 1.02;
    u.onstart = () => captions(text, i + 1, lines.length);
    if (i === lines.length - 1) u.onend = () => { state.speaking = false; captions(null); render(); };
    synth.speak(u);
  });
}
function captions(text, i, n) {
  let el = $("#captions");
  if (!text) { el?.remove(); return; }
  if (!el) { el = document.createElement("div"); el.id = "captions"; el.className = "captions"; el.setAttribute("aria-live", "polite"); document.body.appendChild(el); }
  el.innerHTML = html`<div>${text}<div class="tiny">${i} of ${n} · tap Stop to end</div></div>`.toString();
}
function alertLine(msg) { captions(msg, 1, 1); setTimeout(() => captions(null), 2500); }

// ----------------------------------------------------------------- events
document.addEventListener("click", (ev) => {
  const a = ev.target.closest("[data-act]");
  if (!a) return;
  if (a.dataset.act === "closeSheet" && ev.target.closest("[data-stop]") && !ev.target.closest(".close")) return;
  const s = state.settings;
  switch (a.dataset.act) {
    case "win": s.window = a.dataset.w; state.windowTouched = true; break;
    case "event": state.sheet = a.dataset.id; renderSheet(); return;
    case "closeSheet": state.sheet = null; renderSheet(); return;
    case "co": state.sheet = null; location.hash = `#/research/${a.dataset.t}`; return;
    case "toggleHidden": state.showHidden = !state.showHidden; break;
    case "listen": toggleListen(); return;
    case "mode": s.relative = a.dataset.v === "1"; break;
    case "cat": s.cats = s.cats.includes(a.dataset.c) ? s.cats.filter((c) => c !== a.dataset.c) : [...s.cats, a.dataset.c]; break;
    case "thread": state.openThread = state.openThread === a.dataset.id ? null : a.dataset.id; break;
    case "retry": delete state.research[a.dataset.t]; break;
    default: return;
  }
  store.set("settings", s);
  render();
});

document.addEventListener("input", (ev) => {
  const k = ev.target.dataset?.set;
  if (!k) return;
  state.settings[k] = parseFloat(ev.target.value);
  store.set("settings", state.settings);
  const y = window.scrollY;
  render();
  window.scrollTo(0, y);
  const el = document.querySelector(`[data-set="${k}"]`);
  el?.focus();
});

document.addEventListener("submit", (ev) => {
  const f = ev.target.closest("[data-form=search]");
  if (!f) return;
  ev.preventDefault();
  const t = new FormData(f).get("t").toString().trim().toUpperCase().replace(/\.NS$/, "");
  if (t) location.hash = `#/research/${encodeURIComponent(t)}`;
});

window.addEventListener("hashchange", () => { state.sheet = null; state.openThread = route().th || null; render(); window.scrollTo(0, 0); });
// "New since you last looked": remember when the Today screen was last open.
const markSeen = () => { if (route().tab === "today" && state.events) store.set("lastSeen", Date.now()); };
document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && markSeen());
window.addEventListener("pagehide", markSeen);

load();
