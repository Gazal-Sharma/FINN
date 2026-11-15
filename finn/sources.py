"""Everything that touches the network. Nothing here calls an LLM.

prices   : Yahoo Finance (yfinance, with a plain-HTTP fallback)
filings  : NSE corporate announcements (cookie warm-up), BSE as fallback
screener : company tables + document links (annual reports, concall transcripts)
pdf_text : download a PDF and extract text with pypdf
"""
import io
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from . import IST

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
TIMEOUT = 25


# --------------------------------------------------------------------- prices
def fetch_prices(tickers, days=150):
    """Return {yf_symbol: [(date 'YYYY-MM-DD', close, volume), ...]}."""
    out = {}
    try:
        import yfinance as yf
        df = yf.download(tickers, period=f"{days}d", interval="1d", group_by="ticker",
                         auto_adjust=False, progress=False, threads=True)
        for t in tickers:
            try:
                sub = df[t] if len(tickers) > 1 else df
                rows = []
                for idx, r in sub.dropna(subset=["Close"]).iterrows():
                    rows.append((idx.strftime("%Y-%m-%d"), round(float(r["Close"]), 2), int(r.get("Volume") or 0)))
                if rows:
                    out[t] = rows
            except Exception:
                pass
    except Exception as e:  # yfinance missing or broken -> fallback below
        print("yfinance failed:", e)
    for t in tickers:
        if t not in out:
            try:
                out[t] = _yahoo_chart(t, days)
            except Exception as e:
                print("yahoo chart failed", t, e)
    return out


def _yahoo_chart(symbol, days):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                     params={"range": f"{days}d" if days <= 365 else "1y", "interval": "1d"},
                     headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for ts, c, v in zip(res["timestamp"], q["close"], q["volume"]):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d")
        rows.append((d, round(c, 2), int(v or 0)))
    return rows


# -------------------------------------------------------------------- filings
class NSE:
    """NSE's JSON API needs cookies that are set when you load a normal page."""
    BASE = "https://www.nseindia.com"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                               "Accept": "*/*", "Referer": self.BASE + "/"})
        self.warm = False

    def warmup(self):
        for path in ("/", "/companies-listing/corporate-filings-announcements"):
            try:
                self.s.get(self.BASE + path, timeout=TIMEOUT)
            except requests.RequestException:
                pass
        self.warm = True

    def announcements(self, symbol, start, end):
        if not self.warm:
            self.warmup()
        params = {"index": "equities", "symbol": symbol,
                  "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
        for attempt in range(3):
            r = self.s.get(self.BASE + "/api/corporate-announcements", params=params, timeout=TIMEOUT)
            if r.status_code in (401, 403) and attempt < 2:
                time.sleep(2)
                self.warmup()
                continue
            r.raise_for_status()
            data = r.json()
            rows = data.get("data", data) if isinstance(data, dict) else data
            return [_norm_nse(symbol, x) for x in rows or []]
        return []

    def get_pdf(self, url):
        if not self.warm:
            self.warmup()
        r = self.s.get(url, timeout=60)
        r.raise_for_status()
        return r.content


def _parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return None


def _norm_nse(symbol, x):
    ts = _parse_dt(x.get("sort_date") or x.get("an_dt") or x.get("exchdisstime") or "")
    att = x.get("attchmntFile") or ""
    fid = str(x.get("seq_id") or x.get("an_seq_id") or abs(hash((symbol, x.get("an_dt"), x.get("desc")))))
    return {
        "id": f"nse:{fid}",
        "ticker": symbol,
        "src": "nse",
        "ts": ts.isoformat() if ts else None,
        "subject": (x.get("desc") or "").strip(),
        "text": re.sub(r"\s+", " ", (x.get("attchmntText") or "")).strip(),
        "url": att if att.startswith("http") else None,
    }


def bse_announcements(symbol, scrip, start, end):
    if not scrip:
        return []
    r = requests.get(
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
        params={"pageno": 1, "strCat": -1, "strPrevDate": start.strftime("%Y%m%d"),
                "strScrip": scrip, "strSearch": "P", "strToDate": end.strftime("%Y%m%d"),
                "strType": "C", "subcategory": -1},
        headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"},
        timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for x in r.json().get("Table", []):
        ts = _parse_dt(x.get("NEWS_DT") or x.get("DT_TM") or "")
        att = x.get("ATTACHMENTNAME")
        subj = " ".join(filter(None, [x.get("CATEGORYNAME"), x.get("SUBCATNAME")])) or x.get("NEWSSUB", "")
        out.append({
            "id": f"bse:{x.get('NEWSID')}",
            "ticker": symbol,
            "src": "bse",
            "ts": ts.isoformat() if ts else None,
            "subject": subj.strip(),
            "text": re.sub(r"\s+", " ", (x.get("HEADLINE") or x.get("NEWSSUB") or "")).strip(),
            "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else None,
        })
    return out


def fetch_filings(symbol, scrip, start, end, nse=None):
    """NSE first, BSE only if NSE fails. Returns (filings, source_used, error)."""
    nse = nse or NSE()
    try:
        rows = nse.announcements(symbol, start, end)
        return rows, "nse", None
    except Exception as e:
        err = f"nse: {e}"
    try:
        return bse_announcements(symbol, scrip, start, end), "bse", err
    except Exception as e:
        return [], None, f"{err}; bse: {e}"


def nse_symbol_list():
    r = requests.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                     headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    rows = []
    for line in r.text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) > 2 and parts[2].strip() == "EQ":
            rows.append([parts[0].strip(), parts[1].strip()])
    return rows


# ------------------------------------------------------------------------ pdf
def pdf_text(url, nse=None, max_pages=60, max_bytes=25_000_000):
    """Download and extract text. Returns '' on failure (callers handle absence)."""
    from pypdf import PdfReader
    try:
        if nse and "nseindia.com" in url:
            content = nse.get_pdf(url)
        else:
            r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"},
                             timeout=60)
            r.raise_for_status()
            content = r.content
        if len(content) > max_bytes or not content[:5].startswith(b"%PDF"):
            return ""
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for i, p in enumerate(reader.pages[:max_pages]):
            try:
                pages.append(f"\n[[page {i + 1}]]\n" + (p.extract_text() or ""))
            except Exception:
                continue
        return "".join(pages)
    except Exception as e:
        print("pdf_text failed", url, e)
        return ""


