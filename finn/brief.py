"""The morning brief: one short email per signed-in user who asked for it.

Built from the same public data the app shows (events, prices, research
dossiers), filtered to that user's stocks and alert thresholds. Sent with
Brevo's transactional email API. Used by the nightly job (every opted-in
user, via the Supabase service-role key) and by /api/brief (one user, via
their own sign-in token, so that path needs no secret beyond the Brevo key).
"""
import html
import os
import re
import statistics
from datetime import datetime, timedelta

import requests

from . import IST, config, read_json

DATA = config.PUBLIC_DATA


# ------------------------------------------------------------------ supabase
def _admin_headers():
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def all_users():
    """[(user_id, email)] for every account. Service role only (pipeline)."""
    out, page = [], 1
    while True:
        r = requests.get(f"{config.SUPABASE_URL}/auth/v1/admin/users", params={"page": page, "per_page": 200},
                         headers=_admin_headers(), timeout=20)
        r.raise_for_status()
        users = r.json().get("users", [])
        out += [(u["id"], u.get("email")) for u in users if u.get("email")]
        if len(users) < 200:
            return out
        page += 1


def all_prefs():
    """{user_id: {"followed": [...], **settings}}. Service role only (pipeline)."""
    r = requests.get(f"{config.SUPABASE_URL}/rest/v1/user_prefs", params={"select": "user_id,followed,settings"},
                     headers=_admin_headers(), timeout=20)
    r.raise_for_status()
    return {row["user_id"]: {"followed": row.get("followed") or [], **(row.get("settings") or {})} for row in r.json()}


def user_from_token(token):
    """(user_id, email, prefs) for the person holding this sign-in token. Uses their
    own token, so row-level security limits it to their row; no secret needed."""
    h = {"apikey": config.SUPABASE_PUBLISHABLE, "Authorization": f"Bearer {token}"}
    r = requests.get(f"{config.SUPABASE_URL}/auth/v1/user", headers=h, timeout=15)
    if r.status_code != 200:
        raise PermissionError("not signed in")
    u = r.json()
    r = requests.get(f"{config.SUPABASE_URL}/rest/v1/user_prefs", params={"select": "followed,settings", "user_id": f"eq.{u['id']}"},
                     headers=h, timeout=15)
    r.raise_for_status()
    rows = r.json()
    prefs = {"followed": rows[0].get("followed") or [], **(rows[0].get("settings") or {})} if rows else {}
    return u["id"], u.get("email"), prefs


# ------------------------------------------------------------------- content
def _data(rel, default=None):
    """public/data file from disk, or from the live site if this bundle lacks it."""
    got = read_json(DATA / rel)
    if got is not None:
        return got
    try:
        r = requests.get(f"{config.APP_URL}/data/{rel}", timeout=15)
        return r.json() if r.status_code == 200 else default
    except Exception:
        return default


def _returns(c):
    return [((c[i] / c[i - 1] - 1) * 100 if i and c[i] and c[i - 1] else None) for i in range(len(c))]


def _alerts(prices, tickers, s):
    """Same rule as the app's Alerts tab, for the last session only."""
    out = []
    i = len(prices.get("dates", [])) - 1
    for t in tickers:
        d = prices.get("t", {}).get(t)
        if not d or i < 21:
            continue
        r = _returns(d["c"])
        if r[i] is None:
            continue
        prior = [x for x in r[max(1, i - 60):i] if x is not None]
        sig = statistics.stdev(prior) if len(prior) >= 15 else None
        vols = [x for x in d["v"][i - 20:i] if x]
        volx = d["v"][i] / (sum(vols) / len(vols)) if vols and d["v"][i] else None
        price = (sig and abs(r[i]) >= float(s.get("sigma", 2.5)) * sig) if s.get("relative", True) else abs(r[i]) >= float(s.get("pricePct", 3))
        vol = volx is not None and volx >= float(s.get("volX", 2))
        if price or vol:
            out.append({"t": t, "ret": r[i], "volx": volx, "price": bool(price), "vol": vol, "sig": sig})
    return out


