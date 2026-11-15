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
    ("esop", "unclassified", "hidden", "ESOP / RSU allotment", r"esop|esos|esps|employee stock|stock option|restricted stock|\brsus?\b"),
    ("monitoring", "unclassified", "hidden", "Monitoring-agency report", r"monitoring agency"),
    ("esg", "unclassified", "hidden", "ESG / sustainability report", r"\besg\b|brsr|business responsibility|sustainability report"),
    ("xbrl", "unclassified", "hidden", "XBRL / format filing", r"xbrl|integrated filing \(governance\)"),
    ("auditor_subj", "unclassified", "hidden", "Auditor change", r"^change in auditors?"),
    ("auditor", "unclassified", "hidden", "Auditor appointment", r"T:(appointment|re-?appointment) of (statutory |secretarial |internal |cost )?auditor"),
    ("rta", "unclassified", "hidden", "Registrar / share-transfer change", r"T:share transfer agent|registrar and transfer"),

    # --- results family
    ("results_intimation", "results", "know", "Results date announced",
     r"board meeting intimation|intimation of board meeting|prior intimation.*(results|financial)"),
    ("results_outcome", "results", "act", "Quarterly results filed",
     r"(outcome of board meeting|financial result).*(financial results|results for the (quarter|period|year))|^financial result updates|audited financial results|unaudited financial results|results for the quarter"),
    ("results_clarification", "results", "know", "Clarification on results", r"clarification.*financial results"),
    ("investor_presentation", "results", "know", "Investor / analyst presentation", r"investor presentation|analyst presentation|shareholders'? letter"),

    # --- management change
    ("mgmt_top_exit", "management_change", "act", "Top executive leaving",
     TOP_ROLES + r".{0,120}(resign|cessation|step(s|ping)? down|retire)|(resign|cessation|step(s|ping)? down|retire).{0,120}" + TOP_ROLES),
    ("mgmt_top_join", "management_change", "act", "New top executive",
     TOP_ROLES + r".{0,120}(appoint|elevat|designat|successor)|(appoint|elevat|designat|successor).{0,120}" + TOP_ROLES),
    ("mgmt_other", "management_change", "know", "Board / KMP change",
     r"change in directors?|change in director\(s\)|^retirement|key managerial|change in management|resignation|appointment of (an? )?(independent |additional |non-executive )?director|company secretary|compliance officer|senior management"),

    # --- corporate events
    ("insider", "insider_trading", "know", "Promoter / insider dealing",
     r"insider trading|\bsast\b|regulation 29|regulation 31|reg\.? 7\(2\)|disclosure under sebi takeover"),
    ("mna", "M&A", "act", "Acquisition / merger / JV",
     r"acquisition|amalgamation|merger|demerger|scheme of arrangement|joint venture|takeover|stake (sale|purchase)|divest|slump sale"),
    ("fund_raise_equity", "fund_raise", "act", "Equity raise or buyback",
     r"qualified institutional|\bqip\b|rights issue|preferential (issue|allotment)|buy ?back|further public offer"),
    ("fund_raise_debt", "fund_raise", "know", "Debt raise",
     r"commercial paper|non[- ]?convertible|\bncd|debenture|bond issue|raising of funds|fund raising|allotment of (secured|unsecured)"),
    ("pledge", "pledging", "act", "Promoter pledge change", r"pledge|encumbrance"),
    ("rating_down", "credit_rating", "act", "Credit rating downgraded", r"(credit )?rating.{0,80}(downgrad|negative|watch)|downgrad.{0,40}rating"),
    ("rating_other", "credit_rating", "hidden", "Credit rating reaffirmed / assigned", r"credit rating|rating agency|\bcrisil\b|\bicra\b|care ratings|india ratings"),
    ("orders_passed", "litigation", "know", "Regulatory / tax order", r"^action\(s\) taken or orders passed"),
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
    "For EACH numbered filing return one verdict. category: one of " + ", ".join(CATEGORIES) + ". "
    "tier: act = could move the stock or change the investment thesis; know = worth one line; "
    "hidden = routine paperwork. why: <=8 words. "
    "Return JSON {\"verdicts\":[{\"i\":number,\"category\":...,\"tier\":...,\"why\":...}]}"
)
BATCH = 20


