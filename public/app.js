// Boot, hash router, one delegated click handler, settings in localStorage.
import { html, raw, fmtDay, ago, scanAlerts } from "./lib.js";
import { eventSheet, rankingSheet } from "./cards.js";
import * as V from "./views.js";
import { learn, searchGlossary } from "./learn.js";
import * as Acc from "./account.js";

const DEFAULTS = { window: "24h", relative: true, sigma: 2.5, pricePct: 3, volX: 2,
  cats: ["results", "management_change", "M&A", "fund_raise", "litigation", "pledging", "credit_rating"] };
const SYNCED = ["settings", "theme", "textSize", "voice", "voiceRate", "followed"];
const store = {
  get(k, d) { try { const v = localStorage.getItem("finn." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) {
    try { localStorage.setItem("finn." + k, JSON.stringify(v)); } catch { /* private mode / full */ }
    if (SYNCED.includes(k)) Acc.save(localPrefs());  // no-op unless signed in
  },
};
function localPrefs() {
  const o = {};
  for (const k of SYNCED) { const v = store.get(k, null); if (v != null) o[k] = v; }
  o.followed = o.followed || [];
  return o;
}

const state = {
  settings: { ...DEFAULTS, ...store.get("settings", {}) },
  lastSeen: store.get("lastSeen", 0),
  meta: null, events: null, prices: null, symbols: null,
  dossiers: {}, research: {}, showHidden: false, speaking: false, openThread: null, sheet: null, windowTouched: false,
  theme: store.get("theme", "auto"), glossQ: "", ask: { open: false, q: "", items: [] },
  followed: store.get("followed", []), acct: { step: "email", email: "", msg: "" },
};
// Empty list = follow all 18. Works without an account; signing in only syncs it.
state.isFollowed = (t) => !state.followed.length || state.followed.includes(t);
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
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", dark ? "#161C1B" : "#E3E9E2"));
  if (store.get("textSize", "standard") === "large") root.dataset.size = "large"; else delete root.dataset.size;
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

// Freshness lives at the bottom of Today and in Settings; up here only when something's wrong.
function freshness() {
  const st = state.meta?.status || {};
  const bad = Object.entries(st).filter(([, v]) => !v.ok).map(([k]) => k);
  const p = state.prices?.dates;
  if (!bad.length && !(state.loadError && !p)) return "";
  return html`<div class="fresh">
    ${bad.length ? html`<span class="bad">${bad.join(", ")} failed on the last run, so you're seeing the last good data.</span>` : ""}
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
    <header class="mast"><h1>FINN</h1>
      <div class="mast-actions"><button class="gear" data-act="ask" aria-label="Ask about anything on this screen"><span class="qmark">?</span></button>
      <button class="gear" data-act="settings" aria-label="Settings"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"></path></svg></button></div></header>
    <div class="mast-rule"></div>
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
  const body = state.sheet === "ranking" ? rankingSheet(state.calibration) : state.sheet === "settings" ? settingsSheet() : e ? eventSheet(e, ctx) : null;
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

// ---------------------------------------------------------------- settings
// Everything that's a preference lives here, saved on this device only.
function settingsSheet() {
  const opt = (act, val, cur, label) => html`<button class="chip ${val === cur ? "on" : ""}" data-act="${act}" data-v="${val}">${label}</button>`;
  const vs = voiceOptions();
  const rate = store.get("voiceRate", 1);
  const size = store.get("textSize", "standard");
  return html`<div class="settings"><h3>Settings</h3><div class="small muted">Saved on this device. No account needed.</div>
    ${accountGroup()}
    <div class="grp"><span>Stocks you follow</span>
      <div class="opts">${(state.meta?.portfolio || []).map((c) => html`<button class="chip ${state.followed.includes(c.t) ? "on" : ""}" data-act="follow" data-t="${c.t}">${c.t}</button>`)}</div>
      <div class="hint">${state.followed.length ? html`Today, Alerts and Listen show ${state.followed.length} of ${state.meta?.portfolio?.length || 18}. <button style="color:var(--link)" data-act="followAll">Follow all</button>` : "Following all holdings. Tap stocks to show only those."}</div></div>
    <div class="grp"><span>Appearance</span><div class="opts">${opt("setTheme", "auto", state.theme, "Match my phone")}${opt("setTheme", "light", state.theme, "Day")}${opt("setTheme", "dark", state.theme, "Night")}</div></div>
    <div class="grp"><span>Text size</span><div class="opts">${opt("setSize", "standard", size, "Standard")}${opt("setSize", "large", size, "Larger")}</div></div>
    <div class="grp"><span>Listen: voice</span>
      ${vs.length ? html`<select data-voice aria-label="Voice">${vs.map((v) => html`<option value="${v.name}" ${v.on ? raw("selected") : ""}>${v.label}</option>`)}</select>`
        : html`<div class="hint">Your browser hasn't listed its voices yet. Open this again in a moment.</div>`}
      <div class="opts" style="margin-top:10px">${opt("setRate", "0.9", String(rate), "Slower")}${opt("setRate", "1", String(rate), "Normal")}${opt("setRate", "1.15", String(rate), "Faster")}
        <button class="chip" data-act="testVoice">▶ Try it</button></div>
      <div class="hint">Voices come from your phone or browser, so the list differs by device.</div></div>
    <div class="grp"><span>Today opens on</span><div class="opts">${["24h", "session", "7d", "30d"].map((w) => opt("setWindow", w, state.settings.window, w === "session" ? "Last session" : w))}</div>
      <div class="hint">With 24h, a quiet day (like a weekend) widens to the last trading session automatically.</div></div>
    <div class="grp"><span>"New" markers</span><button class="chip" data-act="resetSeen">Mark everything as seen</button></div>
    <div class="grp" style="border-bottom:0"><span>Data</span><div class="small ink2" style="line-height:1.7">
      ${state.meta?.portfolio?.length || 18} holdings on NSE<br>
      ${state.prices?.dates?.length ? html`Prices as of ${fmtDay(state.prices.dates.at(-1))} close<br>` : ""}
      ${state.meta?.status?.filings ? html`Filings checked ${ago(state.meta.status.filings.at)}<br>` : ""}
      ${state.meta?.generated_at ? html`Feed built ${ago(state.meta.generated_at)}` : ""}</div></div>
  </div>`;
}

function accountGroup() {
  if (!Acc.enabled) return "";
  const u = Acc.currentUser(), a = state.acct;
  if (u) return html`<div class="grp"><span>Account</span><div class="small ink2">Signed in as <b>${u.email}</b>. Your followed stocks, alert thresholds and settings sync across devices.</div>
    <button class="chip" style="margin-top:10px" data-act="signOut">Sign out</button></div>`;
  return html`<div class="grp"><span>Account (optional)</span>
    <div class="hint" style="margin:0 0 10px">Everything works without one. Sign in to sync your stocks, alerts and settings across devices.</div>
    ${a.step === "email"
      ? html`<form class="askform" data-form="email" style="margin:0"><input name="email" type="email" required placeholder="you@example.com" value="${a.email}" autocomplete="email"><button>Send code</button></form>`
      : html`<form class="askform" data-form="code" style="margin:0"><input name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required placeholder="6-digit code" autocomplete="one-time-code"><button>Sign in</button></form>
        <div class="hint">Code sent to ${a.email}. <button style="color:var(--link)" data-act="acctBack">Use a different email</button></div>`}
    ${a.msg ? html`<div class="hint">${a.msg}</div>` : ""}</div>`;
}

// ----------------------------------------------------------------- research
function researchView(t) {
  if (state.dossiers[t]) return V.dossier(state.dossiers[t], state);
  if (state.research[t]?.running && !state.research[t]?.error) return V.researchLoading(t, state.research[t], state);
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
  const tick = setInterval(() => route().t === t && render(), 1000);
  const done = () => { clearInterval(tick); if (route().t === t) render(); };
  // 1) Pre-built or recently cached: instant.
  let d = null;
  if ((state.meta?.research_ready || []).includes(t)) d = await getJSON(`data/research/${t}.json`).catch(() => null);
  if (!d && cached && Date.now() - new Date(cached.generated_at) < 3 * 864e5) d = cached;
  if (d) { state.dossiers[t] = d; state.research[t] = {}; return done(); }
  // 2) Live: show reported numbers first (~2 s), then fill in the promises.
  const call = (part) => fetch(`api/research?t=${encodeURIComponent(t)}${part ? `&part=${part}` : ""}`)
    .then(async (res) => { const j = await res.json().catch(() => ({ error: `Server error ${res.status}` })); if (!res.ok || j.error) throw new Error(j.error || `Server error ${res.status}`); return j; });
  const full = call("");
  try {
    const basic = await call("basic");
    if (!state.dossiers[t]) { state.dossiers[t] = basic; render(); }
  } catch (e) {
    state.research[t] = { ...state.research[t], basicError: e.message };
  }
  try {
    const f = await full;
    state.dossiers[t] = f;
    store.set("r." + t, f);
    state.research[t] = {};
  } catch (e) {
    const msg = /quota/i.test(e.message)
      ? "The free AI quota for today is used up, so the promises can't be read right now. The numbers above are complete; try again tomorrow."
      : `Couldn't read ${t}'s earnings calls just now (${e.message}).`;
    if (state.dossiers[t]) state.research[t] = { fullError: msg };
    else state.research[t] = { error: `Couldn't build research for ${t}: ${e.message}. Check the symbol, or try again in a minute.` };
  }
  done();
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
  const spoken = (t) => `§${t}§`;  // placeholder: written name on screen, spoken name in the voice
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
    const moves = scanAlerts(V.followedPrices(state), state.settings, p.dates.length - 1);
    if (moves.length) lines.push(`Unusual moves in the last session. ${moves.slice(0, 3).map((x) => `${spoken(x.t)} ${x.price ? `moved ${pct(x.ret)}` : "traded"}${x.vol ? ` on ${x.volx.toFixed(1)} times its normal volume` : ""}`).join(". ")}.`);
  }
  lines.push(`${hidden ? `${hidden} routine filings were tucked away. ` : ""}That's your brief.`);
  const name = (t) => state.meta?.portfolio?.find((c) => c.t === t)?.name || state.nameOf(t);
  const voiceName = (t) => state.meta?.portfolio?.find((c) => c.t === t)?.spoken || state.nameOf(t);
  return lines.map(speakable).map((l) => l.replace(/\.\./g, ".")).filter(Boolean).map((l) => ({
    show: l.replace(/§([A-Z0-9&-]+)§/g, (_, t) => name(t)),
    say: l.replace(/§([A-Z0-9&-]+)§/g, (_, t) => voiceName(t)),
  }));
}

// Chrome loads its voice list late; picking before it arrives grabbed whatever
// voice came first. Wait for it, keep the earlier default, and let people choose.
let VOICES = [];
function loadVoices() {
  const v = window.speechSynthesis?.getVoices() || [];
  VOICES = v.filter((x) => x.lang?.toLowerCase().startsWith("en"));
  if (VOICES.length && state.sheet === "settings") renderSheet();
}
if (window.speechSynthesis) { loadVoices(); speechSynthesis.addEventListener?.("voiceschanged", loadVoices); }
function pickVoice() {
  const want = store.get("voice", null);
  return VOICES.find((v) => v.name === want) || VOICES.find((v) => v.lang === "en-IN") ||
    VOICES.find((v) => v.lang?.startsWith("en-GB")) || VOICES[0] || null;
}
function voiceOptions() {
  const cur = pickVoice()?.name;
  return VOICES.map((v) => ({ name: v.name, label: `${v.name.replace(/^(Microsoft|Google)\s+/, "").replace(/\s+Online.*$/, "")} (${v.lang})`, on: v.name === cur }));
}

function toggleListen() {
  const synth = window.speechSynthesis;
  if (!synth) { alertLine("Your browser can't read aloud."); return; }
  if (state.speaking) { synth.cancel(); state.speaking = false; captions(null); render(); return; }
  const lines = briefScript();
  const voice = pickVoice();
  state.speaking = true; render();
  lines.forEach((line, i) => {
    const u = new SpeechSynthesisUtterance(line.say);
    if (voice) { u.voice = voice; u.lang = voice.lang; }
    u.rate = +store.get("voiceRate", 1) || 1;
    u.onstart = () => captions(line.show, i + 1, lines.length);
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
document.addEventListener("change", (ev) => {
  if (ev.target.matches("[data-range]")) {
    const v = ev.target.value;
    if (ev.target.dataset.range === "from") state.customFrom = v; else state.customTo = v;
    if (state.customFrom && state.customTo && state.customFrom > state.customTo) [state.customFrom, state.customTo] = [state.customTo, state.customFrom];
    render(); return;
  }
  if (ev.target.matches("[data-voice]")) { store.set("voice", ev.target.value); if (state.speaking) { speechSynthesis.cancel(); state.speaking = false; captions(null); } renderSheet(); }
});

// ----------------------------------------------------------------- events
document.addEventListener("click", (ev) => {
  const a = ev.target.closest("[data-act]");
  if (!a) return;
  if ((a.dataset.act === "closeSheet" || a.dataset.act === "askClose") && ev.target.closest("[data-stop]") && !ev.target.closest(".close")) return;
  const s = state.settings;
  switch (a.dataset.act) {
    case "win": state.viewWindow = a.dataset.w; state.windowTouched = true;  // this visit only
      if (a.dataset.w === "custom" && !state.customFrom) { const [lo, hi] = V.dataRange(state); state.customTo = hi;
        const d = new Date(hi + "T12:00:00+05:30"); d.setDate(d.getDate() - 6); const f = d.toLocaleDateString("en-CA"); state.customFrom = f < lo ? lo : f; }
      render(); return;
    case "event": state.sheet = a.dataset.id; renderSheet(); return;
    case "closeSheet": state.sheet = null; renderSheet(); return;
    case "ranking": state.sheet = "ranking"; renderSheet(); return;
    case "co": state.sheet = null; location.hash = `#/research/${a.dataset.t}`; return;
    case "toggleHidden": state.showHidden = !state.showHidden; break;
    case "listen": toggleListen(); return;
    case "mode": s.relative = a.dataset.v === "1"; break;
    case "cat": s.cats = s.cats.includes(a.dataset.c) ? s.cats.filter((c) => c !== a.dataset.c) : [...s.cats, a.dataset.c]; break;
    case "thread": state.openThread = state.openThread === a.dataset.id ? null : a.dataset.id; break;
    case "retry": delete state.research[a.dataset.t]; if (state.dossiers[a.dataset.t]?.partial) delete state.dossiers[a.dataset.t]; break;
    case "settings": state.sheet = "settings"; renderSheet(); return;
    case "setTheme": state.theme = a.dataset.v; store.set("theme", state.theme); applyTheme(); renderSheet(); return;
    case "setSize": store.set("textSize", a.dataset.v); applyTheme(); renderSheet(); return;
    case "setRate": store.set("voiceRate", +a.dataset.v); renderSheet(); return;
    case "setWindow": s.window = a.dataset.v; state.viewWindow = null; state.windowTouched = false; store.set("settings", s); renderSheet(); render(); return;
    case "testVoice": { const v = pickVoice(); speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance("This is how your brief will sound."); if (v) { u.voice = v; u.lang = v.lang; } u.rate = +store.get("voiceRate", 1) || 1; speechSynthesis.speak(u); return; }
    case "resetSeen": store.set("lastSeen", Date.now()); location.reload(); return;
    case "follow": { const t = a.dataset.t; state.followed = state.followed.includes(t) ? state.followed.filter((x) => x !== t) : [...state.followed, t];
      store.set("followed", state.followed); renderSheet(); render(); return; }
    case "followAll": state.followed = []; store.set("followed", []); renderSheet(); render(); return;
    case "signOut": Acc.signOut(); return;
    case "acctBack": state.acct = { step: "email", email: state.acct.email, msg: "" }; renderSheet(); return;
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

document.addEventListener("submit", async (ev) => {
  const af = ev.target.closest("[data-form=email], [data-form=code]");
  if (af) {
    ev.preventDefault();
    const a = state.acct;
    try {
      if (af.dataset.form === "email") {
        a.email = new FormData(af).get("email").toString().trim();
        a.msg = "Sending…"; renderSheet();
        await Acc.sendCode(a.email);
        Object.assign(a, { step: "code", msg: "Check your inbox (and spam) for a 6-digit code." });
      } else {
        a.msg = "Checking…"; renderSheet();
        await Acc.verifyCode(a.email, new FormData(af).get("code").toString().trim());
        Object.assign(a, { step: "email", msg: "" });
      }
    } catch (e) { a.msg = e.message.includes("rate") ? "Too many emails sent just now. Try again in a few minutes." : e.message; }
    renderSheet();
    return;
  }
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
Acc.init({
  getLocal: localPrefs,
  applyRemote: (p) => {  // the account's saved prefs win over this device's
    for (const k of SYNCED) if (p[k] != null) try { localStorage.setItem("finn." + k, JSON.stringify(p[k])); } catch { /* ignore */ }
    state.settings = { ...DEFAULTS, ...store.get("settings", {}) };
    state.theme = store.get("theme", "auto");
    state.followed = store.get("followed", []);
    applyTheme(); render();
  },
  changed: () => { if (state.sheet === "settings") renderSheet(); },
});