def _watch_changes(watched):
    """Watched promises whose verdict differs from what the user last saw."""
    changed, steady = [], []
    for w in watched or []:
        d = _data(f"research/{w.get('t')}.json")
        if not d:
            continue
        th = _find_thread(d, w)
        if not th:
            continue
        item = {"t": w["t"], "title": th["title"], "now": th["verdict"], "was": w.get("seen") or w.get("verdict"),
                "actual": th.get("actual"), "note": th.get("note")}
        (changed if item["now"] != item["was"] else steady).append(item)
    return changed, steady


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _find_thread(d, w):
    """Threads are renumbered on rebuild, so match by the earliest quote, then title."""
    for th in d.get("threads", []):
        if th.get("history") and _norm(th["history"][0]["quote"])[:60] == w.get("key"):
            return th
    for th in d.get("threads", []):
        if _norm(th["title"]) == _norm(w.get("title")):
            return th
    return None


VLABEL = {"kept": "kept", "missed": "missed", "on_track": "on track", "off_track": "off track",
          "dropped": "quietly dropped", "pending": "pending", "unverifiable": "can't verify"}


def compose(prefs):
    """(subject, html, text) for one user's brief."""
    meta = _data("meta.json", {}) or {}
    events = (_data("events.json", {}) or {}).get("events", [])
    prices = _data("prices.json", {}) or {}
    names = {sym: n for sym, n in (_data("symbols.json", []) or [])}
    names.update({c["t"]: c["name"] for c in meta.get("portfolio", []) + meta.get("extra", [])})
    universe = list(config.PORTFOLIO) + [t for t in prefs.get("extra", []) if t not in config.PORTFOLIO]
    followed = [t for t in (prefs.get("followed") or []) if t in universe] or universe
    followed = list(dict.fromkeys(followed + [t for t in prefs.get("extra", [])]))

    dates = prices.get("dates", [])
    since = (datetime.fromisoformat(dates[-2] + "T15:30:00+05:30") if len(dates) > 1 else datetime.now(IST) - timedelta(days=1))
    recent = [e for e in events if e["ticker"] in followed and e.get("ts") and datetime.fromisoformat(e["ts"]) >= since]
    act = sorted((e for e in recent if e["tier"] == "act"), key=lambda e: -e["score"])
    know = [e for e in recent if e["tier"] == "know"]
    alerts = _alerts(prices, followed, prefs.get("settings") or prefs)
    changed, steady = _watch_changes(prefs.get("watched"))
    nm = lambda t: re.sub(r"\s+(Ltd\.?|Limited)$", "", names.get(t, t))  # noqa: E731
    LEGAL = re.compile(r"regulation|schedule|pursuant|read with|disclosure under|intimation", re.I)

    def plain(e):  # a filing's own subject is often legal boilerplate; say what it is instead
        one = (e.get("oneliner") or e.get("title") or "").strip()
        if not one or LEGAL.search(one) or len(one) > 140:
            w = (e.get("why") or [e.get("category", "").replace("_", " ")])[0]
            return w[:1].upper() + w[1:]
        return one
    pct = lambda v: f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.1f}%"  # noqa: E731

    lines = []  # (heading, [items]) -> rendered as both html and text
    if act:
        items = []
        for e in act[:6]:
            c = e.get("card") or {}
            if c.get("type") == "results":
                rows = {r["k"]: r for r in c.get("rows", [])}
                rev, pat = rows.get("Revenue"), rows.get("PAT")
                txt = f"Results ({c.get('period')}): revenue {pct(rev['yoy']) if rev and rev.get('yoy') is not None else 'n/a'} YoY, PAT {pct(pat['yoy']) if pat and pat.get('yoy') is not None else 'n/a'} YoY"
            elif c.get("type") == "mgmt" and c.get("people"):
                p = c["people"][0]
                txt = f"{p['name']}, {p.get('role') or ''}: {p.get('change') or 'change'}"
            else:
                txt = plain(e)
            items.append((nm(e["ticker"]), txt))
        lines.append(("Needs you", items))
    if changed:
        lines.append(("Promises you watch: changed", [(nm(w["t"]), f"{w['title']}: {VLABEL.get(w['was'], w['was'])} → {VLABEL.get(w['now'], w['now'])}") for w in changed]))
    if alerts:
        lines.append(("Your alerts, last session", [(nm(a["t"]), ", ".join(filter(None, [f"moved {pct(a['ret'])}" if a["price"] else "",
                                                                                      f"{a['volx']:.1f}× normal volume" if a["vol"] else ""]))) for a in alerts]))
    if know:
        lines.append(("Worth knowing", [(nm(e["ticker"]), plain(e)) for e in know[:5]]))
    if steady and not changed:
        lines.append(("Promises you watch", [(nm(w["t"]), f"{w['title']}: still {VLABEL.get(w['now'], w['now'])}") for w in steady[:5]]))

    day = datetime.now(IST).strftime("%A %-d %B")
    n_act = len(act)
    subject = f"FINN · {day}: " + (f"{n_act} thing{'s' if n_act != 1 else ''} need{'' if n_act != 1 else 's'} you" if n_act else
                                   ("a promise you watch changed" if changed else "nothing needs you"))
    calm = not act and not changed and not alerts
    n_follow = len(followed) if prefs.get("followed") else 0  # 0 = all holdings
    pending = [t for t in prefs.get("extra", []) if t not in prices.get("t", {})]

    esc = html.escape
    sec_html = "".join(
        f'<h2 style="font:700 13px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#14213D;margin:22px 0 8px">{esc(h)}</h2>'
        + "".join(f'<p style="margin:0 0 10px;font:15px/1.5 Arial,sans-serif;color:#22314F"><b style="color:#14213D">{esc(a)}</b> · {esc(b)}</p>' for a, b in items)
        for h, items in lines)
    body = (f'<div style="background:#E3E9E2;padding:24px"><div style="max-width:560px;margin:0 auto;background:#FBFCF9;border:1px solid #CBD5CC;border-radius:4px;padding:24px">'
            f'<div style="font:700 26px Arial,sans-serif;color:#14213D">FINN</div>'
            f'<div style="border-top:2px solid #14213D;border-bottom:1px solid #14213D;height:3px;margin:10px 0 16px"></div>'
            f'<div style="font:600 18px Arial,sans-serif;color:#14213D">{esc(day)}</div>'
            + (f'<div style="font:13px Arial,sans-serif;color:#46546E;margin-top:4px">For the {n_follow} stock{"s" if n_follow != 1 else ""} you follow</div>' if n_follow else "")
            + (f'<p style="font:16px/1.5 Arial,sans-serif;color:#22314F">Nothing needs you since the last session.'
               + (f' {len(recent)} filing{"s" if len(recent) != 1 else ""} from your stocks, all routine.' if not know else
                  f' {len(know)} thing{"s" if len(know) != 1 else ""} worth knowing below.') + '</p>' if calm else "")
            + sec_html
            + (f'<p style="font:13px/1.5 Arial,sans-serif;color:#66717F;margin-top:16px">Filings and prices for {esc(", ".join(pending))} start with the next nightly run.</p>' if pending else "")
            + f'<p style="margin-top:22px"><a href="{config.APP_URL}" style="font:600 15px Arial,sans-serif;color:#2B4C7E">Open FINN ›</a></p>'
            f'<p style="font:12px/1.5 Arial,sans-serif;color:#66717F;margin-top:18px">You get this because you turned on the morning brief in FINN → Settings. '
            f'Turn it off there any time. FINN organises public filings; it doesn\'t tell you what to buy or sell.</p></div></div>')
    text = f"FINN · {day}\n" + (f"For the {n_follow} stocks you follow\n" if n_follow else "") + "\n" + ("Nothing needs you since the last session.\n" if calm else "") + "\n".join(
        f"\n{h.upper()}\n" + "\n".join(f"- {a}: {b}" for a, b in items) for h, items in lines) + f"\n\nOpen FINN: {config.APP_URL}\n"
    return subject, body, text


# --------------------------------------------------------------------- send
def send(to_email, subject, html_body, text):
    key, sender = os.environ.get("BREVO_API_KEY"), os.environ.get("BRIEF_FROM_EMAIL")
    if not key or not sender:
        raise RuntimeError("email isn't set up (BREVO_API_KEY / BRIEF_FROM_EMAIL missing)")
    r = requests.post("https://api.brevo.com/v3/smtp/email", timeout=20,
                      headers={"api-key": key, "accept": "application/json", "content-type": "application/json"},
                      json={"sender": {"email": sender, "name": "FINN"}, "to": [{"email": to_email}],
                            "subject": subject, "htmlContent": html_body, "textContent": text})
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:200]}")
    return r.json().get("messageId")
