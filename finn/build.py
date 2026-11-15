"""Build the push-side files the app reads: raw/ + cache/ -> public/data/.

No network except LLM calls (all cached). Safe to re-run any time.
"""
import os
import re
from datetime import timedelta
from pathlib import Path

from . import config, now_ist, read_json, write_json, classify, extract

RAW = config.RAW
OUT = config.PUBLIC_DATA


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


# --------------------------------------------------------------------- prices
def build_prices(sessions_n=120):
    raw = read_json(RAW / "prices.json", {})
    idx = raw.get(config.INDEX_YF) or []
    dates = [d for d, _, _ in idx][-sessions_n:]
    nmap = {d: c for d, c, _ in idx}
    out = {"dates": dates, "nifty": [nmap.get(d) for d in dates], "t": {}}
    for t in config.PORTFOLIO:
        rows = raw.get(f"{t}.NS") or []
        m = {d: (c, v) for d, c, v in rows}
        out["t"][t] = {"c": [m.get(d, (None, None))[0] for d in dates],
                       "v": [m.get(d, (None, None))[1] for d in dates]}
    write_json(OUT / "prices.json", out)
    return out


# -------------------------------------------------------------- results card
def _row(table, *names):
    for n in names:
        for k, v in table["rows"].items():
            if k.lower().startswith(n.lower()):
                return v
    return None


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100 * (1 if b > 0 else -1), 1)


MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _period_end(label):
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{4})", label or "")
    if not m:
        return None
    return int(m.group(2)) * 12 + MONTHS[m.group(1)]


def screener_results(ticker, session):
    """Deterministic Rev/EBITDA/PBT/PAT with QoQ and YoY from screener's quarterly table."""
    sc = read_json(RAW / "screener" / f"{ticker}.json")
    if not sc or not sc.get("quarters"):
        return None
    q = sc["quarters"]
    periods = q["periods"]
    if len(periods) < 5:
        return None
    # The latest column must be the quarter these results are for (ended 0-3.5 months before filing)
    y, mth = int(session[:4]), int(session[5:7])
    gap = y * 12 + mth - (_period_end(periods[-1]) or 0)
    if gap < 0 or gap > 4:
        return None
    lender = config.company(ticker)["lender"]
    spec = [("Revenue", ("Sales", "Revenue")),
            ("EBITDA" if not lender else "Op. profit", ("Operating Profit", "Financing Profit")),
            ("PBT", ("Profit before tax",)),
            ("PAT", ("Net Profit",))]
    rows = []
    for label, names in spec:
        r = _row(q, *names)
        if not r or r[-1] is None:
            continue
        rows.append({"k": label, "v": r[-1], "qoq": _pct(r[-1], r[-2]), "yoy": _pct(r[-1], r[-5]),
                     "prev_q": r[-2], "year_ago": r[-5]})
    if len(rows) < 3:
        return None
    sales = _row(q, "Sales", "Revenue")
    op = _row(q, "Operating Profit", "Financing Profit")
    margin = None
    if sales and op and sales[-1]:
        mm = lambda i: round(op[i] / sales[i] * 100, 1) if sales[i] and op[i] is not None else None  # noqa: E731
        margin = {"now": mm(-1), "prev_q": mm(-2), "year_ago": mm(-5)}
    return {
        "type": "results", "period": periods[-1], "prev_q": periods[-2], "year_ago": periods[-5],
        "basis": sc["basis"], "unit": "₹ cr", "lender": lender, "rows": rows, "margin": margin,
        "ebitda_note": ("Financing profit (lenders have no EBITDA)" if lender else
                        "EBITDA = screener operating profit (excludes other income)"),
        "source": "screener.in quarterly table", "src_url": sc["url"],
    }


