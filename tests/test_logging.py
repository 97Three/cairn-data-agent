from __future__ import annotations

import json
import logging

from cairn_data_agent.logging import JsonFormatter


def test_json_log_carries_run_id() -> None:
    record = logging.LogRecord(
        name="cairn_data_agent.service",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="run.succeeded",
        args=(),
        exc_info=None,
    )
    record.run_id = "run-123"  # type: ignore[attr-defined]

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "run.succeeded"
    assert payload["runId"] == "run-123"
