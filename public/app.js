// Boot, hash router, one delegated click handler, settings in localStorage.
import { html, fmtDay, ago, scanAlerts } from "./lib.js";
import { eventSheet, rankingSheet } from "./cards.js";
import * as V from "./views.js";
import { learn, searchGlossary } from "./learn.js";

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
  theme: store.get("theme", "auto"), glossQ: "", ask: { open: false, q: "", items: [] },
};
state.nameOf = (t) => state.meta?.portfolio?.find((c) => c.t === t)?.name || state.dossiers[t]?.name || t;
const seenAtBoot = state.lastSeen;
const ctx = {
  nameOf: state.nameOf,
  isNew: (e) => seenAtBoot && new Date(e.ts).getTime() > seenAtBoot,
  researchReady: (t) => (state.meta?.research_ready || []).includes(t) || !!state.dossiers[t],
};

const $ = (s) => document.querySelector(s);

// ------------------------------------------------------------------- theme
const THEMES = ["auto", "light", "dark"];
function applyTheme() {
  const root = document.documentElement;
  if (state.theme === "auto") delete root.dataset.theme; else root.dataset.theme = state.theme;
  const dark = state.theme === "dark" || (state.theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", dark ? "#1F1D1A" : "#F6F1E7"));
}
applyTheme();
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);
const getJSON = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))));

async function load() {
  const [meta, ev, pr] = await Promise.allSettled([getJSON("data/meta.json"), getJSON("data/events.json"), getJSON("data/prices.json")]);
  state.meta = meta.value || { portfolio: [], research_ready: [], status: {} };
  state.events = ev.value?.events || [];
  state.prices = pr.value || null;
  state.loadError = [meta, ev, pr].some((x) => x.status === "rejected");
  render();
  getJSON("data/calibration.json").then((c) => (state.calibration = c)).catch(() => {});
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
  else if (r.tab === "learn") body = learn(state);
  else body = V.today(state, ctx);
  const d = new Date();
  const nAct = (state.events || []).filter((e) => e.tier === "act" && ctx.isNew(e)).length;
  $("#app").innerHTML = html`
    <header class="mast"><h1>FINN</h1><div class="dateline">${d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" })}<br>${state.meta?.portfolio?.length || 18} holdings · NSE<br>
      <button class="theme" data-act="theme" aria-label="Change colour theme">Theme: ${{ auto: "Auto", light: "Light", dark: "Dark" }[state.theme]}</button></div></header>
    ${freshness()}
    <main>${body}</main>`.toString();
  $("#tabs").innerHTML = html`<nav>
    <a href="#/today" class="${r.tab === "today" ? "on" : ""}"><b>Today</b>filings${nAct ? html`<span class="badge">${nAct}</span>` : ""}</a>
    <a href="#/alerts" class="${r.tab === "alerts" ? "on" : ""}"><b>Alerts</b>thresholds</a>
    <a href="#/research" class="${r.tab === "research" ? "on" : ""}"><b>Research</b>promises</a>
    <a href="#/learn" class="${r.tab === "learn" ? "on" : ""}"><b>Learn</b>basics</a></nav>`.toString();
  renderSheet();
  renderAsk();
  if (r.th) { const el = document.getElementById(r.th); if (el) { state.openThread = r.th; el.scrollIntoView({ block: "center" }); } }
}

function renderSheet() {
  let el = $("#sheet");
  if (!state.sheet) { if (el) el.remove(); document.body.style.overflow = ""; return; }
  if (!el) { el = document.createElement("div"); el.id = "sheet"; document.body.appendChild(el); }
  const e = (state.events || []).find((x) => x.id === state.sheet);
  const body = state.sheet === "ranking" ? rankingSheet(state.calibration) : e ? eventSheet(e, ctx) : null;
  el.innerHTML = body ? html`<div class="scrim" data-act="closeSheet"><div class="sheet" data-stop="1"><div class="grab"></div>
    <button class="close" data-act="closeSheet">Close</button>${body}</div></div>`.toString() : "";
  document.body.style.overflow = "hidden";
}

