from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from cairn_data_agent.config import Settings
from cairn_data_agent.database import ConversationRecord, Database, utc_isoformat


def test_utc_isoformat_normalizes_naive_and_offset_datetimes() -> None:
    assert utc_isoformat(datetime(2026, 8, 31, 14, 17, 58)) == "2026-08-31T14:17:58Z"
    assert (
        utc_isoformat(datetime(2026, 8, 31, 22, 17, 58, tzinfo=timezone(timedelta(hours=8))))
        == "2026-08-31T14:17:58Z"
    )
    assert utc_isoformat(datetime(2026, 8, 31, 14, 17, 58, tzinfo=UTC)).endswith("Z")


def test_sqlite_foreign_keys_are_enabled_on_every_connection(settings: Settings) -> None:
    database = Database(settings)
    database.create_schema()

    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    with database.session_factory() as session:
        session.add(ConversationRecord(project_id="missing-project", title="orphan"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
