# FINN: a financial investment agent that keeps score

**Live:** https://finn-jet-eight.vercel.app · **Code:** https://github.com/Gazal-Sharma/FINN

## The point of view

Most "AI for investors" demos are a chat box over a PDF: they summarise what management says. FINN does the opposite. It **keeps score on management**, and it **guards the investor's attention**.

- **Push (Today, Alerts).** Of ~250 filings a month across 18 holdings, FINN surfaces the few that matter, says *why* each is ranked where it is, and checks that ranking against how the stocks have actually reacted.
- **Pull (Research).** For any NSE company, FINN reads the last four earnings-call transcripts and pulls out every promise management made. It checks each quote word for word against the transcript, then scores the promise against the reported numbers: **kept, missed, on/off track, goalposts moved, quietly dropped**, or **can't verify**. This is the brief's "narrative vs numbers", done as a ledger rather than a summary.

The look follows the same idea: an accountant's ledger rather than a trading terminal. Important items are separate sheets of paper, worth-knowing items are lines in a ruled notebook, and routine filings sit in a drawer.

## What it does, against the brief

| Brief | FINN |
|---|---|
| Digest of filings for a window, ranked, routine collapsed | Today: Act / Know / Hidden ("the drawer"), each with a *why*. Windows: 24h (default), last session, 7d, 30d, or a custom date range limited to the data available. On a weekend, an empty 24h widens to the last session and says so. |
| Alerts: volume ×, price ±%, material filing types | Alerts: sliders, plus how many alerts those settings *would have fired* over the last 60 sessions. The default mode measures moves against each stock's usual daily move, because ±3% is noise for DIXON and news for HDFCBANK. Filing-type alerts are chips. |
| Results cards: Revenue, EBITDA, PBT, PAT, QoQ and YoY | One card per results day; the 4–6 related filings are grouped into it. Numbers come from reported tables; EBITDA = operating profit excluding other income (labelled on the card). Lenders show financing profit, since EBITDA doesn't apply to banks. |
| Management-change card with a bio | Names the incoming person first, with the profile the company must file under SEBI Reg 30. When the start-date notice says the profile was "already provided in an earlier intimation", FINN fetches that earlier filing (HDFC Bank: Anup Bagchi, profile from the 1 Oct filing). |
| Every other filing type: one line or priority | Related filings (a QIP's approval, pricing and allotment) are grouped into one item, the same way as results day. Each item carries a one-liner and a market-reaction chip (move vs Nifty, volume multiple). |
| Research on any NSE ticker from annual reports and transcripts | 22 dossiers pre-built (the portfolio plus the demo set). Any other symbol shows its reported numbers in ~2 s, then its promise ledger. Sources are linked on every dossier. |

## Judgment calls, with the evidence

- **Rules first, and the rules checked against history.** About 75% of filings are ranked by ~40 rules, guarded by a 33-case golden test set. FINN then checked every rule against 12 months of filings (2,967) and prices:
  - On an ordinary stock-day with no filing (7,120 of them), a move of ≥2× the stock's usual size happens **4.9%** of the time.
  - Results filings: **5.5×** that rate.
  - Board and management changes: ~2×. Order wins and press releases: ~1.8×.
  - Dividend notices: 0 big moves in 19. Debt raises: 0.6×. So both were moved from Know to Hidden *by the evidence*, not by opinion.

  Two guardrails apply. Rule-ranked Act items are never demoted automatically. Risk signals (litigation, insider dealing, pledges, insolvency, downgrades) are never hidden, because end-of-day prices react to them slowly.
- **Honest about the method's limits.** Filings on results day and the session after are excluded from their own type's numbers, so they don't take credit for the results move. "Clarifications" score 6×, but that's reverse causality: the exchange asks for one *because* the stock moved. The "How FINN ranks" sheet shows the full table.
- **FINN grades itself.** If something ranked Hidden is followed by a big move, the card says FINN under-ranked it.
- **No forced verdicts.**
  - Infosys guides in constant currency, so the reported rupee growth is shown as context, not judged.
  - A segment target (e.g. Polycab's BharatNet ₹800–1,000 cr) is never compared with company revenue.
  - "Quietly dropped" applies only to promises still in the future; a promise whose date has passed is due, not dropped.
  - Years still in progress are *on/off track*, not kept/missed.
- **Login is optional.** Everything works without an account. Signing in (an emailed link, via Supabase) syncs the stocks you follow, alert thresholds and settings across devices. Each user can only read their own row (enforced by the database), so the public key is safe to ship. If sign-in is unavailable, the app carries on without it.
- **For beginners.**
  - A Learn page explains how filings, results, alerts and research connect, with 51 terms in plain language, each saying where it appears in FINN.
  - A **?** Ask helper on every screen answers from that glossary first (instant, free) and calls the cheapest model only when needed. It never gives buy or sell advice.
  - A 60-second **Listen** brief is written for the ear, assembled by code rather than a model, and uses the phone's own voice, which costs nothing.

## How the AI is kept honest

1. **The model never supplies a reported number.** Actual figures come from reported tables, computed in code.
2. **Every promise must quote the transcript.** The quote is searched for in the full transcript (allowing only for PDF spacing noise). **If it isn't found, the promise is dropped**, and the dossier shows how many were dropped. Across 22 companies, 329 promises were found and 291 kept.
3. **The promised number must appear inside the quote**, which catches a vague quote "improved" into a precise figure.
4. **Verdicts are computed in code** from the verified records and the reported numbers.
5. **The one synthesis call sees only verified records.** Every sentence must cite a record, and every number in it must appear in its input, or the sentence is removed. If that fails, the summary is written by code instead.
6. **Results extracted from PDFs must add up** (PBT − tax ≈ PAT), and management names must literally appear in the filing.
7. **The same checks apply to whichever model answers,** including the fallback.

## Architecture and cost

```
GitHub Actions (evening + morning, or on demand)
  fetch  → raw/        NSE filings (cookie warm-up; BSE fallback), prices, screener tables, transcript PDFs
  build  → public/data events, results/management cards, ranking evidence, research dossiers
  commit → Vercel redeploys the static app
Vercel: static app (vanilla JS, no build step) + 2 Python functions
  /api/research  live dossier for any ticker (numbers first, then promises)
  /api/ask       the Ask helper
Supabase (optional): sign-in + one row per user, protected by row-level security
```

- **Model routing (Gemini, Groq as fallback):**
  - triage and one-liners: Flash-Lite
  - extraction: Flash → Flash-Lite
  - synthesis: Pro → Flash
  - Groq takes over when Gemini's free daily quota runs out. Its free tier can't take a whole transcript at once, so it reads transcripts in overlapping pieces of about 5k tokens, with the same checks.
- **Rate limits:** each model is paced below its free-tier limit. A rate limit means *wait and retry*; a used-up daily quota stops cleanly, and the next run resumes.
- **Never pay twice:** every answer is cached (verdicts per filing ID; extractions by prompt and input), and the cache is committed with the data. Research is rebuilt only when a company files a **new transcript**.
- **Cost:** 336 model calls; 35% answered from cache; 1.69M tokens in, 72k out.

  | Item | Cost at Gemini paid list prices |
  |---|---|
  | Whole build | **≈ $0.22** |
  | One company's research, median of 22 | **≈ $0.009** (~76k tokens, ~7 calls) |
  | Most expensive (DIXON) | $0.035 |
  | The whole 30-day feed for 18 stocks (AI triage + one-liners) | **≈ $0.004** |

  Actual spend on the free tiers: $0. Per-call detail is in `logs/usage.jsonl`.

## Known limits

- **Transcript gaps:** TRENT has no transcripts we could find, CDSL's calls contain no measurable promises, and MARUTI has only one transcript. Each dossier says so plainly rather than guessing.
- **Where the numbers come from:** standardised tables on screener.in, which are derived from company filings. Annual reports are linked as sources but not read in full; reading 300-page PDFs live would blow the time budget.
- **Prices are end-of-day** (Yahoo), so reactions are per session, not intraday.
- **Groq fallback:** tested offline, but tonight's run didn't need it, so it hasn't run against the real API.
- **Supabase's free email sender** allows only a few sign-in links an hour. Fine for a demo; a real launch needs its own email service.

## Next

1. Read NSE's XBRL results files directly, so results cards are ready the minute results land.
2. Let signed-in users add their own stocks to the daily job, not just choose among the 18.
3. Phone push notifications for alerts.
4. A management credibility history across years.
5. Tone drift between calls.
6. Per-stock alert overrides.

## How it was built

Built in one evening with Claude: brief → plan → architecture → risks, then iterations driven by testing on a phone. The AI build history accompanies this submission.
