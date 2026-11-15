// Small helpers: escaping templates, formatting, sparklines, price maths.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);

// html`...${x}...` escapes every value unless it is raw() or an array of raw.
export function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => {
    if (v instanceof Raw) out += v.s;
    else if (Array.isArray(v)) out += v.map((x) => (x instanceof Raw ? x.s : esc(x))).join("");
    else if (v === null || v === undefined || v === false) out += "";
    else out += esc(v);
    out += strings[i + 1];
  });
  return raw(out);
}

export const fmtCr = (v) => (v == null ? "—" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString("en-IN") : (+v).toFixed(1));
export const fmtPct = (v, d = 1) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}%`);
export const tone = (v) => (v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "");

const IST = "Asia/Kolkata";
export function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: IST });
  const t = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: IST });
  return `${day}, ${t}`;
}
export function fmtDay(ymd) {
  if (!ymd) return "";
  const d = new Date(ymd + "T12:00:00+05:30");
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: IST });
}
export function ago(iso) {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${m}m ago`;
  if (m < 60 * 36) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}

export function spark(values, { w = 120, h = 32, stroke = "currentColor", mark = null } = {}) {
  const v = values.map((x, i) => [i, x]).filter(([, x]) => x != null);
  if (v.length < 2) return raw("");
  const xs = v.map(([i]) => i), ys = v.map(([, y]) => y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (i) => ((i - x0) / (x1 - x0 || 1)) * (w - 4) + 2;
  const sy = (y) => h - 3 - ((y - y0) / (y1 - y0 || 1)) * (h - 6);
  const d = v.map(([i, y], k) => `${k ? "L" : "M"}${sx(i).toFixed(1)},${sy(y).toFixed(1)}`).join("");
  const dot = mark != null && values[mark] != null
    ? `<circle cx="${sx(mark).toFixed(1)}" cy="${sy(values[mark]).toFixed(1)}" r="2.6" fill="var(--act)"/>` : "";
  return raw(`<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>${dot}</svg>`);
}

// ---------------------------------------------------------------- price maths
export function returns(c) {
  return c.map((x, i) => (i && x != null && c[i - 1] ? (x / c[i - 1] - 1) * 100 : null));
}
function std(a) {
  const v = a.filter((x) => x != null);
  if (v.length < 15) return null;
  const m = v.reduce((s, x) => s + x, 0) / v.length;
  return Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / (v.length - 1));
}

// Returns alerts for each session index in [from, n): {ti, i, ret, sig, volx, price, vol}
export function scanAlerts(prices, s, from) {
  const out = [];
  const n = prices.dates.length;
  for (const [t, d] of Object.entries(prices.t)) {
    const r = returns(d.c);
    for (let i = Math.max(from, 21); i < n; i++) {
      if (r[i] == null) continue;
      const sig = std(r.slice(Math.max(1, i - 60), i));
      const prior = d.v.slice(i - 20, i).filter((x) => x);
      const volx = prior.length >= 10 && d.v[i] ? d.v[i] / (prior.reduce((a, b) => a + b, 0) / prior.length) : null;
      const price = s.relative ? sig != null && Math.abs(r[i]) >= s.sigma * sig : Math.abs(r[i]) >= s.pricePct;
      const vol = volx != null && volx >= s.volX;
      if (price || vol) out.push({ t, i, date: prices.dates[i], ret: r[i], sig, volx, price, vol });
    }
  }
  return out;
}
