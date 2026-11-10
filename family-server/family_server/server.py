"""HTTP server manager running both API and Dashboard listeners in one process."""

from http.server import ThreadingHTTPServer
import logging
import threading
from typing import Optional, Set, Tuple

from . import auth
from .api import make_api_handler
from .dashboard import make_dashboard_handler
from .db import init_db
from .rate_limit import RateLimiter

logger = logging.getLogger("family_server.server")


def start_servers(
    db_path: str,
    api_host: str = "0.0.0.0",
    api_port: int = 8788,
    dashboard_host: str = "0.0.0.0",
    dashboard_port: int = 8787,
    rate_limiter: Optional[RateLimiter] = None,
    session_rate_limiter: Optional[RateLimiter] = None,
    firebase_config: Optional[dict] = None,
    project_id: Optional[str] = None,
    admin_emails: Optional[Set[str]] = None,
    public_origin: Optional[str] = None,
    jwk_manager: Optional[auth.JWKManager] = None,
) -> Tuple[ThreadingHTTPServer, ThreadingHTTPServer, int, int]:
    """Initialize DB and start both API and Dashboard servers in background threads."""
    init_db(db_path)

    if rate_limiter is None:
        rate_limiter = RateLimiter(window_seconds=60.0, max_requests=1)

    api_handler_cls = make_api_handler(db_path, rate_limiter)
    dashboard_handler_cls = make_dashboard_handler(
        db_path=db_path,
        firebase_config=firebase_config,
        project_id=project_id,
        admin_emails=admin_emails,
        public_origin=public_origin,
        session_rate_limiter=session_rate_limiter,
        jwk_manager=jwk_manager,
    )

    api_server = ThreadingHTTPServer((api_host, api_port), api_handler_cls)
    dash_server = ThreadingHTTPServer((dashboard_host, dashboard_port), dashboard_handler_cls)

    actual_api_port = api_server.server_address[1]
    actual_dash_port = dash_server.server_address[1]

    logger.info("Starting API server on %s:%d", api_host, actual_api_port)
    logger.info("Starting Dashboard server on %s:%d", dashboard_host, actual_dash_port)

    t_api = threading.Thread(target=api_server.serve_forever, daemon=True, name="api-server")
    t_dash = threading.Thread(target=dash_server.serve_forever, daemon=True, name="dashboard-server")

    t_api.start()
    t_dash.start()

    return api_server, dash_server, actual_api_port, actual_dash_port


def stop_servers(api_server: ThreadingHTTPServer, dash_server: ThreadingHTTPServer) -> None:
    """Shutdown and close both servers."""
    try:
        api_server.shutdown()
        api_server.server_close()
    except Exception as e:
        logger.warning("Error shutting down API server: %s", e)

    try:
        dash_server.shutdown()
        dash_server.server_close()
    except Exception as e:
        logger.warning("Error shutting down Dashboard server: %s", e)
