from __future__ import annotations

import json

from cairn_data_agent.previews import bounded_preview


def test_small_preview_keeps_its_structure() -> None:
    preview = {"kind": "table", "rows": [{"value": 3}], "rowCount": 1}

    assert bounded_preview(preview, max_bytes=1_024) == preview


def test_large_preview_has_a_hard_serialized_boundary() -> None:
    preview = {
        "kind": "table",
        "rows": [{f"column-{column}": "\x00" * 5_000 for column in range(120)} for _ in range(80)],
        "rowCount": 80,
    }

    bounded = bounded_preview(preview, max_bytes=1_024)
    encoded = json.dumps(bounded, ensure_ascii=False, sort_keys=True).encode("utf-8")

    assert len(encoded) <= 1_024
    assert bounded["truncated"] is True
    assert bounded["candidatePreviewBytes"] > 1_024
