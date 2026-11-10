"""API HTTP request handler for Kanjo family report intake."""

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import logging
import math
import time
from typing import Optional

from . import db
from .rate_limit import RateLimiter
from .validation import check_privacy_backstop, validate_report_payload

logger = logging.getLogger("family_server.api")
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


class APIHandler(BaseHTTPRequestHandler):
    """HTTP handler for the private API listener (port 8788)."""

    server_version = "KanjoFamilyAPI/0.1"

    # Attached by factory/server
    db_path: str = ""
    rate_limiter: Optional[RateLimiter] = None

    def log_message(self, format: str, *args) -> None:
        """Sanitized log output - never prints request bodies or tokens."""
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json_response(self, status: int, data: dict, headers: Optional[dict] = None) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json_response(HTTPStatus.OK, {"status": "ok"})
            return

        # Any other GET is 404
        self._send_json_response(HTTPStatus.NOT_FOUND, {"status": "error", "error": "Not Found"})

    def do_POST(self) -> None:
        if self.path != "/api/report":
            self._send_json_response(HTTPStatus.NOT_FOUND, {"status": "error", "error": "Not Found"})
            return

        # 1. Authenticate bearer token
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Rejected report: missing or invalid Authorization header format")
            self._send_json_response(HTTPStatus.UNAUTHORIZED, {"status": "error", "error": "Unauthorized"})
            return

        raw_token = auth_header[len("Bearer "):].strip()
        if not raw_token:
            logger.warning("Rejected report: empty token")
            self._send_json_response(HTTPStatus.UNAUTHORIZED, {"status": "error", "error": "Unauthorized"})
            return

        token_hash = db.hash_token(raw_token)
        with db.get_connection(self.db_path) as conn:
            member = db.get_member_by_token_hash(conn, token_hash)
            if not member or member["revoked_at"] is not None:
                logger.warning("Rejected report: unrecognized or revoked token")
                self._send_json_response(HTTPStatus.UNAUTHORIZED, {"status": "error", "error": "Unauthorized"})
                return

            member_id = member["id"]
            member_name = member["name"]

            # 2. Check Content-Length if present
            cl_header = self.headers.get("Content-Length")
            if cl_header:
                try:
                    content_length = int(cl_header)
                except ValueError:
                    logger.warning("Rejected report from '%s': invalid Content-Length", member_name)
                    self._send_json_response(HTTPStatus.BAD_REQUEST, {"status": "error", "error": "Invalid Content-Length"})
                    return

                if content_length > MAX_PAYLOAD_BYTES:
                    logger.warning("Rejected report from '%s': Content-Length exceeds 2 MB (%d bytes)", member_name, content_length)
                    # Drain incoming stream so client socket receives 413 cleanly
                    try:
                        remaining = content_length
                        while remaining > 0:
                            chunk = self.rfile.read(min(remaining, 65536))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                    except Exception:
                        pass
                    self.close_connection = True
                    self._send_json_response(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        {"status": "error", "error": "Payload exceeds 2 MB limit"},
                        headers={"Connection": "close"},
                    )
                    return
            else:
                content_length = None

            # 3. Read body with limit
            if content_length is not None:
                raw_body = self.rfile.read(content_length)
            else:
                raw_body = self.rfile.read(MAX_PAYLOAD_BYTES + 1)

            if len(raw_body) > MAX_PAYLOAD_BYTES:
                logger.warning("Rejected report from '%s': body exceeds 2 MB limit", member_name)
                self.close_connection = True
                self._send_json_response(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"status": "error", "error": "Payload exceeds 2 MB limit"},
                    headers={"Connection": "close"},
                )
                return

            # 4. Privacy backstop check
            privacy_err = check_privacy_backstop(raw_body)
            if privacy_err:
                logger.warning("Rejected report from '%s': %s", member_name, privacy_err)
                self._send_json_response(HTTPStatus.BAD_REQUEST, {"status": "error", "error": privacy_err})
                return

            # 5. Parse JSON
            try:
                body_str = raw_body.decode("utf-8")
                payload = json.loads(body_str)
            except Exception:
                logger.warning("Rejected report from '%s': failed to parse JSON payload", member_name)
                self._send_json_response(HTTPStatus.BAD_REQUEST, {"status": "error", "error": "Invalid JSON payload"})
                return

            # 6. Validate payload structure and types
            val_err = validate_report_payload(payload)
            if val_err:
                logger.warning("Rejected report from '%s': %s", member_name, val_err)
                self._send_json_response(HTTPStatus.BAD_REQUEST, {"status": "error", "error": val_err})
                return

            # 7. Rate limiting check (60 s per-token window)
            if self.rate_limiter:
                allowed, retry_after = self.rate_limiter.check_and_record(token_hash, now=time.time())
                if not allowed:
                    logger.warning("Rejected report from '%s': rate limit exceeded (retry in %.1fs)", member_name, retry_after)
                    retry_secs = max(1, int(math.ceil(retry_after)))
                    self._send_json_response(
                        HTTPStatus.TOO_MANY_REQUESTS,
                        {"status": "error", "error": "Rate limit exceeded (1 request per 60s per token)"},
                        headers={"Retry-After": str(retry_secs)},
                    )
                    return

            # 8. Store report in SQLite
            now_iso = datetime.now(timezone.utc).isoformat()
            generated_at = payload.get("generated_at", now_iso)
            db.insert_report(conn, member_id, generated_at, body_str, received_at=now_iso)

            # Trigger hourly prune check on insert
            db.maybe_prune_hourly(conn)

            logger.info("Successfully accepted report from member '%s'", member_name)
            self._send_json_response(HTTPStatus.OK, {"status": "ok", "received_at": now_iso})


def make_api_handler(db_path: str, rate_limiter: RateLimiter):
    """Factory to create an APIHandler class bound to db_path and rate_limiter."""
    class BoundAPIHandler(APIHandler):
        pass

    BoundAPIHandler.db_path = db_path
    BoundAPIHandler.rate_limiter = rate_limiter
    return BoundAPIHandler
