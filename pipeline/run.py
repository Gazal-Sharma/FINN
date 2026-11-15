"""FINN scheduled job, in stages.

    python pipeline/run.py                         # all stages
    python pipeline/run.py --stage filings --tickers INFY,TCS
    python pipeline/run.py --stage research --research INFY

Fetch stages write raw/ (as fetched). Build stages read only raw/ + cache/ and
write public/data/ — they never touch the network except for LLM calls, so they
can be re-run offline. One ticker failing never fails the stage; each stage's
outcome is recorded in raw/status.json and shown in the app.
"""
import argparse
import re
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finn import config, now_ist, read_json, write_json, write_text  # noqa: E402
from finn import sources, classify  # noqa: E402

RAW = config.RAW
STATUS = RAW / "status.json"


def record(stage, ok, note="", **extra):
    st = read_json(STATUS, {})
    st[stage] = {"ok": ok, "at": now_ist().isoformat(timespec="seconds"), "note": note[:300], **extra}
    write_json(STATUS, st, indent=1)
    print(f"[{stage}] {'ok' if ok else 'FAILED'} {note}")


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


# ----------------------------------------------------------------- fetch: smoke
def stage_smoke(args):
    res = {}
    try:
        n = sources.NSE()
        rows = n.announcements("INFY", now_ist() - timedelta(days=10), now_ist())
        res["nse"] = f"ok ({len(rows)} filings)"
    except Exception as e:
        res["nse"] = f"FAIL {e}"
    try:
        s = sources.fetch_screener("INFY")
        res["screener"] = f"ok ({len(s['concalls'])} concalls)"
    except Exception as e:
        res["screener"] = f"FAIL {e}"
    try:
        p = sources.fetch_prices(["INFY.NS"], days=10)
        res["prices"] = f"ok ({len(p.get('INFY.NS', []))} days)"
    except Exception as e:
        res["prices"] = f"FAIL {e}"
    try:
        from finn import llm
        res["gemini"] = llm.resolve_models()
    except Exception as e:
        res["gemini"] = f"FAIL {e}"
    write_json(RAW / "smoke.json", {"at": now_ist().isoformat(), **res}, indent=1)
    for k, v in res.items():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------- fetch: prices
def stage_prices(args, days=150):
    tickers = args.tickers or list(config.PORTFOLIO)
    syms = [f"{t}.NS" for t in tickers] + [config.INDEX_YF]
    data = sources.fetch_prices(syms, days=days)
    old = read_json(RAW / "prices.json", {})
    for k, rows in data.items():  # merge by date so short refreshes never erase backfilled history
        if rows:
            m = {r[0]: r for r in old.get(k, [])}
            m.update({r[0]: r for r in rows})
            old[k] = [m[d] for d in sorted(m)]
    write_json(RAW / "prices.json", old)
    missing = [s for s in syms if s not in data]
    record("prices", not missing or len(missing) < len(syms), f"{len(data)}/{len(syms)} symbols" +
           (f"; missing {','.join(missing)}" if missing else ""))


# --------------------------------------------------------------- fetch: filings
def stage_filings(args):
    tickers = args.tickers or list(config.PORTFOLIO)
    end = now_ist()
    start = end - timedelta(days=args.days)
    nse = sources.NSE()
    used, errors, total = {}, [], 0
    for t in tickers:
        c = config.company(t)
        rows, src, err = sources.fetch_filings(t, c["bse"], start, end, nse=nse)
        if err:
            errors.append(f"{t}: {err[:120]}")
        if src:
            used[src] = used.get(src, 0) + 1
        path = RAW / "filings" / f"{t}.json"
        store = read_json(path, {})
        for f in rows:
            store[f["id"]] = f
        write_json(path, store, indent=None)
        total += len(rows)
        time.sleep(0.8)
    record("filings", bool(used), f"{total} filings; sources {used}" + (f"; errors: {' | '.join(errors[:3])}" if errors else ""))
    stage_docs(args, nse)


