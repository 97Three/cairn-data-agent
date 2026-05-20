from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any]) -> dict[str, Any]:
    table = payload["input"]
    rows = table["rows"]
    column_names = [column["name"] for column in table["columns"]]
    null_counts = {column: sum(row.get(column) is None for row in rows) for column in column_names}
    warnings = [
        f"字段 {column} 有 {count} 个空值" for column, count in null_counts.items() if count
    ]
    if not rows:
        warnings.append("表格没有数据行")
    return {
        "kind": "skill-result",
        "check": "tabular-quality",
        "rowCount": table["rowCount"],
        "nullCounts": null_counts,
        "warnings": warnings,
    }
