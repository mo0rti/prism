"""Durable local state for the connected Prism board service.

The wiki remains authoritative.  This module stores only grants, previews,
operation receipts, and the last change cursor in a small SQLite journal.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat
import threading
from typing import Iterator
from urllib.parse import quote

from prism_cli.fs_safety import CloudSyncPathError, reparse_kind


class BoardLockError(RuntimeError):
    """The workspace is already served by another process."""


class BoardStore:
    """One process-held lock and a serialized SQLite journal."""

    def __init__(self, root: Path, *, process_lock: bool = False) -> None:
        self.root = root
        self.state_dir = root / ".prism" / "state"
        self.db_path = self.state_dir / "board.sqlite3"
        self.lock_path = self.state_dir / "board.lock"
        self._thread_lock = threading.RLock()
        self._lock_stream = None
        self.process_locked = process_lock
        self._connection: sqlite3.Connection | None = None
        self._prepare_state_path()
        try:
            if process_lock:
                self._acquire_process_lock()
            self._check_sqlite_paths()
            self._connection = sqlite3.connect(
                self.db_path,
                timeout=5,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._check_sqlite_paths()
            self._initialize()
        except Exception:
            self.close()
            raise

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Board store is closed.")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._thread_lock:
            connection = self.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Serialize a read through execute and complete cursor consumption.

        Python 3.12/3.13 can return inconsistent rows when one SQLite
        connection is used concurrently, even when SQLite itself is in
        serialized mode. Callers must consume every cursor inside this
        context; the same lock is used by transaction writes.
        """

        with self._thread_lock:
            yield self.connection

    def close(self) -> None:
        with self._thread_lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            stream, self._lock_stream = self._lock_stream, None
            if stream is not None:
                _release_lock_stream(stream)

    def _prepare_state_path(self) -> None:
        prism_dir = self.root / ".prism"
        for path in (prism_dir, self.state_dir):
            if path.exists():
                self._require_plain_directory(path)
            else:
                path.mkdir()
                self._require_plain_directory(path)
        if self.db_path.exists():
            self._require_plain_file(self.db_path)
        if self.lock_path.exists():
            self._require_plain_file(self.lock_path)

    def _acquire_process_lock(self) -> None:
        self._lock_stream = _acquire_lock_stream(self.lock_path)

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS grants (
                    participant_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('human', 'agent')),
                    writable INTEGER NOT NULL CHECK (writable IN (0, 1)),
                    active INTEGER NOT NULL CHECK (active IN (0, 1)),
                    board_id TEXT NOT NULL,
                    workflow_version TEXT NOT NULL,
                    asset_digest TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS previews (
                    preview_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL REFERENCES grants(participant_id),
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consumed_by TEXT
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL REFERENCES grants(participant_id),
                    preview_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    receipt_json TEXT,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT,
                    participant_id TEXT,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            COMMIT;
            """
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(grants)")}
        if "asset_digest" not in columns:
            self.connection.execute("ALTER TABLE grants ADD COLUMN asset_digest TEXT NOT NULL DEFAULT ''")

    def _check_sqlite_paths(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(str(self.db_path) + suffix)
            if path.exists():
                self._require_plain_file(path)

    @staticmethod
    def _require_plain_directory(path: Path) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ValueError(f"Unable to inspect Prism state path: {path.name}.") from exc
        if reparse_kind(info) == "cloud":
            raise CloudSyncPathError()
        if not stat.S_ISDIR(info.st_mode) or BoardStore._is_reparse_point(info):
            raise ValueError(f"Prism state path must be a real directory: {path.name}.")

    @staticmethod
    def _require_plain_file(path: Path) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ValueError(f"Unable to inspect Prism state file: {path.name}.") from exc
        if reparse_kind(info) == "cloud":
            raise CloudSyncPathError()
        if not stat.S_ISREG(info.st_mode) or BoardStore._is_reparse_point(info):
            raise ValueError(f"Prism state file must be a regular file: {path.name}.")

    @staticmethod
    def _is_reparse_point(info: os.stat_result) -> bool:
        return reparse_kind(info) != "none"


@contextmanager
def workspace_process_lock(root: Path, *, create: bool) -> Iterator[Path | None]:
    """Hold the board's process lock without opening or creating its database.

    When ``create`` is false and runtime state does not exist, this context is
    a no-op. Explicit updates to an already pinned workspace pass ``create``
    so a server and installer serialize on the same lock even before the
    first grant has created SQLite state.
    """

    root = Path(root)
    prism_dir = root / ".prism"
    state_dir = prism_dir / "state"
    lock_path = state_dir / "board.lock"
    for path in (prism_dir, state_dir):
        if _inspect_directory(path):
            continue
        if not create:
            yield None
            return
        try:
            path.mkdir()
        except FileExistsError:
            # A concurrent creator may have made this directory between lstat
            # and mkdir; verify it before trusting the resulting path.
            pass
        _require_plain_directory(path)
    stream = _acquire_lock_stream(lock_path)
    try:
        yield lock_path
    finally:
        _release_lock_stream(stream)


def unresolved_board_operations(root: Path) -> list[tuple[str, str]]:
    """Read non-applied journal rows without initializing runtime state."""

    prism_dir = Path(root) / ".prism"
    state_dir = prism_dir / "state"
    if not _inspect_directory(prism_dir):
        return []
    try:
        if not _inspect_directory(state_dir):
            return []
    except ValueError:
        raise
    database = state_dir / "board.sqlite3"
    try:
        info = database.lstat()
    except FileNotFoundError:
        return []
    if reparse_kind(info) == "cloud":
        raise CloudSyncPathError()
    if not stat.S_ISREG(info.st_mode) or _is_reparse_point(info):
        raise ValueError("Prism board journal must be a regular file before workflow upgrade.")

    uri_path = quote(str(database.resolve(strict=True)).replace("\\", "/"), safe="/:")
    try:
        connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, timeout=1)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if "operations" not in tables:
                raise ValueError("Prism board journal has no operations table; workflow upgrade is unsafe until it is repaired.")
            rows = connection.execute(
                "SELECT operation_id, state FROM operations WHERE state IS NULL OR state <> 'applied' ORDER BY created_at, operation_id"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"Unable to inspect the Prism board journal before workflow upgrade: {exc}") from exc
    return [(str(operation_id), str(state) if state is not None else "unknown") for operation_id, state in rows]


def count_active_grants(root: Path, identity: tuple[str, str, str] | None = None) -> tuple[int, int] | None:
    """Count active grants without creating or initializing runtime state.

    Returns ``None`` when the workspace has no board journal yet. Otherwise it
    returns ``(active, current)``: every non-revoked grant, and the subset
    issued for ``identity`` (board ID, workflow version, asset digest). Without
    an identity ``current`` equals ``active``. The journal is opened read-only
    and no token or token hash is read.
    """

    prism_dir = Path(root) / ".prism"
    state_dir = prism_dir / "state"
    if not _inspect_directory(prism_dir) or not _inspect_directory(state_dir):
        return None
    database = state_dir / "board.sqlite3"
    try:
        info = database.lstat()
    except FileNotFoundError:
        return None
    if reparse_kind(info) == "cloud":
        raise CloudSyncPathError()
    if not stat.S_ISREG(info.st_mode) or _is_reparse_point(info):
        raise ValueError("Prism board journal must be a regular file.")

    uri_path = quote(str(database.resolve(strict=True)).replace("\\", "/"), safe="/:")
    try:
        connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, timeout=1)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "grants" not in tables:
                return 0, 0
            active = connection.execute("SELECT COUNT(*) FROM grants WHERE active = 1").fetchone()[0]
            if identity is None:
                return int(active), int(active)
            current = connection.execute(
                "SELECT COUNT(*) FROM grants WHERE active = 1 AND board_id = ? AND workflow_version = ? AND asset_digest = ?",
                identity,
            ).fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"Unable to read the Prism board journal: {exc}") from exc
    return int(active), int(current)


def _inspect_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError(f"Unable to inspect Prism runtime directory {path.name}: {exc}") from exc
    if reparse_kind(info) == "cloud":
        raise CloudSyncPathError()
    if not stat.S_ISDIR(info.st_mode) or _is_reparse_point(info):
        raise ValueError(f"Prism runtime path must be a real directory: {path.name}.")
    return True


def _require_plain_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError(f"Unable to inspect Prism runtime file {path.name}: {exc}") from exc
    if reparse_kind(info) == "cloud":
        raise CloudSyncPathError()
    if not stat.S_ISREG(info.st_mode) or _is_reparse_point(info):
        raise ValueError(f"Prism runtime file must be a regular file: {path.name}.")


def _is_reparse_point(info: os.stat_result) -> bool:
    return reparse_kind(info) != "none"


def _acquire_lock_stream(lock_path: Path):
    _require_plain_file(lock_path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise BoardLockError("Unable to open the workspace process lock safely.") from exc
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    try:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or _is_reparse_point(info):
            raise BoardLockError("The workspace process lock is not a regular file.")
        if info.st_size == 0:
            stream.write(b"\0")
            stream.flush()
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BoardLockError("Another Prism board service or workflow upgrade already holds this workspace lock.") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BoardLockError("Another Prism board service or workflow upgrade already holds this workspace lock.") from exc
    except Exception:
        stream.close()
        raise
    return stream


def _release_lock_stream(stream) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass
    try:
        stream.close()
    except OSError:
        pass


def _require_plain_directory(path: Path) -> None:
    if not _inspect_directory(path):
        raise ValueError(f"Prism runtime directory is unavailable: {path.name}.")