def stage_docs(args, nse=None):
    """PDF text only for filings that need it: results, management change, unmatched."""
    nse = nse or sources.NSE()
    tickers = args.tickers or list(config.PORTFOLIO)
    cutoff = (now_ist() - timedelta(days=args.days)).isoformat()
    todo = []
    for t in tickers:
        for f in read_json(RAW / "filings" / f"{t}.json", {}).values():
            if not f.get("url") or (f.get("ts") or "") < cutoff:
                continue
            if (RAW / "docs" / f"{safe(f['id'])}.txt").exists():
                continue
            v = classify.rule_verdict(f)
            if v is None or v["rule"] in ("results_outcome", "mgmt_top_exit", "mgmt_top_join", "mgmt_other"):
                todo.append(f)
    todo.sort(key=lambda f: f["ts"] or "", reverse=True)
    got = 0
    for f in todo[: args.max_docs]:
        txt = sources.pdf_text(f["url"], nse=nse, max_pages=25)
        write_text(RAW / "docs" / f"{safe(f['id'])}.txt", txt)  # empty file = tried, failed
        got += bool(txt)
        time.sleep(0.5)
    record("docs", True, f"{got}/{min(len(todo), args.max_docs)} PDFs extracted ({len(todo)} wanted)")


def stage_backfill(args):
    """One-off: ~12 months of filings + ~18 months of prices, for ranking evidence.
    No PDFs and no AI: old filings are judged by rules only."""
    stage_prices(args, days=560)
    tickers = args.tickers or list(config.PORTFOLIO)
    nse = sources.NSE()
    end = now_ist()
    total, errs = 0, []
    for t in tickers:
        path = RAW / "filings" / f"{t}.json"
        store = read_json(path, {})
        for k in range(6):  # six ~2-month chunks
            e = end - timedelta(days=61 * k)
            s_ = e - timedelta(days=61)
            rows, src, err = sources.fetch_filings(t, config.company(t)["bse"], s_, e, nse=nse)
            if err:
                errs.append(f"{t}: {err[:80]}")
            for f in rows:
                store.setdefault(f["id"], f)
            total += len(rows)
            time.sleep(0.7)
        write_json(path, store)
        print(f"[backfill] {t}: {len(store)} filings stored", flush=True)
    record("backfill", total > 0, f"{total} filings fetched over 12 months" + (f"; {len(errs)} chunk errors" if errs else ""))


# -------------------------------------------------------------- fetch: screener
def stage_screener(args):
    tickers = args.tickers or sorted(set(config.PORTFOLIO) | set(config.RESEARCH_SET) | set(args.research or []))
    ok, bad = 0, []
    for t in tickers:
        try:
            write_json(RAW / "screener" / f"{t}.json", sources.fetch_screener(t))
            ok += 1
        except Exception as e:
            bad.append(f"{t}: {str(e)[:80]}")
        time.sleep(2.5)
    record("screener", ok > 0, f"{ok}/{len(tickers)}" + (f"; {' | '.join(bad[:3])}" if bad else ""))


def stage_symbols(args):
    try:
        rows = sources.nse_symbol_list()
        write_json(config.PUBLIC_DATA / "symbols.json", rows)
        record("symbols", True, f"{len(rows)} NSE symbols")
    except Exception as e:
        record("symbols", False, str(e))


# ----------------------------------------------------------- fetch: transcripts
def fetch_transcripts(t, nse=None, n=4):
    """Latest n transcripts: screener's links first, NSE filings as fallback."""
    nse = nse or sources.NSE()
    folder = RAW / "transcripts" / t
    index = read_json(folder / "index.json", [])
    have = {x["url"] for x in index if x.get("chars", 0) > 2000}
    sc = read_json(RAW / "screener" / f"{t}.json") or sources.fetch_screener(t)
    cands = [{"when": c["when"], "url": c["transcript"]} for c in sc.get("concalls", []) if c.get("transcript")]
    got = [x for x in index if x["url"] in have]
    for c in cands:
        if len(got) >= n:
            break
        if c["url"] in have:
            continue
        txt = sources.pdf_text(c["url"], nse=nse, max_pages=60)
        if len(txt) > 2000:
            fname = safe(c["when"] or str(len(got))) + ".txt"
            write_text(folder / fname, txt)
            got.append({"when": c["when"], "url": c["url"], "file": fname, "chars": len(txt)})
        time.sleep(1)
    if len(got) < n:  # BSE-hosted links blocked? try NSE filings
        for f in sources.find_transcripts_on_nse(t, nse=nse):
            if len(got) >= n:
                break
            if f["url"] in {g["url"] for g in got}:
                continue
            txt = sources.pdf_text(f["url"], nse=nse, max_pages=60)
            if len(txt) > 2000:
                when = (f["ts"] or "")[:7]
                fname = safe(f"nse-{when}-{f['id']}") + ".txt"
                write_text(folder / fname, txt)
                got.append({"when": when, "url": f["url"], "file": fname, "chars": len(txt), "via": "nse"})
    write_json(folder / "index.json", got, indent=1)
    return got


