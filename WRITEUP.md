# FINN: covering note (draft)

## What I built

FINN is a phone-first app with one point of view: **an investor's scarce resource is attention, and management's scarce resource is credibility.** So FINN does two jobs:

1. **Today / Alerts (push).** Every filing across an 18-stock portfolio is ranked **Act / Know / Hidden**, and each ranking says *why*. Results-day paperwork (outcome, results, press release, deck, newspaper ad, concall notice) collapses into **one** results card: Revenue, EBITDA, PBT, PAT with QoQ and YoY. Management changes show who the incoming person is, taken from the profile the company is required to file. Every event shows how the market actually reacted (abnormal move vs Nifty, volume multiple). When FINN hid something the market cared about, it says so.
2. **Research (pull).** It **keeps score on management**. FINN reads the last four earnings-call transcripts and extracts every forward-looking promise, then scores each one against reported numbers: *kept, missed, on/off track, goalposts moved, quietly dropped,* or *can't verify*. It's analysing management rather than summarising them, which is the brief's own worked example.

## Key decisions

- **No chat box.** The investor's day is triage, then a deep dive. Today is a ranked feed with a designed "nothing needs you" state. Research is a dossier that opens on the promise ledger. A chat box would make the user do the asking.
- **Rules first, AI only where rules can't decide.** Exchanges already tag filings with a subject, so ~75% are decided by ~40 regex rules covered by a golden test set. The rest go to the cheapest Gemini model **in batches of 20** and are cached per filing ID, so no filing is ever paid for twice.
- **The AI never supplies a number it can't check.**
  - Results numbers come from reported tables, computed in code.
  - When FINN does extract from a PDF, the arithmetic must reconcile (PBT − tax ≈ PAT).
  - Every promise quote must be found word-for-word in the transcript, and the promised number must appear inside that quote. Otherwise it's dropped, and the app shows how many were dropped.
  - Verdicts are computed in code.
  - The one "strong model" call sees only verified records. Every number it writes must exist in its input, and every sentence must cite a record, or that sentence is removed.
- **Honest comparisons.** Infosys guides in constant currency; we only have INR numbers, so those verdicts carry a "≈". Lenders have no EBITDA, so their card shows financing profit instead. Guided years still in progress are *on/off track*, not kept/missed.
- **Alerts are calibrated, not just configured.** Sliders show how many alerts you *would have had* over the last 60 sessions. The default mode measures moves against each stock's own volatility: ±3% is noise for DIXON and news for HDFCBANK.
- **Learn, for beginners.** A plain-language page explaining how filings, results, alerts and research connect, a glossary in which each term says where it appears in FINN, and verified beginner reading (Zerodha Varsity first). A floating **Ask** button on every screen answers from the glossary instantly and for free, and calls the cheapest Gemini model only when the glossary doesn't cover the question. It's told what screen you're on and never gives buy or sell advice.
- **Listen.** A 60-second spoken brief using the phone's own speech engine. It costs nothing and is assembled from the ranked events by code, not written by a model. The script is written for the ear: "(s)" becomes a plural, "Q2 FY27" becomes "the September 2026 quarter", "₹" and "%" are spoken in words, and legal filing subjects are replaced with a plain description.

## Architecture and cost

- **Pipeline:** a GitHub Actions job (scheduled, plus on demand) fetches NSE filings, prices, screener tables and transcripts into `raw/`. Build stages turn `raw/` into static JSON in `public/data/`. The raw data, LLM cache and usage log are all committed, so every run is reproducible and nothing is paid for twice.
- **Hosting:** Vercel serves the static app. One Python function builds research live for a ticker that isn't in the snapshot, using the same code as the pipeline. That's how it generalises to any NSE symbol.
- **Model routing (Gemini only):**

  | Task | Model chain |
  |---|---|
  | Triage | flash-lite → flash |
  | Extraction | flash → flash-lite |
  | Synthesis | pro → flash |

  Model names are discovered at runtime. A model that returns "rate limited" is skipped for the rest of the run instead of waited on.
- **Cost:** see `logs/usage.jsonl` (per call: ticker, task, model, tokens, cache hit, list-price cost). TODO: fill in per-company cost after the final run.

## What I left out, on purpose

- **LinkedIn scraping** for management bios. It's behind a login wall and against its terms. The SEBI-required "brief profile" in the filing is primary and reliable.
- **Annual-report deep reads.** Linked as sources. Balance-sheet and cash-flow numbers come from reported tables; reading 300-page PDFs live would blow the time budget.
- **Real phone push notifications.** That would need VAPID keys, a server and an installed app on iOS. Alerts live in an in-app inbox.
- **News and broker notes,** per the brief.

## Why there's no login (yet)

FINN shows "my" portfolio, but everything in it comes from public filings, and a reviewer should be able to open the link and see the app straight away. Settings (theme, voice, text size, default window) are saved on the device. Accounts are the first next step: saved portfolios, settings and alert rules per user. That's a small database and a hosted sign-in, and it's deliberately out of scope for a prototype people open cold.

## Research that feels instant

Dossiers for the whole portfolio plus the demo set are pre-built. The evening job only rebuilds a company when a **new earnings-call transcript** appears (the feed already detects those), so it costs almost nothing. For any other NSE symbol, the page shows the reported numbers in ~2 seconds, then the promise ledger fills in. Transcripts are read four at a time. Each Gemini model is paced below its free-tier rate, a rate limit means *wait and retry*, and a used-up daily quota stops cleanly so the next run carries on.

## Where I'd take it next

- Accounts: saved portfolios, settings and alert rules per user.
- Use NSE's XBRL results files for the results card, so it's ready the minute results are filed.
- Calibrate rule weights from 12 months of per-category market reactions.
- Per-stock alert overrides.
- A management-credibility history across years.
- Tone drift between calls.
