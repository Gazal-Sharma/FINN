"""Vercel function: GET /api/ask?q=...&screen=today&t=INFY -> {"answer": "..."}

The Ask helper on every screen. The app answers from its own glossary first;
this is only called when the glossary doesn't cover the question. Cheapest model,
short answers, no buy/sell advice. Answers are cached by the CDN for a day.
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("FINN_RUNTIME", "api")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SYSTEM = (
    "You are the help assistant inside FINN, an app for Indian stock-market investors who may be complete "
    "beginners. Answer in plain, friendly English for someone with no finance background: at most 110 words, "
    "short sentences, no jargon without explaining it, and one small everyday example (use ₹ and Indian companies "
    "where helpful). If the term appears in FINN, end with one sentence on where to see it in the app.\n"
    "FINN's screens: Today (company filings ranked Act / Know / Hidden, results cards with Revenue, EBITDA, PBT, "
    "PAT and QoQ/YoY change, a 'Market ±x% vs Nifty' reaction chip); Alerts (price and volume thresholds, "
    "'N× usual move', 'N× 20-day average volume'); Research (management's promises from earnings calls marked "
    "Kept, Missed, On track, Off track, Goalposts moved, Quietly dropped or Can't verify, plus numbers such as "
    "cash conversion, debt/equity, ROCE); Learn (glossary).\n"
    "Never tell the user to buy, sell or hold anything and never predict prices; if asked, explain what they "
    "could look at instead. If the question isn't about investing, markets, companies or FINN, say briefly that "
    "you can only help with those. Return JSON {\"answer\": \"...\"}."
)


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj, cache=False):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=86400" if cache else "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        question = re.sub(r"\s+", " ", (q.get("q") or [""])[0]).strip()[:300]
        screen = re.sub(r"[^a-z]", "", (q.get("screen") or ["today"])[0])[:12]
        ticker = re.sub(r"[^A-Z0-9&-]", "", (q.get("t") or [""])[0].upper())[:20]
        if len(question) < 3:
            return self._send(400, {"error": "Ask a question, e.g. ?q=What is EBITDA"})
        try:
            from finn import llm

            def validate(o):
                if isinstance(o, list) and o:
                    o = o[0]
                a = str((o or {}).get("answer", "")).strip()
                if not a or len(a) > 1500:
                    raise ValueError("bad answer")
                return {"answer": a}
            ctx = f"The user is on the {screen} screen" + (f", looking at {ticker}" if ticker else "") + "."
            out = llm.ask("explain", SYSTEM, f"{ctx}\nQuestion: {question}", ticker=ticker, validate=validate, max_out=500)
            return self._send(200, out, cache=True)
        except Exception as e:
            return self._send(502, {"error": str(e)[:200]})
