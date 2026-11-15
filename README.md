# FINN: Financial Investment Agent

A phone-first app for an NSE investor that does two things:

- **Push (Today, Alerts).** It tells you what changed in your 18 holdings, ranked **Act / Know / Hidden**, with routine paperwork folded away. Results-day filings collapse into one card with Revenue / EBITDA / PBT / PAT QoQ and YoY. Management changes show who the new person is.
- **Pull (Research).** It **keeps score on management**. For any NSE ticker it reads the last four earnings-call transcripts and extracts every promise. Each quote is checked word-for-word against the transcript, and each promise is scored against the reported numbers: kept, missed, goalposts moved, or quietly dropped.

## Try it on a phone (3 taps)

1. **Today** shows the default window, the last 24 hours. On a weekend it widens to the last trading session and says so. Tap **▶ Listen** for a 60-second spoken brief.
2. **Alerts**: drag the sliders. The panel shows how many alerts you *would have had* over the last 60 sessions with those settings.
3. **Research → INFY**: promised vs delivered first. Tap any promise to see the exact quote and the transcript it came from. Type any other NSE symbol to build one live (~1 min).

## How it's built

```
public/            static app (vanilla ES modules, no build step), served by Vercel
  data/            built by the pipeline: meta, prices, events, research/<T>.json, symbols
api/research.py    Vercel function: live dossier for a ticker not in the snapshot
finn/              shared Python core
  sources.py       NSE (cookie warm-up) → BSE fallback, yfinance, screener, PDF text
  classify.py      rules → category + tier + "why"; results-day grouping; market reaction
  extract.py       Gemini extraction with verification (quotes, numbers, names)
  research.py      promise ledger: deterministic scoring + one checked synthesis call
  build.py         raw/ → public/data (push side)
  llm.py           Gemini routing (flash-lite → flash → pro), cache, usage log
pipeline/run.py    scheduled job in stages: fetch → raw/, build → public/data/
.github/workflows  runs the pipeline on a schedule and on demand, commits the data
raw/  cache/  logs/  committed: what was fetched, cached LLM answers, token usage
```

**Run locally:** `pip install -r requirements-pipeline.txt`, set `GEMINI_API_KEY`, run `python pipeline/run.py` (or `--stage build`, `--stage research --research INFY`). Then serve `public/` with any static server.

**Tests:** `python tests/test_rules.py`

See `WRITEUP.md` for the decisions, trade-offs and what's deliberately left out.
