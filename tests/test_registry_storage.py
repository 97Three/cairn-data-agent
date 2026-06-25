from __future__ import annotations

from pathlib import Path

import pytest

from cairn_data_agent.registry import RegistryError, ScenarioRegistry, SkillRegistry
from cairn_data_agent.storage import LocalBlobStore


def test_blob_store_is_content_addressed(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    first = store.put(b"same bytes")
    second = store.put(b"same bytes")
    assert first == second
    assert store.get(first.sha256) == b"same bytes"
    with pytest.raises(ValueError, match="digest"):
        store.get("../unsafe")

    blob_path = tmp_path / "blobs" / first.sha256[:2] / first.sha256[2:]
    blob_path.write_bytes(b"tampered")
    with pytest.raises(OSError, match="verification"):
        store.get(first.sha256)


def test_bundled_scenarios_are_domain_extensions(project_root: Path) -> None:
    bundles = ScenarioRegistry(project_root / "scenarios").list()
    assert {bundle.manifest.metadata.name for bundle in bundles} >= {
        "travel-budget",
        "learning-notes",
    }
    assert all(bundle.examples for bundle in bundles)


def test_new_scenario_is_discovered_without_core_change(tmp_path: Path) -> None:
    root = tmp_path / "new-domain"
    root.mkdir()
    (root / "knowledge.md").write_text("仅用于测试。", encoding="utf-8")
    (root / "examples.yaml").write_text(
        "- id: demo\n  question: 演示\n  plan:\n"
        "    version: cairn.data-plan/v1\n    goal: 演示\n"
        "    asset_ids: [$selected]\n    steps:\n"
        "      - {id: inspect_asset, kind: inspect, asset_id: $tabular}\n",
        encoding="utf-8",
    )
    (root / "evals.yaml").write_text("version: test\n", encoding="utf-8")
    (root / "scenario.yaml").write_text(
        "apiVersion: cairn.data-agent/v1alpha1\nkind: Scenario\nmetadata:\n"
        "  name: new-domain\n  version: 0.1.0\n  displayName: 新领域\n"
        "  description: 动态发现测试\nsupportedAssetTypes: [csv]\n"
        "instructions: 只分析已选数据。\nknowledge: [knowledge.md]\n"
        "skills: []\nexamples: examples.yaml\nevaluations: evals.yaml\n",
        encoding="utf-8",
    )
    bundle = ScenarioRegistry(tmp_path).get("new-domain")
    assert bundle.manifest.metadata.display_name == "新领域"


def test_registry_blocks_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "unsafe"
    root.mkdir()
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    (root / "examples.yaml").write_text("[]", encoding="utf-8")
    (root / "scenario.yaml").write_text(
        "apiVersion: cairn.data-agent/v1alpha1\nkind: Scenario\nmetadata:\n"
        "  name: unsafe\n  version: 0.1.0\n  displayName: Unsafe\n"
        "  description: Unsafe\nsupportedAssetTypes: [markdown]\n"
        "instructions: test\nknowledge: [../outside.md]\nskills: []\n"
        "examples: examples.yaml\nevaluations: examples.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="边界"):
        ScenarioRegistry(tmp_path).list()


def test_instruction_skill_is_safe_to_register(project_root: Path) -> None:
    skills = SkillRegistry(project_root / "skills").manifests()
    assert [(item.metadata.name, item.effect) for item in skills] == [("tabular-quality", "read")]
