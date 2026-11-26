"""tests/integration/test_pragmas.py — SQLite pragma verification.

Checks that WAL, foreign_keys, synchronous=NORMAL, and busy_timeout=5000
are applied on SQLite connections (including WAL on a real file-backed DB).
"""
from __future__ import annotations

import pytest


class TestSQLitePragmas:
    def _query_pragma(self, app, pragma: str) -> object:
        from app.extensions import db

        with app.app_context():
            result = db.session.execute(db.text(f"PRAGMA {pragma}")).fetchone()
            return result[0] if result else None

    def _is_memory_db(self, app) -> bool:
        return "memory" in app.config.get("SQLALCHEMY_DATABASE_URI", "")

    def test_journal_mode_wal_on_file_db(self, tmp_path):
        """WAL mode must be active for file-backed SQLite databases."""
        from sqlalchemy import create_engine, event

        from app.extensions import _sqlite_pragmas

        db_path = tmp_path / "wal_check.db"
        engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        event.listen(engine, "connect", _sqlite_pragmas)
        try:
            with engine.connect() as conn:
                mode = conn.exec_driver_sql("PRAGMA journal_mode").fetchone()[0]
                fk = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()[0]
                timeout = conn.exec_driver_sql("PRAGMA busy_timeout").fetchone()[0]
                sync = conn.exec_driver_sql("PRAGMA synchronous").fetchone()[0]
            assert mode == "wal", f"Expected WAL journal mode, got {mode!r}"
            assert fk == 1
            assert timeout == 5000
            assert sync == 1  # NORMAL == 1
        finally:
            engine.dispose()

    def test_journal_mode_wal(self, app):
        if self._is_memory_db(app):
            pytest.skip(
                "WAL journal mode is not available for :memory: SQLite "
                "(verified on file-backed DB in test_journal_mode_wal_on_file_db)."
            )
        mode = self._query_pragma(app, "journal_mode")
        assert mode == "wal", f"Expected WAL journal mode, got {mode!r}"

    def test_foreign_keys_on(self, app):
        fk = self._query_pragma(app, "foreign_keys")
        assert fk == 1, f"Expected foreign_keys=1, got {fk!r}"

    def test_busy_timeout_set(self, app):
        timeout = self._query_pragma(app, "busy_timeout")
        assert timeout == 5000, f"Expected busy_timeout=5000, got {timeout!r}"