def _ai_batch(batch, docs_text):
    """One model call for up to BATCH filings. Returns {filing_id: verdict}."""
    from . import llm
    lines = []
    for i, f in enumerate(batch):
        body = (f.get("text") or "")[:400]
        if docs_text and docs_text.get(f["id"]):
            body += " || " + re.sub(r"\s+", " ", docs_text[f["id"]][:700])
        lines.append(f"{i}. [{f['ticker']}] {f.get('subject', '')}: {body}")

    def validate(o):
        got = {}
        o = o if isinstance(o, dict) else {"verdicts": o if isinstance(o, list) else []}
        for v in o.get("verdicts", []):
            if not isinstance(v, dict):
                continue
            i = v.get("i")
            if isinstance(i, int) and 0 <= i < len(batch) and v.get("category") in CATEGORIES \
                    and v.get("tier") in ("act", "know", "hidden"):
                got[i] = {"category": v["category"], "tier": v["tier"], "why": str(v.get("why", ""))[:80]}
        if len(got) < len(batch) * 0.8:
            raise ValueError(f"only {len(got)}/{len(batch)} verdicts")
        return {str(k): v for k, v in got.items()}
    res = llm.ask("classify", AI_SYSTEM, "\n".join(lines), ticker="batch", validate=validate, max_out=120 * len(batch))
    return {batch[int(k)]["id"]: {**v, "rule": "ai", "source": "ai"} for k, v in res.items()}


def classify(filings, docs_text=None, use_ai=True):
    """Return {filing_id: verdict}. Rules first; the rest go to the cheapest model
    in batches of 20, and each verdict is cached per filing id (cache/verdicts.json)."""
    cache_path = config.CACHE / "verdicts.json"
    cached = read_json(cache_path, {})
    rule_v = {f["id"]: rule_verdict(f) for f in filings}
    need = [f for f in filings if rule_v[f["id"]] is None and f["id"] not in cached]
    print(f"[build] classify: {len(filings)} filings, {len(filings) - len(need)} decided by rules/cache, "
          f"{len(need)} need AI{'' if use_ai else ' (no key: skipped)'}", flush=True)
    if use_ai:
        for b in range(0, len(need), BATCH):
            batch = need[b:b + BATCH]
            print(f"[build] AI triage batch {b // BATCH + 1}/{-(-len(need) // BATCH)} ({len(batch)} filings)", flush=True)
            try:
                cached.update(_ai_batch(batch, docs_text))
                write_json(cache_path, cached, indent=1)  # save as we go
            except Exception as e:
                print("ai classify batch failed", e)
    out = {}
    for f in filings:
        v = rule_v[f["id"]] or cached.get(f["id"]) or {
            "category": "unclassified", "tier": "know", "why": "Unrecognised filing type", "rule": "fallback", "source": "rule"}
        blob = f"{f.get('subject', '')} {f.get('text', '')[:700]}"
        score, reasons = config.TIER_BASE[v["tier"]], []
        if v["tier"] != "hidden":
            for rx, delta, reason in MODIFIERS:
                if rx.search(blob):
                    score += delta
                    reasons.append(reason)
        out[f["id"]] = {**v, "score": score, "mods": reasons}
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
                "evidence": v.get("evidence"),
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


# --------------------------------------------------------------- calibration
# Evidence for the tiers: how often does each filing type coincide with a big
# move in the stock (>= 2x its usual daily move, net of Nifty) on the session it
# could first affect, compared with an ordinary day with no filings at all?
BIG = 2.0
MIN_N = 12
DEMOTE_BELOW = 1.25   # Know -> Hidden if lift is below this
PROMOTE_ABOVE = 2.0   # Hidden -> Know if lift is at least this
PROTECTED = {"litigation", "insider", "pledge", "insolvency", "rating_down"}  # risk signals: never demoted
LABELS = {rid: why for rid, _, _, why, _ in RULES}


def _series(rows):
    return {d: (c, v) for d, c, v in rows}


