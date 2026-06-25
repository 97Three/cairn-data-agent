from __future__ import annotations

import pytest
from pydantic import ValidationError

from cairn_data_agent.contracts import DataPlan
from cairn_data_agent.policy import PlanPolicyError, validate_plan


def plan(**changes: object) -> DataPlan:
    value: dict[str, object] = {
        "version": "cairn.data-plan/v1",
        "goal": "汇总数据",
        "asset_ids": ["asset-1"],
        "steps": [
            {
                "id": "summary",
                "kind": "aggregate",
                "input": "asset:asset-1",
                "group_by": ["category"],
                "metrics": [{"column": "amount", "operation": "sum", "alias": "total"}],
            }
        ],
    }
    value.update(changes)
    return DataPlan.model_validate(value)


def test_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        plan(debug=True)


def test_policy_accepts_scoped_plan() -> None:
    validated = validate_plan(plan(), {"asset-1"})
    assert validated.ordered_step_ids == ("summary",)


def test_policy_rejects_unselected_asset() -> None:
    with pytest.raises(PlanPolicyError, match="未选择"):
        validate_plan(plan(), {"another-asset"})


def test_policy_rejects_duplicate_plan_assets() -> None:
    with pytest.raises(PlanPolicyError, match="重复"):
        validate_plan(plan(asset_ids=["asset-1", "asset-1"]), {"asset-1"})


def test_policy_rejects_declared_but_unconsumed_asset() -> None:
    with pytest.raises(PlanPolicyError, match="未被任何步骤消费.*asset-2"):
        validate_plan(
            plan(asset_ids=["asset-1", "asset-2"]),
            {"asset-1", "asset-2"},
        )


def test_policy_rejects_forward_step_reference() -> None:
    value = plan().model_dump()
    value["steps"] = [
        {"id": "early", "kind": "limit", "input": "step:late", "count": 1},
        {"id": "late", "kind": "limit", "input": "asset:asset-1", "count": 1},
    ]
    with pytest.raises(PlanPolicyError, match="已出现"):
        validate_plan(DataPlan.model_validate(value), {"asset-1"})


def test_derive_requires_one_right_operand() -> None:
    value = plan().model_dump()
    value["steps"] = [
        {
            "id": "bad",
            "kind": "derive",
            "input": "asset:asset-1",
            "output_column": "result",
            "operation": "add",
            "left_column": "amount",
        }
    ]
    with pytest.raises(ValidationError, match="exactly one"):
        DataPlan.model_validate(value)


def test_policy_rejects_skill_not_authorized_by_scenario() -> None:
    value = plan().model_dump()
    value["steps"] = [
        {
            "id": "extension",
            "kind": "skill",
            "skill": "tabular-quality@0.1.0",
            "input": "asset:asset-1",
        }
    ]
    skill_plan = DataPlan.model_validate(value)
    with pytest.raises(PlanPolicyError, match="未授权 Skill"):
        validate_plan(skill_plan, {"asset-1"}, allowed_skill_ids=set())
    validate_plan(
        skill_plan,
        {"asset-1"},
        allowed_skill_ids={"tabular-quality@0.1.0"},
    )
