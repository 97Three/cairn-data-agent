from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from zipfile import ZipFile

import pytest
import yaml


@pytest.fixture
def verifier(project_root: Path) -> ModuleType:
    spec = spec_from_file_location(
        "cairn_distribution_verifier", project_root / "scripts/verify-wheel.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _minimal_wheel_entries(project_root: Path, package_content: bytes) -> list[tuple[str, bytes]]:
    dist_info = "cairn_data_agent-0.1.0.dist-info"
    metadata = (
        b"Metadata-Version: 2.5\n"
        b"Name: cairn-data-agent\n"
        b"Version: 0.1.0\n"
        b"License-Expression: MIT\n"
        b"License-File: LICENSE\n\n"
    )
    return [
        ("cairn_data_agent/__init__.py", package_content),
        (f"{dist_info}/METADATA", metadata),
        (f"{dist_info}/WHEEL", b"Wheel-Version: 1.0\n"),
        (f"{dist_info}/entry_points.txt", b""),
        (f"{dist_info}/licenses/LICENSE", (project_root / "LICENSE").read_bytes()),
        (f"{dist_info}/RECORD", b""),
    ]


def _write_wheel(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with ZipFile(path, mode="w") as archive:
        for name, content in entries:
            archive.writestr(name, content)


def test_wheel_verifier_rejects_unexpected_member(
    verifier: ModuleType, project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_source = tmp_path / "__init__.py"
    package_source.write_bytes(b'__version__ = "0.1.0"\n')
    monkeypatch.setattr(
        verifier,
        "expected_wheel_files",
        lambda _: {"cairn_data_agent/__init__.py": package_source},
    )
    entries = _minimal_wheel_entries(project_root, package_source.read_bytes())
    entries.append(("cairn_data_agent/private/internal.json", b"{}"))
    wheel = tmp_path / "unexpected.whl"
    _write_wheel(wheel, entries)

    with pytest.raises(SystemExit, match="unexpected"):
        verifier.verify_wheel(wheel, project_root)


def test_wheel_verifier_rejects_duplicate_member(
    verifier: ModuleType, project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_source = tmp_path / "__init__.py"
    package_source.write_bytes(b'__version__ = "0.1.0"\n')
    monkeypatch.setattr(
        verifier,
        "expected_wheel_files",
        lambda _: {"cairn_data_agent/__init__.py": package_source},
    )
    entries = _minimal_wheel_entries(project_root, package_source.read_bytes())
    entries.append(("cairn_data_agent/__init__.py", b"tampered\n"))
    wheel = tmp_path / "duplicate.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_wheel(wheel, entries)

    with pytest.raises(SystemExit, match="重复成员名"):
        verifier.verify_wheel(wheel, project_root)


def test_demo_verifier_accepts_multiple_cases_and_requires_the_full_set(
    verifier: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario_root = tmp_path / "scenarios" / "sample"
    scenario_root.mkdir(parents=True)
    cases = [
        {
            "id": "plan-case",
            "expect": {
                "decision": "plan",
                "finalArtifactKind": "table",
                "evidenceRequired": True,
            },
        },
        {
            "id": "clarification-case",
            "expect": {"decision": "clarification", "evidenceRequired": False},
        },
    ]
    (scenario_root / "evals.yaml").write_text(
        yaml.safe_dump({"version": "cairn.scenario-evals/v1", "cases": cases}),
        encoding="utf-8",
    )
    runs = [
        {
            "scenario": "sample",
            "case": "plan-case",
            "status": "succeeded",
            "artifactCount": 1,
            "finalArtifactKind": "table",
            "answer": "结果 [artifact:example]",
        },
        {
            "scenario": "sample",
            "case": "clarification-case",
            "status": "needs_input",
            "artifactCount": 0,
            "finalArtifactKind": None,
            "answer": None,
        },
    ]
    result = tmp_path / "demo.json"
    result.write_text(
        json.dumps({"version": "cairn.demo-result/v1", "mode": "offline", "runs": runs}),
        encoding="utf-8",
    )
    monkeypatch.setattr(verifier, "EXPECTED_SCENARIOS", {"sample"})

    verifier.verify_demo(result, tmp_path)

    result.write_text(
        json.dumps({"version": "cairn.demo-result/v1", "mode": "offline", "runs": runs[:1]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="case 清单不一致"):
        verifier.verify_demo(result, tmp_path)