def filing_results(ticker, event):
    for f in event["filings"]:
        text = _doc(f["id"])
        if len(text) < 1500:
            continue
        try:
            r = extract.results_from_text(text, ticker=ticker)
        except Exception as e:
            print("results extract failed", ticker, e)
            continue
        cur, pq, ya = r["cols"]
        lender = config.company(ticker)["lender"]
        rows = []
        for key, label in (("revenue", "Revenue"), ("ebitda", "EBITDA" if not lender else "Op. profit"),
                           ("pbt", "PBT"), ("pat", "PAT")):
            if cur.get(key) is None:
                continue
            rows.append({"k": label, "v": cur[key], "qoq": _pct(cur[key], pq.get(key)),
                         "yoy": _pct(cur[key], ya.get(key)), "prev_q": pq.get(key), "year_ago": ya.get(key)})
        return {"type": "results", "period": (r.get("periods") or {}).get("current"), "basis": r.get("basis"),
                "unit": "₹ cr", "lender": lender, "rows": rows, "margin": None,
                "ebitda_note": "First cut from the filing (EBITDA = PBT + finance cost + depreciation − other income)",
                "source": "results filing (AI-extracted, arithmetic-checked)", "src_url": f["url"], "first_cut": True}
    return None


def _doc(fid):
    p = RAW / "docs" / f"{safe(fid)}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def mgmt_card(ticker, event):
    people = []
    for f in event["filings"]:
        text = _doc(f["id"]) or f.get("text", "")
        if len(text) < 200:
            continue
        try:
            people += extract.mgmt_from_text(text, ticker=ticker)["people"]
        except Exception as e:
            print("mgmt extract failed", ticker, e)
    seen, uniq = set(), []
    for p in people:
        k = extract.norm(p["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    if not uniq:
        return None
    return {"type": "mgmt", "people": uniq, "source": "the company's filing (Reg 30 'brief profile')"}


# ---------------------------------------------------------------------- build
def build_all(args=None):
    use_ai = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    prices = build_prices()
    sessions = prices["dates"]
    cutoff = (now_ist() - timedelta(days=getattr(args, "days", 30) or 30)).isoformat()
    filings = []
    for t in config.PORTFOLIO:
        for f in read_json(RAW / "filings" / f"{t}.json", {}).values():
            if (f.get("ts") or "") >= cutoff:
                filings.append(f)
    docs = {f["id"]: _doc(f["id"]) for f in filings}
    verdicts = classify.classify(filings, docs_text=docs, use_ai=use_ai)
    events = classify.group_events(filings, verdicts, sessions)

    for e in events:
        e["reaction"] = classify.reaction(e["ticker"], e["session"], prices)
        r = e["reaction"]
        if r.get("status") == "ok" and e["tier"] == "hidden" and abs(r["abn"]) >= 4:
            e["undergraded"] = True  # FINN hid it but the market moved: say so
        if e["tier"] == "hidden":
            continue
        if e["category"] == "results" and e["rule"] == "results_outcome":
            e["card"] = screener_results(e["ticker"], e["session"])
            if e["card"] is None and use_ai:
                e["card"] = filing_results(e["ticker"], e)
        elif e["category"] == "management_change" and use_ai:
            e["card"] = mgmt_card(e["ticker"], e)
        if not e["card"] and use_ai and (not e["oneliner"] or len(e["oneliner"]) > 200):
            lead = e["filings"][-1]
            try:
                e["oneliner"] = extract.one_line(e["title"], (lead.get("text") or "") + "\n" + _doc(lead["id"])[:2500],
                                                 ticker=e["ticker"])
                e["oneliner_ai"] = True
            except Exception as ex:
                print("one-liner failed", e["id"], ex)

    write_json(OUT / "events.json", {"generated_at": now_ist().isoformat(timespec="seconds"), "events": events})

    research = sorted(p.stem for p in (OUT / "research").glob("*.json")) if (OUT / "research").exists() else []
    status = read_json(RAW / "status.json", {})
    meta = {
        "generated_at": now_ist().isoformat(timespec="seconds"),
        "sample": False,
        "last_session": sessions[-1] if sessions else None,
        "rules_version": config.RULES_VERSION,
        "status": status,
        "portfolio": [config.company(t) for t in config.PORTFOLIO],
        "research_ready": research,
        "research_set": list(config.RESEARCH_SET),
        "counts": {k: sum(1 for e in events if e["tier"] == k) for k in ("act", "know", "hidden")},
    }
    write_json(OUT / "meta.json", meta, indent=1)
    print(f"built {len(events)} events from {len(filings)} filings; tiers {meta['counts']}")
