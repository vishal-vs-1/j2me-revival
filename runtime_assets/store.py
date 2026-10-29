"""Per-game durable recipes, sources, deduplicated jobs, and recoverable leases."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import sqlite3
import time
import uuid

from runtime_assets.contracts import Recipe, SourceRecord

SCHEMA_VERSION = 1
STATES = frozenset({"QUEUED", "RUNNING", "DEFERRED", "READY", "FAILED"})


@dataclass(frozen=True)
class JobLease:
    source_id: str
    recipe_key: str
    owner: str
    token: str
    expires_at: float
    attempts: int


@dataclass(frozen=True)
class JobRecord:
    source_id: str
    recipe_key: str
    state: str
    priority: int
    attempts: int
    next_attempt_at: float | None
    relative_output: str | None
    error: str | None


class AssetStore:
    """Short, atomic SQLite transactions. Expensive file/model work stays outside."""

    def __init__(self, workspace: Path, *, busy_timeout_ms: int = 3000):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.database = self.workspace / "asset-cache.sqlite"
        self.busy_timeout_ms = max(100, min(int(busy_timeout_ms), 30000))
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=self.busy_timeout_ms / 1000,
                             isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return db

    @contextmanager
    def _read(self):
        """Yield a short-lived read connection and always close it."""
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        """Run one short write transaction and close its connection."""
        db = self._connect()
        begun = False
        try:
            db.execute("BEGIN IMMEDIATE")
            begun = True
            yield db
            db.commit()
        except BaseException:
            if begun:
                db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self):
        with self._read() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"Asset database version {version} is newer than this application")
            if version == 0:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE recipes (
                      recipe_key TEXT PRIMARY KEY,
                      canonical_json TEXT NOT NULL
                    );
                    CREATE TABLE sources (
                      source_id TEXT PRIMARY KEY,
                      width INTEGER NOT NULL CHECK(width > 0),
                      height INTEGER NOT NULL CHECK(height > 0),
                      relative_path TEXT NOT NULL,
                      origin TEXT NOT NULL,
                      created_at REAL NOT NULL
                    );
                    CREATE TABLE jobs (
                      source_id TEXT NOT NULL REFERENCES sources(source_id),
                      recipe_key TEXT NOT NULL REFERENCES recipes(recipe_key),
                      state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','DEFERRED','READY','FAILED')),
                      priority INTEGER NOT NULL DEFAULT 0,
                      attempts INTEGER NOT NULL DEFAULT 0,
                      next_attempt_at REAL,
                      lease_owner TEXT,
                      lease_token TEXT,
                      lease_until REAL,
                      relative_output TEXT,
                      error TEXT,
                      updated_at REAL NOT NULL,
                      PRIMARY KEY(source_id, recipe_key)
                    );
                    CREATE INDEX jobs_schedule ON jobs(state, priority DESC, updated_at);
                    CREATE INDEX jobs_lease_expiry ON jobs(state, lease_until);
                    CREATE TABLE consumed_events (
                      event_id TEXT PRIMARY KEY,
                      consumed_at REAL NOT NULL
                    );
                    PRAGMA user_version=1;
                    COMMIT;
                """)

    def _write(self):
        """Open a fresh connection and begin a short writer-serialized transaction."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    def _relative_path(value: str) -> str:
        if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
            raise ValueError("Asset path must be a relative POSIX path")
        path = PurePosixPath(value)
        if (path.is_absolute() or not path.parts or
                any(part in (".", "..") or ":" in part for part in path.parts)):
            raise ValueError("Asset path must remain inside its game workspace")
        return path.as_posix()

    def resolve_path(self, relative_path: str) -> Path:
        relative = self._relative_path(relative_path)
        target = (self.workspace / Path(*PurePosixPath(relative).parts)).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as error:
            raise ValueError("Asset path escapes its game workspace") from error
        return target

    @staticmethod
    def _verify_recipe_row(db, recipe: Recipe):
        row = db.execute("SELECT canonical_json FROM recipes WHERE recipe_key=?", (recipe.key,)).fetchone()
        if row is not None and row["canonical_json"] != recipe.canonical_json():
            raise RuntimeError("Recipe hash collision or corrupt recipe row")

    def register_recipe(self, recipe: Recipe) -> str:
        if not isinstance(recipe, Recipe):
            raise TypeError("Expected an immutable Recipe")
        db = self._write()
        try:
            self._verify_recipe_row(db, recipe)
            db.execute("INSERT OR IGNORE INTO recipes(recipe_key,canonical_json) VALUES (?,?)",
                       (recipe.key, recipe.canonical_json()))
            db.commit()
            return recipe.key
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def recipe_json(self, recipe_key: str) -> str | None:
        with self._read() as db:
            row = db.execute("SELECT canonical_json FROM recipes WHERE recipe_key=?", (recipe_key,)).fetchone()
            if row is None:
                return None
            recipe = Recipe.from_json(row["canonical_json"])
            if recipe.key != recipe_key:
                raise RuntimeError("Stored recipe key does not match its contents")
            return recipe.canonical_json()

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self._read() as db:
            row = db.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
            if row is None:
                return None
            return SourceRecord(row["source_id"], row["width"], row["height"],
                                row["relative_path"], row["origin"])

    def list_sources(self) -> list[SourceRecord]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM sources ORDER BY source_id").fetchall()
            return [SourceRecord(row["source_id"], row["width"], row["height"],
                                 row["relative_path"], row["origin"]) for row in rows]

    def register_source(self, source: SourceRecord, *, now: float | None = None):
        if not isinstance(source, SourceRecord):
            raise TypeError("Expected a validated SourceRecord")
        relative = self._relative_path(source.relative_path)
        timestamp = time.time() if now is None else float(now)
        db = self._write()
        try:
            current = db.execute("SELECT width,height,relative_path FROM sources WHERE source_id=?",
                                 (source.source_id,)).fetchone()
            if current is not None and (current["width"], current["height"]) != (
                    source.width, source.height):
                raise ValueError("A source ID was registered with conflicting dimensions")
            db.execute("""INSERT OR IGNORE INTO sources
                       (source_id,width,height,relative_path,origin,created_at)
                       VALUES (?,?,?,?,?,?)""",
                       (source.source_id, source.width, source.height, relative, source.origin, timestamp))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _enqueue_in_transaction(self, db, source_id, recipe_key, priority, timestamp, force):
        if db.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone() is None:
            raise KeyError("Register the source before queuing its enhancement")
        if db.execute("SELECT 1 FROM recipes WHERE recipe_key=?", (recipe_key,)).fetchone() is None:
            raise KeyError("Register the recipe before queuing its enhancement")
        current = db.execute("SELECT state,priority FROM jobs WHERE source_id=? AND recipe_key=?",
                             (source_id, recipe_key)).fetchone()
        if current is None:
            db.execute("""INSERT INTO jobs(source_id,recipe_key,state,priority,updated_at)
                       VALUES (?,?,'QUEUED',?,?)""", (source_id, recipe_key, int(priority), timestamp))
            return True
        state = current["state"]
        if state == "QUEUED":
            if int(priority) > current["priority"]:
                db.execute("UPDATE jobs SET priority=?,updated_at=? WHERE source_id=? AND recipe_key=?",
                           (int(priority), timestamp, source_id, recipe_key))
            return False
        if state == "RUNNING":
            return False
        if state in ("READY", "DEFERRED") and not force:
            return False
        db.execute("""UPDATE jobs SET state='QUEUED', priority=max(priority,?),
                   next_attempt_at=NULL, lease_owner=NULL, lease_token=NULL, lease_until=NULL,
                   relative_output=NULL, error=NULL, updated_at=?
                   WHERE source_id=? AND recipe_key=?""",
                   (int(priority), timestamp, source_id, recipe_key))
        return True

    def enqueue(self, source_id: str, recipe_key: str, priority: int = 0,
                *, now: float | None = None, force: bool = False) -> bool:
        timestamp = time.time() if now is None else float(now)
        db = self._write()
        try:
            changed = self._enqueue_in_transaction(db, source_id, recipe_key, priority, timestamp, force)
            db.commit()
            return changed
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register_capture_event(self, event_id: str, source: SourceRecord, recipe: Recipe,
                               priority: int = 0, *, now: float | None = None) -> bool:
        """Atomically register a source/job and consume its event exactly once."""
        if not event_id or len(event_id) > 200 or "\x00" in event_id:
            raise ValueError("Invalid capture event ID")
        timestamp = time.time() if now is None else float(now)
        relative = self._relative_path(source.relative_path)
        db = self._write()
        try:
            seen = db.execute("SELECT 1 FROM consumed_events WHERE event_id=?", (event_id,)).fetchone()
            if seen is not None:
                db.commit()
                return False
            self._verify_recipe_row(db, recipe)
            db.execute("INSERT OR IGNORE INTO recipes(recipe_key,canonical_json) VALUES (?,?)",
                       (recipe.key, recipe.canonical_json()))
            current = db.execute("SELECT width,height,relative_path FROM sources WHERE source_id=?",
                                 (source.source_id,)).fetchone()
            if current is not None and (current["width"], current["height"]) != (
                    source.width, source.height):
                raise ValueError("A source ID was registered with conflicting dimensions")
            db.execute("""INSERT OR IGNORE INTO sources
                       (source_id,width,height,relative_path,origin,created_at)
                       VALUES (?,?,?,?,?,?)""",
                       (source.source_id, source.width, source.height, relative, source.origin, timestamp))
            added = self._enqueue_in_transaction(db, source.source_id, recipe.key, priority, timestamp, False)
            db.execute("INSERT INTO consumed_events(event_id,consumed_at) VALUES (?,?)", (event_id, timestamp))
            db.commit()
            return added
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def consume_event_once(self, event_id: str, *, now: float | None = None) -> bool:
        """Small primitive for non-source events; source registration should use register_capture_event."""
        if not event_id or len(event_id) > 200:
            raise ValueError("Invalid event ID")
        timestamp = time.time() if now is None else float(now)
        with self._transaction() as db:
            cursor = db.execute("INSERT OR IGNORE INTO consumed_events(event_id,consumed_at) VALUES (?,?)",
                                (event_id, timestamp))
            return cursor.rowcount == 1

    def mark_imported_ready(self, source_id: str, recipe_key: str, relative_output: str,
                            *, now: float | None = None) -> bool:
        """Adopt a separately validated legacy file; never supersede a live worker lease."""
        relative = self._relative_path(relative_output)
        timestamp = time.time() if now is None else float(now)
        if not self.resolve_path(relative).is_file():
            raise FileNotFoundError(relative)
        db = self._write()
        try:
            self._enqueue_in_transaction(db, source_id, recipe_key, 0, timestamp, False)
            cursor = db.execute("""UPDATE jobs SET state='READY',next_attempt_at=NULL,
                       lease_owner=NULL,lease_token=NULL,lease_until=NULL,relative_output=?,
                       error=NULL,updated_at=?
                       WHERE source_id=? AND recipe_key=? AND state!='RUNNING'""",
                                (relative, timestamp, source_id, recipe_key))
            db.commit()
            return cursor.rowcount == 1
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get_job(self, source_id: str, recipe_key: str) -> JobRecord | None:
        with self._read() as db:
            row = db.execute("SELECT * FROM jobs WHERE source_id=? AND recipe_key=?",
                             (source_id, recipe_key)).fetchone()
            if row is None:
                return None
            return JobRecord(row["source_id"], row["recipe_key"], row["state"], row["priority"],
                             row["attempts"], row["next_attempt_at"], row["relative_output"], row["error"])

    def list_ready(self, recipe_key: str) -> list[JobRecord]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM jobs WHERE recipe_key=? AND state='READY' ORDER BY source_id",
                              (recipe_key,)).fetchall()
            return [JobRecord(row["source_id"], row["recipe_key"], row["state"],
                              row["priority"], row["attempts"], row["next_attempt_at"],
                              row["relative_output"], row["error"]) for row in rows]

    def counts(self, recipe_key: str | None = None) -> dict[str, int]:
        with self._read() as db:
            if recipe_key is None:
                rows = db.execute("SELECT state,count(*) AS amount FROM jobs GROUP BY state").fetchall()
            else:
                rows = db.execute("SELECT state,count(*) AS amount FROM jobs WHERE recipe_key=? GROUP BY state",
                                  (recipe_key,)).fetchall()
            result = {state: 0 for state in STATES}
            result.update({row["state"]: row["amount"] for row in rows})
            result["sources"] = db.execute("SELECT count(*) FROM sources").fetchone()[0]
            return result

    def invalidate_ready(self, source_id: str, recipe_key: str, *, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET state='QUEUED',relative_output=NULL,error=NULL,
                               updated_at=? WHERE source_id=? AND recipe_key=? AND state='READY'""",
                                (timestamp, source_id, recipe_key))
            return cursor.rowcount == 1

    def recover_expired(self, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else float(now)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET state='QUEUED',lease_owner=NULL,lease_token=NULL,
                               lease_until=NULL,next_attempt_at=NULL,error='Recovered expired worker lease',
                               updated_at=? WHERE state='RUNNING' AND lease_until<=?""",
                                (timestamp, timestamp))
            recovered = cursor.rowcount
            db.execute("""UPDATE jobs SET state='QUEUED',next_attempt_at=NULL,updated_at=?
                       WHERE state='FAILED' AND next_attempt_at IS NOT NULL AND next_attempt_at<=?""",
                       (timestamp, timestamp))
            return recovered

    def claim(self, owner: str, *, now: float | None = None, lease_seconds: float = 60.0,
              recipe_key: str | None = None) -> JobLease | None:
        leases = self.claim_batch(owner, now=now, lease_seconds=lease_seconds,
                                  recipe_key=recipe_key, max_count=1)
        return leases[0] if leases else None

    def claim_batch(self, owner: str, *, now: float | None = None,
                    lease_seconds: float = 60.0, recipe_key: str | None = None,
                    max_count: int = 16, max_pixels: int | None = None) -> list[JobLease]:
        """Atomically lease a bounded group; skipped jobs retain state and attempt count."""
        if not owner or len(owner) > 128:
            raise ValueError("Worker owner must be a short non-empty ID")
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        if isinstance(max_count, bool) or not isinstance(max_count, int) or not 1 <= max_count <= 512:
            raise ValueError("Batch count must be between 1 and 512")
        if max_pixels is not None and (isinstance(max_pixels, bool) or
                                      not isinstance(max_pixels, int) or max_pixels <= 0):
            raise ValueError("Batch pixel budget must be positive")
        timestamp = time.time() if now is None else float(now)
        db = self._write()
        try:
            db.execute("""UPDATE jobs SET state='QUEUED',lease_owner=NULL,lease_token=NULL,
                       lease_until=NULL,next_attempt_at=NULL,error='Recovered expired worker lease',
                       updated_at=? WHERE state='RUNNING' AND lease_until<=?""",
                       (timestamp, timestamp))
            db.execute("""UPDATE jobs SET state='QUEUED',next_attempt_at=NULL,updated_at=?
                       WHERE state='FAILED' AND next_attempt_at IS NOT NULL AND next_attempt_at<=?""",
                       (timestamp, timestamp))
            condition = """(j.state='QUEUED' OR (j.state='DEFERRED' AND
                           (j.next_attempt_at IS NULL OR j.next_attempt_at<=?)))"""
            parameters: list = [timestamp]
            if recipe_key is not None:
                condition += " AND j.recipe_key=?"
                parameters.append(recipe_key)
            parameters.append(max_count * 4)
            rows = db.execute("""SELECT j.*,s.width,s.height FROM jobs j
                              JOIN sources s ON s.source_id=j.source_id WHERE """ + condition +
                              " ORDER BY j.priority DESC,j.updated_at,j.source_id LIMIT ?",
                              parameters).fetchall()
            selected = []
            pixels = 0
            for row in rows:
                area = row["width"] * row["height"]
                # Always service the highest-priority job, even if it needs its
                # own batch. Never push large images behind newly arriving jobs.
                if selected and max_pixels is not None and pixels + area > max_pixels:
                    continue
                selected.append(row)
                pixels += area
                if len(selected) >= max_count or max_pixels is not None and pixels >= max_pixels:
                    break
            expires = timestamp + float(lease_seconds)
            leases = []
            for row in selected:
                token = uuid.uuid4().hex
                cursor = db.execute("""UPDATE jobs SET state='RUNNING',attempts=attempts+1,
                       lease_owner=?,lease_token=?,lease_until=?,next_attempt_at=NULL,error=NULL,updated_at=?
                       WHERE source_id=? AND recipe_key=? AND state IN ('QUEUED','DEFERRED')""",
                                    (owner, token, expires, timestamp, row["source_id"], row["recipe_key"]))
                if cursor.rowcount != 1:
                    raise RuntimeError("An asset batch lease changed during its transaction")
                leases.append(JobLease(row["source_id"], row["recipe_key"], owner, token,
                                       expires, row["attempts"] + 1))
            db.commit()
            return leases
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def renew(self, lease: JobLease, *, now: float | None = None, lease_seconds: float = 60.0) -> JobLease | None:
        timestamp = time.time() if now is None else float(now)
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        expires = timestamp + float(lease_seconds)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET lease_until=?,updated_at=?
                               WHERE source_id=? AND recipe_key=? AND state='RUNNING'
                                 AND lease_owner=? AND lease_token=? AND lease_until>?""",
                                (expires, timestamp, lease.source_id, lease.recipe_key,
                                 lease.owner, lease.token, timestamp))
            if cursor.rowcount != 1:
                return None
            return JobLease(lease.source_id, lease.recipe_key, lease.owner, lease.token,
                            expires, lease.attempts)

    def defer(self, lease: JobLease, *, retry_at: float, reason: str,
              now: float | None = None) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET state='DEFERRED',next_attempt_at=?,lease_owner=NULL,
                               lease_token=NULL,lease_until=NULL,error=?,updated_at=?
                               WHERE source_id=? AND recipe_key=? AND state='RUNNING'
                                 AND lease_owner=? AND lease_token=? AND lease_until>?""",
                                (float(retry_at), reason[:2000], timestamp, lease.source_id,
                                 lease.recipe_key, lease.owner, lease.token, timestamp))
            return cursor.rowcount == 1

    def mark_ready(self, lease: JobLease, relative_output: str, *, now: float | None = None) -> bool:
        relative = self._relative_path(relative_output)
        timestamp = time.time() if now is None else float(now)
        if not self.resolve_path(relative).is_file():
            raise FileNotFoundError(relative)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET state='READY',next_attempt_at=NULL,lease_owner=NULL,
                               lease_token=NULL,lease_until=NULL,relative_output=?,error=NULL,updated_at=?
                               WHERE source_id=? AND recipe_key=? AND state='RUNNING'
                                 AND lease_owner=? AND lease_token=? AND lease_until>?""",
                                (relative, timestamp, lease.source_id, lease.recipe_key,
                                 lease.owner, lease.token, timestamp))
            return cursor.rowcount == 1

    def mark_failed(self, lease: JobLease, error: str, *, retry_at: float | None,
                    now: float | None = None) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET state='FAILED',next_attempt_at=?,lease_owner=NULL,
                               lease_token=NULL,lease_until=NULL,relative_output=NULL,error=?,updated_at=?
                               WHERE source_id=? AND recipe_key=? AND state='RUNNING'
                                 AND lease_owner=? AND lease_token=? AND lease_until>?""",
                                (retry_at, str(error)[:2000], timestamp, lease.source_id,
                                 lease.recipe_key, lease.owner, lease.token, timestamp))
            return cursor.rowcount == 1

    def reschedule(self, lease: JobLease, reason: str, *, now: float | None = None) -> bool:
        """Release owned work back to admission control without inventing a new lease."""
        timestamp = time.time() if now is None else float(now)
        with self._transaction() as db:
            cursor = db.execute("""UPDATE jobs SET state='QUEUED',next_attempt_at=NULL,
                               lease_owner=NULL,lease_token=NULL,lease_until=NULL,
                               relative_output=NULL,error=?,updated_at=?
                               WHERE source_id=? AND recipe_key=? AND state='RUNNING'
                                 AND lease_owner=? AND lease_token=? AND lease_until>?""",
                                (str(reason)[:2000], timestamp, lease.source_id, lease.recipe_key,
                                 lease.owner, lease.token, timestamp))
            return cursor.rowcount == 1

    def pending_count(self) -> int:
        with self._read() as db:
            return db.execute("SELECT count(*) FROM jobs WHERE state IN ('QUEUED','RUNNING','DEFERRED')").fetchone()[0]

    def has_waiting(self,recipe_key: str) -> bool:
        with self._read() as db:
            return db.execute("SELECT 1 FROM jobs WHERE recipe_key=? AND state IN ('QUEUED','DEFERRED') LIMIT 1",
                              (recipe_key,)).fetchone() is not None

