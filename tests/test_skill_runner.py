from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cairn_data_agent.registry import SkillRegistry
from cairn_data_agent.skill_runner import SkillExecutionError, TrustedSkillRunner


def _valid_payload() -> dict[str, Any]:
    return {
        "input": {
            "kind": "table",
            "columns": [{"name": "value", "type": "String"}],
            "rows": [{"value": "example"}],
            "rowCount": 1,
            "columnCount": 1,
            "truncated": False,
        },
        "arguments": {},
    }


def test_skill_runner_rejects_input_schema_violation(project_root: Path) -> None:
    runner = TrustedSkillRunner(SkillRegistry(project_root / "skills"))

    with pytest.raises(SkillExecutionError, match="输入不符合 schema"):
        runner.execute("tabular-quality@0.1.0", {"arguments": {}})


def test_skill_runner_rejects_output_schema_violation(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = TrustedSkillRunner(SkillRegistry(project_root / "skills"))
    monkeypatch.setattr(
        runner,
        "_load_function",
        lambda *_: lambda _payload: {"kind": "unexpected"},
    )

    with pytest.raises(SkillExecutionError, match="输出无效"):
        runner.execute("tabular-quality@0.1.0", _valid_payload())


def test_skill_runner_rejects_oversized_output(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = TrustedSkillRunner(SkillRegistry(project_root / "skills"))
    monkeypatch.setattr(
        runner,
        "_load_function",
        lambda *_: (
            lambda _payload: {
                "kind": "skill-result",
                "check": "tabular-quality",
                "rowCount": 1,
                "nullCounts": {},
                "warnings": ["x" * 70_000],
            }
        ),
    )

    with pytest.raises(SkillExecutionError, match="超过 manifest 限额"):
        runner.execute("tabular-quality@0.1.0", _valid_payload())
