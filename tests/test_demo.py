from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from cairn_data_agent import demo
from cairn_data_agent.demo import DemoError, _evaluation_cases, _fixture_path
from cairn_data_agent.registry import ScenarioRegistry


def test_all_scenario_evaluations_resolve_to_synthetic_examples(project_root) -> None:
    scenarios = ScenarioRegistry(project_root / "scenarios").list()

    cases = [case for scenario in scenarios for case in _evaluation_cases(project_root, scenario)]

    assert len(cases) >= len(scenarios)
    assert len(
        {
            (scenario.manifest.metadata.name, case["id"])
            for scenario in scenarios
            for case in _evaluation_cases(project_root, scenario)
        }
    ) == len(cases)
    assert all(case["fixture"].is_relative_to(project_root / "examples") for case in cases)
    assert all(case["expect"]["evidenceRequired"] is True for case in cases)


def test_evaluation_fixture_cannot_escape_examples(project_root) -> None:
    scenario = ScenarioRegistry(project_root / "scenarios").get("travel-budget")

    with pytest.raises(DemoError, match="examples"):
        _fixture_path(project_root, scenario, "../../README.md")


def test_demo_rejects_distribution_without_scenarios(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demo, "built_in_resources_root", lambda: tmp_path)

    with pytest.raises(DemoError, match="未发现任何 Scenario"):
        demo.main()


def test_evaluation_pack_supports_multiple_cases(project_root, tmp_path) -> None:
    scenario = ScenarioRegistry(project_root / "scenarios").get("travel-budget")
    scenario_root = tmp_path / "scenarios" / "travel-budget"
    examples_root = tmp_path / "examples"
    scenario_root.mkdir(parents=True)
    examples_root.mkdir()
    (examples_root / "fixture.csv").write_text("category,amount\ntravel,10\n", encoding="utf-8")
    cases = [
        {
            "id": case_id,
            "question": "按类别汇总金额。",
            "assetFixture": "../../examples/fixture.csv",
            "expect": {
                "decision": "plan",
                "finalArtifactKind": "table",
                "evidenceRequired": True,
            },
        }
        for case_id in ("first", "second")
    ]
    (scenario_root / "evals.yaml").write_text(
        yaml.safe_dump({"version": "cairn.scenario-evals/v1", "cases": cases}),
        encoding="utf-8",
    )

    loaded = _evaluation_cases(tmp_path, replace(scenario, root=scenario_root))

    assert [case["id"] for case in loaded] == ["first", "second"]


@pytest.mark.parametrize(
    ("cases", "message"),
    [
        ([], "至少需要一个 case"),
        (
            [
                {
                    "id": "duplicate",
                    "question": "问题一",
                    "assetFixture": "../../examples/fixture.csv",
                    "expect": {"decision": "plan", "evidenceRequired": True},
                },
                {
                    "id": "duplicate",
                    "question": "问题二",
                    "assetFixture": "../../examples/fixture.csv",
                    "expect": {"decision": "plan", "evidenceRequired": True},
                },
            ],
            "id 重复",
        ),
    ],
)
def test_evaluation_pack_rejects_empty_or_duplicate_cases(
    project_root, tmp_path, cases, message
) -> None:
    scenario = ScenarioRegistry(project_root / "scenarios").get("travel-budget")
    scenario_root = tmp_path / "scenarios" / "travel-budget"
    examples_root = tmp_path / "examples"
    scenario_root.mkdir(parents=True)
    examples_root.mkdir()
    (examples_root / "fixture.csv").write_text("category,amount\ntravel,10\n", encoding="utf-8")
    (scenario_root / "evals.yaml").write_text(
        yaml.safe_dump({"version": "cairn.scenario-evals/v1", "cases": cases}),
        encoding="utf-8",
    )

    with pytest.raises(DemoError, match=message):
        _evaluation_cases(tmp_path, replace(scenario, root=scenario_root))
