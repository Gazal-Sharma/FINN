// Learn page: what FINN does, how the parts connect, a plain-language glossary
// tied to where each term appears in the app, and a short reading list.
import { html } from "./lib.js";

// [term, also-known-as, plain meaning, where in FINN, group]
export const GLOSSARY = [
  // The basics
  ["NSE", "National Stock Exchange", "India's largest stock exchange, where shares of listed companies are bought and sold. Every company in FINN is listed here.", "The symbol you type in Research (e.g. INFY) is the company's NSE symbol.", "Basics"],
  ["Ticker", "symbol", "A short code for a company on the exchange, like INFY for Infosys or LT for Larsen & Toubro.", "Shown next to every company name, and what you type in Research.", "Basics"],
  ["Filing", "announcement, disclosure", "An official notice a listed company must send to the stock exchange: results, a new CEO, a big order, a court case, even routine paperwork. Hundreds land every week.", "Today: every card and row started as one or more filings.", "Basics"],
  ["Regulation 30", "Reg 30, LODR", "The SEBI rule that says companies must tell the exchange promptly about anything that could matter to investors. It's why filings exist, and why management changes come with a short profile of the new person.", "Today: management-change cards use the profile from the Reg 30 filing.", "Basics"],
  ["SEBI", "", "The Securities and Exchange Board of India, the market regulator. It writes the rules companies and brokers must follow.", "", "Basics"],
  ["Financial year (FY)", "FY27", "Indian companies count their year from April to March. FY27 means April 2026 to March 2027.", "Research: promises like 'FY27 revenue growth' refer to this year.", "Basics"],
  ["Quarter (Q1–Q4)", "Q2 FY27", "A three-month block of the financial year. Q1 is Apr–Jun, Q2 Jul–Sep, Q3 Oct–Dec, Q4 Jan–Mar. Q2 FY27 is July–September 2026.", "Results cards are labelled by the quarter's last month, e.g. 'Sep 2026'.", "Basics"],
  ["Nifty", "Nifty 50", "An index of 50 large Indian companies. When people say 'the market was up 1%', they usually mean the Nifty.", "Today: 'vs Nifty' shows how a stock moved compared with the market.", "Basics"],
  ["Consolidated vs standalone", "", "Standalone numbers cover only the parent company. Consolidated numbers add its subsidiaries, so they show the whole group. FINN uses consolidated when available.", "Results cards and Research numbers say which basis they use.", "Basics"],

  // Results numbers
  ["Results", "quarterly results, earnings", "A company's report card for the quarter: how much it sold, spent and earned. Listed companies must publish results within 45 days of a quarter ending.", "Today: a results card, ranked Act. Many related filings are grouped into it.", "Results"],
  ["Revenue", "sales, top line", "Money the company earned from selling its products or services, before paying any costs.", "First row of every results card.", "Results"],
  ["EBITDA", "operating profit", "Earnings before interest, tax, depreciation and amortisation. Roughly: profit from the core business before loans, taxes and wear-and-tear. FINN uses operating profit excluding other income.", "Second row of the results card. Banks show 'Op. profit' instead, because EBITDA doesn't apply to lenders.", "Results"],
  ["Margin", "EBITDA margin, operating margin", "Profit as a percentage of revenue. A 20% margin means ₹20 of profit for every ₹100 of sales. Rising margins usually mean the business is getting more efficient or has pricing power.", "Results card (margin line), and many Research promises are margin targets.", "Results"],
  ["EBIT margin", "operating margin (IT companies)", "Like EBITDA margin but after depreciation. IT companies such as Infosys usually guide on this one.", "Research: Infosys's '20–22% operating margin' promise is checked against EBIT margin.", "Results"],
  ["PBT", "profit before tax", "Profit after all costs, interest and depreciation, but before tax.", "Third row of the results card.", "Results"],
  ["PAT", "net profit, bottom line", "Profit after tax: what's finally left for shareholders.", "Last row of the results card.", "Results"],
  ["QoQ", "quarter on quarter", "Change compared with the previous quarter (e.g. Sep vs Jun). Useful for momentum, but some businesses are seasonal.", "Results card, middle column.", "Results"],
  ["YoY", "year on year", "Change compared with the same quarter last year (e.g. Sep 2026 vs Sep 2025). Removes seasonal effects, so it's usually the fairer comparison.", "Results card, last column.", "Results"],
  ["Other income", "", "Money from things outside the main business, like interest on cash. It can flatter profit, which is why FINN's EBITDA leaves it out.", "", "Results"],

  // Health
  ["Cash from operations", "CFO, operating cash flow", "Actual cash the business generated in the year. Profit is an accounting number; cash is harder to fake.", "Research → Numbers table, 'Cash from ops'.", "Health"],
  ["Cash conversion", "CFO / PAT", "Cash from operations divided by profit. Around 1 or above means profits are turning into real cash; well below 1 for years can be a warning sign.", "Research → Numbers: 'Cash conversion (CFO/PAT, 3y)'.", "Health"],
  ["Debt to equity", "D/E", "How much the company has borrowed compared with shareholders' money. 0.1 is very little debt; above 1 means more debt than equity.", "Research → Numbers: 'Debt / equity'.", "Health"],
  ["ROCE", "return on capital employed", "How much profit the business makes on all the money invested in it. Higher is better; 20%+ is strong.", "Research → Numbers.", "Health"],
  ["Cash conversion cycle", "CCC", "How many days money stays stuck in stock and unpaid customer bills before coming back as cash. Shorter is better.", "Research → Numbers.", "Health"],

  // Management & promises
  ["Earnings call", "concall, conference call", "A call after results where management explains the quarter and answers analysts' questions. It's where most promises are made.", "Research reads the last four calls.", "Promises"],
  ["Transcript", "", "The written record of an earnings call. FINN quotes it word for word.", "Research: tap any promise to see the exact quote and open the transcript.", "Promises"],
  ["Guidance", "outlook, target", "What management says will happen, e.g. 'revenue will grow 4–6% this year' or 'margins will stay at 20–22%'.", "Research: each guidance statement becomes a promise in the ledger.", "Promises"],
  ["Constant currency", "CC", "Growth measured as if exchange rates hadn't changed. IT companies earn in dollars, so reported rupee growth can look better or worse purely because of the rupee.", "Research: CC promises show the rupee number for context but get no verdict.", "Promises"],
  ["KMP", "key managerial personnel", "The top officers the law cares about: CEO/MD, CFO and company secretary.", "Today: changes to these are ranked Act; other board changes are Know.", "Promises"],
  ["Independent director", "", "A board member who isn't part of management or the promoter family, there to protect ordinary shareholders.", "", "Promises"],
  ["Promoter", "", "The founders or controlling group of a company (e.g. the Tata group for Tata Power).", "Today: promoter share pledges and dealings are flagged.", "Promises"],

  // Market moves
  ["Volume", "", "How many shares changed hands in a day. A sudden jump often means news or big investors acting.", "Alerts: 'Volume N× 20-day average'.", "Market"],
  ["20-day average volume", "", "The typical daily volume over the last 20 trading days. FINN compares today against it.", "Alerts and the market-reaction chip ('1.8× vol').", "Market"],
  ["Abnormal move", "vs Nifty", "A stock's move minus the market's move. If the stock rose 2% and the Nifty rose 1.5%, the abnormal move is +0.5%: that part is about the company, not the market.", "Today: the 'Market ±x% vs Nifty' chip on every card.", "Market"],
  ["Usual move", "volatility, σ", "How much a stock typically moves in a day. ±3% is routine for some stocks and rare for others.", "Alerts → 'Relative to each stock': alerts fire when a move is N× the usual.", "Market"],
  ["Trading session", "", "One trading day (9:15 am to 3:30 pm). A filing after 3:30 pm can only move the stock in the next session.", "Today: the 'Last session' window; market reactions use the right session.", "Market"],

  // Corporate actions
  ["Dividend", "record date", "Cash a company pays shareholders out of profits. The record date decides who gets it.", "Today: usually Hidden, because history shows it rarely moves the stock.", "Actions"],
  ["Bonus issue / stock split", "", "Extra free shares, or one share split into several. More shares at a lower price each; the value of your holding doesn't change.", "", "Actions"],
  ["Buyback", "", "The company buys back its own shares, usually a sign it thinks the shares are cheap.", "Ranked Act.", "Actions"],
  ["QIP", "qualified institutional placement", "Raising money by selling new shares to big institutions. Brings in cash but dilutes existing shareholders.", "Ranked Act.", "Actions"],
  ["NCD / commercial paper", "debt raise", "Ways for a company to borrow money from investors. Routine for finance companies.", "Usually Hidden: history shows these rarely move the stock.", "Actions"],
  ["Pledge", "promoter pledge", "Promoters using their shares as collateral for a loan. If the share price falls, lenders can sell them, which can push the price down further.", "Ranked Act; never hidden.", "Actions"],
  ["Credit rating", "", "An agency's view of how safely a company can repay debt. Downgrades matter; reaffirmations rarely do.", "Downgrades are Act; reaffirmations Hidden.", "Actions"],

  // FINN's own words
  ["Act / Know / Hidden", "tiers", "FINN's three ranks. Act could move the stock or change your view. Know is worth one line. Hidden is routine paperwork, folded away but still one tap away.", "Today, and the 'How FINN ranks' sheet.", "FINN"],
  ["How FINN ranks", "evidence", "Rules decide each filing's rank, then FINN checks them against 12 months of history. Filing types that don't move stocks more than an ordinary day get hidden.", "Today → 'How FINN ranks'.", "FINN"],
  ["Kept / Missed", "", "For promises whose period is over: did the reported numbers meet what management promised?", "Research ledger.", "FINN"],
  ["On track / Off track", "", "For promises whose year isn't over yet: based on the quarters reported so far, are they heading there?", "Research ledger.", "FINN"],
  ["Goalposts moved", "", "Management changed its own target between calls, raised or lowered. Lowering quietly is a warning sign.", "Research ledger, amber tag.", "FINN"],
  ["Quietly dropped", "", "A promise that's still in the future, but management stopped mentioning it on the last two calls.", "Research ledger, struck-through tag.", "FINN"],
  ["Can't verify", "", "The promise is real, but the reported numbers can't confirm it: e.g. a segment target, store count or guidance in constant currency. FINN says so rather than guess.", "Research ledger.", "FINN"],
  ["Verified quote", "", "Every promise's quote is checked word for word against the transcript. If the AI got the words or the number wrong, the promise is dropped.", "Research: '✓ N quotes verified in source'.", "FINN"],
];

