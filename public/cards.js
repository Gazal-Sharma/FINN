// Card renderers. Every value from data goes through html`` (escaped).
import { html, raw, fmtCr, fmtPct, tone, fmtWhen } from "./lib.js";

export function reactionChip(r) {
  if (!r || r.status !== "ok") return html`<span class="react muted">Market: reacts next session</span>`;
  return html`<span class="react">Market <b class="${tone(r.abn)}">${fmtPct(r.abn)}</b> vs Nifty${r.vol_x ? html` · ${r.vol_x.toFixed(1)}× vol` : ""}</span>`;
}

function resultsBody(c) {
  const rows = c.rows.map((r) => html`<tr><td>${r.k}</td><td>${fmtCr(r.v)}</td>
    <td class="${tone(r.qoq)}">${fmtPct(r.qoq)}</td><td class="${tone(r.yoy)}">${fmtPct(r.yoy)}</td></tr>`);
  const m = c.margin;
  return html`
    <table class="res"><thead><tr><th>${c.period || "This quarter"}</th><th>${c.unit}</th><th>QoQ</th><th>YoY</th></tr></thead>
    <tbody>${rows}</tbody></table>
    ${m && m.now != null ? html`<div class="small ink2">${c.lender ? "Op. margin" : "EBITDA margin"} ${m.now}% · last qtr ${m.prev_q ?? "—"}% · year ago ${m.year_ago ?? "—"}%</div>` : ""}
    <div class="tiny muted" style="margin-top:4px">${c.ebitda_note}. ${c.basis ? html`${c.basis[0].toUpperCase() + c.basis.slice(1)}. ` : ""}Source: <a href="${c.src_url}" target="_blank" rel="noopener">${c.source}</a></div>`;
}

function mgmtBody(c) {
  const ppl = c.people.map((p) => html`<div class="person">
    <div class="nm">${p.name} <span class="pill know">${p.change || ""}</span></div>
    <div class="small ink2">${p.role || ""}${p.effective ? html` · from ${p.effective}` : ""}${p.reason ? html` · ${p.reason}` : ""}</div>
    ${p.profile ? html`<div class="small" style="margin-top:4px">${p.profile}</div>` : ""}
    ${p.background?.length ? html`<div class="bg">${p.background.map((b) => html`<span>${b}</span>`)}</div>` : ""}
  </div>`);
  return html`${ppl}<div class="tiny muted" style="margin-top:6px">Profile from ${c.source}.</div>`;
}

export function eventCard(e, ctx) {
  const c = e.card;
  return html`<article class="card act">
    <div class="top">
      <button class="co" data-act="co" data-t="${e.ticker}">${ctx.nameOf(e.ticker)}<small>${e.ticker}</small></button>
      <span>${ctx.isNew(e) ? html`<span class="pill new">New</span> ` : ""}<span class="pill act">Act</span></span>
    </div>
    <div class="tiny muted">${fmtWhen(e.ts)}</div>
    <div class="headline">${c?.type === "results" ? `Results · ${c.period || ""}` : e.oneliner || e.title}</div>
    ${c?.type === "results" ? resultsBody(c) : c?.type === "mgmt" ? mgmtBody(c) : ""}
    ${e.undergraded ? html`<div class="flag">FINN ranked this low, but the stock moved. Flagged for rule review.</div>` : ""}
    <div class="why">${reactionChip(e.reaction)}
      <span>Why: ${e.why.join(" · ")}</span>
      <button data-act="event" data-id="${e.id}">Filings ›</button>
      ${ctx.researchReady(e.ticker) ? html`<a href="#/research/${e.ticker}">Promises vs delivery ›</a>` : ""}
    </div>
  </article>`;
}

export function knowRow(e, ctx) {
  return html`<button class="row" data-act="event" data-id="${e.id}">
    <div><div class="t">${ctx.nameOf(e.ticker)}</div><div class="tiny muted">${fmtWhen(e.ts)}</div></div>
    <div><div class="l">${ctx.isNew(e) ? html`<span class="pill new">New</span> ` : ""}${e.card?.type === "results" ? `Results · ${e.card.period}` : e.oneliner || e.title}</div>
    <div class="w">${e.why.join(" · ")}</div></div>
  </button>`;
}

export function eventSheet(e, ctx) {
  const fl = e.filings.map((f) => html`<li><b>${f.subject || "Filing"}</b> <span class="tiny muted">${fmtWhen(f.ts)} · ${f.tier}</span><br>
    <span class="ink2">${f.text}</span> ${f.url ? html`<a href="${f.url}" target="_blank" rel="noopener">PDF ›</a>` : ""}</li>`);
  return html`<div class="co">${ctx.nameOf(e.ticker)}<small>${e.ticker}</small></div>
    <p class="headline">${e.oneliner || e.title}</p>
    ${e.card?.type === "results" ? resultsBody(e.card) : e.card?.type === "mgmt" ? mgmtBody(e.card) : ""}
    <h3 class="caps" style="margin-top:16px">Why FINN ranked it ${e.tier}</h3>
    <p class="small">${e.why.join(" · ")} <span class="muted">(${e.rule === "ai" ? "AI triage, cached" : `rule: ${e.rule}`}${e.oneliner_ai ? "; one-line summary by AI" : ""})</span></p>
    ${e.evidence ? html`<p class="small ink2">Evidence: past filings of this type moved the stock ≥2× its usual move <b>${Math.round(e.evidence.big_rate * 100)}%</b> of the time (n=${e.evidence.n})${e.evidence.lift != null ? html`, ${e.evidence.lift.toFixed(1)}× an ordinary day` : ""}. <button class="why" style="display:inline;color:var(--link)" data-act="ranking">How FINN ranks ›</button></p>` : ""}
    <p>${reactionChip(e.reaction)}</p>
    <h3 class="caps" style="margin-top:16px">${e.filings.length} filing${e.filings.length > 1 ? "s" : ""}</h3>
    <ul class="flist">${fl}</ul>
    <p><a href="#/research/${e.ticker}">Open ${e.ticker} research ›</a></p>`;
}

