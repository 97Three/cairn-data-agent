from __future__ import annotations

import json

import pytest

from cairn_data_agent.config import Settings
from cairn_data_agent.contracts import DataPlan
from cairn_data_agent.database import ArtifactRecord
from cairn_data_agent.model import AnswerEvidenceError, OpenAICompatibleAgentModel
from cairn_data_agent.registry import ScenarioRegistry


class StubModel(OpenAICompatibleAgentModel):
    def __init__(self, responses: list[str]):
        super().__init__(Settings(model_mode="openai-compatible"))
        self.responses = iter(responses)

    def _complete(self, messages: list[dict[str, str]]) -> str:
        assert messages
        return next(self.responses)


def test_openai_compatible_plan_accepts_fenced_json(project_root: object) -> None:
    plan = {
        "version": "cairn.data-plan/v1",
        "goal": "检查资产",
        "asset_ids": ["asset-1"],
        "steps": [{"id": "inspect_asset", "kind": "inspect", "asset_id": "asset-1"}],
    }
    model = StubModel([f"```json\n{json.dumps(plan)}\n```"])
    scenario = ScenarioRegistry(project_root / "scenarios").get("travel-budget")  # type: ignore[operator]
    decision = model.plan(context={"question": "检查"}, scenario=scenario, assets=[])
    assert isinstance(decision, DataPlan)


def test_openai_answer_rejects_missing_evidence_reference() -> None:
    artifact = ArtifactRecord(
        id="artifact-1",
        project_id="project-1",
        run_id="run-1",
        step_id="summary",
        kind="table",
        mime_type="application/json",
        blob_sha256="a" * 64,
        byte_size=2,
        preview={"rows": [{"total": 3}]},
        lineage={},
    )
    model = StubModel(["总计是 3。"])
    with pytest.raises(AnswerEvidenceError, match="至少引用"):
        model.answer(question="总计？", instruction="简洁回答", artifacts=[artifact])


def test_openai_answer_evidence_contains_only_actually_cited_artifacts() -> None:
    artifacts = [
        ArtifactRecord(
            id=f"artifact-{index}",
            project_id="project-1",
            run_id="run-1",
            step_id=f"step-{index}",
            kind="table",
            mime_type="application/json",
            blob_sha256=str(index) * 64,
            byte_size=2,
            preview={"rows": [{"value": index}]},
            lineage={},
        )
        for index in range(1, 3)
    ]
    model = StubModel(["结论来自第二份结果 [artifact:artifact-2]。"])
    answer = model.answer(question="结论？", instruction="简洁回答", artifacts=artifacts)
    assert [item["artifactId"] for item in answer.evidence] == ["artifact-2"]


def test_openai_answer_cannot_cite_artifact_outside_visible_window() -> None:
    artifacts = [
        ArtifactRecord(
            id=f"artifact-{index}",
            project_id="project-1",
            run_id="run-1",
            step_id=f"step-{index}",
            kind="table",
            mime_type="application/json",
            blob_sha256=f"{index:064x}",
            byte_size=2,
            preview={"rows": []},
            lineage={},
        )
        for index in range(9)
    ]
    model = StubModel(["引用不可见结果 [artifact:artifact-0]。"])
    with pytest.raises(AnswerEvidenceError, match="未提供"):
        model.answer(question="结论？", instruction="简洁回答", artifacts=artifacts)
