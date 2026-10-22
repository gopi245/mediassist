"""Open-access mode (MEDIASSIST_OPEN=1): no sign-in, every visitor is the owner. Run on its own:
python -m unittest tests.test_open_access  (the flag is read when the server module is imported)."""
import http.cookiejar
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="mediassist-open-")
os.environ["MEDIASSIST_DATA"] = TMP
os.environ["MEDIASSIST_DB"] = os.path.join(TMP, "open.db")
os.environ["MEDIASSIST_OPEN"] = "1"
sys.path.insert(0, ROOT)

import server  # noqa: E402
from app import core  # noqa: E402
from app.setup import init  # noqa: E402

PORT = 8798


class OpenAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not server.OPEN_ACCESS:
            raise unittest.SkipTest("server was imported without MEDIASSIST_OPEN=1 (run this file on its own)")
        init(demo=True, quiet=True)
        try:
            os.remove(os.path.join(ROOT, "FIRST-LOGIN.txt"))
        except OSError:
            pass
        core.reset_conn()
        cls.srv = server.ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(TMP, ignore_errors=True)

    def call(self, op, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with op.open(req) as r:
            return r.status, json.loads(r.read())

    def test_visitor_is_owner_without_signing_in(self):
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        st, me = self.call(op, "/api/me")
        self.assertEqual(st, 200)
        self.assertEqual((me["role"], me["open_access"], me["mfa_required"]), ("owner", True, False))
        st, d = self.call(op, "/api/dashboard")
        self.assertEqual((st, d["mode"]), (200, "org"))
        self.call(op, "/api/branch", {"branch_id": 1})
        self.assertEqual(self.call(op, "/api/me")[1]["branch"]["code"], "CH", "branch switch sticks to the open session")
        self.call(op, "/api/logout", {})
        self.assertEqual(self.call(op, "/api/me")[1]["role"], "owner", "signing out just starts a fresh open session")


if __name__ == "__main__":
    unittest.main()
