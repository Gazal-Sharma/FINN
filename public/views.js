// Screens: Today, Alerts, Research. Each returns an html`` string from state.
import { html, raw, fmtPct, fmtCr, tone, fmtDay, fmtWhen, ago, spark, scanAlerts } from "./lib.js";
import { eventCard, knowRow, threadRow, reactionChip } from "./cards.js";

export const CATS = [["results", "Results"], ["management_change", "Mgmt change"], ["M&A", "M&A"], ["fund_raise", "Fund raise"],
  ["litigation", "Litigation"], ["pledging", "Pledging"], ["credit_rating", "Credit rating"], ["insider_trading", "Insider trades"],
  ["capex", "Capex"], ["press_release", "Orders / PR"], ["dividend", "Dividend"], ["bonus_split", "Bonus / split"]];

// ------------------------------------------------------------------- Today
export function windowStart(state, win) {
  const now = Date.now();
  if (win === "custom" && state.customFrom) return new Date(state.customFrom + "T00:00:00+05:30").getTime();
  if (win === "24h") return now - 864e5;
  if (win === "7d") return now - 7 * 864e5;
  if (win === "30d") return now - 30 * 864e5;
  const d = state.prices?.dates || [];
  const prev = d[d.length - 2];
  return prev ? new Date(prev + "T15:30:00+05:30").getTime() : now - 3 * 864e5;
}

export function windowEnd(state, win) {
  return win === "custom" && state.customTo ? new Date(state.customTo + "T23:59:59+05:30").getTime() : Infinity;
}

export function dataRange(state) {
  const ts = (state.events || []).map((e) => e.ts).filter(Boolean).sort();
  const day = (iso) => new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  return ts.length ? [day(ts[0]), day(ts.at(-1))] : [null, null];
}

export function windowLabel(state, win) {
  if (win === "custom") {
    const f = (d) => d ? new Date(d + "T12:00:00+05:30").toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "…";
    return `${f(state.customFrom)} – ${f(state.customTo)}`;
  }
  if (win === "session") { const d = state.prices?.dates || []; return `Since ${fmtDay(d[d.length - 2])} close`; }
  return { "24h": "Last 24 hours", "7d": "Last 7 days", "30d": "Last 30 days" }[win];
}

export function todayEvents(state) {
  const all = state.events || [];
  let win = state.viewWindow || state.settings.window, note = "";
  const pick = (w) => all.filter((e) => { const t = new Date(e.ts).getTime(); return t >= windowStart(state, w) && t <= windowEnd(state, w); });
  let evs = pick(win);
  if (!evs.some((e) => e.tier !== "hidden") && win === "24h" && !state.windowTouched) {
    for (const w of ["session", "7d"]) {
      const alt = pick(w);
      if (alt.some((e) => e.tier !== "hidden")) {
        note = `Nothing material in the last 24 hours${new Date().getDay() % 6 === 0 ? " (markets are shut today)" : ""}. Showing ${windowLabel(state, w).replace(/^./, (c) => c.toLowerCase())} instead.`;
        win = w; evs = alt; break;
      }
    }
  }
  return { win, note, evs };
}