def calibrate(filings, raw_prices):
    """Return {"baseline":..., "rules": {rule_id: stats + decision}} using rules
    (and cached AI verdicts) only: no new AI calls, no network."""
    import statistics
    nifty = raw_prices.get(config.INDEX_YF) or []
    dates = [d for d, _, _ in nifty]
    if len(dates) < 80:
        return None
    pos = {d: i for i, d in enumerate(dates)}
    nc = [c for _, c, _ in nifty]
    cached = read_json(config.CACHE / "verdicts.json", {})

    z_by = {}  # (ticker, date) -> (z, volx)
    for t in config.PORTFOLIO:
        m = _series(raw_prices.get(f"{t}.NS") or [])
        c = [m.get(d, (None, None))[0] for d in dates]
        v = [m.get(d, (None, None))[1] for d in dates]
        ab = [None] + [((c[i] / c[i - 1] - 1) - (nc[i] / nc[i - 1] - 1)) * 100
                       if c[i] and c[i - 1] and nc[i] and nc[i - 1] else None for i in range(1, len(dates))]
        for i in range(61, len(dates)):
            if ab[i] is None:
                continue
            prior = [x for x in ab[i - 60:i] if x is not None]
            if len(prior) < 30:
                continue
            sd = statistics.pstdev(prior)
            vols = [x for x in v[i - 20:i] if x]
            volx = v[i] / (sum(vols) / len(vols)) if vols and v[i] else None
            z_by[(t, dates[i])] = (abs(ab[i]) / sd if sd else 0, volx)

    by_session = defaultdict(list)
    for f in filings:
        if f["ticker"] not in config.PORTFOLIO:
            continue
        s = reaction_session(f["ts"], dates)
        if s in pos:
            by_session[(f["ticker"], s)].append(f)

    rules_by = {}
    for key, fs in by_session.items():
        rules = []
        for f in fs:
            v = rule_verdict(f) or ({**cached[f["id"]], "rule": f"ai:{cached[f['id']]['category']}"} if f["id"] in cached else None)
            if v:
                rules.append(v["rule"])
        rules_by[key] = set(rules)
    # Results moves spill into the session after; filings in that window would be
    # credited with a move they didn't cause, so they're left out (both sides).
    results_window = set()
    for (t, d), rs in rules_by.items():
        if "results_outcome" in rs:
            i = pos[d]
            results_window.update({(t, d), (t, dates[i + 1]) if i + 1 < len(dates) else (t, d)})
    samples = defaultdict(set)
    for key, rs in rules_by.items():
        if key not in z_by:
            continue
        for r in rs:
            if key in results_window and r != "results_outcome":
                continue
            samples[r].add(key)

    filing_days = set(by_session) | results_window
    base = [z for k, (z, _) in z_by.items() if k not in filing_days]
    base_big = sum(1 for z in base if z >= BIG) / len(base) if base else 0.05
    out = {"window": [dates[61], dates[-1]], "big": BIG, "min_n": MIN_N,
           "baseline": {"n": len(base), "big_rate": round(base_big, 3),
                        "median_z": round(statistics.median(base), 2) if base else None},
           "rules": {}}
    tier_of = {rid: tier for rid, _, tier, _, _ in RULES}
    for r, keys in samples.items():
        zs = [z_by[k][0] for k in keys]
        vx = [z_by[k][1] for k in keys if z_by[k][1]]
        big = sum(1 for z in zs if z >= BIG) / len(zs)
        lift = big / base_big if base_big else None
        tier = tier_of.get(r, "ai")
        decision, why = "keep", ""
        if len(zs) < MIN_N:
            decision, why = "keep", f"only {len(zs)} past examples; kept by judgment"
        elif r in PROTECTED:
            why = "risk signal; kept regardless of price reaction"
        elif tier in ("know", "ai") and lift is not None and lift < DEMOTE_BELOW:
            decision = "demote"
            why = f"moved the stock ≥{BIG:g}× usual {big:.0%} of the time vs {base_big:.0%} on an ordinary day"
        elif tier == "hidden" and lift is not None and lift >= PROMOTE_ABOVE and round(big * len(zs)) >= 3:
            decision = "promote"
            why = f"moved the stock ≥{BIG:g}× usual {big:.0%} of the time vs {base_big:.0%} on an ordinary day"
        out["rules"][r] = {"label": LABELS.get(r, r.replace("ai:", "AI-judged ")), "tier": tier, "n": len(zs),
                           "big_rate": round(big, 3), "lift": round(lift, 2) if lift is not None else None,
                           "median_z": round(statistics.median(zs), 2),
                           "median_volx": round(statistics.median(vx), 2) if vx else None,
                           "decision": decision, "why": why}
    return out


def apply_calibration(verdicts, calib):
    """Move tiers where the evidence says so, and attach the evidence to every verdict."""
    if not calib:
        return verdicts
    rules = calib["rules"]
    for v in verdicts.values():
        key = v["rule"] if v["rule"] != "ai" else f"ai:{v['category']}"
        c = rules.get(key)
        if not c:
            continue
        v["evidence"] = {k: c[k] for k in ("n", "big_rate", "lift", "decision")}
        if c["decision"] == "demote" and v["tier"] == "know":
            v["tier"], v["score"] = "hidden", 0
            v["mods"] = ["evidence: " + c["why"]]
        elif c["decision"] == "demote" and v["tier"] == "act" and v["rule"] == "ai":
            v["tier"], v["score"] = "know", config.TIER_BASE["know"]  # AI said act; history disagrees
            v["mods"] = ["evidence: " + c["why"]]
        elif c["decision"] == "promote" and v["tier"] == "hidden":
            v["tier"], v["score"] = "know", config.TIER_BASE["know"]
            v["mods"] = ["evidence: " + c["why"]]
    return verdicts
