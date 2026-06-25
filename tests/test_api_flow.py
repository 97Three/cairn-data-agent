from __future__ import annotations

import io
from pathlib import Path

import pytest
import xlsxwriter
from fastapi.testclient import TestClient


def upload(client: TestClient, project_id: str, path: Path, media_type: str) -> dict[str, object]:
    response = client.post(
        f"/api/projects/{project_id}/assets",
        files={"file": (path.name, path.read_bytes(), media_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_travel_csv_reaches_evidence_answer(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    scenarios = client.get("/api/scenarios")
    assert scenarios.status_code == 200
    assert "travel-budget" in {item["name"] for item in scenarios.json()}
    asset = upload(
        client, project_id, project_root / "examples" / "travel-expenses.csv", "text/csv"
    )
    preview = client.get(f"/api/assets/{asset['id']}/preview").json()["preview"]
    assert preview["rowCount"] == 6

    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "哪些旅行费用类别超出了预算？",
            "assetIds": [asset["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["createdAt"].endswith("Z")
    assert run["completedAt"].endswith("Z")
    assert [step["kind"] for step in run["steps"]] == ["derive", "aggregate", "sort"]
    assert run["artifacts"][-1]["kind"] == "table"
    assert f"[artifact:{run['artifacts'][-1]['id']}]" in run["answer"]
    assert run["artifacts"][-1]["lineage"]["inputArtifactIds"]

    restored = client.get(f"/api/runs/{run['id']}")
    assert restored.status_code == 200
    assert restored.json()["answer"] == run["answer"]


def test_learning_notes_answer_has_source_lines(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    asset = upload(
        client,
        project_id,
        project_root / "examples" / "learning-notes.md",
        "text/markdown",
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "learning-notes",
            "question": "笔记里推荐了哪些提高长期记忆的复习方法？",
            "assetIds": [asset["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["artifacts"][-1]["kind"] == "evidence"
    assert run["artifacts"][-1]["preview"]["hits"]
    assert "learning-notes.md:L" in run["answer"]


def test_unknown_offline_question_requests_clarification(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    asset = upload(
        client, project_id, project_root / "examples" / "travel-expenses.csv", "text/csv"
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "请做一个完全无关的任务",
            "assetIds": [asset["id"]],
        },
    )
    run = response.json()
    assert run["status"] == "needs_input"
    assert run["clarification"]["options"]
    assert run["artifacts"] == []


def test_xlsx_is_profiled(client: TestClient, project_id: str, tmp_path: Path) -> None:
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("expenses")
    for column, value in enumerate(["category", "budget_cny", "actual_cny"]):
        sheet.write(0, column, value)
    sheet.write_row(1, 0, ["food", 100, 120])
    workbook.close()
    path = tmp_path / "synthetic.xlsx"
    path.write_bytes(output.getvalue())
    asset = upload(
        client,
        project_id,
        path,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert asset["kind"] == "xlsx"
    assert asset["profile"]["rowCount"] == 1


def test_xlsx_with_multiple_sheets_is_rejected(client: TestClient, project_id: str) -> None:
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.add_worksheet("first").write_row(0, 0, ["value"])
    workbook.add_worksheet("second").write_row(0, 0, ["value"])
    workbook.close()

    response = client.post(
        f"/api/projects/{project_id}/assets",
        files={
            "file": (
                "multiple.xlsx",
                output.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 422
    assert "必须且只能包含一个工作表" in response.json()["detail"]
    assert client.get(f"/api/projects/{project_id}").json()["assets"] == []


def test_asset_scope_and_type_are_enforced(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    asset = upload(
        client,
        project_id,
        project_root / "examples" / "learning-notes.md",
        "text/markdown",
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析费用预算",
            "assetIds": [asset["id"]],
        },
    )
    assert response.status_code == 422
    assert "不支持" in response.json()["detail"]


def test_project_restores_assets_messages_and_runs(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    upload(client, project_id, project_root / "examples" / "travel-expenses.csv", "text/csv")
    project = client.get(f"/api/projects/{project_id}")
    assert project.status_code == 200
    assert len(project.json()["assets"]) == 1
    assert len(project.json()["conversations"]) == 1
    assert project.json()["defaultConversationId"] == project.json()["conversations"][0]["id"]
    assert project.json()["messages"] == []
    assert project.json()["createdAt"].endswith("Z")
    assert project.json()["conversations"][0]["createdAt"].endswith("Z")
    assert project.json()["assets"][0]["createdAt"].endswith("Z")


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("/api/projects/stale-project", "Project 不存在"),
        ("/api/assets/missing-asset/preview", "资产不存在"),
        ("/api/runs/missing-run", "Run 不存在"),
        ("/api/artifacts/missing-artifact", "Artifact 不存在"),
    ],
)
def test_directly_addressed_missing_resources_return_404(
    client: TestClient, path: str, detail: str
) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


def test_missing_project_lookups_return_404(client: TestClient) -> None:
    conversation = client.post(
        "/api/projects/missing-project/conversations", json={"title": "新对话"}
    )
    assert conversation.status_code == 404

    upload_response = client.post(
        "/api/projects/missing-project/assets",
        files={"file": ("data.csv", b"value\n1\n", "text/csv")},
    )
    assert upload_response.status_code == 404

    ask_response = client.post(
        "/api/projects/missing-project/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": ["missing-asset"],
        },
    )
    assert ask_response.status_code == 404


def test_request_scope_errors_remain_422(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    second = client.post("/api/projects", json={"name": "隔离项目"}).json()
    asset = upload(
        client, project_id, project_root / "examples" / "travel-expenses.csv", "text/csv"
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": [asset["id"]],
            "conversationId": second["defaultConversationId"],
        },
    )
    assert response.status_code == 422
    assert "Conversation" in response.json()["detail"]


def test_conversation_scopes_messages_and_runs(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    conversation = client.post(
        f"/api/projects/{project_id}/conversations", json={"title": "预算复盘"}
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    asset = upload(
        client, project_id, project_root / "examples" / "travel-expenses.csv", "text/csv"
    )

    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "哪些旅行费用类别超出了预算？",
            "assetIds": [asset["id"]],
            "conversationId": conversation_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["conversationId"] == conversation_id

    follow_up = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "继续分析预算费用",
            "assetIds": [asset["id"]],
            "conversationId": conversation_id,
        },
    )
    assert follow_up.status_code == 200, follow_up.text
    conversation_context = follow_up.json()["contextSnapshot"]["conversation"]
    assert conversation_context["id"] == conversation_id
    assert [item["role"] for item in conversation_context["history"]] == ["user", "assistant"]

    restored = client.get(f"/api/projects/{project_id}").json()
    scoped_messages = [
        message for message in restored["messages"] if message["conversationId"] == conversation_id
    ]
    assert [message["role"] for message in scoped_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert restored["runs"][-1]["conversationId"] == conversation_id


def test_conversation_cannot_cross_project_scope(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    second = client.post("/api/projects", json={"name": "隔离项目"}).json()
    asset = upload(
        client, project_id, project_root / "examples" / "travel-expenses.csv", "text/csv"
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": [asset["id"]],
            "conversationId": second["defaultConversationId"],
        },
    )
    assert response.status_code == 422
    assert "Conversation" in response.json()["detail"]


def test_asset_cannot_cross_project_scope(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    second = client.post("/api/projects", json={"name": "另一个项目"}).json()
    asset = upload(
        client,
        second["id"],
        project_root / "examples" / "travel-expenses.csv",
        "text/csv",
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "travel-budget",
            "question": "分析预算费用",
            "assetIds": [asset["id"]],
        },
    )
    assert response.status_code == 422
    assert "不属于" in response.json()["detail"]


def test_authorized_pure_skill_runs_before_stock_summary(
    client: TestClient, project_id: str, project_root: Path
) -> None:
    asset = upload(
        client,
        project_id,
        project_root / "examples" / "synthetic-market.csv",
        "text/csv",
    )
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={
            "scenarioName": "stock-research",
            "question": "按代码汇总平均收盘价和成交量",
            "assetIds": [asset["id"]],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert [step["kind"] for step in run["steps"]] == ["skill", "aggregate"]
    assert run["artifacts"][0]["preview"]["check"] == "tabular-quality"
    assert "不构成投资建议" in run["answer"]
