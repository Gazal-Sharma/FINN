"""Vercel function: GET /api/research?t=TICKER[&part=basic] -> dossier JSON.

part=basic returns the reported numbers in ~2 s so the page can show them at
once; the full call (promises, verdicts) follows.

Uses the same finn.research.build() as the scheduled job, so any NSE ticker
works the same way as the pre-built ones. ?ping=1 is a health check.
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("FINN_RUNTIME", "api")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=21600, stale-while-revalidate=86400" if code == 200 else "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if q.get("ping"):
            return self._send(200, {"ok": True, "key": bool(os.environ.get("GEMINI_API_KEY")), "py": sys.version})
        t = (q.get("t") or [""])[0].upper().strip()
        if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", t):
            return self._send(400, {"error": "Give an NSE symbol, e.g. ?t=INFY"})
        started = time.time()
        part = (q.get("part") or ["full"])[0]
        try:
            from finn import research
            if part == "basic":  # step 1: reported numbers only, no AI, ~2 s
                d = research.build_basic(t)
                d["seconds"] = round(time.time() - started, 1)
                return self._send(200, d)
            d = research.build(t, offline_raw=False)
            d["live"] = True
            d["seconds"] = round(time.time() - started, 1)
            return self._send(200, d)
        except Exception as e:
            msg = str(e)
            code = 404 if "not found" in msg.lower() else 502
            return self._send(code, {"error": msg[:300], "ticker": t, "seconds": round(time.time() - started, 1)})
