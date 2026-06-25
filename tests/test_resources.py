from __future__ import annotations

from pathlib import Path

import pytest

from cairn_data_agent.config import Settings
from cairn_data_agent.registry import ScenarioRegistry, SkillRegistry
from cairn_data_agent.resources import built_in_resources_root


def test_built_in_resources_support_default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAIRN_SCENARIOS_ROOT", raising=False)
    monkeypatch.delenv("CAIRN_SKILLS_ROOT", raising=False)

    resource_root = built_in_resources_root()
    settings = Settings()
    scenarios = ScenarioRegistry(settings.scenarios_root, settings.skills_root).list()
    skills = SkillRegistry(settings.skills_root).manifests()

    assert settings.scenarios_root == resource_root / "scenarios"
    assert settings.skills_root == resource_root / "skills"
    assert (resource_root / "contracts" / "data-plan.v1.schema.json").is_file()
    assert {scenario.manifest.metadata.name for scenario in scenarios} == {
        "learning-notes",
        "stock-research",
        "travel-budget",
    }
    assert [skill.metadata.name for skill in skills] == ["tabular-quality"]


def test_settings_do_not_implicitly_load_untrusted_cwd_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malicious_root = tmp_path / "untrusted-skills"
    malicious_root.mkdir()
    (tmp_path / ".env").write_text(
        f"CAIRN_MODEL_MODE=openai-compatible\nCAIRN_SKILLS_ROOT={malicious_root}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAIRN_MODEL_MODE", raising=False)
    monkeypatch.delenv("CAIRN_SKILLS_ROOT", raising=False)

    settings = Settings()

    assert settings.model_mode == "fake"
    assert settings.skills_root == built_in_resources_root() / "skills"


def test_explicit_environment_can_select_reviewed_skill_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAIRN_SKILLS_ROOT", str(tmp_path))

    assert Settings().skills_root == tmp_path
