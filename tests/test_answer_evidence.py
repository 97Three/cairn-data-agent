from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cairn_data_agent.model import AnswerResult, FakeAgentModel
from cairn_data_agent.service import DataAgentService


class InvalidEvidenceModel(FakeAgentModel):
    def answer(self, **_: object) -> AnswerResult:
        return AnswerResult(text="伪造结论 [artifact:not-from-this-run]", evidence=[])


class MissingStructuredEvidenceModel(FakeAgentModel):
    def answer(self, **kwargs: object) -> AnswerResult:
        artifacts = kwargs["artifacts"]
        assert isinstance(artifacts, list)
        return AnswerResult(text=f"有效引用 [artifact:{artifacts[-1].id}]", evidence=[])


def test_failed_answer_returns_complete_failed_run(client: TestClient, project_id: str) -> None:
    service: DataAgentService = client.app.state.service
    service.model = InvalidEvidenceModel()
    upload = client.post(
        f"/api/projects/{project_id}/assets",
        files={
            "file": (
                "expenses.csv",
                b"category,budget_cny,actual_cny\nfood,100,120\n",
                "text/csv",
            )
        },
    )
    assert upload.status_code == 201

    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": [upload.json()["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["id"]
    assert run["status"] == "failed"
    assert "未提供" in run["answer"]
    assert run["steps"] and all(step["status"] == "succeeded" for step in run["steps"])
    assert run["artifacts"]

    restored = client.get(f"/api/runs/{run['id']}")
    assert restored.status_code == 200
    assert restored.json() == run


def test_rollback_failure_does_not_replace_original_run_error(
    client: TestClient, project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service: DataAgentService = client.app.state.service
    service.model = InvalidEvidenceModel()
    upload = client.post(
        f"/api/projects/{project_id}/assets",
        files={"file": ("expenses.csv", b"category,budget_cny,actual_cny\nfood,100,120\n")},
    )
    original_rollback = Session.rollback
    calls = 0

    def fail_first_rollback(session: Session) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic rollback error")
        original_rollback(session)

    monkeypatch.setattr(Session, "rollback", fail_first_rollback)
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": [upload.json()["id"]],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "未提供" in response.json()["answer"]
    assert "rollback" not in response.json()["answer"]


def test_structured_evidence_must_match_body_citations(client: TestClient, project_id: str) -> None:
    service: DataAgentService = client.app.state.service
    service.model = MissingStructuredEvidenceModel()
    upload = client.post(
        f"/api/projects/{project_id}/assets",
        files={"file": ("expenses.csv", b"category,budget_cny,actual_cny\nfood,100,120\n")},
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": [upload.json()["id"]],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "结构化 evidence 与正文引用不一致" in response.json()["answer"]