// ----------------------------------------------------------- promise ledger
const VLABEL = { kept: "Kept", missed: "Missed", on_track: "On track", off_track: "Off track", dropped: "Quietly dropped",
  pending: "Pending", unverifiable: "Can't verify" };

const rng = (h) => (h.low == null && h.high == null ? "" : h.low === h.high || h.high == null ? `${h.low}${h.unit === "%" ? "%" : ` ${h.unit || ""}`}` :
  h.low == null ? `≤${h.high}${h.unit === "%" ? "%" : ` ${h.unit || ""}`}` : `${h.low}–${h.high}${h.unit === "%" ? "%" : ` ${h.unit || ""}`}`);

export function threadRow(t, calls, open) {
  const last = t.history[t.history.length - 1];
  const byCall = new Map(t.history.map((h) => [h.call_idx, h]));
  const cells = calls.map((c, i) => {
    const h = byCall.get(i);
    return html`<div class="${h ? "has" : ""}">${c.replace(/^(\w{3})\w*\s+(\d{2})(\d{2})$/, "$1 '$3")}<br>${h ? rng(h) || "said" : "—"}</div>`;
  });
  const a = t.actual;
  return html`<div class="thread" id="${t.id}">
    <button data-act="thread" data-id="${t.id}" style="width:100%;text-align:left">
      <div class="tt"><b>${t.title}</b>
        <span><span class="v ${t.verdict}">${VLABEL[t.verdict] || t.verdict}</span>${t.moved ? html` <span class="v moved">Goalposts ${t.moved}</span>` : ""}</span></div>
      <div class="callrow">${cells}</div>
      <div class="pa">${rng(last) ? html`Promised <b>${rng(last)}</b>${last.basis ? ` (${last.basis})` : ""} for ${t.horizon || "—"}` : html`<span class="ink2">${t.horizon || ""}</span>`}
        ${a ? html` · Actual <b>${a.unit === "%" ? `${(+a.value).toFixed(1)}%` : `₹${fmtCr(a.value)} cr`}</b> <span class="muted">${a.label}, ${a.period}${t.approx ? " ≈" : ""}</span>` : ""}</div>
      ${t.note ? html`<div class="tiny muted">${t.note}</div>` : ""}
    </button>
    ${open ? html`${t.history.map((h) => html`<div class="quote">“${h.quote}”</div>
      <div class="tiny muted">${h.speaker ? `${h.speaker}, ` : ""}${h.call} call · <a href="${h.src_url}" target="_blank" rel="noopener">transcript ›</a> · quote verified in source</div>`)}` : ""}
  </div>`;
}

export function rankingSheet(c) {
  if (!c) return html`<p>Ranking evidence isn't built yet.</p>`;
  const rows = Object.entries(c.rules).sort((a, b) => b[1].n - a[1].n);
  const dec = { keep: "", demote: "↓ demoted", promote: "↑ promoted" };
  return html`<div class="co">How FINN ranks</div>
    <p class="small ink2">Rules sort filings into Act / Know / Hidden. Then FINN checks them against history: on the session each past filing could first affect, did the stock move at least ${c.big}× its usual daily move (net of Nifty)? On an ordinary day with no filing that happens <b>${Math.round(c.baseline.big_rate * 100)}%</b> of the time. A Know type that isn't more likely than that is hidden; a Hidden type that is ${"≥"}2× as likely is promoted. Types with fewer than ${c.min_n} examples keep their judged tier. Risk signals (litigation, insider dealing, pledges) are never demoted, because end-of-day prices react to them slowly.</p>
    <table class="res"><thead><tr><th>Filing type</th><th>n</th><th>Big move</th><th>vs normal</th><th></th></tr></thead><tbody>
    ${rows.map(([, r]) => html`<tr><td>${r.label} <span class="tiny muted">${r.tier === "ai" ? "" : r.tier}</span></td><td>${r.n}</td><td>${Math.round(r.big_rate * 100)}%</td>
      <td class="${r.lift >= 1.5 ? "up" : r.lift < 1 ? "muted" : ""}">${r.lift == null ? "—" : `${r.lift.toFixed(1)}×`}</td><td class="tiny">${dec[r.decision]}</td></tr>`)}</tbody></table>
    <p class="tiny muted">Window ${c.window[0]} → ${c.window[1]}; ${c.baseline.n} ordinary stock-days as the baseline. Filings on a results day or the session after are excluded from their own type, so the results move isn't credited to them.</p>`;
}

export { VLABEL, raw };