const GROUPS = [["Basics", "The basics"], ["Results", "Reading results"], ["Health", "Is the business healthy?"],
  ["Promises", "Management and promises"], ["Market", "How the stock moved"], ["Actions", "Corporate actions"], ["FINN", "FINN's own words"]];

export const READS = [
  ["Zerodha Varsity: all modules", "https://zerodha.com/varsity/modules/", "Free, India-specific lessons from absolute basics upward. The best place to start."],
  ["Varsity: Introduction to fundamental analysis", "https://zerodha.com/varsity/chapter/introduction-fundamental-analysis/", "What it means to study a business before investing."],
  ["Varsity: Understanding the P&L statement", "https://zerodha.com/varsity/chapter/understanding-the-pl-statement/", "Revenue, other income and expenses, line by line on a real Indian company."],
  ["Varsity: Understanding the P&L statement, part 2", "https://zerodha.com/varsity/chapter/understanding-pl-statement-part2/", "Finance costs, depreciation, tax and profit after tax."],
  ["Medium: Fundamental analysis summary (Varsity notes)", "https://medium.com/anil-sardiwal/fundamental-analysis-summary-zerodha-varsity-80c99827ff1d", "A reader's chapter-by-chapter summary, handy for revision."],
  ["Groww: How to read and understand quarterly reports", "https://groww.in/blog/how-to-read-and-understand-quarterly-reports", "A short walk-through of what's in a results filing."],
  ["ICICI Direct: Earnings season, all you need to know", "https://www.icicidirect.com/ilearn/stocks/articles/earning-season-and-reports-all-you-need-to-know", "What results season is and why stocks react."],
  ["EquitiesIndia: How to read quarterly results", "https://equitiesindia.com/learn/fundamental-analysis/quarterly-results-reading", "YoY vs QoQ, red flags, and using concall transcripts, the same idea as FINN's Research."],
  ["SEBI investor website", "https://investor.sebi.gov.in/", "The regulator's own free guides, videos and tools for investors."],
];

