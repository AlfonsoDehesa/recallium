"""Internal SQLite migration runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Callable

from recallium.errors import MigrationError


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class MigrationStatus:
    db_path: str
    current_version: int
    latest_version: int
    pending_versions: list[int]

    @property
    def up_to_date(self) -> bool:
        return len(self.pending_versions) == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "db_path": self.db_path,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "pending_versions": self.pending_versions,
            "up_to_date": self.up_to_date,
        }


def _default_migrations() -> list[Migration]:
    from recallium.migrations.versions import list_migrations

    return list_migrations()


class MigrationRunner:
    def __init__(
        self, db_path: Path | str, *, migrations: list[Migration] | None = None
    ) -> None:
        self.db_path = Path(db_path)
        configured = migrations if migrations is not None else _default_migrations()
        self.migrations = sorted(configured, key=lambda migration: migration.version)
        self._validate_migrations()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _validate_migrations(self) -> None:
        versions = [migration.version for migration in self.migrations]
        if len(set(versions)) != len(versions):
            raise MigrationError("duplicate migration versions are not allowed")
        if any(version <= 0 for version in versions):
            raise MigrationError("migration versions must be positive integers")

    def _latest_version(self) -> int:
        if not self.migrations:
            return 0
        return self.migrations[-1].version

    def _read_user_version(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def _ensure_metadata_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

    def _record_migration(
        self, connection: sqlite3.Connection, migration: Migration, *, applied_at: str
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (migration.version, migration.name, applied_at),
        )

    def _reconcile_existing_metadata(
        self, connection: sqlite3.Connection, *, current_version: int
    ) -> None:
        if current_version <= 0:
            return
        row = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
        existing_rows = int(row[0]) if row else 0
        if existing_rows > 0:
            return
        applied_at = _utc_now_iso()
        for migration in self.migrations:
            if migration.version <= current_version:
                self._record_migration(
                    connection, migration, applied_at=f"{applied_at}:reconciled"
                )

    def status(self) -> MigrationStatus:
        latest_version = self._latest_version()
        with self._connect() as connection:
            current_version = self._read_user_version(connection)
            pending = [
                migration.version
                for migration in self.migrations
                if migration.version > current_version
            ]
        return MigrationStatus(
            db_path=str(self.db_path),
            current_version=current_version,
            latest_version=latest_version,
            pending_versions=pending,
        )

    def migrate(self) -> MigrationStatus:
        latest_version = self._latest_version()
        with self._connect() as connection:
            self._ensure_metadata_table(connection)
            current_version = self._read_user_version(connection)
            if current_version > latest_version:
                raise MigrationError(
                    "database schema version is newer than this Recallium build supports"
                )

            self._reconcile_existing_metadata(
                connection, current_version=current_version
            )

            for migration in self.migrations:
                if migration.version <= current_version:
                    continue
                try:
                    with connection:
                        migration.upgrade(connection)
                        self._record_migration(
                            connection,
                            migration,
                            applied_at=_utc_now_iso(),
                        )
                        connection.execute(f"PRAGMA user_version = {migration.version}")
                except sqlite3.DatabaseError as exc:
                    raise MigrationError(
                        f"failed applying migration v{migration.version:03d} "
                        f"({migration.name}): {exc}"
                    ) from exc
                current_version = migration.version

        return self.status()
