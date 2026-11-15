"""Vercel function: POST /api/brief with the user's sign-in token -> emails them
their morning brief now ("Send me a test brief").

Uses the caller's own Supabase token to read only their row (row-level
security), so the only secret here is the Brevo key for sending.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

os.environ.setdefault("FINN_RUNTIME", "api")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_recent = {}  # user_id -> last send time (per warm instance; a light brake on repeats)


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return self._send(401, {"error": "Sign in first."})
        try:
            from finn import brief
            uid, email, prefs = brief.user_from_token(auth[7:])
        except PermissionError:
            return self._send(401, {"error": "Your sign-in has expired. Sign in again."})
        except Exception as e:
            return self._send(502, {"error": f"Couldn't read your settings: {str(e)[:120]}"})
        if time.time() - _recent.get(uid, 0) < 120:
            return self._send(429, {"error": "A brief was just sent. Give it a couple of minutes."})
        try:
            subject, html_body, text = brief.compose(prefs)
            brief.send(email, subject, html_body, text)
            _recent[uid] = time.time()
            return self._send(200, {"ok": True, "to": email, "subject": subject})
        except Exception as e:
            return self._send(502, {"error": str(e)[:200]})
