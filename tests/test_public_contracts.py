from __future__ import annotations

import json
import tomllib
from hashlib import sha256
from pathlib import Path

import jsonschema
import yaml

from cairn_data_agent.contracts import DataPlan


def test_release_metadata_declares_mit_license(project_root: Path) -> None:
    license_text = (project_root / "LICENSE").read_text(encoding="utf-8")
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    package_json = json.loads((project_root / "web" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (project_root / "web" / "package-lock.json").read_text(encoding="utf-8")
    )
    web_license = (project_root / "web" / "public" / "LICENSE.txt").read_text(encoding="utf-8")
    third_party_notices = (project_root / "web" / "public" / "THIRD_PARTY_NOTICES.txt").read_text(
        encoding="utf-8"
    )

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 Cairn Data Agent contributors" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert sha256(license_text.encode("utf-8")).hexdigest() == (
        "94d78e29fc15de825ae7b520d038764a0259f844c6d38c432b15e01a3b03866e"
    )
    assert pyproject["project"]["license"] == "MIT"
    assert pyproject["project"]["license-files"] == ["LICENSE"]
    assert package_json["license"] == "MIT"
    assert package_lock["packages"][""]["license"] == "MIT"
    assert web_license == license_text
    for package_name, display_name in (
        ("react", "React"),
        ("react-dom", "React DOM"),
        ("scheduler", "Scheduler"),
    ):
        version = package_lock["packages"][f"node_modules/{package_name}"]["version"]
        assert f"{display_name} {version}" in third_party_notices
    assert "Modernizr 3.0.0pre (Custom Build) | MIT" in third_party_notices


def test_public_schemas_are_valid_and_accept_scenario_plans(project_root: Path) -> None:
    plan_schema = json.loads(
        (project_root / "contracts" / "data-plan.v1.schema.json").read_text(encoding="utf-8")
    )
    clarification_schema = json.loads(
        (project_root / "contracts" / "clarification.v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(plan_schema)
    jsonschema.Draft202012Validator.check_schema(clarification_schema)

    for examples_path in sorted((project_root / "scenarios").glob("*/examples.yaml")):
        examples = yaml.safe_load(examples_path.read_text(encoding="utf-8"))
        for example in examples:
            jsonschema.validate(example["plan"], plan_schema)
            DataPlan.model_validate(example["plan"])


def test_runtime_plan_dump_matches_public_schema(project_root: Path) -> None:
    """Cover nullable/default serialization for every public Plan step variant."""
    plan = DataPlan.model_validate(
        {
            "version": "cairn.data-plan/v1",
            "goal": "exercise every public step",
            "asset_ids": ["table-a", "table-b", "doc-a"],
            "steps": [
                {"id": "inspect", "kind": "inspect", "asset_id": "table-a"},
                {
                    "id": "filtered",
                    "kind": "filter",
                    "input": "asset:table-a",
                    "predicates": [{"column": "amount", "operator": "is_not_null"}],
                },
                {
                    "id": "selected",
                    "kind": "select",
                    "input": "step:filtered",
                    "columns": ["id", "amount", "baseline"],
                },
                {
                    "id": "derived_column",
                    "kind": "derive",
                    "input": "step:selected",
                    "output_column": "delta",
                    "operation": "subtract",
                    "left_column": "amount",
                    "right_column": "baseline",
                },
                {
                    "id": "derived_value",
                    "kind": "derive",
                    "input": "step:derived_column",
                    "output_column": "scaled",
                    "operation": "multiply",
                    "left_column": "delta",
                    "right_value": 2,
                },
                {
                    "id": "summary",
                    "kind": "aggregate",
                    "input": "step:derived_value",
                    "metrics": [{"column": "scaled", "operation": "sum", "alias": "total"}],
                },
                {
                    "id": "joined",
                    "kind": "join",
                    "left": "asset:table-a",
                    "right": "asset:table-b",
                    "left_on": ["id"],
                    "right_on": ["id"],
                },
                {
                    "id": "sorted",
                    "kind": "sort",
                    "input": "step:joined",
                    "by": [{"column": "id"}],
                },
                {
                    "id": "limited",
                    "kind": "limit",
                    "input": "step:sorted",
                    "count": 10,
                },
                {
                    "id": "retrieved",
                    "kind": "retrieve",
                    "asset_ids": ["doc-a"],
                    "query": "evidence",
                },
                {
                    "id": "quality",
                    "kind": "skill",
                    "skill": "tabular-quality@0.1.0",
                },
            ],
        }
    )
    serialized = plan.model_dump(mode="json")
    plan_schema = json.loads(
        (project_root / "contracts" / "data-plan.v1.schema.json").read_text(encoding="utf-8")
    )

    jsonschema.validate(serialized, plan_schema)
    assert DataPlan.model_validate(serialized) == plan
