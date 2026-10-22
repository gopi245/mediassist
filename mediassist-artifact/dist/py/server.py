"""MediAssist v2 - hospitals, clinics and medical shops in one system.

Run:   python server.py            (add --demo on the very first run for sample data)
Open:  http://localhost:8000
Standard library only. Optional: `pip install anthropic` for the AI document reader.
"""
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from app import (m_accounts, m_admin, m_appointments, m_billing, m_clinical, m_docs, m_ipd, m_lab, m_pharmacy,  # noqa: F401  (register routes)
                 m_pdf, m_portal, m_reports, m_alerts, m_assistant, m_tracker, m_upload, m_watch, m_weekly, m_care, notify)
from app.core import BASE, ROLES, ROUTES, ApiError, all_access, db, now_str, reset_conn, to_json
from app.setup import init

STATIC = os.path.join(BASE, "app", "static")
PORT = int(os.environ.get("PORT", "8000"))
TRUST_PROXY = os.environ.get("TRUST_PROXY", "") in ("1", "true", "yes")
PUBLIC_PAGES = {"/my": "my.html", "/up": "up.html", "/book": "book.html", "/display": "display.html", "/feedback": "feedback.html"}
BIG_BODY = ("/api/documents", "/api/ai/", "/api/import/", "/api/public/upload")
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    server_version = "MediAssist"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------ output
    def send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        if self.https:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if getattr(self, "set_cookie", None):
            self.send_header("Set-Cookie", self.set_cookie)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def static(self, rel):
        path = os.path.normpath(os.path.join(STATIC, rel))
        if not path.startswith(os.path.normpath(STATIC)) or not os.path.isfile(path):
            return self.send(404, "Not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        extra = {"Cache-Control": "no-cache"}
        if rel == "sw.js":
            extra["Service-Worker-Allowed"] = "/"
        self.send(200, data, ctype, extra)

    # ------------------------------------------------------------ session
    def load_session(self, c):
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        self.token = jar["sid"].value if "sid" in jar else ""
        self.user, self.branch, self.mfa_ok = None, 0, False
        if self.token:
            row = c.execute("SELECT s.branch_id sb, s.mfa_ok, u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1",
                            (self.token, time.time())).fetchone()
            if row:
                self.user = dict(row)
                self.mfa_ok = bool(row["mfa_ok"])
                self.branch = row["sb"] if all_access(self.user) else (row["branch_id"] or 0)

    # ------------------------------------------------------------ dispatch
    def handle_any(self, method):
        url = urlparse(self.path)
        self.set_cookie, self.download, self.inline = None, None, False
        # X-Forwarded-* are only meaningful behind a reverse proxy that sets them (TRUST_PROXY=1 in DEPLOY.md);
        # otherwise any client could spoof its IP (rate limits) or claim HTTPS.
        if TRUST_PROXY:
            self.https = self.headers.get("X-Forwarded-Proto", "") == "https"
            self.client_ip = (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0])
        else:
            self.https = False
            self.client_ip = self.client_address[0]
        try:
            if method in ("GET", "HEAD") and not url.path.startswith("/api/"):
                if url.path in ("/", "/index.html"):
                    return self.static("index.html")
                if url.path in PUBLIC_PAGES:
                    return self.static(PUBLIC_PAGES[url.path])
                return self.static(url.path.lstrip("/"))
            c = db()
            self.load_session(c)
            for m, rx, perm, fn in ROUTES:
                match = rx.match(url.path)
                if not match or m != (method if method != "HEAD" else "GET"):
                    continue
                if method == "POST" and "application/json" not in self.headers.get("Content-Type", ""):
                    raise ApiError(415, "JSON required")  # blocks cross-site form posts before anything else runs
                if perm:
                    if not self.user:
                        raise ApiError(401, "Please sign in")
                    if perm != "mfa" and not self.mfa_ok:
                        raise ApiError(401, "Enter your two-step sign-in code", mfa_required=True)
                    if perm not in ("any", "mfa") and perm not in ROLES.get(self.user["role"], set()):
                        raise ApiError(403, "Your role can't do this")
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    limit = 22_000_000 if url.path.startswith(BIG_BODY) else 1_000_000
                    if n > limit:
                        raise ApiError(413, "Request too large")
                    try:
                        body = json.loads(self.rfile.read(n) or b"{}")
                    except ValueError:
                        raise ApiError(400, "Invalid JSON")
                    if not isinstance(body, dict):
                        raise ApiError(400, "Invalid JSON")
                    key = self.headers.get("Idempotency-Key", "")[:80]
                    if key and self.user:
                        prev = c.execute("SELECT status, response FROM idempotency WHERE key=?", (f"{self.user['id']}:{key}",)).fetchone()
                        if prev:
                            return self.send(prev[0], prev[1], extra={"Idempotent-Replay": "true"})
                result = fn(self, c, body, parse_qs(url.query), *match.groups())
                if self.download:
                    name, data, mime = self.download
                    disp = "inline" if self.inline else "attachment"
                    return self.send(200, data if isinstance(data, bytes) else data.encode("utf-8"), mime,
                                     {"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(name)}"})
                out = to_json(result)
                if method == "POST" and self.user and self.headers.get("Idempotency-Key"):
                    c.execute("INSERT OR IGNORE INTO idempotency(key,at,status,response) VALUES(?,?,?,?)",
                              (f"{self.user['id']}:{self.headers['Idempotency-Key'][:80]}", time.time(), 200, out))
                return self.send(200, out)
            raise ApiError(404, "Not found")
        except ApiError as e:
            self.send(e.status, to_json({"error": str(e), **e.extra}))
        except Exception as e:
            traceback.print_exc()
            try:
                db().execute("INSERT INTO error_log(at,method,path,error) VALUES(?,?,?,?)", (now_str(), method, url.path, repr(e)[:1000]))
            except Exception:
                pass
            self.send(500, to_json({"error": "Something went wrong on the server. It has been logged for the administrator."}))
        finally:
            reset_conn()

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("HEAD")

    def do_POST(self):
        self.handle_any("POST")


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    init(demo="--demo" in sys.argv)
    reset_conn()
    threading.Thread(target=m_reports.scheduler_loop, daemon=True).start()
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"MediAssist running\n  this computer:   http://localhost:{PORT}\n  other computers: http://{lan_ip()}:{PORT}\n"
          f"  token screen:    http://localhost:{PORT}/display?branch=CH\n  online booking:  http://localhost:{PORT}/book?branch=CH\nPress Ctrl+C to stop.")
    srv = ThreadingHTTPServer((host, PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
