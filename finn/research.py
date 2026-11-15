"""Pull side: a research dossier for any NSE ticker.

Order of trust:
  numbers  -> screener tables, computed in code (the model never supplies an actual)
  promises -> extracted by the model, kept only if the quote is found verbatim in the
              transcript and the promised number is inside that quote
  verdicts -> scored in code (kept / missed / pending / dropped / can't verify)
  prose    -> one strong-model call over the verified records only; every number it
              writes must exist in its input, every claim must cite a record
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import config, extract, llm, now_ist, read_json, sources

RAW = config.RAW
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


# ------------------------------------------------------------------ inputs
def _load_inputs(ticker, offline_raw):
    if offline_raw:
        sc = read_json(RAW / "screener" / f"{ticker}.json")
        if not sc:
            raise RuntimeError(f"no screener data for {ticker}")
        idx = read_json(RAW / "transcripts" / ticker / "index.json", [])
        calls = []
        for x in idx:
            p = RAW / "transcripts" / ticker / x["file"]
            if p.exists():
                calls.append({"when": x["when"], "url": x["url"], "text": p.read_text(encoding="utf-8")})
        return sc, calls
    sc = sources.fetch_screener(ticker)
    links = [c for c in sc.get("concalls", []) if c.get("transcript")][:6]

    def get(c):
        return {"when": c["when"], "url": c["transcript"], "text": sources.pdf_text(c["transcript"], max_pages=60)}
    with ThreadPoolExecutor(4) as ex:
        calls = [c for c in ex.map(get, links) if len(c["text"]) > 2000][:4]
    return sc, calls


def _when_key(w):
    m = re.search(r"([A-Z][a-z]{2})\w*\s+(\d{4})", w or "")
    if m:
        return int(m.group(2)) * 12 + MONTHS.get(m.group(1)[:3], 0)
    m = re.search(r"(\d{4})-(\d{2})", w or "")
    return int(m.group(1)) * 12 + int(m.group(2)) if m else 0


# ----------------------------------------------------------------- numbers
def _row(tbl, *names):
    if not tbl:
        return None
    for n in names:
        for k, v in tbl["rows"].items():
            if k.lower().startswith(n.lower()):
                return v
    return None


class Fin:
    """Screener tables with helpers to compute actuals for a guided period."""

    def __init__(self, sc, lender):
        self.sc, self.lender = sc, lender
        self.q, self.a = sc.get("quarters"), sc.get("annual")
        self.qp = self.q["periods"] if self.q else []
        self.ap = [p for p in (self.a["periods"] if self.a else [])]

    def qser(self, *names):
        return _row(self.q, *names) or []

    def aser(self, *names):
        return _row(self.a, *names) or []

    def _q_index(self, label):
        return self.qp.index(label) if label in self.qp else None

    def fy_quarters(self, fy):  # fy = 2027 -> Jun 2026, Sep 2026, Dec 2026, Mar 2027
        return [f"Jun {fy - 1}", f"Sep {fy - 1}", f"Dec {fy - 1}", f"Mar {fy}"]

    def metric_value(self, metric, margin_type, labels):
        """Aggregate a metric over quarter labels (sum flows; margins on sums)."""
        idx = [self._q_index(l) for l in labels]
        if any(i is None for i in idx):
            return None
        S = self.qser("Sales", "Revenue")
        OP = self.qser("Operating Profit", "Financing Profit")
        D = self.qser("Depreciation")
        NP = self.qser("Net Profit")

        def tot(series):
            vals = [series[i] for i in idx] if series else []
            return sum(vals) if vals and all(v is not None for v in vals) else None
        s = tot(S)
        if metric in ("revenue", "revenue_growth"):
            return s
        if metric == "profit_growth":
            return tot(NP)
        if metric == "margin":
            if not s:
                return None
            if margin_type == "pat":
                n = tot(NP)
            elif margin_type == "ebit":
                op, d = tot(OP), tot(D)
                n = (op - d) if op is not None and d is not None else None
            else:
                n = tot(OP)
            return round(n / s * 100, 2) if n is not None else None
        return None

    def snapshot(self):
        S, OP, NP = self.qser("Sales", "Revenue"), self.qser("Operating Profit", "Financing Profit"), self.qser("Net Profit")
        n = min(8, len(self.qp))
        quarters = {
            "labels": self.qp[-n:],
            "revenue": S[-n:], "pat": NP[-n:],
            "opm": [round(o / s * 100, 1) if s and o is not None else None for o, s in zip(OP[-n:], S[-n:])],
        }
        ap = [p for p in self.ap if p != "TTM"]
        k = min(6, len(ap))
        aS = self.aser("Sales", "Revenue")[:len(ap)][-k:]
        aOP = self.aser("Operating Profit", "Financing Profit")[:len(ap)][-k:]
        aNP = self.aser("Net Profit")[:len(ap)][-k:]
        cf = self.sc.get("cashflow")
        cfo = []
        if cf:
            m = dict(zip(cf["periods"], _row(cf, "Cash from Operating") or []))
            cfo = [m.get(p) for p in ap[-k:]]
        years = {"labels": ap[-k:], "revenue": aS, "pat": aNP,
                 "opm": [round(o / s * 100, 1) if s and o is not None else None for o, s in zip(aOP, aS)],
                 "cfo": cfo}
        conv = [round(c / p, 2) for c, p in zip(cfo[-3:], aNP[-3:]) if c is not None and p]
        bal = self.sc.get("balance")
        bs = {}
        if bal:
            eq = (_row(bal, "Equity Capital") or [None])[-1]
            res = (_row(bal, "Reserves") or [None])[-1]
            debt = (_row(bal, "Borrowings") or [None])[-1]
            bs = {"period": bal["periods"][-1], "borrowings": debt,
                  "equity": (eq or 0) + (res or 0) if eq is not None else None}
            if debt is not None and bs["equity"]:
                bs["de"] = round(debt / bs["equity"], 2)
        rat = self.sc.get("ratios")
        if rat:
            for key, names in (("roce", ("ROCE",)), ("ccc", ("Cash Conversion Cycle",)), ("wc_days", ("Working Capital Days",)),
                               ("debtor_days", ("Debtor Days",))):
                r = _row(rat, *names)
                if r:
                    bs[key] = r[-1]
                    bs[key + "_prev"] = r[-4] if len(r) >= 4 else None
        return {"quarters": quarters, "years": years, "cash_conversion_3y": conv, "balance": bs,
                "top": self.sc.get("top", {}), "basis": self.sc.get("basis")}


# ------------------------------------------------------------- horizons
def parse_horizon(h):
    """-> ("fy", 2027) | ("q", "Dec 2026") | ("h", (2027, 2)) | None"""
    h = (h or "").upper().replace(" ", "")
    m = re.search(r"Q([1-4])FY'?(\d{2,4})", h)
    if m:
        fy = int(m.group(2)) % 100 + 2000
        q = int(m.group(1))
        return ("q", {1: f"Jun {fy - 1}", 2: f"Sep {fy - 1}", 3: f"Dec {fy - 1}", 4: f"Mar {fy}"}[q])
    m = re.search(r"H([12])FY'?(\d{2,4})", h)
    if m:
        return ("h", (int(m.group(2)) % 100 + 2000, int(m.group(1))))
    m = re.search(r"FY'?(\d{2,4})", h)
    if m:
        return ("fy", int(m.group(1)) % 100 + 2000)
    return None


def horizon_end(h):
    """(year, month) when a horizon ends, or None for 'long term' etc."""
    hz = parse_horizon(h)
    if not hz:
        return None
    kind, val = hz
    if kind == "fy":
        return (val, 3)
    if kind == "q":
        return (int(val[-4:]), MONTHS[val[:3]])
    fy, half = val
    return (fy - 1, 9) if half == 1 else (fy, 3)


def horizon_passed(h, today=None):
    end = horizon_end(h)
    if not end:
        return False
    today = today or now_ist().date()
    return (today.year, today.month) > end


def _period_done(labels, fin):
    return all(l in fin.qp for l in labels)


def evaluate(thread_items, fin, today=None):
    """Deterministic verdict for one thread (items oldest first)."""
    today = today or now_ist().date()
    latest = thread_items[-1]
    metric, unit = latest.get("metric"), (latest.get("unit") or "").strip()
    lo, hi = latest.get("low"), latest.get("high")
    lo = lo if lo is not None else hi
    hi = hi if hi is not None else lo
    hz = parse_horizon(latest.get("horizon"))
    basis = (latest.get("basis") or "").lower()
    approx = any(x in basis for x in ("constant currency", "cc", "usd", "dollar"))
    res = {"verdict": "unverifiable", "approx": approx, "actual": None, "note": ""}

    nums = [(it.get("low"), it.get("high")) for it in thread_items if it.get("low") is not None or it.get("high") is not None]
    if len(nums) >= 2 and nums[0] != nums[-1]:
        a = (nums[0][0] if nums[0][0] is not None else nums[0][1])
        b = (nums[-1][0] if nums[-1][0] is not None else nums[-1][1])
        res["moved"] = "raised" if b > a else ("lowered" if b < a else "changed")

    measurable = metric in ("revenue_growth", "revenue", "margin", "profit_growth") and lo is not None and hz
    if measurable and metric in ("revenue_growth", "profit_growth", "margin") and unit not in ("%", ""):
        measurable = False
        res["note"] = "Guided relative to the market or in other units; can't check from company totals"
    if measurable and metric == "revenue":
        annual = [x for x in fin.aser("Sales", "Revenue") if x]
        if unit.lower() not in ("cr", "crore", "₹ cr", "rs cr", "inr") or not annual or lo < 0.5 * annual[-1]:
            measurable = False
            res["note"] = "Segment or product-level target; segment numbers aren't in the reported tables"
    if fin.lender and metric == "margin" and latest.get("margin_type") != "pat":
        measurable = False
        res["note"] = "Lender margins (NIM) aren't in the tables we use"
    if not measurable:
        if not res["note"]:
            res["note"] = "No reported number to check this against" if lo is not None else "Qualitative promise"
        return res
    if metric == "margin" and unit not in ("%", ""):
        res["note"] = "Unit not comparable"
        return res

    kind, val = hz
    if kind == "fy":
        cur, prev = fin.fy_quarters(val), fin.fy_quarters(val - 1)
    elif kind == "q":
        y, m = int(val[-4:]), val[:3]
        cur, prev = [val], [f"{m} {y - 1}"]
    else:
        fy, half = val
        q = fin.fy_quarters(fy)
        cur = q[:2] if half == 1 else q[2:]
        prev = fin.fy_quarters(fy - 1)[:2] if half == 1 else fin.fy_quarters(fy - 1)[2:]
    done = [l for l in cur if l in fin.qp]
    complete = len(done) == len(cur)
    if not done:
        res.update(verdict="pending", note="Period hasn't reported yet")
        return res
    prev_done = [prev[cur.index(l)] for l in done]
    period_label = (f"FY{str(val)[2:]}" if kind == "fy" else str(val)) + ("" if complete else f" so far ({len(done)} of {len(cur)} qtrs)")
    mt = latest.get("margin_type") or ("ebit" if "ebit" in basis and "ebitda" not in basis else "ebitda")

    if metric in ("revenue_growth", "profit_growth"):
        a, b = fin.metric_value(metric, None, done), fin.metric_value(metric, None, prev_done)
        if a is None or not b:
            res["note"] = "Missing quarters in the table"
            return res
        actual, tol = round((a / b - 1) * 100, 1), 0.5
        res["actual"] = {"value": actual, "unit": "%", "label": ("Revenue" if metric == "revenue_growth" else "PAT") + " growth, INR reported", "period": period_label}
    elif metric == "margin":
        actual = fin.metric_value("margin", mt, done)
        if actual is None:
            res["note"] = "Missing quarters in the table"
            return res
        tol = 0.3
        res["actual"] = {"value": actual, "unit": "%", "label": {"ebit": "EBIT margin", "pat": "PAT margin"}.get(mt, "EBITDA margin"), "period": period_label}
    else:  # absolute revenue target, crore
        if unit.lower() not in ("cr", "crore", "₹ cr", "rs cr"):
            res["note"] = "Target unit isn't ₹ crore"
            return res
        actual = fin.metric_value("revenue", None, done)
        if actual is None:
            return res
        if not complete:  # annualise run-rate for an in-progress year
            actual = actual / len(done) * len(cur)
            period_label += ", annualised"
        tol = lo * 0.02
        res["actual"] = {"value": round(actual), "unit": "cr", "label": "Revenue", "period": period_label}

    if approx and metric in ("revenue_growth", "profit_growth"):
        # Constant-currency guidance vs INR reported growth: currency moves can swing this by
        # several points, so show the number as context but don't give a verdict.
        res["verdict"] = "unverifiable"
        res["note"] = (f"Guided in constant currency; reported INR growth is {actual}% ({period_label}), "
                       "which includes currency moves, so no verdict")
        return res
    ok = actual >= lo - tol
    if complete:
        res["verdict"] = "kept" if ok else "missed"
    else:
        res["verdict"] = "on_track" if ok else "off_track"
    return res


# --------------------------------------------------------------- synthesis
SYN_SYS = (
    "You are an investment analyst writing for a portfolio manager. You get ONLY verified records: management "
    "promises with code-computed verdicts (ids T#) and financial facts (ids F#). Do not use any outside knowledge "
    "about the company. Every number you write must appear in the records. Be direct and specific; no filler.\n"
    "Return JSON {\"headline\":\"<=18 words: does management deliver what it promises?\","
    "\"points\":[{\"text\":\"<=30 words\",\"refs\":[ids]}] (3-4 points on narrative vs numbers),"
    "\"bull\":[{\"text\":\"<=22 words\",\"refs\":[ids]}] (2-3),\"bear\":[{\"text\":\"<=22 words\",\"refs\":[ids]}] (2-3)}"
)


def _fmt(x):
    return "n/a" if x is None else (f"{x:,.1f}" if isinstance(x, float) else str(x))


def synthesise(ticker, threads, snap):
    recs, facts = [], []
    for t in threads:
        a = t.get("actual") or {}
        hist = "; ".join(f"{h['call']}: {_fmt(h.get('low'))}-{_fmt(h.get('high'))}{h.get('unit') or ''}" for h in t["history"])
        recs.append(f"{t['id']} | {t['title']} | horizon {t['horizon']} | promised {hist} | verdict {t['verdict']}"
                    + (f" ({t['moved']})" if t.get("moved") else "")
                    + (f" | actual {a.get('value')}{a.get('unit')} {a.get('label')} {a.get('period')}" if a else "")
                    + (f" | note {t['note']}" if t.get("note") else ""))
    y, q, b = snap["years"], snap["quarters"], snap["balance"]
    facts.append(f"F1 | annual revenue {list(zip(y['labels'], y['revenue']))}")
    facts.append(f"F2 | annual operating margin % {list(zip(y['labels'], y['opm']))}")
    facts.append(f"F3 | annual PAT {list(zip(y['labels'], y['pat']))}")
    facts.append(f"F4 | cash from operations {list(zip(y['labels'], y['cfo']))}; CFO/PAT last 3y {snap['cash_conversion_3y']}")
    facts.append(f"F5 | balance {b}")
    facts.append(f"F6 | quarterly revenue {list(zip(q['labels'], q['revenue']))}; margin % {q['opm']}")
    blob = "PROMISES\n" + "\n".join(recs) + "\n\nFACTS (₹ crore unless %)\n" + "\n".join(facts)
    allowed = extract.numbers_in(blob)
    ids = {t["id"] for t in threads} | {f"F{i}" for i in range(1, 7)}

    def ok_num(n):
        return n <= 31 or any(abs(n - a) <= max(0.15, abs(a) * 0.005) for a in allowed) or n in (2024, 2025, 2026, 2027, 2028)

    def validate(o):
        if isinstance(o, list) and o and isinstance(o[0], dict):
            o = o[0]
        clean = {"headline": str(o.get("headline", ""))[:160]}
        bad = [n for n in extract.numbers_in(clean["headline"]) if not ok_num(n)]
        if bad:
            raise ValueError(f"headline numbers not in records: {bad}")
        for key in ("points", "bull", "bear"):
            keep = []
            for p in o.get(key, []) or []:
                text, refs = str(p.get("text", "")), [r for r in p.get("refs", []) if r in ids]
                if not refs or any(not ok_num(n) for n in extract.numbers_in(text)):
                    continue  # unsupported sentence -> dropped, not shown
                keep.append({"text": text, "refs": refs})
            clean[key] = keep
        if not clean["points"]:
            raise ValueError("no supported points")
        return clean
    return llm.ask("synthesis", SYN_SYS, f"Company: {ticker}\n\n{blob}", ticker=ticker, validate=validate, max_out=2500)


def template_synthesis(threads):
    """Plain, code-written summary used when no model is available."""
    c = {k: [t for t in threads if t["verdict"] == k] for k in ("kept", "missed", "on_track", "off_track", "dropped", "unverifiable", "pending")}
    moved = [t for t in threads if t.get("moved")]
    parts = [f"{len(threads)} verified promises"]
    for k, label in (("kept", "kept"), ("missed", "missed"), ("on_track", "on track"), ("off_track", "off track"),
                     ("dropped", "quietly dropped"), ("unverifiable", "not checkable from reported numbers")):
        if c[k]:
            parts.append(f"{len(c[k])} {label}")
    pts = []
    for t in (c["missed"] + c["off_track"] + c["dropped"] + moved + c["kept"] + c["on_track"])[:4]:
        a = t.get("actual")
        txt = f"{t['title']}: {t['verdict'].replace('_', ' ')}"
        if t.get("moved"):
            txt += f", goalposts {t['moved']}"
        if a:
            txt += f" ({a['label']} {a['value']}{'%' if a['unit'] == '%' else ' cr'}, {a['period']})"
        if t not in [p for p in []]:
            pts.append({"text": txt + ".", "refs": [t["id"]]})
    return {"headline": ", ".join(parts) + ".", "points": pts, "bull": [], "bear": [], "fallback": True}


# -------------------------------------------------------------------- build
def build(ticker, offline_raw=False):
    ticker = ticker.upper().strip()
    co = config.company(ticker)
    sc, calls = _load_inputs(ticker, offline_raw)
    co["name"] = sc.get("name") or co["name"]
    fin = Fin(sc, co["lender"])
    calls.sort(key=lambda c: _when_key(c["when"]))
    calls = calls[-4:]
    call_labels = [c["when"] for c in calls]

    stats = {"transcripts": len(calls), "found": 0, "dropped_quote": 0, "dropped_number": 0}
    items = []

    print(f"[research {ticker}] {len(calls)} transcripts: {', '.join(call_labels)}", flush=True)
    t0 = time.time()

    def run(c):
        try:
            r = extract.guidance_from_transcript(c["text"], c["when"], ticker=ticker)
        except Exception as e:
            print(f"[research {ticker}] {c['when']}: extraction failed ({str(e)[:100]})", flush=True)
            return [], {"found": 0, "dropped_quote": 0, "dropped_number": 0}
        print(f"[research {ticker}] {c['when']}: {r[1]['found']} promises found, {len(r[0])} verified "
              f"({time.time() - t0:.0f}s)", flush=True)
        return r
    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(run, calls))
    for c, (kept, st) in zip(calls, results):
        for k in ("found", "dropped_quote", "dropped_number"):
            stats[k] += st[k]
        for it in kept:
            it["src_url"] = c["url"]
            it["call_idx"] = call_labels.index(c["when"])
        items += kept
    stats["verified"] = len(items)

    grouped = extract.thread_items(items, ticker=ticker)["threads"] if items else []
    threads = []
    for n, g in enumerate(grouped, 1):
        its = sorted((items[i] for i in g["items"]), key=lambda it: it["call_idx"])
        ev = evaluate(its, fin)
        last_idx = its[-1]["call_idx"]
        silent = len(calls) >= 3 and last_idx <= len(calls) - 3
        passed = horizon_passed(its[-1].get("horizon"))
        since = f"Last mentioned {call_labels[last_idx]}; not repeated on the {len(calls) - 1 - last_idx} calls since"
        if silent and not passed and ev["verdict"] in ("pending", "unverifiable"):
            ev["verdict"] = "dropped"  # still in the future, but management stopped talking about it
            ev["note"] = since
        elif silent and ev["verdict"] in ("on_track", "off_track"):
            ev["note"] = (ev["note"] + ". " if ev["note"] else "") + since
        elif passed and ev["verdict"] in ("pending", "unverifiable"):
            ev["verdict"] = "unverifiable"
            ev["note"] = f"Came due ({its[-1].get('horizon')}); the reported numbers can't confirm it" + (
                f". {since}" if silent else "")
        threads.append({
            "id": f"T{n}", "title": g["title"] or its[-1].get("topic", ""), "metric": its[-1].get("metric"),
            "horizon": its[-1].get("horizon"), **ev,
            "history": [{"call": it["call"], "call_idx": it["call_idx"], "low": it.get("low"), "high": it.get("high"),
                         "unit": it.get("unit"), "basis": it.get("basis"), "kind": it.get("kind"),
                         "speaker": it.get("speaker"), "quote": it["quote"], "src_url": it["src_url"]} for it in its],
        })
    order = {"missed": 0, "off_track": 1, "dropped": 2, "kept": 3, "on_track": 4, "pending": 5, "unverifiable": 6}
    threads.sort(key=lambda t: (order.get(t["verdict"], 9), 0 if t.get("moved") else 1))

    cnt = {k: sum(1 for t in threads if t["verdict"] == k) for k in order}
    cnt["moved"] = sum(1 for t in threads if t.get("moved"))
    resolved = cnt["kept"] + cnt["missed"]
    snap = fin.snapshot()

    print(f"[research {ticker}] {len(threads)} promise threads scored; writing verdict ({time.time() - t0:.0f}s)", flush=True)
    synthesis = None
    if threads:
        try:
            synthesis = synthesise(ticker, threads, snap)
        except Exception as e:
            print("synthesis failed", ticker, e)
            synthesis = template_synthesis(threads)

    business = None
    if calls:
        try:
            business = extract.business_from_text(calls[-1]["text"], ticker=ticker)
            business["call"] = calls[-1]["when"]
        except Exception as e:
            print("business failed", ticker, e)

    return {
        "ticker": ticker, "name": co["name"], "lender": co["lender"],
        "generated_at": now_ist().isoformat(timespec="seconds"),
        "calls": call_labels, "stats": stats,
        "credibility": {**cnt, "resolved": resolved,
                        "line": (f"Kept {cnt['kept']} of {resolved} promises that have come due" if resolved else
                                 "No promise has come due yet in this window")},
        "threads": threads, "synthesis": synthesis, "business": business, "numbers": snap,
        "docs": {"transcripts": [{"call": c["when"], "url": c["url"]} for c in calls],
                 "annual_reports": sc.get("annual_reports", [])[:3], "screener": sc.get("url")},
        "no_transcripts": not calls,
    }