// --------------------------------------------------------------------- ask
// Floating helper: glossary first (instant, free); AI only when asked.
const SUGGEST = {
  today: ["What do Act, Know and Hidden mean?", "What does 'vs Nifty' mean?", "What is EBITDA?"],
  alerts: ["What is 20-day average volume?", "What does '2× usual move' mean?", "Why do stocks move on results?"],
  research: ["What does 'goalposts moved' mean?", "What is constant currency?", "What is cash conversion?"],
  learn: ["What is a filing?", "What's the difference between QoQ and YoY?", "What is a promoter pledge?"],
};
function renderAsk() {
  let fab = $("#askfab");
  if (!fab) { fab = document.createElement("button"); fab.id = "askfab"; fab.className = "askfab"; fab.dataset.act = "ask";
    fab.innerHTML = '<span class="q">?</span>Ask'; fab.setAttribute("aria-label", "Ask about anything on this screen"); document.body.appendChild(fab); }
  fab.style.display = state.ask.open || state.sheet ? "none" : "";
  let el = $("#ask");
  if (!state.ask.open) { el?.remove(); if (!state.sheet) document.body.style.overflow = ""; return; }
  if (!el) { el = document.createElement("div"); el.id = "ask"; document.body.appendChild(el); }
  const r = route();
  const a = state.ask;
  el.innerHTML = html`<div class="askwrap" data-act="askClose"><div class="askpanel" data-stop="1">
    <button class="close" data-act="askClose" style="float:right;color:var(--link)">Close</button>
    <h3>Ask FINN</h3><div class="small muted">Any word or number you don't understand, in plain language.${r.t ? ` You're looking at ${r.t}.` : ""}</div>
    <form class="askform" data-form="ask"><input name="q" value="${a.q}" placeholder="e.g. What is EBITDA margin?" autocomplete="off" enterkeyhint="send"><button>Ask</button></form>
    ${!a.items.length ? html`<div class="chips" style="flex-wrap:wrap">${(SUGGEST[r.tab] || SUGGEST.today).map((q) => html`<button class="chip" data-act="askSuggest" data-q="${q}">${q}</button>`)}</div>` : ""}
    ${a.items.map((it) => html`<div class="answer"><div class="small muted" style="margin-bottom:6px">${it.q}</div>
      ${it.gloss.map((g) => html`<div><b class="serif" style="font-size:17px">${g[0]}</b> ${g[2]}${g[3] ? html`<div class="small ink2" style="margin-top:4px">In FINN · ${g[3]}</div>` : ""}</div>`)}
      ${it.ai ? html`<div style="${it.gloss.length ? "margin-top:10px;border-top:1px solid var(--rule);padding-top:10px" : ""}">${it.ai}</div><div class="src">Explained by AI from general knowledge · not investment advice</div>`
        : it.loading ? html`<div class="src">Asking…</div>`
        : it.err ? html`<div class="src">${it.err}</div>`
        : html`<button class="small" style="color:var(--link);margin-top:8px" data-act="askAI" data-i="${a.items.indexOf(it)}">${it.gloss.length ? "Explain more simply with AI ›" : "Ask AI ›"}</button>`}
    </div>`)}
  </div></div>`.toString();
  document.body.style.overflow = "hidden";
}

function askQuestion(q) {
  q = (q || "").trim().slice(0, 300);
  if (!q) return;
  const gloss = searchGlossary(q, 2);
  const item = { q, gloss, ai: null, loading: false, err: null };
  state.ask.items = [item, ...state.ask.items].slice(0, 6);
  state.ask.q = "";
  if (!gloss.length) askAI(item); else renderAsk();
}

async function askAI(item) {
  item.loading = true; renderAsk();
  const r = route();
  try {
    const res = await fetch(`api/ask?q=${encodeURIComponent(item.q)}&screen=${r.tab}${r.t ? `&t=${encodeURIComponent(r.t)}` : ""}`);
    const j = await res.json().catch(() => ({}));
    if (!res.ok || !j.answer) throw new Error(j.error || `error ${res.status}`);
    item.ai = j.answer;
  } catch (e) {
    item.err = "Couldn't reach the AI helper just now. The Learn tab has plain-language explanations of every term.";
  }
  item.loading = false; renderAsk();
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
// Written for the ear: no brackets, codes or symbols that a speech engine reads literally.
const QMONTH = { 1: "June", 2: "September", 3: "December", 4: "March" };
function speakable(t) {
  return String(t || "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/(\w)\(s\)/gi, "$1s")                                   // manager(s) -> managers
    .replace(/\bQ([1-4])\s?FY\s?'?(\d{2})\b/gi, (_, q, y) => `the ${QMONTH[q]} ${q === "4" ? 2000 + +y : 1999 + +y} quarter`)
    .replace(/\bFY\s?'?(\d{2})\b/g, (_, y) => `financial year 20${y}`)
    .replace(/(?:₹|\bRs\.?|\bINR)\s?([\d,.]+)\s?(cr|crores?|lakhs?|mn|bn)?\b\.?/gi, (_, n, u) =>
      `${n} ${u ? { cr: "crore", crore: "crore", crores: "crore", lakh: "lakh", lakhs: "lakh", mn: "million", bn: "billion" }[u.toLowerCase()] + " " : ""}rupees`)
    .replace(/(\d)\s?[-–]\s?(\d)/g, "$1 to $2")                     // 3-5% -> 3 to 5 percent
    .replace(/(\d)\s?%/g, "$1 percent")
    .replace(/\bw\.?e\.?f\.?/gi, "from").replace(/\bReg\.?\s?(\d+)/g, "Regulation $1")
    .replace(/\bKMP\b/g, "key management").replace(/\bYoY\b/g, "year on year").replace(/\bQoQ\b/g, "quarter on quarter")
    .replace(/\bLtd\.?/g, "Limited").replace(/\bPvt\.?/g, "Private").replace(/\bvs\.?\b/gi, "versus").replace(/\bapprox\.?/gi, "about")
    .replace(/\bNo\.\s?(\d)/g, "number $1").replace(/&/g, " and ").replace(/\s\/\s|\//g, " or ")
    .replace(/\([^)]*\)/g, "").replace(/[\[\]{}*_#|"“”]/g, "").replace(/\s+([,.])/g, "$1").replace(/\s+/g, " ").trim();
}
const lc = (s) => (s ? s[0].toLowerCase() + s.slice(1) : s);
const CHANGE = { appointed: "has been appointed", resigned: "has resigned", retired: "is retiring", redesignated: "has been redesignated", ceased: "has stepped down" };

function briefScript() {
  const { win, evs } = V.todayEvents(state);
  const spoken = (t) => state.meta?.portfolio?.find((c) => c.t === t)?.spoken || state.nameOf(t);
  const pct = (v) => (v == null ? "" : `${v < 0 ? "down" : "up"} ${Math.abs(v).toFixed(1)} percent`);
  const crore = (v) => `${Math.round(v).toLocaleString("en-IN")} crore rupees`;
  const act = evs.filter((e) => e.tier === "act").sort((a, b) => b.score - a.score);
  const know = evs.filter((e) => e.tier === "know");
  const hidden = evs.filter((e) => e.tier === "hidden").reduce((s, e) => s + e.filings.length, 0);
  // A filing's own subject is often legal boilerplate; say it plainly instead.
  const plain = (e) => {
    const one = e.oneliner || "";
    const legal = /regulation|schedule|pursuant|read with|disclosure under|intimation/i.test(one);
    return !one || legal || one.length > 140 ? lc(e.why[0] || e.category.replace("_", " ")) : one.split(/(?<=[a-z])\. /)[0];
  };
  const lines = [`${V.windowLabel(state, win)}. ${act.length ? `${act.length === 1 ? "One thing needs" : `${act.length} things need`} your attention.` : "Nothing needs your attention."}`];
  for (const e of act.slice(0, 5)) {
    const c = e.card;
    if (c?.type === "results") {
      const rev = c.rows.find((r) => r.k === "Revenue"), pat = c.rows.find((r) => r.k === "PAT");
      lines.push(`${spoken(e.ticker)} reported results. Revenue was ${rev ? crore(rev.v) : "not available"}${rev?.yoy != null ? `, ${pct(rev.yoy)} from a year ago` : ""}.${pat?.yoy != null ? ` Profit after tax was ${pct(pat.yoy)}.` : ""}`);
    } else if (c?.type === "mgmt") {
      const p = c.people[0];
      lines.push(`At ${spoken(e.ticker)}, ${p.name} ${CHANGE[p.change] || p.change || "changes role"}${p.role ? ` as ${p.role}` : ""}.${p.profile ? " " + p.profile.split(/(?<=[a-z])\. /)[0] + "." : ""}`);
    } else lines.push(`${spoken(e.ticker)}: ${plain(e)}.`);
  }
  if (know.length) lines.push(`Also worth knowing. ${know.slice(0, 4).map((e) => `${spoken(e.ticker)}: ${plain(e)}`).join(". ")}.`);
  const p = state.prices;
  if (p) {
    const moves = scanAlerts(p, state.settings, p.dates.length - 1);
    if (moves.length) lines.push(`Unusual moves in the last session. ${moves.slice(0, 3).map((x) => `${spoken(x.t)} ${x.price ? `moved ${pct(x.ret)}` : "traded"}${x.vol ? ` on ${x.volx.toFixed(1)} times its normal volume` : ""}`).join(". ")}.`);
  }
  lines.push(`${hidden ? `${hidden} routine filings were tucked away. ` : ""}That's your brief.`);
  return lines.map(speakable).map((l) => l.replace(/\.\./g, ".")).filter(Boolean);
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
  if ((a.dataset.act === "closeSheet" || a.dataset.act === "askClose") && ev.target.closest("[data-stop]") && !ev.target.closest(".close")) return;
  const s = state.settings;
  switch (a.dataset.act) {
    case "win": s.window = a.dataset.w; state.windowTouched = true; break;
    case "event": state.sheet = a.dataset.id; renderSheet(); return;
    case "closeSheet": state.sheet = null; renderSheet(); return;
    case "ranking": state.sheet = "ranking"; renderSheet(); return;
    case "co": state.sheet = null; location.hash = `#/research/${a.dataset.t}`; return;
    case "toggleHidden": state.showHidden = !state.showHidden; break;
    case "listen": toggleListen(); return;
    case "mode": s.relative = a.dataset.v === "1"; break;
    case "cat": s.cats = s.cats.includes(a.dataset.c) ? s.cats.filter((c) => c !== a.dataset.c) : [...s.cats, a.dataset.c]; break;
    case "thread": state.openThread = state.openThread === a.dataset.id ? null : a.dataset.id; break;
    case "retry": delete state.research[a.dataset.t]; break;
    case "theme": state.theme = THEMES[(THEMES.indexOf(state.theme) + 1) % 3]; store.set("theme", state.theme); applyTheme(); break;
    case "ask": state.ask.open = true; renderAsk(); setTimeout(() => document.querySelector(".askform input")?.focus(), 50); return;
    case "askClose": state.ask.open = false; renderAsk(); return;
    case "askSuggest": askQuestion(a.dataset.q); return;
    case "askAI": askAI(state.ask.items[+a.dataset.i]); return;
    default: return;
  }
  store.set("settings", s);
  render();
});

document.addEventListener("input", (ev) => {
  if (ev.target.matches("[data-gloss]")) {  // glossary filter: re-render, keep focus and caret
    state.glossQ = ev.target.value;
    const y = window.scrollY;
    render();
    window.scrollTo(0, y);
    const el = document.querySelector("[data-gloss]");
    el?.focus(); el?.setSelectionRange(el.value.length, el.value.length);
    return;
  }
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
  if (ev.target.closest("[data-form=ask]")) {
    ev.preventDefault();
    askQuestion(new FormData(ev.target).get("q").toString());
    return;
  }
  const f = ev.target.closest("[data-form=search]");
  if (!f) return;
  ev.preventDefault();
  const t = new FormData(f).get("t").toString().trim().toUpperCase().replace(/\.NS$/, "");
  if (t) location.hash = `#/research/${encodeURIComponent(t)}`;
});

window.addEventListener("hashchange", () => { state.sheet = null; state.ask.open = false; state.openThread = route().th || null; render(); window.scrollTo(0, 0); });
// "New since you last looked": remember when the Today screen was last open.
const markSeen = () => { if (route().tab === "today" && state.events) store.set("lastSeen", Date.now()); };
document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && markSeen());
window.addEventListener("pagehide", markSeen);

load();
