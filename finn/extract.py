"""LLM extraction tasks. Every function validates what the model returns;
anything the model says that can't be checked against the source is dropped."""
import re

from . import llm

UNIT_TO_CR = {"crore": 1.0, "crores": 1.0, "cr": 1.0, "lakh": 0.01, "lakhs": 0.01, "lacs": 0.01,
              "million": 0.1, "millions": 0.1, "mn": 0.1, "billion": 100.0, "bn": 100.0, "thousand": 0.0001}


def norm(s):
    return re.sub(r"[^a-z0-9%.]+", " ", (s or "").lower()).strip()


def quote_in_text(quote, text, min_ratio=0.88):
    """True if the quote appears in the source (exact after normalising, or a
    near-exact window match to tolerate PDF line-break / hyphenation noise)."""
    q, t = norm(quote), norm(text)
    if len(q) < 12:
        return False
    if q in t:
        return True
    from difflib import SequenceMatcher
    qw = q.split()
    tw = t.split()
    if len(qw) < 4:
        return False
    # anchor on each 4-word shingle; compare a same-length window
    anchors = set()
    for i in range(0, len(qw) - 3, max(1, len(qw) // 6)):
        sh = " ".join(qw[i:i + 4])
        pos = t.find(sh)
        while pos != -1 and len(anchors) < 40:
            anchors.add((t[:pos].count(" "), i))
            pos = t.find(sh, pos + 1)
    for tpos, qi in anchors:
        start = max(0, tpos - qi)
        window = " ".join(tw[start:start + len(qw) + 3])
        if SequenceMatcher(None, q, window).ratio() >= min_ratio:
            return True
    return False


def as_obj(o, key):
    """Models sometimes return a bare list where we asked for {key: [...]}."""
    if isinstance(o, list):
        return {key: o}
    return o if isinstance(o, dict) else {key: []}


def numbers_in(s):
    return {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", s or "") if x.replace(",", "").replace(".", "")}


# --------------------------------------------------------------- results card
RESULTS_SYS = (
    "You read an Indian listed company's quarterly results filing. Use ONLY numbers printed in the text. "
    "Prefer the CONSOLIDATED statement if present. Return JSON: {\"basis\":\"consolidated|standalone\","
    "\"unit\":\"crore|lakh|million\",\"periods\":{\"current\":\"e.g. Q2 FY27 / quarter ended 30 Sep 2026\","
    "\"prev_quarter\":\"...\",\"year_ago\":\"...\"},"
    "\"rows\":{\"revenue_from_operations\":[cur,prevq,yearago],\"other_income\":[..],\"finance_costs\":[..],"
    "\"depreciation\":[..],\"profit_before_tax\":[..],\"tax_expense\":[..],\"profit_after_tax\":[..]}}. "
    "Use null for anything not printed. Do not compute anything."
)


def results_from_text(text, ticker=""):
    def validate(o):
        if isinstance(o, list) and o and isinstance(o[0], dict):
            o = o[0]
        rows = o.get("rows") or {}
        need = ["revenue_from_operations", "profit_before_tax", "profit_after_tax"]
        for k in need:
            v = rows.get(k)
            if not isinstance(v, list) or len(v) != 3 or v[0] is None:
                raise ValueError(f"missing {k}")
        pbt, tax, pat = rows["profit_before_tax"][0], (rows.get("tax_expense") or [None])[0], rows["profit_after_tax"][0]
        if tax is not None and pbt and abs((pbt - tax) - pat) > max(abs(pat) * 0.06, 1):
            raise ValueError("PBT - tax != PAT")  # usually wrong column/statement
        nums = numbers_in(text)
        if rows["revenue_from_operations"][0] not in nums and round(rows["revenue_from_operations"][0], 2) not in nums:
            raise ValueError("revenue not found in filing text")
        return o
    o = llm.ask("extract", RESULTS_SYS, text[:60000], ticker=ticker, validate=validate, max_out=1200)
    k = UNIT_TO_CR.get(str(o.get("unit", "crore")).lower(), 1.0)
    rows = o["rows"]

    def col(i):
        g = lambda name: (rows.get(name) or [None, None, None])[i]  # noqa: E731
        rev, pbt, pat = g("revenue_from_operations"), g("profit_before_tax"), g("profit_after_tax")
        fin, dep, oi = g("finance_costs"), g("depreciation"), g("other_income")
        ebitda = (pbt + (fin or 0) + (dep or 0) - (oi or 0)) if pbt is not None and dep is not None else None
        sc = lambda x: round(x * k, 1) if x is not None else None  # noqa: E731
        return {"revenue": sc(rev), "ebitda": sc(ebitda), "pbt": sc(pbt), "pat": sc(pat)}
    return {"basis": o.get("basis"), "periods": o.get("periods"), "cols": [col(0), col(1), col(2)]}


# ---------------------------------------------------------- management change
MGMT_SYS = (
    "You read an Indian company's filing about a management or board change. Use ONLY the text. "
    "Return JSON: {\"people\":[{\"name\":\"exact as written\",\"role\":\"e.g. Chief Financial Officer\","
    "\"change\":\"appointed|resigned|retired|redesignated|ceased\",\"effective\":\"date or null\","
    "\"reason\":\"short, or null\",\"profile\":\"<=45 words, from the brief profile in the filing, or null\","
    "\"background\":[\"previous employers / roles named in the filing\"]}]}"
)


def mgmt_from_text(text, ticker=""):
    def validate(o):
        o = as_obj(o, "people")
        ppl = []
        for p in o.get("people", []):
            if not isinstance(p, dict):
                continue
            name = (p.get("name") or "").strip()
            if not name or norm(name) not in norm(text):
                continue  # name must literally appear in the filing
            p["background"] = [b for b in (p.get("background") or []) if norm(b.split(",")[0])[:20] in norm(text)][:4]
            ppl.append(p)
        if not ppl:
            raise ValueError("no verifiable people")
        return {"people": ppl[:4]}
    return llm.ask("extract", MGMT_SYS, text[:30000], ticker=ticker, validate=validate, max_out=1200)


# ------------------------------------------------------------------ one-liner
LINE_SYS = ("Summarise this stock-exchange filing for an investor in ONE line of at most 22 words. "
            "Plain facts from the text only, include any amount or date. Return JSON {\"line\":\"...\"}.")


def one_line(subject, text, ticker=""):
    def validate(o):
        if isinstance(o, list) and o:
            o = o[0] if isinstance(o[0], dict) else {"line": str(o[0])}
        line = str(o.get("line", "")).strip()
        if not line or len(line) > 220:
            raise ValueError("bad line")
        for n in numbers_in(line):  # every number must come from the source
            if n not in numbers_in(subject + " " + text) and n > 31:
                raise ValueError("number not in source")
        return {"line": line}
    return llm.ask("summarize", LINE_SYS, f"Subject: {subject}\n{text[:3000]}", ticker=ticker,
                   validate=validate, max_out=200)["line"]


# ------------------------------------------------------- guidance / promises
METRICS = ["revenue_growth", "revenue", "margin", "profit_growth", "volume_growth", "capex", "capacity",
           "order_book", "market_share", "debt", "other"]

GUIDE_SYS = (
    "You extract forward-looking commitments made by MANAGEMENT (not analysts) on an Indian company's earnings "
    "call. Include explicit guidance, targets, and clear directional promises about the business (e.g. growth, "
    "margins, capex, capacity, launches, debt). Skip vague pleasantries and anything about the past.\n"
    "For each, return the EXACT sentence(s) from the transcript as `quote` (copy verbatim, max 60 words).\n"
    "Return JSON {\"items\":[{\"metric\":one of " + "|".join(METRICS) + ","
    "\"topic\":\"short label, e.g. 'FY27 revenue growth guidance' or 'Dahej plant commissioning'\","
    "\"kind\":\"guidance|target|directional\","
    "\"low\":number or null,\"high\":number or null,\"unit\":\"% | cr | GW | MW | units | x | days | other\","
    "\"basis\":\"e.g. constant currency, INR, YoY, EBIT margin, EBITDA margin, or null\","
    "\"margin_type\":\"ebit|ebitda|pat|gross|null\","
    "\"horizon\":\"e.g. FY27, Q3FY27, FY28, H2FY27, medium term\",\"speaker\":\"name or role\",\"quote\":\"...\"}]}"
)


def guidance_from_transcript(text, call_label, ticker=""):
    """Returns (verified_items, dropped_count). An item survives only if its
    quote is found in the transcript and its numbers appear in the quote."""
    stats = {"found": 0, "dropped_quote": 0, "dropped_number": 0}

    def validate(o):
        o = as_obj(o, "items")
        if not isinstance(o.get("items"), list):
            raise ValueError("no items list")
        o["items"] = [x for x in o["items"] if isinstance(x, dict)]
        return o
    try:
        o = llm.ask("extract", GUIDE_SYS, f"Call: {call_label}\n\nTRANSCRIPT:\n{text[:180000]}", ticker=ticker,
                    validate=validate, max_out=6000)
    except llm.LLMError as e:
        # Gemini out of quota (or every model refused the whole transcript): read it in
        # ~5k-token pieces with the fallback provider and merge. Checks below are identical.
        if not llm.resolve_models().get("groq") or isinstance(e, llm.QuotaExhausted) and "groq" in str(e):
            raise
        print(f"    extract {ticker} {call_label}: falling back to chunked reading ({str(e)[:80]})", flush=True)
        o = {"items": []}
        for n, chunk in enumerate(_chunks(text[:180000]), 1):
            part = llm.ask("extract_chunk", GUIDE_SYS, f"Call: {call_label} (part {n})\n\nTRANSCRIPT EXCERPT:\n{chunk}",
                           ticker=ticker, validate=validate, max_out=2500)
            o["items"] += part["items"]
    kept = []
    for it in o["items"]:
        stats["found"] += 1
        q = it.get("quote") or ""
        if not quote_in_text(q, text):
            stats["dropped_quote"] += 1
            continue
        qn = numbers_in(q)
        bad = [v for v in (it.get("low"), it.get("high")) if isinstance(v, (int, float)) and float(v) not in qn]
        if bad:
            stats["dropped_number"] += 1
            continue
        if it.get("metric") not in METRICS:
            it["metric"] = "other"
        key = norm(q)[:120]
        if any(norm(k["quote"])[:120] == key for k in kept):
            continue  # same promise seen twice (chunk overlap)
        it["call"] = call_label
        kept.append(it)
    return kept, stats


def _chunks(text, size=18000, overlap=600):
    """Split on paragraph breaks into ~size-char pieces, overlapping a little so a
    promise that straddles a boundary is still seen whole in one of them."""
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            k = text.rfind("\n", i + size // 2, j)
            j = k if k > 0 else j
        out.append(text[max(0, i - overlap):j])
        i = j
    return out


THREAD_SYS = (
    "You are given numbered management commitments from several earnings calls of one company, oldest first. "
    "Group items that are about the SAME commitment (same metric and same target period / project) into threads. "
    "Return JSON {\"threads\":[{\"title\":\"<=8 words\",\"items\":[item numbers]}]}. Every item in exactly one thread."
)


def thread_items(items, ticker=""):
    listing = "\n".join(f"{i}. [{it['call']}] {it['metric']} | {it.get('topic')} | horizon {it.get('horizon')} | "
                        f"{it.get('low')}-{it.get('high')} {it.get('unit') or ''}" for i, it in enumerate(items))

    def validate(o):
        o = as_obj(o, "threads")
        seen = set()
        out = []
        for th in o.get("threads", []):
            if not isinstance(th, dict):
                continue
            ids = [i for i in th.get("items", []) if isinstance(i, int) and 0 <= i < len(items) and i not in seen]
            seen.update(ids)
            if ids:
                out.append({"title": str(th.get("title", ""))[:80], "items": ids})
        for i in range(len(items)):  # anything the model forgot becomes its own thread
            if i not in seen:
                out.append({"title": items[i].get("topic", ""), "items": [i]})
        return {"threads": out}
    if not items:
        return {"threads": []}
    return llm.ask("extract", THREAD_SYS, listing, ticker=ticker, validate=validate, max_out=2000)


BUSINESS_SYS = (
    "From this earnings-call transcript opening, describe the business for an investor. Use ONLY the text. "
    "Return JSON {\"what\":\"<=30 words\",\"segments\":[{\"name\":\"...\",\"note\":\"<=12 words, include share % only if stated\"}],"
    "\"quote\":\"one verbatim sentence supporting `what`\"}"
)


def business_from_text(text, ticker=""):
    def validate(o):
        if isinstance(o, list) and o and isinstance(o[0], dict):
            o = o[0]
        if not o.get("what"):
            raise ValueError("no what")
        o["quote_verified"] = quote_in_text(o.get("quote", ""), text)
        o["segments"] = (o.get("segments") or [])[:6]
        return o
    return llm.ask("extract", BUSINESS_SYS, text[:40000], ticker=ticker, validate=validate, max_out=900)
