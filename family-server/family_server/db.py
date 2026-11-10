"""Database storage and queries for Kanjo family usage server."""

from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
import sqlite3
from typing import Dict, List, Optional, Tuple


def hash_token(token: str) -> str:
    """Compute SHA-256 hex digest of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_db(db_path: str) -> None:
    """Ensure database parent directory exists and initialize schema."""
    parent_dir = os.path.dirname(os.path.abspath(db_path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                token_sha256 TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                received_at TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reports_member_received ON reports(member_id, received_at);
            CREATE INDEX IF NOT EXISTS idx_reports_received ON reports(received_at);

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
            """
        )
        conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    """Create a new SQLite connection with configured pragmas."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    return conn


def add_member(conn: sqlite3.Connection, name: str) -> Tuple[str, int]:
    """Add a new member. Returns (raw_token, member_id). Raises ValueError if duplicate."""
    name = name.strip()
    if not name:
        raise ValueError("Member name cannot be empty.")

    cur = conn.cursor()
    cur.execute("SELECT id FROM members WHERE name = ?", (name,))
    if cur.fetchone():
        raise ValueError(f"Member '{name}' already exists.")

    token = secrets.token_urlsafe(32)
    token_sha256 = hash_token(token)
    created_at = datetime.now(timezone.utc).isoformat()

    cur.execute(
        "INSERT INTO members (name, token_sha256, created_at, revoked_at) VALUES (?, ?, ?, NULL)",
        (name, token_sha256, created_at),
    )
    member_id = cur.lastrowid
    conn.commit()
    return token, member_id


def get_member_by_token(conn: sqlite3.Connection, token: str) -> Optional[Dict]:
    """Look up a member by raw bearer token."""
    token_sha256 = hash_token(token)
    return get_member_by_token_hash(conn, token_sha256)


def get_member_by_token_hash(conn: sqlite3.Connection, token_sha256: str) -> Optional[Dict]:
    """Look up a member by token SHA-256."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, created_at, revoked_at FROM members WHERE token_sha256 = ?",
        (token_sha256,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    return None


def list_members(conn: sqlite3.Connection) -> List[Dict]:
    """List all registered members in order of creation."""
    cur = conn.cursor()
    cur.execute("SELECT id, name, created_at, revoked_at FROM members ORDER BY id ASC")
    return [dict(r) for r in cur.fetchall()]


def revoke_member(conn: sqlite3.Connection, name: str) -> bool:
    """Revoke a member by name. Returns True if revoked, False if already revoked."""
    name = name.strip()
    cur = conn.cursor()
    cur.execute("SELECT id, revoked_at FROM members WHERE name = ?", (name,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Member '{name}' not found.")

    if row["revoked_at"] is not None:
        return False

    revoked_at = datetime.now(timezone.utc).isoformat()
    cur.execute("UPDATE members SET revoked_at = ? WHERE id = ?", (revoked_at, row["id"]))
    conn.commit()
    return True


def insert_report(
    conn: sqlite3.Connection,
    member_id: int,
    generated_at: str,
    payload_json: str,
    received_at: Optional[str] = None,
) -> int:
    """Insert a report record."""
    if received_at is None:
        received_at = datetime.now(timezone.utc).isoformat()

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reports (member_id, received_at, generated_at, payload_json) VALUES (?, ?, ?, ?)",
        (member_id, received_at, generated_at, payload_json),
    )
    report_id = cur.lastrowid
    conn.commit()
    return report_id


def get_member_latest_report(conn: sqlite3.Connection, member_id: int) -> Optional[Dict]:
    """Fetch the latest report for a given member."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, member_id, received_at, generated_at, payload_json FROM reports "
        "WHERE member_id = ? ORDER BY received_at DESC, id DESC LIMIT 1",
        (member_id,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    return None


def get_all_latest_reports(conn: sqlite3.Connection) -> List[Dict]:
    """Fetch the latest report for all active members."""
    cur = conn.cursor()
    members = list_members(conn)
    result = []
    for m in members:
        rep = get_member_latest_report(conn, m["id"])
        result.append({"member": m, "report": rep})
    return result


def prune_reports(conn: sqlite3.Connection, now: Optional[datetime] = None) -> int:
    """Prune reports according to retention policy:
    - Latest report per member is always kept.
    - Last report per member per day is kept for up to 90 days.
    - Intermediate reports on the same day are deleted.
    - Reports older than 90 days (not being the latest) are deleted.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    cutoff_date = (now - timedelta(days=90)).date().isoformat()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members")
    member_rows = cur.fetchall()

    total_deleted = 0
    for m_row in member_rows:
        member_id = m_row["id"]
        cur.execute(
            "SELECT id, received_at FROM reports WHERE member_id = ? ORDER BY received_at ASC, id ASC",
            (member_id,),
        )
        reports = cur.fetchall()
        if not reports:
            continue

        keep_ids = set()
        # 1. Overall latest report for this member
        latest_id = reports[-1]["id"]
        keep_ids.add(latest_id)

        # 2. Last report per day within 90 days
        day_groups: Dict[str, List[int]] = {}
        for r in reports:
            day_str = r["received_at"][:10]
            day_groups.setdefault(day_str, []).append(r["id"])

        for day_str, ids in day_groups.items():
            if day_str >= cutoff_date:
                keep_ids.add(ids[-1])

        to_delete = [r["id"] for r in reports if r["id"] not in keep_ids]
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            cur.execute(f"DELETE FROM reports WHERE id IN ({placeholders})", to_delete)
            total_deleted += len(to_delete)

    conn.commit()
    return total_deleted


def maybe_prune_hourly(conn: sqlite3.Connection, now: Optional[datetime] = None) -> Optional[int]:
    """Run prune if at least 1 hour has elapsed since last prune."""
    if now is None:
        now = datetime.now(timezone.utc)

    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key = 'last_prune_time'")
    row = cur.fetchone()
    should_prune = False

    if not row or not row["value"]:
        should_prune = True
    else:
        try:
            val_str = row["value"]
            if val_str.endswith("Z"):
                val_str = val_str[:-1] + "+00:00"
            last_dt = datetime.fromisoformat(val_str)
            if (now - last_dt).total_seconds() >= 3600.0:
                should_prune = True
        except Exception:
            should_prune = True

    if should_prune:
        deleted = prune_reports(conn, now)
        prune_sessions(conn, now)
        cur.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_prune_time', ?)",
            (now.isoformat(),),
        )
        conn.commit()
        return deleted

    return None


def create_session(conn: sqlite3.Connection, email: str, expires_days: int = 7) -> str:
    """Create a new server-side session for an authenticated email.
    
    Generates a cryptographically random 32-byte session ID,
    stores sha256(session_id) in SQLite sessions table,
    and returns the raw session ID.
    """
    raw_session_id = secrets.token_urlsafe(32)
    id_hash = hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    expires_at = (now + timedelta(days=expires_days)).isoformat()

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (id_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (id_hash, email.lower().strip(), created_at, expires_at),
    )
    conn.commit()
    return raw_session_id


def get_session(conn: sqlite3.Connection, raw_session_id: str, now: Optional[datetime] = None) -> Optional[Dict]:
    """Retrieve session record if valid and not expired."""
    if not raw_session_id:
        return None
    if now is None:
        now = datetime.now(timezone.utc)

    id_hash = hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()
    cur = conn.cursor()
    cur.execute(
        "SELECT id_hash, email, created_at, expires_at FROM sessions WHERE id_hash = ?",
        (id_hash,),
    )
    row = cur.fetchone()
    if not row:
        return None

    # Check expiration
    expires_str = row["expires_at"]
    if expires_str.endswith("Z"):
        expires_str = expires_str[:-1] + "+00:00"
    try:
        expires_dt = datetime.fromisoformat(expires_str)
        if now > expires_dt:
            delete_session(conn, raw_session_id)
            return None
    except Exception:
        return None

    return dict(row)


def delete_session(conn: sqlite3.Connection, raw_session_id: str) -> bool:
    """Delete a session by raw session ID."""
    if not raw_session_id:
        return False
    id_hash = hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE id_hash = ?", (id_hash,))
    conn.commit()
    return cur.rowcount > 0


def prune_sessions(conn: sqlite3.Connection, now: Optional[datetime] = None) -> int:
    """Delete all expired sessions."""
    if now is None:
        now = datetime.now(timezone.utc)
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    conn.commit()
    return cur.rowcount


def get_setting(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve setting value by key."""
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    if row and row["value"] is not None:
        return row["value"]
    return default


def set_setting(conn: sqlite3.Connection, key: str, value: Optional[str]) -> None:
    """Set or remove setting key in database."""
    cur = conn.cursor()
    if value is None:
        cur.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
    conn.commit()


def get_all_settings(conn: sqlite3.Connection) -> Dict[str, str]:
    """Fetch all settings as a key-value dictionary."""
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    return {row["key"]: row["value"] for row in cur.fetchall()}
