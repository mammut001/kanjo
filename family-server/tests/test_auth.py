"""Comprehensive unit tests for Firebase Google sign-in auth flow, JWT verification,
RSASSA-PKCS1-v1_5 SHA-256 in pure Python, session lifecycle, CSRF, rate limiting, and security headers.
"""

import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import logging
import os
import random
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from family_server import auth
from family_server import db
from family_server.auth import DIGEST_INFO_SHA256_PREFIX
from family_server.rate_limit import RateLimiter
from family_server.server import start_servers, stop_servers


# ---------------------------------------------------------------------------
# Pure-Python RSA Key Generation for Tests (Deterministic via Miller-Rabin)
# ---------------------------------------------------------------------------

def is_prime(n: int, k: int = 10) -> bool:
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0:
        return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def gen_prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits) | (3 << (bits - 2)) | 1
        if is_prime(candidate):
            return candidate


def generate_test_rsa_keypair(bits: int = 1024, seed: int = 42):
    """Generate fixed deterministic RSA keypair in pure Python (n, e, d)."""
    rng = random.Random(seed)
    half_bits = bits // 2
    p = gen_prime(half_bits, rng)
    q = gen_prime(half_bits, rng)
    n = p * q
    phi = (p - 1) * (q - 1)
    e = 65537
    d = pow(e, -1, phi)
    return n, e, d


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def rsa_sign_pkcs1_v1_5(message: bytes, d: int, n: int) -> bytes:
    """Sign message using RSASSA-PKCS1-v1_5 with SHA-256."""
    k = (n.bit_length() + 7) // 8
    h = hashlib.sha256(message).digest()
    t = DIGEST_INFO_SHA256_PREFIX + h
    ps_len = k - len(t) - 3
    em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
    em_int = int.from_bytes(em, "big")
    sig_int = pow(em_int, d, n)
    return sig_int.to_bytes(k, "big")


class MockJWKManager(auth.JWKManager):
    """Mock JWKManager supplying the test RSA key."""

    def __init__(self, key_map):
        super().__init__()
        self.key_map = key_map

    def get_jwk(self, kid: str):
        return self.key_map.get(kid)


class TestFirebaseAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Generate 1024-bit test RSA keypair deterministically (takes < 0.5s)
        cls.n, cls.e, cls.d = generate_test_rsa_keypair(bits=1024, seed=1337)
        cls.kid = "test-firebase-kid-1"
        cls.project_id = "kanjo-family-usage"
        cls.public_origin = "https://usage.paytonpei.top"
        cls.admin_emails = {"admin@paytonpei.top", "alice@example.com"}

        cls.mock_jwk_manager = MockJWKManager({
            cls.kid: (cls.n, cls.e),
        })

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "auth_test.db")
        db.init_db(self.db_path)

        # Rate limiter with 10 max requests per 60 seconds
        self.session_rate_limiter = RateLimiter(window_seconds=60.0, max_requests=10)

        # Capture logs to verify token is never logged
        self.log_stream = io.StringIO()
        self.log_handler = logging.StreamHandler(self.log_stream)
        self.logger = logging.getLogger("family_server")
        self.logger.addHandler(self.log_handler)
        self.logger.setLevel(logging.INFO)

        self.api_server, self.dash_server, self.api_port, self.dash_port = start_servers(
            db_path=self.db_path,
            api_host="127.0.0.1",
            api_port=0,
            dashboard_host="127.0.0.1",
            dashboard_port=0,
            session_rate_limiter=self.session_rate_limiter,
            project_id=self.project_id,
            admin_emails=self.admin_emails,
            public_origin=self.public_origin,
            jwk_manager=self.mock_jwk_manager,
        )

    def tearDown(self):
        stop_servers(self.api_server, self.dash_server)
        self.logger.removeHandler(self.log_handler)
        self.tmp_dir.cleanup()

    def _create_token(
        self,
        headers: dict = None,
        claims: dict = None,
        tamper_sig: bool = False,
        use_key: tuple = None,
    ) -> str:
        """Helper to create and sign test JWT tokens."""
        n = use_key[0] if use_key else self.n
        d = use_key[1] if use_key else self.d

        now = time.time()
        hdr = {"alg": "RS256", "kid": self.kid}
        if headers:
            hdr.update(headers)

        payload = {
            "iss": f"https://securetoken.google.com/{self.project_id}",
            "aud": self.project_id,
            "exp": now + 3600,
            "iat": now - 10,
            "auth_time": now - 10,
            "sub": "google-user-id-999",
            "email_verified": True,
            "email": "admin@paytonpei.top",
            "firebase": {"sign_in_provider": "google.com"},
        }
        if claims:
            payload.update(claims)

        h_b64 = b64url_encode(json.dumps(hdr).encode("utf-8"))
        p_b64 = b64url_encode(json.dumps(payload).encode("utf-8"))
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")

        alg = hdr.get("alg")
        if alg == "none":
            return f"{h_b64}.{p_b64}."
        elif alg == "HS256":
            sig = hmac.new(b"secret", signing_input, hashlib.sha256).digest()
            return f"{h_b64}.{p_b64}.{b64url_encode(sig)}"

        sig_bytes = rsa_sign_pkcs1_v1_5(signing_input, d, n)
        if tamper_sig:
            # Invert the last byte
            sig_bytes = sig_bytes[:-1] + bytes([sig_bytes[-1] ^ 0xFF])

        return f"{h_b64}.{p_b64}.{b64url_encode(sig_bytes)}"

    def _dash_request(
        self,
        method: str,
        path: str,
        data: bytes = None,
        headers: dict = None,
    ):
        """Send HTTP request to dashboard listener."""
        url = f"http://127.0.0.1:{self.dash_port}{path}"
        req_headers = headers.copy() if headers else {}
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

        # Custom opener to prevent auto-following redirects so we can inspect 302/303
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            with opener.open(req) as resp:
                status = resp.status
                body = resp.read()
                resp_headers = dict(resp.getheaders())
                return status, body, resp_headers
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read()
            resp_headers = dict(e.headers)
            return status, body, resp_headers

    # -----------------------------------------------------------------------
    # JWT Verification Test Cases
    # -----------------------------------------------------------------------

    def test_valid_token_creates_session_cookie(self):
        """Valid Firebase ID token must create a server session and set __Host- cookie."""
        token = self._create_token()
        payload = json.dumps({"idToken": token}).encode("utf-8")

        status, body, headers = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": self.public_origin,
            },
        )
        self.assertEqual(status, 200, f"Expected 200 OK, got {status}: {body.decode('utf-8')}")
        res_data = json.loads(body.decode("utf-8"))
        self.assertEqual(res_data.get("status"), "ok")

        # Verify Set-Cookie header and security flags
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("__Host-family_session=", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Max-Age=604800", cookie)

        # Extract session ID from cookie
        session_id = cookie.split("__Host-family_session=")[1].split(";")[0].strip()

        # Verify session is persisted in SQLite DB
        with db.get_connection(self.db_path) as conn:
            session_row = db.get_session(conn, session_id)
            self.assertIsNotNone(session_row)
            self.assertEqual(session_row["email"], "admin@paytonpei.top")

        # Verify token is NEVER logged
        logs = self.log_stream.getvalue()
        self.assertNotIn(token, logs)

    def test_wrong_aud(self):
        token = self._create_token(claims={"aud": "wrong-project-id"})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_wrong_iss(self):
        token = self._create_token(claims={"iss": "https://securetoken.google.com/wrong-project"})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_expired_token(self):
        token = self._create_token(claims={"exp": time.time() - 100})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_alg_none(self):
        token = self._create_token(headers={"alg": "none"})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_alg_hs256(self):
        token = self._create_token(headers={"alg": "HS256"})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_unknown_kid(self):
        token = self._create_token(headers={"kid": "unknown-nonexistent-kid"})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_bad_signature(self):
        token = self._create_token(tamper_sig=True)
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_tampered_payload(self):
        token = self._create_token()
        h, p, s = token.split(".")
        # Tamper payload part by re-encoding a different payload with same signature
        tampered_p = b64url_encode(json.dumps({"sub": "attacker", "email": "admin@paytonpei.top"}).encode("utf-8"))
        tampered_token = f"{h}.{tampered_p}.{s}"
        payload = json.dumps({"idToken": tampered_token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_email_not_verified(self):
        token = self._create_token(claims={"email_verified": False})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_provider_not_google(self):
        token = self._create_token(claims={"firebase": {"sign_in_provider": "password"}})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 401)

    def test_email_not_allowlisted(self):
        token = self._create_token(claims={"email": "unauthorized.user@gmail.com"})
        payload = json.dumps({"idToken": token}).encode("utf-8")
        status, body, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": self.public_origin},
        )
        self.assertEqual(status, 403, "Email outside allowlist must receive 403 Forbidden")
        res_data = json.loads(body.decode("utf-8"))
        self.assertIn("error", res_data)

    # -----------------------------------------------------------------------
    # Session, Cookie, and Route Protection Tests
    # -----------------------------------------------------------------------

    def test_session_required_for_dashboard_html_and_json(self):
        # 1. Unauthenticated HTML request to / -> 302/303 redirect to /login
        status, _, headers = self._dash_request("GET", "/")
        self.assertIn(status, (302, 303))
        self.assertEqual(headers.get("Location"), "/login")

        # 2. Unauthenticated JSON request to / -> 401 Unauthorized
        status, body, _ = self._dash_request(
            "GET",
            "/",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(status, 401)
        res = json.loads(body.decode("utf-8"))
        self.assertEqual(res.get("error"), "Unauthorized")

    def test_valid_session_accesses_dashboard(self):
        with db.get_connection(self.db_path) as conn:
            sess_id = db.create_session(conn, "admin@paytonpei.top")

        status, body, headers = self._dash_request(
            "GET",
            "/",
            headers={"Cookie": f"__Host-family_session={sess_id}"},
        )
        self.assertEqual(status, 200)
        html_str = body.decode("utf-8")
        self.assertIn("家庭用量汇总", html_str)
        self.assertIn("admin@paytonpei.top", html_str)
        self.assertIn("退出", html_str)

        # Authenticated pages must have Cache-Control: no-store
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_expired_session_rejected(self):
        # Create expired session in DB
        with db.get_connection(self.db_path) as conn:
            sess_id = db.create_session(conn, "admin@paytonpei.top", expires_days=-1)

        status, _, headers = self._dash_request(
            "GET",
            "/",
            headers={"Cookie": f"__Host-family_session={sess_id}"},
        )
        self.assertIn(status, (302, 303))
        self.assertEqual(headers.get("Location"), "/login")

    def test_logout_invalidates_session_and_clears_cookie(self):
        with db.get_connection(self.db_path) as conn:
            sess_id = db.create_session(conn, "admin@paytonpei.top")

        # Call /auth/logout with valid Origin and Cookie
        status, body, headers = self._dash_request(
            "POST",
            "/auth/logout",
            headers={
                "Origin": self.public_origin,
                "Cookie": f"__Host-family_session={sess_id}",
            },
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/login")

        # Verify cookie cleared
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("__Host-family_session=", cookie)
        self.assertIn("Max-Age=0", cookie)

        # Verify DB session removed
        with db.get_connection(self.db_path) as conn:
            sess_row = db.get_session(conn, sess_id)
            self.assertIsNone(sess_row)

        # Subsequent request to / must now be redirected to /login
        status2, _, headers2 = self._dash_request(
            "GET",
            "/",
            headers={"Cookie": f"__Host-family_session={sess_id}"},
        )
        self.assertIn(status2, (302, 303))
        self.assertEqual(headers2.get("Location"), "/login")

    # -----------------------------------------------------------------------
    # CSRF Protection Tests
    # -----------------------------------------------------------------------

    def test_csrf_protection_on_dashboard_posts(self):
        token = self._create_token()
        payload = json.dumps({"idToken": token}).encode("utf-8")

        # 1. Missing Origin and missing Sec-Fetch-Site -> 403 Forbidden
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)

        # 2. Evil Origin -> 403 Forbidden
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://malicious-site.com",
            },
        )
        self.assertEqual(status, 403)

        # 3. Sec-Fetch-Site: same-origin when Origin is absent -> allowed
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(status, 200)

        # 4. Valid Origin matching FAMILY_PUBLIC_ORIGIN -> allowed
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": self.public_origin,
            },
        )
        self.assertEqual(status, 200)

    # -----------------------------------------------------------------------
    # Security Headers Tests
    # -----------------------------------------------------------------------

    def test_security_headers_present_on_responses(self):
        status, _, headers = self._dash_request("GET", "/login")
        self.assertEqual(status, 200)

        # 1. Content-Security-Policy
        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self' https://apis.google.com https://www.gstatic.com", csp)
        self.assertIn("connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com", csp)
        self.assertIn("frame-src https://kanjo-family-usage.firebaseapp.com", csp)
        self.assertIn("img-src 'self' data: https://lh3.googleusercontent.com", csp)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("base-uri 'none'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

        # 2. Strict-Transport-Security
        self.assertEqual(headers.get("Strict-Transport-Security"), "max-age=31536000")

        # 3. X-Content-Type-Options
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

        # 4. Referrer-Policy
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

        # 5. Cross-Origin-Opener-Policy
        self.assertEqual(headers.get("Cross-Origin-Opener-Policy"), "same-origin-allow-popups")

    # -----------------------------------------------------------------------
    # Rate Limiting & Size Limits Tests
    # -----------------------------------------------------------------------

    def test_rate_limiting_auth_session_by_client_ip(self):
        token = self._create_token()
        payload = json.dumps({"idToken": token}).encode("utf-8")

        # Make 10 requests from client IP 203.0.113.1
        for i in range(10):
            status, _, _ = self._dash_request(
                "POST",
                "/auth/session",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Origin": self.public_origin,
                    "CF-Connecting-IP": "203.0.113.1",
                },
            )
            self.assertEqual(status, 200, f"Request {i+1} should succeed")

        # 11th request from same IP must be rejected with 429
        status11, _, headers11 = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": self.public_origin,
                "CF-Connecting-IP": "203.0.113.1",
            },
        )
        self.assertEqual(status11, 429)
        self.assertIn("Retry-After", headers11)

        # Request from different IP 203.0.113.2 should still succeed
        status_other, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": self.public_origin,
                "CF-Connecting-IP": "203.0.113.2",
            },
        )
        self.assertEqual(status_other, 200)

    def test_request_size_limit_on_dashboard(self):
        # 64 KB limit on /auth/session
        large_body = b"x" * (65536 + 10)
        status, _, _ = self._dash_request(
            "POST",
            "/auth/session",
            data=large_body,
            headers={
                "Content-Type": "application/json",
                "Origin": self.public_origin,
            },
        )
        self.assertEqual(status, 413)

    # -----------------------------------------------------------------------
    # Static Assets & Healthz
    # -----------------------------------------------------------------------

    def test_static_asset_serving_and_traversal_prevention(self):
        # GET /static/login.js -> 200 OK
        status, body, headers = self._dash_request("GET", "/static/login.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript", headers.get("Content-Type", ""))
        self.assertIn("signInWithPopup", body.decode("utf-8"))

        # Directory traversal attempt -> 404
        status, _, _ = self._dash_request("GET", "/static/../../__init__.py")
        self.assertEqual(status, 404)

    def test_healthz_unauthenticated(self):
        status, body, _ = self._dash_request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