export function today(state, ctx) {
  if (!state.events) return html`<div class="skel"></div><div class="skel"></div>`;
  const { win, note, evs } = todayEvents(state);
  const act = evs.filter((e) => e.tier === "act").sort((a, b) => b.score - a.score || (b.ts > a.ts ? 1 : -1));
  const know = evs.filter((e) => e.tier === "know").sort((a, b) => (b.ts > a.ts ? 1 : -1));
  const hid = evs.filter((e) => e.tier === "hidden");
  const nFilings = evs.reduce((s, e) => s + e.filings.length, 0);
  const hidByCat = {};
  hid.forEach((e) => (hidByCat[e.category] = (hidByCat[e.category] || 0) + e.filings.length));
  const hidFilings = Object.values(hidByCat).reduce((a, b) => a + b, 0);
  const moves = state.prices ? scanAlerts(state.prices, state.settings, state.prices.dates.length - 1) : [];
  const firstOld = know.findIndex((e) => !ctx.isNew(e));

  const [lo, hi] = dataRange(state);
  return html`
  <div class="strip">
    <div class="lede">${windowLabel(state, win)}
      <div class="counts">${act.length ? html`<mark>${act.length} need${act.length === 1 ? "s" : ""} you</mark>` : html`<b>Nothing needs you</b>`} · ${know.length} worth knowing</div></div>
    <button class="listen ${state.speaking ? "on" : ""}" data-act="listen">${state.speaking ? "■ Stop" : "▶ Listen"}</button>
  </div>
  <div class="chips">${["24h", "session", "7d", "30d", "custom"].map((w) => html`<button class="chip ${w === win ? "on" : ""}" data-act="win" data-w="${w}">${{ session: "Last session", custom: "Custom" }[w] || w}</button>`)}</div>
  ${win === "custom" ? html`<div class="range"><label>From <input type="date" data-range="from" min="${lo}" max="${hi}" value="${state.customFrom || lo}"></label>
     <label>To <input type="date" data-range="to" min="${lo}" max="${hi}" value="${state.customTo || hi}"></label>
     <div class="tiny muted">Filings are available from ${fmtDay(lo)} to ${fmtDay(hi)}.</div></div>` : ""}
  ${note ? html`<div class="note">${note}</div>` : ""}

  ${moves.length ? html`<a class="note" href="#/alerts" style="display:block;color:inherit;text-decoration:none">
     <b>Unusual moves, ${fmtDay(state.prices.dates.at(-1))}:</b> ${moves.slice(0, 4).map((m, i) => html`${i ? " · " : ""}${m.t} ${m.price ? fmtPct(m.ret) : ""}${m.vol ? ` ${m.volx.toFixed(1)}× vol` : ""}`)}${moves.length > 4 ? ` +${moves.length - 4} more` : ""} ›</a>` : ""}

  ${!act.length && !know.length ? html`<div class="allclear"><div class="big">Nothing needs you.</div>
     <p class="small muted">${hidFilings} routine filing${hidFilings === 1 ? "" : "s"} filed and hidden. FINN will tell you when something matters.</p></div>` : ""}

  ${act.length ? html`<div class="sec"><h2 class="act">Act</h2></div>${act.map((e) => eventCard(e, ctx))}` : ""}
  ${know.length ? html`<div class="sec"><h2>Know</h2></div>
     <div class="ruled">${know.map((e, i) => html`${i === firstOld && firstOld > 0 ? html`<div class="newline">seen before</div>` : ""}${knowRow(e, ctx)}`)}</div>` : ""}

  ${hid.length ? html`<button class="hiddenbar" data-act="toggleHidden" aria-expanded="${state.showHidden ? "true" : "false"}"><b>Drawer · ${hidFilings} routine filing${hidFilings === 1 ? "" : "s"} ${state.showHidden ? "▴" : "▾"}</b>${Object.entries(hidByCat).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${n} ${c.replace(/_/g, " ").replace("unclassified", "other")}`).join(", ")}</button>
     ${state.showHidden ? html`<div class="drawer-open">${hid.map((e) => knowRow(e, ctx))}</div>` : ""}` : ""}
  <p class="small muted" style="margin-top:12px">Tiers are rules checked against how the stocks actually reacted. <button style="color:var(--link)" data-act="ranking">How FINN ranks ›</button></p>

  ${pulse(state)}
  <p class="foot">${nFilings} filings in this window${state.prices?.dates?.length ? ` · prices as of ${fmtDay(state.prices.dates.at(-1))} close` : ""}${state.meta?.status?.filings ? ` · filings checked ${ago(state.meta.status.filings.at)}` : ""}</p>`;
}

function pulse(state) {
  const p = state.prices;
  if (!p || !p.dates.length) return "";
  const i = p.dates.length - 1;
  const nr = p.nifty[i] && p.nifty[i - 1] ? (p.nifty[i] / p.nifty[i - 1] - 1) * 100 : 0;
  const cells = Object.entries(p.t).map(([t, d]) => {
    const r = d.c[i] && d.c[i - 1] ? (d.c[i] / d.c[i - 1] - 1) * 100 : null;
    const a = r == null ? null : r - nr;
    return html`<button data-act="co" data-t="${t}"><b>${t}</b><span class="${tone(a)}">${fmtPct(a, 1)}</span></button>`;
  });
  return html`<div class="sec"><h2>Portfolio pulse</h2><span class="tiny muted">${fmtDay(p.dates[i])} · vs Nifty ${fmtPct(nr)}</span></div>
    <div class="pulse">${cells}</div>`;
}

// ------------------------------------------------------------------ Alerts
export function alerts(state) {
  const s = state.settings, p = state.prices;
  if (!p) return html`<div class="skel"></div>`;
  const n = p.dates.length, from = Math.max(21, n - 60);
  const all = scanAlerts(p, s, from);
  const days = n - from;
  const perDay = Array.from({ length: days }, () => ({ p: 0, v: 0 }));
  all.forEach((a) => { const k = perDay[a.i - from]; if (a.price) k.p++; if (a.vol) k.v++; });
  const byT = {};
  all.forEach((a) => (byT[a.t] = (byT[a.t] || 0) + 1));
  const top = Object.entries(byT).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const perWeek = (all.length / days) * 5;
  const recent = all.filter((a) => a.i >= n - 10).sort((a, b) => b.i - a.i || Math.abs(b.ret) - Math.abs(a.ret));
  const fil = (state.events || []).filter((e) => e.tier !== "hidden" && s.cats.includes(e.category) && new Date(e.ts) > Date.now() - 7 * 864e5);
  const maxDay = Math.max(1, ...perDay.map((d) => d.p + d.v));

  return html`
  <div class="sec"><h2>What counts as unusual</h2><span class="tiny muted">you decide; FINN watches</span></div>
  <div class="seg">
    <button class="${s.relative ? "on" : ""}" data-act="mode" data-v="1">Relative to each stock</button>
    <button class="${!s.relative ? "on" : ""}" data-act="mode" data-v="0">Fixed % move</button>
  </div>
  <div class="tiny muted">${s.relative ? "A move counts when it's bigger than N× that stock's usual daily move (60-day). ±3% is routine for DIXON, rare for HDFCBANK." : "Same % threshold for every stock."}</div>
  <div class="ctl">${s.relative
    ? html`<label>Price move <b>${s.sigma.toFixed(1)}× usual</b></label><input type="range" min="1.5" max="5" step="0.5" value="${s.sigma}" data-set="sigma">`
    : html`<label>Price move <b>±${s.pricePct.toFixed(1)}%</b></label><input type="range" min="1" max="10" step="0.5" value="${s.pricePct}" data-set="pricePct">`}</div>
  <div class="ctl"><label>Volume <b>${s.volX.toFixed(2).replace(/0$/, "")}× 20-day average</b></label>
    <input type="range" min="1.5" max="5" step="0.25" value="${s.volX}" data-set="volX"></div>

  <div class="backtest">
    <div class="caps">With these settings, over the last ${days} sessions</div>
    <div class="big">${all.length} alert${all.length === 1 ? "" : "s"} <span class="small muted">≈ ${perWeek.toFixed(1)} a week</span></div>
    <div class="dots">${perDay.map((d) => html`<i class="${d.p && d.v ? "pv" : d.p ? "p" : d.v ? "v" : ""}" style="height:${d.p + d.v ? 6 + ((d.p + d.v) / maxDay) * 20 : 3}px" title=""></i>`)}</div>
    <div class="tiny muted"><span style="color:var(--ink)">■</span> price <span style="color:var(--warn)">■</span> volume <span style="color:var(--act)">■</span> both · ${fmtDay(p.dates[from])} → ${fmtDay(p.dates[n - 1])}</div>
    ${top.length ? html`<div class="small" style="margin-top:6px">Most alerts: ${top.map(([t, c], i) => html`${i ? ", " : ""}<b>${t}</b> ${Math.round((c / all.length) * 100)}%`)}</div>` : ""}
  </div>

  <div class="sec"><h2>Filing alerts</h2><span class="tiny muted">types you care about</span></div>
  <div class="chips" style="flex-wrap:wrap">${CATS.map(([k, l]) => html`<button class="chip ${s.cats.includes(k) ? "on" : ""}" data-act="cat" data-c="${k}">${l}</button>`)}</div>
  ${fil.length ? fil.slice(0, 8).map((e) => html`<button class="alert" data-act="event" data-id="${e.id}">
      <div><b class="serif">${e.ticker}</b> <span class="small">${e.card?.type === "results" ? `Results · ${e.card.period}` : e.oneliner || e.title}</span><div class="tiny muted">${fmtWhen(e.ts)} · ${e.category.replace("_", " ")}</div></div>
      <span class="pill ${e.tier}">${e.tier === "act" ? "Act" : "Know"}</span></button>`)
    : html`<p class="small muted">No filings of these types in the last 7 days.</p>`}

  <div class="sec"><h2>Price and volume alerts</h2><span class="tiny muted">last 10 sessions</span></div>
  ${recent.length ? recent.slice(0, 15).map((a) => html`<button class="alert" data-act="co" data-t="${a.t}">
      <div><b class="serif">${a.t}</b> <span class="small">${a.price ? html`<span class="${tone(a.ret)}">${fmtPct(a.ret)}</span>${a.sig ? html` <span class="muted">(${(Math.abs(a.ret) / a.sig).toFixed(1)}× usual)</span>` : ""}` : ""}${a.price && a.vol ? " · " : ""}${a.vol ? `${a.volx.toFixed(1)}× volume` : ""}</span>
      <div class="tiny muted">${fmtDay(a.date)}</div></div>
      <div style="width:90px">${spark(p.t[a.t].c.slice(Math.max(0, a.i - 29), a.i + 1), { w: 90, h: 28, mark: Math.min(29, a.i) })}</div></button>`)
    : html`<p class="small muted">Nothing crossed your thresholds in the last 10 sessions.</p>`}`;
}

// ---------------------------------------------------------------- Research
export function researchHome(state) {
  const ready = state.meta?.research_ready || [];
  const port = (state.meta?.portfolio || []).filter((c) => !ready.includes(c.t));
  return html`
  <form class="search" data-form="search">
    <input name="t" list="syms" placeholder="Any NSE symbol, e.g. TATAPOWER" autocomplete="off" autocapitalize="characters" spellcheck="false">
    <button>Research</button>
  </form>
  <datalist id="syms">${(state.symbols || []).slice(0, 3000).map(([s, n]) => html`<option value="${s}">${n}</option>`)}</datalist>
  <p class="small ink2">FINN reads the last four earnings-call transcripts, pulls out every promise management made, checks each quote word-for-word against the transcript, then scores it against the reported numbers. No news, no broker notes, no model memory.</p>
  <div class="sec"><h2>Ready to read</h2><span class="tiny muted">pre-built</span></div>
  <div class="tiles">${ready.map((t) => html`<a href="#/research/${t}"><b>${t}</b><span class="tiny muted">${state.nameOf(t)}</span></a>`)}</div>
  <div class="sec"><h2>Your portfolio</h2><span class="tiny muted">built live, ~1 min</span></div>
  <div class="tiles">${port.map((c) => html`<a href="#/research/${c.t}"><b>${c.t}</b><span class="tiny muted">${c.name}</span></a>`)}</div>`;
}

export function researchLoading(t, r, state) {
  const secs = Math.round((Date.now() - r.started) / 1000);
  return html`<div class="dossier-h"><div class="co">${state.nameOf(t)}<small>${t}</small></div></div>
  ${recentFor(t, state)}
  <div class="card"><div class="caps">Building live · ${secs}s</div>
   <ol class="progress small">
    <li>Find the last four earnings-call transcripts</li>
    <li>Extract every forward-looking promise (cheap model)</li>
    <li>Check each quote word-for-word against the transcript; drop any that don't match</li>
    <li>Score promises against reported numbers (code, not AI)</li>
    <li>Write the verdict from verified records only (strong model)</li>
   </ol><p class="tiny muted">Usually 30–90 seconds. The result is cached, so the next person gets it instantly.</p></div>`;
}

export function recentFor(t, state) {
  const evs = (state.events || []).filter((e) => e.ticker === t && e.tier !== "hidden").slice(0, 3);
  if (!evs.length) return "";
  return html`<div class="sec"><h2>Recent filings</h2></div>${evs.map((e) => html`<button class="row" data-act="event" data-id="${e.id}">
    <div class="tiny muted">${fmtWhen(e.ts)}</div><div class="l">${e.card?.type === "results" ? `Results · ${e.card.period}` : e.oneliner || e.title} ${reactionChip(e.reaction)}</div></button>`)}`;
}

function credLine(cr) {
  const bits = [];
  if (cr.resolved) bits.push(html`Kept <b>${cr.kept}</b> of ${cr.resolved} that came due`);
  if (cr.missed) bits.push(html`<span class="down">${cr.missed} missed</span>`);
  if (cr.on_track) bits.push(html`<span class="up">${cr.on_track} on track</span>`);
  if (cr.off_track) bits.push(html`<span class="down">${cr.off_track} off track</span>`);
  if (cr.dropped) bits.push(html`<span class="muted">${cr.dropped} quietly dropped</span>`);
  if (cr.moved) bits.push(html`<span class="warn">goalposts moved ${cr.moved === 1 ? "once" : `${cr.moved}×`}</span>`);
  if (cr.unverifiable) bits.push(html`<span class="muted">${cr.unverifiable} not checkable</span>`);
  return bits.length ? html`${bits.map((b, i) => html`${i ? " · " : ""}${b}`)}` : "No measurable promises in these calls.";
}

function promisesWaiting(d, state) {
  const r = state.research[d.ticker] || {};
  if (r.fullError) return html`<div class="note">${r.fullError}</div><button class="listen" data-act="retry" data-t="${d.ticker}">Try again</button>`;
  const secs = r.started ? Math.round((Date.now() - r.started) / 1000) : 0;
  return html`<div class="waiting"><b style="color:var(--head)">Reading ${d.calls?.length || 4} earnings calls…</b>
    <div class="small ink2" style="margin-top:4px">Pulling out every promise, checking each quote word for word, then scoring it against the numbers below. Usually under a minute${secs ? ` · ${secs}s` : ""}.</div>
    <div class="bar"><i></i></div></div>`;
}

export function dossier(d, state) {
  const cr = d.credibility, st = d.stats, syn = d.synthesis, nb = d.numbers;
  const threads = d.threads || [];
  const q = nb?.quarters || {}, y = nb?.years || {}, b = nb?.balance || {};
  return html`
  <div class="dossier-h">
    <div class="co">${d.name}<small>${d.ticker}${d.live ? " · built live" : ""}</small></div>
    <div class="tiny muted">${d.calls?.length ? `Calls: ${d.calls.join(", ")} · ` : ""}${d.partial ? "numbers ready" : `built ${ago(d.generated_at)}`}</div>
  </div>
  ${recentFor(d.ticker, state)}

  <div class="sec"><h2>Promised vs delivered</h2><span class="tiny muted">last ${d.calls?.length || 4} calls</span></div>
  ${d.partial ? promisesWaiting(d, state) : d.no_transcripts ? html`<div class="note">No earnings-call transcripts found for ${d.ticker} in the last year. Without management's own words FINN won't guess what they promised. The numbers below are still real.</div>` : html`
   <div class="cred">${credLine(cr)}</div>
   <span class="verified">✓ ${st.verified} quotes verified in source · ${st.dropped_quote + st.dropped_number} dropped</span>
   ${syn ? html`<p class="serif" style="font-size:17px;margin:12px 0 4px">${syn.headline}</p>
     <div class="pts">${syn.points.map((p) => html`<p>${p.text}${p.refs.map((r) => html`<a class="ref" href="#/research/${d.ticker}/${r}">${r}</a>`)}</p>`)}</div>` : ""}
   <div class="ledgerbox">${threads.map((t) => threadRow(t, d.calls, state.openThread === t.id))}</div>
   <p class="tiny muted">Tap a promise for the exact quote. Actuals are computed from reported numbers in code. ≈ means guidance was in constant currency or USD and we checked against INR.</p>`}

  ${syn && (syn.bull?.length || syn.bear?.length) ? html`<div class="sec"><h2>Bull vs bear</h2></div>
    <div class="bb"><div><h3 class="up">Bull</h3>${syn.bull.map((p) => html`<p>${p.text}${p.refs.map((r) => html`<span class="ref">${r}</span>`)}</p>`)}</div>
    <div><h3 class="down">Bear</h3>${syn.bear.map((p) => html`<p>${p.text}${p.refs.map((r) => html`<span class="ref">${r}</span>`)}</p>`)}</div></div>` : ""}

  ${nb ? html`<div class="sec"><h2>Numbers</h2><span class="tiny muted">₹ cr · ${nb.basis || ""} · F1–F6</span></div>
   <div class="kv">
     <div><span class="tiny muted">Revenue, ${q.labels?.at(-1) || ""}</span><b>${fmtCr(q.revenue?.at(-1))}</b>${spark(q.revenue || [], { w: 100, h: 26 })}</div>
     <div><span class="tiny muted">${d.lender ? "Op." : "EBITDA"} margin</span><b>${q.opm?.at(-1) ?? "—"}%</b>${spark(q.opm || [], { w: 100, h: 26 })}</div>
     <div><span class="tiny muted">PAT</span><b>${fmtCr(q.pat?.at(-1))}</b>${spark(q.pat || [], { w: 100, h: 26 })}</div>
   </div>
   <table class="res"><thead><tr><th>Year</th><th>Revenue</th><th>Margin</th><th>PAT</th><th>Cash from ops</th></tr></thead>
   <tbody>${(y.labels || []).map((l, i) => html`<tr><td>${l}</td><td>${fmtCr(y.revenue[i])}</td><td>${y.opm[i] ?? "—"}%</td><td>${fmtCr(y.pat[i])}</td><td>${fmtCr(y.cfo?.[i])}</td></tr>`)}</tbody></table>
   <div class="kv">
     <div><span class="tiny muted">Cash conversion (CFO/PAT, 3y)</span><b>${nb.cash_conversion_3y?.length ? nb.cash_conversion_3y.map((x) => x.toFixed(2)).join(" · ") : "—"}</b><span class="tiny ${nb.cash_conversion_3y?.some((x) => x < 0.7) ? "down" : "muted"}">${nb.cash_conversion_3y?.some((x) => x < 0.7) ? "profit not turning into cash" : "profit turns into cash"}</span></div>
     <div><span class="tiny muted">Debt / equity</span><b>${b.de ?? "—"}</b><span class="tiny muted">borrowings ₹${fmtCr(b.borrowings)} cr</span></div>
     <div><span class="tiny muted">${b.ccc != null ? "Cash conversion cycle" : "ROCE"}</span><b>${b.ccc != null ? `${b.ccc} days` : b.roce != null ? `${b.roce}%` : "—"}</b><span class="tiny muted">${b.ccc != null && b.ccc_prev != null ? `${b.ccc_prev} days 3y ago` : b.roce != null && b.ccc != null ? `ROCE ${b.roce}%` : ""}</span></div>
   </div>` : ""}

  ${d.business ? html`<div class="sec"><h2>The business</h2><span class="tiny muted">in management's words, ${d.business.call}</span></div>
   <p>${d.business.what}</p>
   ${d.business.segments?.length ? html`<ul class="small">${d.business.segments.map((s) => html`<li><b>${s.name}</b>${s.note ? ` — ${s.note}` : ""}</li>`)}</ul>` : ""}
   ${d.business.quote && d.business.quote_verified ? html`<div class="quote">“${d.business.quote}”</div>` : ""}` : ""}

  <div class="sec"><h2>Sources</h2><span class="tiny muted">primary only</span></div>
  <ul class="small">${(d.docs?.transcripts || []).map((x) => html`<li><a href="${x.url}" target="_blank" rel="noopener">${x.call} earnings-call transcript</a></li>`)}
   ${(d.docs?.annual_reports || []).map((x) => html`<li><a href="${x.url}" target="_blank" rel="noopener">${x.label}</a></li>`)}
   ${d.docs?.screener ? html`<li><a href="${d.docs.screener}" target="_blank" rel="noopener">Reported financials (screener.in tables)</a></li>` : ""}</ul>`;
}