export function searchGlossary(q, n = 3) {
  const words = (q || "").toLowerCase().replace(/[^a-z0-9/& ]/g, " ").split(/\s+/).filter((w) => w.length > 1);
  if (!words.length) return [];
  const scored = GLOSSARY.map((g) => {
    const name = `${g[0]} ${g[1]}`.toLowerCase();
    let s = 0;
    for (const w of words) {
      if (name.split(/[^a-z0-9]+/).includes(w)) s += 3;
      else if (name.includes(w) && w.length > 3) s += 2;
      else if (g[2].toLowerCase().includes(w) && w.length > 4) s += 0.3;
    }
    if (name && (q || "").toLowerCase().includes(g[0].toLowerCase())) s += 4;
    return [s, g];
  }).filter(([s]) => s >= 2).sort((a, b) => b[0] - a[0]);
  return scored.slice(0, n).map(([, g]) => g);
}

const term = (g) => html`<div class="term"><b>${g[0]}</b>${g[1] ? html`<span class="aka">${g[1]}</span>` : ""}
  <p>${g[2]}</p>${g[3] ? html`<div class="where">${g[3]}</div>` : ""}</div>`;

export function learn(state) {
  const q = (state.glossQ || "").trim().toLowerCase();
  const match = (g) => !q || `${g[0]} ${g[1]} ${g[2]}`.toLowerCase().includes(q);
  return html`<div class="learn">
  <h2 class="big">New to this? Start here.</h2>
  <p class="lead">FINN watches 18 companies for you. Every day those companies send official notices to the stock exchange. Most are paperwork; a few really matter. FINN reads them all, shows you the few that matter, and checks whether each company's management actually does what it says it will.</p>

  <div class="sec"><h2>How FINN fits together</h2></div>
  <div class="flow">
    <a href="#/today"><span class="n">1</span><div><b>Companies file, FINN sorts</b><span>Every filing is ranked Act, Know or Hidden. Results-day paperwork becomes one results card. Open <u>Today</u>.</span></div></a>
    <a href="#/today"><span class="n">2</span><div><b>Results show the numbers</b><span>Revenue, EBITDA, PBT and PAT, compared with last quarter (QoQ) and last year (YoY), plus how the stock reacted.</span></div></a>
    <a href="#/alerts"><span class="n">3</span><div><b>You decide what's unusual</b><span>Set how big a price or volume move should be before FINN flags it, and see how often that would have fired. Open <u>Alerts</u>.</span></div></a>
    <a href="#/research/INFY"><span class="n">4</span><div><b>Promises meet numbers</b><span>On earnings calls, management makes promises. FINN collects them, checks the quotes, and compares them with the results that followed. Open <u>Research</u>.</span></div></a>
  </div>
  <div class="chain"><span>Earnings call</span><i>→</i><span>promise</span><i>→</i><span>next results</span><i>→</i><span>kept, missed or dropped</span></div>
  <p class="small muted">That loop is the heart of FINN: what management says, checked against what the numbers later show.</p>

  <div class="sec"><h2>Reading a day in FINN</h2></div>
  <ol class="small" style="line-height:1.7;padding-left:20px">
    <li>Start with <b>Act</b>. If it's empty, nothing important happened, and that's good news.</li>
    <li>On a results card, look at <b>YoY</b> first (it removes seasonality), then whether the <b>margin</b> rose or fell.</li>
    <li>Check the <b>market chip</b>: a big move vs Nifty means investors cared.</li>
    <li>Curious about a company? Open <b>Research</b> and read the promises first. A company that keeps its word is easier to trust.</li>
  </ol>

  <div class="sec"><h2>Words, in plain language</h2><span class="tiny muted">${GLOSSARY.length} terms</span></div>
  <input class="gloss-search" data-gloss placeholder="Filter terms, e.g. margin" value="${state.glossQ || ""}" autocomplete="off">
  ${GROUPS.map(([k, label]) => {
    const items = GLOSSARY.filter((g) => g[4] === k && match(g));
    return items.length ? html`<h3 class="caps" style="margin:18px 0 0">${label}</h3>${items.map(term)}` : "";
  })}
  <p class="small muted" style="margin-top:14px">Still stuck? Tap <b>Ask</b> at the bottom right of any screen.</p>

  <div class="sec"><h2>Read more</h2><span class="tiny muted">free, beginner-friendly</span></div>
  <div class="reads">${READS.map(([t, u, d]) => html`<a href="${u}" target="_blank" rel="noopener"><b>${t} ›</b><span>${d}</span></a>`)}</div>
  <p class="tiny muted" style="margin:16px 0">FINN explains and organises public information. It doesn't tell you what to buy or sell.</p>
  </div>`;
}
