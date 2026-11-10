"""Authentication and token verification using pure-Python RSA and Firebase JWKs."""

import base64
import hashlib
import hmac
import json
import logging
import re
import threading
import time
from typing import Dict, Optional, Set, Tuple
import urllib.request

logger = logging.getLogger("family_server.auth")

GOOGLE_JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
DIGEST_INFO_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def base64url_decode(s: str) -> bytes:
    """Decode unpadded or padded base64url-encoded string."""
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def base64url_to_int(s: str) -> int:
    """Decode base64url string to big-endian unsigned integer."""
    raw = base64url_decode(s)
    return int.from_bytes(raw, byteorder="big")


def int_to_base64url(val: int) -> str:
    """Encode an unsigned integer to unpadded base64url."""
    byte_len = max(1, (val.bit_length() + 7) // 8)
    raw = val.to_bytes(byte_len, byteorder="big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_rs256_signature(signing_input_bytes: bytes, signature_bytes: bytes, n: int, e: int) -> bool:
    """Verify RSASSA-PKCS1-v1_5 SHA-256 signature in pure Python with constant-time check.
    
    1. Computes modulus length in bytes: k = (n.bit_length() + 7) // 8
    2. Rejects if signature length != k or out of range [0, n)
    3. Performs RSA operation m = pow(sig, e, n)
    4. Encodes EMSA-PKCS1-v1_5 structure: 0x00 || 0x01 || PS (0xFF) || 0x00 || DigestInfo(SHA256)
    5. Performs constant-time comparison hmac.compare_digest(recovered, expected)
    """
    k = (n.bit_length() + 7) // 8
    prefix_len = len(DIGEST_INFO_SHA256_PREFIX)
    # DigestInfo = prefix (19 bytes) + SHA-256 hash (32 bytes) = 51 bytes
    t_len = prefix_len + 32
    if k < t_len + 11:
        return False

    if len(signature_bytes) != k:
        return False

    s = int.from_bytes(signature_bytes, byteorder="big")
    if s < 0 or s >= n:
        return False

    # RSA operation
    m = pow(s, e, n)
    try:
        recovered_em = m.to_bytes(k, byteorder="big")
    except OverflowError:
        return False

    # Build expected EMSA-PKCS1-v1_5 structure
    h = hashlib.sha256(signing_input_bytes).digest()
    t = DIGEST_INFO_SHA256_PREFIX + h
    ps_len = k - len(t) - 3
    if ps_len < 8:
        return False

    expected_em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
    return hmac.compare_digest(recovered_em, expected_em)


class JWKManager:
    """Fetches and caches Google's public JWK keys honoring Cache-Control max-age."""

    def __init__(self, jwk_url: str = GOOGLE_JWKS_URL):
        self.jwk_url = jwk_url
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[int, int]] = {}  # kid -> (n, e)
        self._expires_at: float = 0.0

    def get_jwk(self, kid: str) -> Optional[Tuple[int, int]]:
        """Get (n, e) for a given key ID, refreshing cache as needed."""
        now = time.time()
        with self._lock:
            # If cache is empty or expired, fetch keys
            if not self._cache or now >= self._expires_at:
                self._fetch_keys(now)

            if kid in self._cache:
                return self._cache[kid]

            # Refetch once on unknown kid in case of key rotation
            logger.info("Unknown kid '%s'; refetching JWKs once", kid)
            self._fetch_keys(now)
            return self._cache.get(kid)

    def _fetch_keys(self, now: float) -> None:
        """Fetch keys from Google JWKs endpoint."""
        try:
            req = urllib.request.Request(
                self.jwk_url,
                headers={"User-Agent": "KanjoFamilyServer/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                cc = resp.headers.get("Cache-Control", "")
                max_age = 3600  # Fallback: 1 hour
                m = re.search(r"max-age=(\d+)", cc)
                if m:
                    try:
                        max_age = int(m.group(1))
                    except ValueError:
                        pass
                self._expires_at = now + max_age

                new_cache: Dict[str, Tuple[int, int]] = {}
                for key_entry in data.get("keys", []):
                    if (
                        key_entry.get("kty") == "RSA"
                        and key_entry.get("kid")
                        and "n" in key_entry
                        and "e" in key_entry
                    ):
                        try:
                            n_val = base64url_to_int(key_entry["n"])
                            e_val = base64url_to_int(key_entry["e"])
                            new_cache[key_entry["kid"]] = (n_val, e_val)
                        except Exception as parse_err:
                            logger.warning("Error parsing JWK entry: %s", parse_err)
                self._cache = new_cache
                logger.info("Fetched %d JWK key(s), cached until %f", len(self._cache), self._expires_at)
        except Exception as e:
            logger.error("Failed to fetch Google JWKs from %s: %s", self.jwk_url, e)


_default_jwk_manager: Optional[JWKManager] = None


def get_default_jwk_manager() -> JWKManager:
    global _default_jwk_manager
    if _default_jwk_manager is None:
        _default_jwk_manager = JWKManager()
    return _default_jwk_manager


def verify_firebase_id_token(
    id_token: str,
    project_id: str,
    admin_emails: Set[str],
    jwk_manager: Optional[JWKManager] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict]]:
    """Verify Firebase ID token server-side in pure Python.
    
    Returns:
        (success: bool, error_message: str, claims: Optional[dict])
    """
    if now is None:
        now = time.time()

    if jwk_manager is None:
        jwk_manager = get_default_jwk_manager()

    parts = id_token.split(".")
    if len(parts) != 3:
        return False, "Malformed token format: expected 3 dot-separated segments", None

    header_b64, payload_b64, signature_b64 = parts

    # 1. Parse header
    try:
        header_bytes = base64url_decode(header_b64)
        header = json.loads(header_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"Failed to parse JWT header: {e}", None

    alg = header.get("alg")
    if alg != "RS256":
        return False, f"Invalid token algorithm '{alg}': RS256 is strictly required", None

    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        return False, "Missing or invalid kid in JWT header", None

    # 2. Look up public key
    key_tuple = jwk_manager.get_jwk(kid)
    if not key_tuple:
        return False, f"Key ID '{kid}' not found in Google JWKs", None

    n, e = key_tuple

    # 3. Parse payload/claims
    try:
        payload_bytes = base64url_decode(payload_b64)
        claims = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"Failed to parse JWT payload: {e}", None

    # 4. Verify cryptographic signature
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        signature_bytes = base64url_decode(signature_b64)
    except Exception as e:
        return False, f"Invalid base64url signature encoding: {e}", None

    if not verify_rs256_signature(signing_input, signature_bytes, n, e):
        return False, "RSA signature verification failed", None

    # 5. Validate claims
    # iss: must be https://securetoken.google.com/<project_id>
    expected_iss = f"https://securetoken.google.com/{project_id}"
    if claims.get("iss") != expected_iss:
        return False, f"Invalid token issuer: expected '{expected_iss}', got '{claims.get('iss')}'", claims

    # aud: must be project_id
    if claims.get("aud") != project_id:
        return False, f"Invalid token audience: expected '{project_id}', got '{claims.get('aud')}'", claims

    # exp: must be in the future
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= now:
        return False, f"Token has expired (exp={exp}, now={now:.1f})", claims

    # iat: issued in the past (with 300s clock skew tolerance)
    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or iat > now + 300:
        return False, f"Token issued in the future (iat={iat}, now={now:.1f})", claims

    # auth_time: authentication in the past (with 300s clock skew tolerance)
    auth_time = claims.get("auth_time")
    if not isinstance(auth_time, (int, float)) or auth_time > now + 300:
        return False, f"Token auth_time in the future (auth_time={auth_time}, now={now:.1f})", claims

    # sub: non-empty string
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str) or not sub.strip():
        return False, "Token subject (sub) is empty or missing", claims

    # email_verified: must be boolean True
    if claims.get("email_verified") is not True:
        return False, "Email address has not been verified", claims

    # firebase.sign_in_provider: must be "google.com"
    firebase_claim = claims.get("firebase")
    if not isinstance(firebase_claim, dict) or firebase_claim.get("sign_in_provider") != "google.com":
        provider = firebase_claim.get("sign_in_provider") if isinstance(firebase_claim, dict) else None
        return False, f"Invalid sign-in provider: expected 'google.com', got '{provider}'", claims

    # email: lower-cased must be in FAMILY_ADMIN_EMAILS
    email = claims.get("email")
    if not email or not isinstance(email, str):
        return False, "Token missing email claim", claims

    clean_email = email.strip().lower()
    if clean_email not in admin_emails:
        return False, f"Email '{clean_email}' is not in authorized admin emails", claims

    return True, "", claims
