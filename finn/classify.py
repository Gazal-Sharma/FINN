"""Filings -> category + tier (act / know / hidden) + why, then grouped into events.

Categories are exactly the ones in ENAM's reference document. Rules decide
first; only filings no rule matches go to the cheapest model, and that verdict
is cached per filing id (cache/verdicts.json) so we never pay twice.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from . import config, read_json, write_json, IST

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]

TOP_ROLES = r"(managing director|\bmd\b|\bceo\b|chief executive|\bcfo\b|chief financial|chairman|chairperson|whole[- ]?time director|executive director|\bcoo\b|chief operating|joint managing)"

# (rule_id, category, tier, why, regex over "subject | text") — first match wins.
RULES = [
    # --- noise first, so phrases like "newspaper ... results" stay hidden
    ("newspaper", "unclassified", "hidden", "Newspaper ad copy", r"newspaper|publication of (financial )?results"),
    ("trading_window", "unclassified", "hidden", "Trading window notice", r"trading window"),
    ("certificates", "unclassified", "hidden", "Compliance certificate", r"certificate under|reg(ulation)?\.? ?74 ?\(5\)|loss of share|duplicate share|compliance certificate|regulation 40\(9\)|74\(5\)"),
    ("esop", "unclassified", "hidden", "ESOP allotment", r"esop|esos|esps|employee stock|stock option"),
    ("esg", "unclassified", "hidden", "ESG / sustainability report", r"\besg\b|brsr|business responsibility|sustainability report"),
    ("xbrl", "unclassified", "hidden", "XBRL / format filing", r"xbrl|integrated filing \(governance\)"),
    ("auditor", "unclassified", "hidden", "Auditor appointment", r"T:(appointment|re-?appointment) of (statutory |secretarial |internal |cost )?auditor"),
    ("rta", "unclassified", "hidden", "Registrar / share-transfer change", r"T:share transfer agent|registrar and transfer"),

    # --- results family
    ("results_intimation", "results", "know", "Results date announced",
     r"board meeting intimation|intimation of board meeting|prior intimation.*(results|financial)"),
    ("results_outcome", "results", "act", "Quarterly results filed",
     r"(outcome of board meeting|financial result).*(financial results|results for the (quarter|period|year))|^financial result updates|audited financial results|unaudited financial results|results for the quarter"),
    ("results_clarification", "results", "know", "Clarification on results", r"clarification.*financial results"),
    ("investor_presentation", "results", "know", "Investor presentation", r"investor presentation"),

    # --- management change
    ("mgmt_top_exit", "management_change", "act", "Top executive leaving",
     TOP_ROLES + r".{0,120}(resign|cessation|step(s|ping)? down|retire)|(resign|cessation|step(s|ping)? down|retire).{0,120}" + TOP_ROLES),
    ("mgmt_top_join", "management_change", "act", "New top executive",
     TOP_ROLES + r".{0,120}(appoint|elevat|designat|successor)|(appoint|elevat|designat|successor).{0,120}" + TOP_ROLES),
    ("mgmt_other", "management_change", "know", "Board / KMP change",
     r"change in directors|key managerial|change in management|resignation|appointment of (an? )?(independent |additional |non-executive )?director|company secretary|compliance officer|senior management"),

    # --- corporate events
    ("insider", "insider_trading", "know", "Promoter / insider dealing",
     r"insider trading|\bsast\b|regulation 29|regulation 31|reg\.? 7\(2\)|disclosure under sebi takeover"),
    ("mna", "M&A", "act", "Acquisition / merger / JV",
     r"acquisition|amalgamation|merger|demerger|scheme of arrangement|joint venture|takeover|stake (sale|purchase)|divest|slump sale"),
    ("fund_raise_equity", "fund_raise", "act", "Equity raise or buyback",
     r"qualified institutional|\bqip\b|rights issue|preferential (issue|allotment)|buy ?back|further public offer"),
    ("fund_raise_debt", "fund_raise", "know", "Debt raise",
     r"commercial paper|non-convertible debenture|\bncd|bond issue|raising of funds|fund raising|allotment of (secured|unsecured)"),
    ("pledge", "pledging", "act", "Promoter pledge change", r"pledge|encumbrance"),
    ("rating_down", "credit_rating", "act", "Credit rating downgraded", r"(credit )?rating.{0,80}(downgrad|negative|watch)|downgrad.{0,40}rating"),
    ("rating_other", "credit_rating", "hidden", "Credit rating reaffirmed / assigned", r"credit rating|rating agency|\bcrisil\b|\bicra\b|care ratings|india ratings"),
    ("insolvency", "litigation", "act", "Insolvency / restructuring", r"insolvency|\bnclt\b|\bibc\b|winding up|corporate debtor"),
    ("litigation", "litigation", "know", "Legal / regulatory action",
     r"litigation|dispute|regulatory action|penalty|show cause|demand order|tax demand|\border\b.{0,40}(sebi|court|tribunal|authority)|fine|warning letter|import alert|\busfda\b|form 483|search and seizure"),
    ("bonus_split", "bonus_split", "know", "Bonus issue / stock split", r"\bbonus\b|sub-?division|stock split|split of"),
    ("dividend", "dividend", "know", "Dividend / record date", r"dividend|record date|book closure"),
    ("capex", "capex", "know", "Capacity / capex",
     r"capex|capital expenditure|capacity expansion|new (plant|facility|factory|unit)|commission(ing|ed) of|greenfield|brownfield"),
    ("transcript", "earnings_call", "know", "Concall transcript out (feeds the promise ledger)", r"transcript"),
    ("concall", "earnings_call", "hidden", "Earnings-call notice / recording",
     r"T:earnings call|conference call|con\. call|concall|audio recording|video recording"),
    ("investor_meet", "investor_meetings", "hidden", "Investor meeting",
     r"analysts?/institutional investor meet|investor meet|investor conference|analyst meet|schedule of (analyst|investor)"),
    ("agm_egm", "agm_egm", "hidden", "AGM / EGM paperwork", r"\bagm\b|\begm\b|general meeting|shareholders meeting|scrutini[sz]er"),
    ("postal_ballot", "postal_ballot", "hidden", "Postal ballot", r"postal ballot|e-?voting"),
    ("order_win", "press_release", "know", "Order win / contract", r"bagging|receiving of orders|order win|order (received|worth|valued)|contract (award|worth|win)|letter of (award|intent)"),
    ("clarification", "press_release", "know", "Clarification on news / volume", r"clarification|spurt in volume|price movement"),
    ("press_release", "press_release", "know", "Press release", r"press release|media release|launch|partnership|collaborat|\bmou\b"),
    ("general_update", "unclassified", "hidden", "General update", r"^general updates?$|^updates$"),
]
# A regex starting "T:" is matched against the filing text only (NSE's generic
# subject lines, e.g. "Change in Directors/.../Share Transfer Agent", would
# otherwise trigger it for every director change).
_COMPILED = [(rid, cat, tier, why, rx.startswith("T:"), re.compile(rx[2:] if rx.startswith("T:") else rx, re.I))
             for rid, cat, tier, why, rx in RULES]

MODIFIERS = [  # (regex, delta, reason) on top of the tier base score
    (re.compile(r"\b(ceo|cfo|managing director|chief executive|chief financial)\b", re.I), 15, "CEO/CFO/MD"),
    (re.compile(r"resign|cessation|step(s|ping)? down", re.I), 8, "exit, not appointment"),
    (re.compile(r"with immediate effect", re.I), 5, "immediate effect"),
    (re.compile(r"independent director", re.I), -15, "independent director"),
]


def rule_verdict(f):
    text = f.get("text", "")[:700]
    blob = f"{f.get('subject', '')} | {text}"
    for rid, cat, tier, why, text_only, rx in _COMPILED:
        if rx.search(text if text_only else blob):
            return {"category": cat, "tier": tier, "why": why, "rule": rid, "source": "rule"}
    return None


AI_SYSTEM = (
    "You triage Indian stock-exchange filings for a busy investor. Use only the text given. "
    "Return JSON: {\"category\": one of " + ", ".join(CATEGORIES) +
    ", \"tier\": \"act\"|\"know\"|\"hidden\", \"why\": \"<=8 words\"}. "
    "act = could move the stock or change the thesis; know = worth a line; hidden = routine paperwork."
)


def _validate_ai(obj):
    if not isinstance(obj, dict) or obj.get("category") not in CATEGORIES or obj.get("tier") not in ("act", "know", "hidden"):
        raise ValueError("bad verdict shape")
    obj["why"] = str(obj.get("why", ""))[:80]
    return obj


def classify(filings, docs_text=None, use_ai=True):
    """Return {filing_id: verdict}. AI verdicts are cached in cache/verdicts.json."""
    from . import llm
    cache_path = config.CACHE / "verdicts.json"
    cached = read_json(cache_path, {})
    out, dirty = {}, False
    for f in filings:
        v = rule_verdict(f)
        if v is None:
            c = cached.get(f["id"])
            if c:
                v = c
            elif use_ai:
                body = (f.get("text") or "")[:600]
                if docs_text and docs_text.get(f["id"]):
                    body += "\n" + docs_text[f["id"]][:1500]
                try:
                    a = llm.ask("classify", AI_SYSTEM, f"Subject: {f.get('subject')}\nText: {body}",
                                ticker=f["ticker"], validate=_validate_ai, max_out=200)
                    v = {**a, "rule": "ai", "source": "ai"}
                    cached[f["id"]] = v
                    dirty = True
                except Exception as e:
                    print("ai classify failed", f["id"], e)
            if v is None:
                v = {"category": "unclassified", "tier": "know", "why": "Unrecognised filing type",
                     "rule": "fallback", "source": "rule"}
        blob = f"{f.get('subject', '')} {f.get('text', '')[:700]}"
        score, reasons = config.TIER_BASE[v["tier"]], []
        if v["tier"] != "hidden":
            for rx, delta, reason in MODIFIERS:
                if rx.search(blob):
                    score += delta
                    reasons.append(reason)
        out[f["id"]] = {**v, "score": score, "mods": reasons}
    if dirty:
        write_json(cache_path, cached, indent=1)
    return out


# ------------------------------------------------------------------ sessions
def reaction_session(ts_iso, sessions):
    """Trading session a filing can first move: same day if before 15:30 IST, else next."""
    if not ts_iso:
        return None
    ts = datetime.fromisoformat(ts_iso).astimezone(IST)
    d = ts.date()
    if ts.hour * 60 + ts.minute >= 15 * 60 + 30:
        d = d + timedelta(days=1)
    ds = d.isoformat()
    for s in sessions:
        if s >= ds:
            return s
    # in the future relative to our price data: next weekday
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


RESULTS_FAMILY = {"results", "earnings_call", "dividend", "press_release", "investor_meetings", "unclassified"}


def clean_text(t):
    t = re.sub(r"^.{0,80}?has informed the exchange (about|regarding|that)\s*", "", t or "", flags=re.I)
    t = re.sub(r"^.{0,80}?has submitted (to the exchange )?", "", t, flags=re.I)
    t = t.strip(" .:-")
    return (t[:1].upper() + t[1:]) if t else ""


def group_events(filings, verdicts, sessions):
    """Results-day and management-change filings collapse into one event each."""
    by_key = defaultdict(list)
    for f in filings:
        f["session"] = reaction_session(f["ts"], sessions)
        by_key[(f["ticker"], f["session"])].append(f)

    events = []
    for (ticker, session), fs in by_key.items():
        fs.sort(key=lambda f: verdicts[f["id"]]["score"], reverse=True)
        used = set()
        has_results = any(verdicts[f["id"]]["rule"] == "results_outcome" for f in fs)
        groups = []
        if has_results:
            g = [f for f in fs if verdicts[f["id"]]["category"] in RESULTS_FAMILY]
            groups.append(("results", g))
            used.update(f["id"] for f in g)
        mg = [f for f in fs if f["id"] not in used and verdicts[f["id"]]["category"] == "management_change"]
        if len(mg) > 1:
            groups.append(("management_change", mg))
            used.update(f["id"] for f in mg)
        for f in fs:
            if f["id"] not in used:
                groups.append((verdicts[f["id"]]["category"], [f]))
        for kind, g in groups:
            lead = max(g, key=lambda f: verdicts[f["id"]]["score"])
            v = verdicts[lead["id"]]
            why = [v["why"]] + v.get("mods", [])
            if len(g) > 1:
                why.append(f"{len(g)} related filings grouped")
            events.append({
                "id": f"{ticker}:{session}:{kind}:{lead['id'].split(':')[-1]}",
                "ticker": ticker,
                "session": session,
                "ts": max(f["ts"] or "" for f in g),
                "category": v["category"],
                "tier": v["tier"],
                "score": v["score"],
                "rule": v["rule"],
                "why": why,
                "title": lead["subject"] or v["category"],
                "oneliner": clean_text(lead.get("text", ""))[:220],
                "filings": [{"id": f["id"], "subject": f["subject"], "text": clean_text(f.get("text", ""))[:200],
                             "url": f["url"], "ts": f["ts"], "tier": verdicts[f["id"]]["tier"]}
                            for f in sorted(g, key=lambda f: f["ts"] or "")],
                "card": None,
                "reaction": None,
            })
    events.sort(key=lambda e: (e["ts"] or ""), reverse=True)
    return events


def reaction(ticker, session, prices):
    """Market reaction on the session a filing could first affect."""
    dates = prices.get("dates", [])
    t = prices.get("t", {}).get(ticker)
    if not t or session not in dates:
        return {"status": "pending"}
    i = dates.index(session)
    if i == 0:
        return {"status": "pending"}
    c, v, n = t["c"], t["v"], prices["nifty"]
    if not c[i] or not c[i - 1]:
        return {"status": "pending"}
    ret = (c[i] / c[i - 1] - 1) * 100
    nret = (n[i] / n[i - 1] - 1) * 100 if n[i] and n[i - 1] else 0.0
    prior = [x for x in v[max(0, i - 20):i] if x]
    vol_x = (v[i] / (sum(prior) / len(prior))) if prior and v[i] else None
    return {"status": "ok", "ret": round(ret, 2), "abn": round(ret - nret, 2),
            "vol_x": round(vol_x, 2) if vol_x else None}
