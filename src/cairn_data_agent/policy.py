from __future__ import annotations

from dataclasses import dataclass

from .contracts import DataPlan


class PlanPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedPlan:
    plan: DataPlan
    ordered_step_ids: tuple[str, ...]


def _parse_reference(reference: str) -> tuple[str, str]:
    kind, separator, identifier = reference.partition(":")
    if separator != ":" or kind not in {"asset", "step"} or not identifier:
        raise PlanPolicyError(f"无效输入引用：{reference}")
    return kind, identifier


def validate_plan(
    plan: DataPlan, allowed_asset_ids: set[str], allowed_skill_ids: set[str] | None = None
) -> ValidatedPlan:
    authorized_skills = allowed_skill_ids or set()
    plan_assets = set(plan.asset_ids)
    if len(plan.asset_ids) != len(plan_assets):
        raise PlanPolicyError("计划资产范围不能包含重复项")
    if not plan_assets.issubset(allowed_asset_ids):
        raise PlanPolicyError("计划引用了用户未选择的资产")
    if not plan_assets:
        raise PlanPolicyError("计划必须固定至少一个资产")

    seen_steps: set[str] = set()
    consumed_asset_ids: set[str] = set()
    for step in plan.steps:
        if step.id in seen_steps:
            raise PlanPolicyError(f"步骤 ID 重复：{step.id}")

        direct_asset_ids: list[str] = []
        if step.kind == "inspect":
            direct_asset_ids.append(step.asset_id)
        elif step.kind == "retrieve":
            direct_asset_ids.extend(step.asset_ids)
        elif step.kind == "skill" and step.skill not in authorized_skills:
            raise PlanPolicyError(f"步骤 {step.id} 使用了未授权 Skill：{step.skill}")
        if not set(direct_asset_ids).issubset(plan_assets):
            raise PlanPolicyError(f"步骤 {step.id} 引用了计划范围外的资产")
        consumed_asset_ids.update(direct_asset_ids)

        for reference in step.input_references():
            kind, identifier = _parse_reference(reference)
            if kind == "asset" and identifier not in plan_assets:
                raise PlanPolicyError(f"步骤 {step.id} 引用了计划范围外的资产")
            if kind == "asset":
                consumed_asset_ids.add(identifier)
            if kind == "step" and identifier not in seen_steps:
                raise PlanPolicyError(f"步骤 {step.id} 必须引用已出现的上游步骤")
        seen_steps.add(step.id)

    unused_asset_ids = sorted(plan_assets - consumed_asset_ids)
    if unused_asset_ids:
        raise PlanPolicyError(f"计划声明了未被任何步骤消费的资产：{', '.join(unused_asset_ids)}")

    return ValidatedPlan(plan=plan, ordered_step_ids=tuple(step.id for step in plan.steps))