def stage_transcripts(args):
    nse = sources.NSE()
    tickers = args.research or config.PREBUILD
    summary = []
    for t in tickers:
        try:
            got = fetch_transcripts(t, nse=nse)
            summary.append(f"{t}:{len(got)}")
        except Exception as e:
            summary.append(f"{t}:ERR {str(e)[:60]}")
    record("transcripts", True, " ".join(summary))


# ------------------------------------------------------------------ build stages
def stage_build(args):
    """raw/ -> public/data (prices.json, events.json, meta.json). No network."""
    from finn import build
    build.build_all(args)


def stage_research(args):
    """Pre-build dossiers in PREBUILD order. Skips any whose transcripts haven't changed.
    Stops cleanly when the free daily quota runs out; the next run carries on."""
    from finn import research, llm
    tickers = args.research or config.PREBUILD
    built, skipped, failed, left = [], [], [], []
    for i, t in enumerate(tickers):
        out = config.PUBLIC_DATA / "research" / f"{t}.json"
        if not args.force and not research.needs_rebuild(read_json(out), t):
            skipped.append(t)
            continue
        if not (RAW / "transcripts" / t / "index.json").exists():
            try:
                if not (RAW / "screener" / f"{t}.json").exists():
                    write_json(RAW / "screener" / f"{t}.json", sources.fetch_screener(t))
                fetch_transcripts(t)
            except Exception as e:
                print(f"[research {t}] couldn't fetch inputs: {e}", flush=True)
        try:
            d = research.build(t, offline_raw=True)
            write_json(out, d)
            built.append(t)
            print(f"[research] done {t} ({len(built)} built, {len(tickers) - i - 1} to go)", flush=True)
        except llm.QuotaExhausted as e:
            print(f"[research] stopping: {e}", flush=True)
            left = tickers[i:]
            break
        except Exception as e:
            traceback.print_exc()
            failed.append(t)
    note = f"built {len(built)} ({','.join(built) or '-'}); unchanged {len(skipped)}"
    if failed:
        note += f"; failed {','.join(failed)}"
    if left:
        note += f"; quota ran out before {','.join(left)}"
    record("research", bool(built or skipped), note)
    meta = read_json(config.PUBLIC_DATA / "meta.json")
    if meta:  # let the app know which dossiers exist without a full rebuild
        meta["research_ready"] = sorted(p.stem for p in (config.PUBLIC_DATA / "research").glob("*.json"))
        meta["status"] = read_json(STATUS, {})
        write_json(config.PUBLIC_DATA / "meta.json", meta, indent=1)


STAGES = {
    "smoke": stage_smoke, "prices": stage_prices, "filings": stage_filings, "docs": stage_docs,
    "screener": stage_screener, "symbols": stage_symbols, "transcripts": stage_transcripts,
    "build": stage_build, "research": stage_research, "backfill": stage_backfill,
}
ALL = ["prices", "filings", "screener", "symbols", "transcripts", "build", "research"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", help=",".join(["all"] + list(STAGES)))
    ap.add_argument("--tickers", default="", help="comma list (default: portfolio)")
    ap.add_argument("--research", default="", help="comma list (default: research set)")
    ap.add_argument("--days", type=int, default=30, help="filings look-back window")
    ap.add_argument("--max-docs", type=int, default=60)
    ap.add_argument("--force", action="store_true", help="rebuild research even if unchanged")
    args = ap.parse_args()
    args.tickers = [x.strip().upper() for x in args.tickers.split(",") if x.strip()]
    args.research = [x.strip().upper() for x in args.research.split(",") if x.strip()]
    stages = ALL if args.stage == "all" else args.stage.split(",")
    for s in stages:
        print(f"=== {s} ===", flush=True)
        try:
            STAGES[s](args)
        except Exception as e:
            traceback.print_exc()
            record(s, False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
