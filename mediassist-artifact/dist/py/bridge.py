"""Runs the MediAssist server inside the browser (Pyodide). Requests from the page's fetch()
are handed to the real request handler; the database lives in the browser and is saved to
IndexedDB by the page."""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import sys

os.environ["MEDIASSIST_DATA"] = "/data"
os.environ["MEDIASSIST_DB"] = "/data/mediassist.db"
sys.path.insert(0, "/ma")

from app import core, m_admin  # noqa: E402


def _fast_hash(password, salt, rounds=2000):
    # Demo in the browser: Pyodide has no OpenSSL pbkdf2_hmac, so this is PBKDF2-HMAC-SHA256
    # (one block) in plain Python with fewer rounds. The installed server keeps 200,000 rounds.
    key = password.encode()
    u = hmac.new(key, bytes.fromhex(salt) + b"\x00\x00\x00\x01", hashlib.sha256).digest()
    out = bytearray(u)
    for _ in range(rounds - 1):
        u = hmac.new(key, u, hashlib.sha256).digest()
        out = bytearray(a ^ b for a, b in zip(out, u))
    return bytes(out).hex()


core.hash_pw = _fast_hash
m_admin.hash_pw = _fast_hash

import server  # noqa: E402  (registers every route)
from app.setup import init  # noqa: E402

DEMO_PASSWORD = "demo1234"


def boot(fresh):
    init(demo=bool(fresh), quiet=True)
    c = core.db()
    if fresh:
        for (uid,) in c.execute("SELECT id FROM users").fetchall():
            salt = secrets.token_hex(16)
            c.execute("UPDATE users SET salt=?, pw=? WHERE id=?", (salt, _fast_hash(DEMO_PASSWORD, salt), uid))
        c.execute("UPDATE settings SET value='0' WHERE key='auto_send'")
    core.reset_conn()
    return True


class BrowserRequest(server.Handler):
    def __init__(self, method, path, headers, body):  # no socket: built from the page's fetch()
        self.command, self.path, self.headers = method, path, headers
        self.rfile, self.client_address, self.out = io.BytesIO(body), ("127.0.0.1", 0), None

    def send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.out = (status, ctype, extra or {}, getattr(self, "set_cookie", None), data)


def handle(method, path, headers_json, body_b64):
    headers = json.loads(headers_json)
    body = base64.b64decode(body_b64) if body_b64 else b""
    headers["Content-Length"] = str(len(body))
    req = BrowserRequest(method, path, headers, body)
    req.handle_any(method)
    status, ctype, extra, cookie, data = req.out
    return json.dumps({"status": status, "ctype": ctype, "headers": extra, "cookie": cookie, "body": base64.b64encode(data).decode()})


def snapshot():
    c = core.db()
    data = c.serialize()
    core.reset_conn()
    return data