# ------------------------------------------------------------------- screener
def _num(s):
    s = (s or "").replace(",", "").replace("%", "").strip()
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _table(soup, section_id):
    sec = soup.find("section", id=section_id)
    if not sec:
        return None
    tbl = sec.find("table", class_="data-table")
    if not tbl:
        return None
    heads = [th.get_text(" ", strip=True) for th in tbl.find("thead").find_all("th")][1:]
    rows = {}
    for tr in tbl.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        label = re.sub(r"[\s+]+$", "", tds[0].get_text(" ", strip=True)).replace("\xa0", " ").strip()
        label = label.rstrip("+").strip()
        rows[label] = [_num(td.get_text(strip=True)) for td in tds[1:]]
    return {"periods": heads, "rows": rows}


def fetch_screener(symbol):
    """Consolidated page first; fall back to standalone if it has no quarterly data."""
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    last_err = None
    for path in (f"/company/{symbol}/consolidated/", f"/company/{symbol}/"):
        try:
            r = sess.get("https://www.screener.in" + path, timeout=TIMEOUT)
            if r.status_code == 404:
                last_err = "not found"
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            last_err = str(e)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        q = _table(soup, "quarters")
        if not q or not q["rows"]:
            last_err = "no quarterly table"
            continue
        out = {
            "symbol": symbol,
            "basis": "consolidated" if "consolidated" in path else "standalone",
            "url": "https://www.screener.in" + path,
            "name": (soup.find("h1").get_text(strip=True) if soup.find("h1") else symbol),
            "quarters": q,
            "annual": _table(soup, "profit-loss"),
            "balance": _table(soup, "balance-sheet"),
            "cashflow": _table(soup, "cash-flow"),
            "ratios": _table(soup, "ratios"),
            "top": {},
            "concalls": [],
            "annual_reports": [],
        }
        for li in soup.select("#top-ratios li"):
            n = li.find(class_="name")
            v = li.find(class_="number")
            if n and v:
                out["top"][n.get_text(strip=True)] = _num(v.get_text(strip=True))
        for li in soup.select(".concalls li"):
            date_div = li.find("div")
            when = date_div.get_text(" ", strip=True) if date_div else ""
            links = {}
            for a in li.find_all("a", href=True):
                links[a.get_text(" ", strip=True).lower()] = a["href"]
            tr = next((v for k, v in links.items() if "transcript" in k), None)
            out["concalls"].append({"when": when, "transcript": tr, "ppt": links.get("ppt")})
        for a in soup.select(".annual-reports li a[href]"):
            out["annual_reports"].append({"label": a.get_text(" ", strip=True), "url": a["href"]})
        return out
    raise RuntimeError(f"screener {symbol}: {last_err}")


def find_transcripts_on_nse(symbol, nse=None, months=14):
    """Fallback when screener's transcript links (often BSE-hosted) are unreachable."""
    nse = nse or NSE()
    end = datetime.now(IST)
    out = []
    for k in range(0, months, 6):
        e = end - timedelta(days=30 * k)
        s = e - timedelta(days=30 * 6)
        try:
            for f in nse.announcements(symbol, s, e):
                blob = (f["subject"] + " " + f["text"]).lower()
                if "transcript" in blob and f["url"]:
                    out.append(f)
        except Exception:
            break
    out.sort(key=lambda f: f["ts"] or "", reverse=True)
    return out
