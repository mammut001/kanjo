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
                revoked_at TEXT,
                merged_into INTEGER
            );

            CREATE TABLE IF NOT EXISTS member_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                token_sha256 TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                origin_member_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_member_tokens_member ON member_tokens(member_id);

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                received_at TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                device_id TEXT NOT NULL DEFAULT '',
                device_name TEXT
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
        # Idempotent migration for existing databases without device columns.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
        if "device_id" not in cols:
            conn.execute("ALTER TABLE reports ADD COLUMN device_id TEXT NOT NULL DEFAULT ''")
        if "device_name" not in cols:
            conn.execute("ALTER TABLE reports ADD COLUMN device_name TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_member_device_received "
            "ON reports(member_id, device_id, received_at)"
        )

        # Idempotent migration for members.merged_into and member_tokens backfill.
        member_cols = {row["name"] for row in conn.execute("PRAGMA table_info(members)").fetchall()}
        if "merged_into" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN merged_into INTEGER")
        conn.execute(
            """
            INSERT OR IGNORE INTO member_tokens (member_id, token_sha256, created_at, revoked_at)
            SELECT id, token_sha256, created_at, revoked_at
            FROM members
            """
        )
        # Idempotent migration: the member a token was issued to, kept across merges.
        token_cols = {row["name"] for row in conn.execute("PRAGMA table_info(member_tokens)").fetchall()}
        if "origin_member_id" not in token_cols:
            conn.execute("ALTER TABLE member_tokens ADD COLUMN origin_member_id INTEGER")
        conn.execute(
            """
            UPDATE member_tokens SET origin_member_id = COALESCE(
                (SELECT m.id FROM members m WHERE m.token_sha256 = member_tokens.token_sha256),
                member_id)
            WHERE origin_member_id IS NULL
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
        "INSERT INTO members (name, token_sha256, created_at, revoked_at, merged_into) VALUES (?, ?, ?, NULL, NULL)",
        (name, token_sha256, created_at),
    )
    member_id = cur.lastrowid
    cur.execute(
        "INSERT INTO member_tokens (member_id, token_sha256, created_at, revoked_at, origin_member_id) "
        "VALUES (?, ?, ?, NULL, ?)",
        (member_id, token_sha256, created_at, member_id),
    )
    conn.commit()
    return token, member_id


def get_member_by_token(conn: sqlite3.Connection, token: str) -> Optional[Dict]:
    """Look up an active owning member by raw bearer token."""
    token_sha256 = hash_token(token)
    return get_member_by_token_hash(conn, token_sha256)


def get_member_by_token_hash(conn: sqlite3.Connection, token_sha256: str) -> Optional[Dict]:
    """Look up an active owning member by an active token SHA-256."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.id, m.name, m.created_at, m.revoked_at, m.merged_into
        FROM member_tokens mt
        JOIN members m ON m.id = mt.member_id
        WHERE mt.token_sha256 = ?
          AND mt.revoked_at IS NULL
          AND m.revoked_at IS NULL
          AND m.merged_into IS NULL
        """,
        (token_sha256,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    return None


def get_member_by_name(conn: sqlite3.Connection, name: str) -> Optional[Dict]:
    """Look up a member by trimmed name."""
    clean = name.strip()
    if not clean:
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, created_at, revoked_at, merged_into FROM members WHERE name = ?",
        (clean,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    return None


def list_members(conn: sqlite3.Connection, include_merged: bool = True) -> List[Dict]:
    """List registered members in order of creation."""
    cur = conn.cursor()
    if include_merged:
        cur.execute(
            "SELECT id, name, created_at, revoked_at, merged_into FROM members ORDER BY id ASC"
        )
    else:
        cur.execute(
            "SELECT id, name, created_at, revoked_at, merged_into FROM members "
            "WHERE merged_into IS NULL ORDER BY id ASC"
        )
    return [dict(r) for r in cur.fetchall()]


def revoke_member(conn: sqlite3.Connection, name: str) -> bool:
    """Revoke a member and all of its active tokens by name. Returns True if revoked, False if already revoked.

    For a merged member, revokes the tokens issued to it that the merge moved to the target.
    """
    name = name.strip()
    cur = conn.cursor()
    cur.execute("SELECT id, revoked_at, merged_into FROM members WHERE name = ?", (name,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Member '{name}' not found.")

    if row["revoked_at"] is not None:
        if row["merged_into"] is None:
            return False
        cur.execute(
            "UPDATE member_tokens SET revoked_at = ? WHERE origin_member_id = ? AND revoked_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), row["id"]),
        )
        conn.commit()
        return cur.rowcount > 0

    revoked_at = datetime.now(timezone.utc).isoformat()
    cur.execute("UPDATE members SET revoked_at = ? WHERE id = ?", (revoked_at, row["id"]))
    cur.execute(
        "UPDATE member_tokens SET revoked_at = ? WHERE member_id = ? AND revoked_at IS NULL",
        (revoked_at, row["id"]),
    )
    conn.commit()
    return True


def rotate_member_token(conn: sqlite3.Connection, member_id: int) -> str:
    """Revoke all active tokens for a member and issue a new active token."""
    cur = conn.cursor()
    cur.execute("SELECT id, name, revoked_at, merged_into FROM members WHERE id = ?", (member_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Member ID {member_id} not found.")
    if row["merged_into"] is not None:
        raise ValueError(f"Member '{row['name']}' is merged and cannot rotate tokens.")
    if row["revoked_at"] is not None:
        raise ValueError(f"Member '{row['name']}' is revoked and cannot rotate tokens.")

    new_token = secrets.token_urlsafe(32)
    new_hash = hash_token(new_token)
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN")
        cur.execute(
            "UPDATE member_tokens SET revoked_at = ? WHERE member_id = ? AND revoked_at IS NULL",
            (now_iso, member_id),
        )
        cur.execute(
            "INSERT INTO member_tokens (member_id, token_sha256, created_at, revoked_at, origin_member_id) "
            "VALUES (?, ?, ?, NULL, ?)",
            (member_id, new_hash, now_iso, member_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return new_token


def list_member_tokens(conn: sqlite3.Connection, member_name: str) -> List[Dict]:
    """List token metadata (id, 8-char hash prefix, created_at, revoked_at) for a member."""
    clean = member_name.strip()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members WHERE name = ?", (clean,))
    m_row = cur.fetchone()
    if not m_row:
        raise ValueError(f"Member '{clean}' not found.")

    cur.execute(
        "SELECT id, member_id, token_sha256, created_at, revoked_at "
        "FROM member_tokens WHERE member_id = ? ORDER BY id ASC",
        (m_row["id"],),
    )
    return [
        {
            "id": r["id"],
            "member_id": r["member_id"],
            "token_prefix": r["token_sha256"][:8],
            "created_at": r["created_at"],
            "revoked_at": r["revoked_at"],
        }
        for r in cur.fetchall()
    ]


def legacy_device_id_for_token(conn: sqlite3.Connection, token_sha256: str, member_id: int) -> str:
    """Device id for a report from an old client (no ``device`` in the payload).

    A token that was moved here by ``merge_members`` still lists its original member in
    ``members.token_sha256``; its old-client reports go to ``legacy:<original member id>``
    (the same slot its pre-merge reports were moved to). Otherwise ``''``.
    """
    row = conn.execute("SELECT id FROM members WHERE token_sha256 = ?", (token_sha256,)).fetchone()
    if row is not None and row[0] != member_id:
        return f"legacy:{row[0]}"
    return ""


def merge_members(conn: sqlite3.Connection, from_id: int, into_id: int) -> Dict[str, int]:
    """Merge FROM member's active tokens and reports into INTO member in one transaction."""
    if from_id == into_id:
        raise ValueError("Cannot merge a member into itself.")

    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        else:
            # Acquire a write lock before reading even in a caller's transaction.
            conn.execute("UPDATE members SET id = id WHERE 0")
        cur = conn.cursor()
        cur.execute("SELECT id, name, revoked_at, merged_into FROM members WHERE id = ?", (from_id,))
        from_row = cur.fetchone()
        if not from_row:
            raise ValueError(f"Source member ID {from_id} not found.")

        cur.execute("SELECT id, name, revoked_at, merged_into FROM members WHERE id = ?", (into_id,))
        into_row = cur.fetchone()
        if not into_row:
            raise ValueError(f"Target member ID {into_id} not found.")

        if from_row["merged_into"] is not None:
            raise ValueError(f"Member '{from_row['name']}' is already merged.")
        if from_row["revoked_at"] is not None:
            raise ValueError(f"Member '{from_row['name']}' is already revoked.")
        if into_row["merged_into"] is not None:
            raise ValueError(f"Target member '{into_row['name']}' is already merged.")
        if into_row["revoked_at"] is not None:
            raise ValueError(f"Target member '{into_row['name']}' is already revoked.")
        now_iso = datetime.now(timezone.utc).isoformat()
        legacy_dev_id = f"legacy:{from_id}"

        cur.execute(
            "UPDATE member_tokens SET member_id = ? WHERE member_id = ? AND revoked_at IS NULL",
            (into_id, from_id),
        )
        tokens_moved = cur.rowcount

        cur.execute(
            "UPDATE reports SET member_id = ?, device_id = ? WHERE member_id = ? AND device_id = ''",
            (into_id, legacy_dev_id, from_id),
        )
        legacy_moved = cur.rowcount

        cur.execute(
            "UPDATE reports SET member_id = ? WHERE member_id = ? AND device_id != ''",
            (into_id, from_id),
        )
        tagged_moved = cur.rowcount

        cur.execute(
            "UPDATE members SET merged_into = ?, revoked_at = ? WHERE id = ?",
            (into_id, now_iso, from_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "tokens_moved": tokens_moved,
        "reports_moved": legacy_moved + tagged_moved,
    }


def insert_report(
    conn: sqlite3.Connection,
    member_id: int,
    generated_at: str,
    payload_json: str,
    received_at: Optional[str] = None,
    device_id: str = "",
    device_name: Optional[str] = None,
) -> int:
    """Insert a report record."""
    if received_at is None:
        received_at = datetime.now(timezone.utc).isoformat()

    dev_id = device_id or ""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reports (member_id, received_at, generated_at, payload_json, device_id, device_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (member_id, received_at, generated_at, payload_json, dev_id, device_name),
    )
    report_id = cur.lastrowid
    conn.commit()
    return report_id


def get_member_latest_report(conn: sqlite3.Connection, member_id: int) -> Optional[Dict]:
    """Fetch the latest report for a given member."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, member_id, received_at, generated_at, payload_json, device_id, device_name "
        "FROM reports WHERE member_id = ? ORDER BY received_at DESC, id DESC LIMIT 1",
        (member_id,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    return None


def get_member_latest_reports_by_device(conn: sqlite3.Connection, member_id: int) -> List[Dict]:
    """Fetch the latest report for each distinct device_id of a member."""
    cur = conn.cursor()
    cur.execute(
        "SELECT r.id, r.member_id, r.received_at, r.generated_at, r.payload_json, r.device_id, r.device_name "
        "FROM reports r "
        "WHERE r.id IN ("
        "    SELECT (SELECT r2.id FROM reports r2 "
        "            WHERE r2.member_id = ? AND r2.device_id = devices.device_id "
        "            ORDER BY r2.received_at DESC, r2.id DESC LIMIT 1) "
        "    FROM (SELECT DISTINCT device_id FROM reports WHERE member_id = ?) AS devices"
        ") "
        "ORDER BY r.received_at DESC, r.id DESC",
        (member_id, member_id),
    )
    return [dict(r) for r in cur.fetchall()]


def get_all_latest_reports(conn: sqlite3.Connection) -> List[Dict]:
    """Fetch the latest report for all non-merged members."""
    members = list_members(conn, include_merged=False)
    result = []
    for m in members:
        rep = get_member_latest_report(conn, m["id"])
        result.append({"member": m, "report": rep})
    return result


def get_all_latest_device_reports(conn: sqlite3.Connection) -> List[Dict]:
    """Fetch the latest report per device for all non-merged members."""
    members = list_members(conn, include_merged=False)
    return [
        {"member": m, "reports": get_member_latest_reports_by_device(conn, m["id"])}
        for m in members
    ]


def list_member_devices(conn: sqlite3.Connection, member_name: str) -> List[Dict]:
    """List distinct devices (with latest report info and report count) for a member."""
    name = member_name.strip()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members WHERE name = ?", (name,))
    m_row = cur.fetchone()
    if not m_row:
        raise ValueError(f"Member '{name}' not found.")
    member_id = m_row["id"]

    cur.execute(
        "SELECT device_id, COUNT(*) AS report_count "
        "FROM reports WHERE member_id = ? GROUP BY device_id",
        (member_id,),
    )
    counts = {row["device_id"]: row["report_count"] for row in cur.fetchall()}

    latest = get_member_latest_reports_by_device(conn, member_id)
    for rep in latest:
        rep["report_count"] = counts.get(rep["device_id"], 1)
    return latest


def remove_member_device(conn: sqlite3.Connection, member_name: str, device_id: str) -> int:
    """Remove all reports for a specific device of a member. Returns deleted row count."""
    name = member_name.strip()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members WHERE name = ?", (name,))
    m_row = cur.fetchone()
    if not m_row:
        raise ValueError(f"Member '{name}' not found.")
    member_id = m_row["id"]

    cur.execute(
        "DELETE FROM reports WHERE member_id = ? AND device_id = ?",
        (member_id, device_id),
    )
    deleted = cur.rowcount
    conn.commit()
    return deleted


def prune_reports(conn: sqlite3.Connection, now: Optional[datetime] = None) -> int:
    """Prune reports according to per-(member_id, device_id) retention policy:
    - Latest report per (member_id, device_id) is always kept.
    - Last report per (member_id, device_id) per day is kept for up to 90 days.
    - Intermediate reports on the same day for the same device are deleted.
    - Reports older than 90 days (not being the latest for that device) are deleted.
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
            "SELECT id, device_id, received_at FROM reports WHERE member_id = ? "
            "ORDER BY received_at ASC, id ASC",
            (member_id,),
        )
        reports = cur.fetchall()
        if not reports:
            continue

        by_device: Dict[str, List] = {}
        for r in reports:
            by_device.setdefault(r["device_id"] or "", []).append(r)

        keep_ids = set()
        for dev_reports in by_device.values():
            # 1. Overall latest report for this (member_id, device_id)
            keep_ids.add(dev_reports[-1]["id"])

            # 2. Last report per day within 90 days for this device
            day_groups: Dict[str, List[int]] = {}
            for r in dev_reports:
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
