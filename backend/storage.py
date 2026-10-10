"""SQLite persistence used by the GeoIntelligence Hub bridge."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


BASE_DIR = Path(__file__).resolve().parent


def _database_path():
    configured = os.getenv("DATABASE_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else BASE_DIR / path

    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("sqlite:///"):
        configured = url[10:]
        path = Path(configured)
        return path if path.is_absolute() else BASE_DIR / path
    return BASE_DIR / "geointelligence.db"


DATABASE_PATH = _database_path()


def _now():
    return time.time()


def _new_id():
    return str(uuid.uuid4())


@contextmanager
def connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn, table, name, definition):
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    """Create or safely extend the local schema without dropping existing data."""
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL DEFAULT '',
                google_id TEXT UNIQUE,
                password_hash TEXT,
                legacy_password_hash TEXT,
                avatar_url TEXT,
                institution TEXT,
                role TEXT NOT NULL DEFAULT 'researcher',
                is_active INTEGER NOT NULL DEFAULT 1,
                setup_step INTEGER NOT NULL DEFAULT 0,
                cloud_project_id TEXT,
                created_at REAL,
                updated_at REAL,
                last_login REAL
            );

            CREATE TABLE IF NOT EXISTS ee_connections (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                google_project_id TEXT NOT NULL,
                ee_access_token TEXT,
                ee_refresh_token TEXT,
                token_expires_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 0,
                oauth_connected INTEGER NOT NULL DEFAULT 0,
                ee_authenticated INTEGER NOT NULL DEFAULT 0,
                ee_available INTEGER NOT NULL DEFAULT 0,
                analysis_available INTEGER NOT NULL DEFAULT 0,
                google_subject TEXT,
                google_email TEXT,
                last_error TEXT,
                verified_at REAL,
                created_at REAL,
                updated_at REAL,
                UNIQUE(user_id, google_project_id)
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at REAL,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS study_areas (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                geojson TEXT NOT NULL,
                area_hectares REAL,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS analysis_jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                study_area_id TEXT REFERENCES study_areas(id) ON DELETE SET NULL,
                analysis_type TEXT NOT NULL,
                parameters TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                started_at REAL,
                completed_at REAL,
                ee_task_id TEXT,
                error_message TEXT,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS analysis_results (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                stats TEXT NOT NULL DEFAULT '{}',
                tile_url TEXT,
                geotiff_url TEXT,
                geojson_url TEXT,
                interpretation TEXT,
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                default_zoom REAL NOT NULL DEFAULT 13,
                default_center_lat REAL NOT NULL DEFAULT -6.7736,
                default_center_lng REAL NOT NULL DEFAULT 39.2230,
                preferred_basemap TEXT NOT NULL DEFAULT 'osm',
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at REAL NOT NULL,
                revoked_at REAL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS oauth_states (
                state_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS exports (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                job_id TEXT REFERENCES analysis_jobs(id) ON DELETE SET NULL,
                analysis_type TEXT NOT NULL DEFAULT '',
                format TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                parameters TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                download_url TEXT,
                file_path TEXT,
                ee_task_id TEXT,
                error_message TEXT,
                created_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_exports_user ON exports(user_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_ee_connections_user ON ee_connections(user_id);
            CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_jobs_user ON analysis_jobs(user_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_results_user ON analysis_results(user_id);
            """
        )

        # The checked-in database was created by an older SQLAlchemy prototype.
        # Extend its tables in place instead of deleting or recreating them.
        for name, definition in (
            ("password_hash", "TEXT"),
            ("legacy_password_hash", "TEXT"),
            ("setup_step", "INTEGER NOT NULL DEFAULT 0"),
            ("cloud_project_id", "TEXT"),
        ):
            _ensure_column(conn, "users", name, definition)

        for name, definition in (
            ("oauth_connected", "INTEGER NOT NULL DEFAULT 0"),
            ("ee_authenticated", "INTEGER NOT NULL DEFAULT 0"),
            ("ee_available", "INTEGER NOT NULL DEFAULT 0"),
            ("analysis_available", "INTEGER NOT NULL DEFAULT 0"),
            ("google_subject", "TEXT"),
            ("google_email", "TEXT"),
            ("last_error", "TEXT"),
            ("updated_at", "REAL"),
        ):
            _ensure_column(conn, "ee_connections", name, definition)

        for name, definition in (
            ("created_at", "REAL"),
            ("updated_at", "REAL"),
        ):
            _ensure_column(conn, "projects", name, definition)

        conn.execute("UPDATE users SET is_active = 1 WHERE is_active IS NULL")
        conn.execute("UPDATE users SET role = 'researcher' WHERE role IS NULL OR role = ''")
        conn.execute("UPDATE users SET setup_step = 0 WHERE setup_step IS NULL")
        conn.execute("UPDATE projects SET status = 'draft' WHERE status IS NULL OR status = ''")


def migrate_legacy_users(users_file):
    """Import legacy JSON identities while leaving the source file untouched."""
    try:
        with open(users_file, "r", encoding="utf-8") as handle:
            legacy = json.load(handle)
    except (OSError, ValueError):
        return

    if not isinstance(legacy, dict):
        return

    with connection() as conn:
        for raw_email, info in legacy.items():
            if not isinstance(info, dict):
                continue
            email = str(raw_email).strip().lower()
            if not email:
                continue
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE users SET cloud_project_id = COALESCE(cloud_project_id, ?), "
                    "full_name = CASE WHEN full_name = '' THEN ? ELSE full_name END, "
                    "updated_at = ? WHERE id = ?",
                    (info.get("projectId"), info.get("name", ""), _now(), existing[0]),
                )
                continue

            conn.execute(
                "INSERT INTO users (id, email, full_name, legacy_password_hash, setup_step, "
                "cloud_project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _new_id(), email, info.get("name", ""), info.get("password"),
                    min(int(info.get("setupStep", 0) or 0), 4), info.get("projectId"),
                    info.get("createdAt", _now()), _now(),
                ),
            )


def get_user(email):
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_session(user_id, ttl_seconds):
    token = secrets.token_urlsafe(32)
    now = _now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (_new_id(), user_id, hashlib.sha256(token.encode()).hexdigest(), now + ttl_seconds, now),
        )
    return token


def session_user_id(token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = _now()
    with connection() as conn:
        row = conn.execute(
            "SELECT s.user_id FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ? AND COALESCE(u.is_active, 1) = 1",
            (token_hash, now),
        ).fetchone()
        return row[0] if row else None


def revoke_session(token):
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connection() as conn:
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ?", (_now(), token_hash))


def revoke_user_sessions(user_id):
    with connection() as conn:
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (_now(), user_id))


def hash_password(password):
    iterations = 310000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password, stored, legacy=None):
    if stored and stored.startswith("pbkdf2_sha256$"):
        try:
            _, raw_iterations, raw_salt, raw_digest = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), base64.urlsafe_b64decode(raw_salt), int(raw_iterations)
            )
            return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), raw_digest)
        except (TypeError, ValueError):
            return False
    legacy_hash = legacy or stored
    return bool(legacy_hash) and hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), legacy_hash)


def encryption_key():
    configured = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not configured:
        configured = os.getenv("SESSION_SECRET", "").strip()
    if not configured:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    try:
        Fernet(configured.encode())
        return configured.encode()
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(configured.encode()).digest())


def seal(value):
    if value is None:
        return None
    return Fernet(encryption_key()).encrypt(value.encode()).decode()


def unseal(value):
    if not value:
        return None
    try:
        return Fernet(encryption_key()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None
