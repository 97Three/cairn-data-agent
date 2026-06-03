from __future__ import annotations

import json
import mimetypes
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .bootstrap import build_service
from .config import Settings
from .contracts import AskRequest, ProjectCreate
from .registry import ScenarioBundle
from .resources import built_in_resources_root
from .service import DataAgentService


class DemoError(ValueError):
    pass


def _fixture_path(project_root: Path, scenario: ScenarioBundle, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise DemoError("evaluation assetFixture 必须是非空相对路径")
    relative = Path(raw_path)
    if relative.is_absolute():
        raise DemoError("evaluation assetFixture 不得是绝对路径")
    try:
        fixture = (scenario.root / relative).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise DemoError(f"evaluation fixture 不存在：{raw_path}") from error
    examples_root = (project_root / "examples").resolve(strict=True)
    if not fixture.is_relative_to(examples_root) or not fixture.is_file():
        raise DemoError("evaluation fixture 必须位于内置资源根 examples 目录")
    return fixture


def _evaluation_cases(project_root: Path, scenario: ScenarioBundle) -> list[dict[str, Any]]:
    path = scenario.root / scenario.manifest.evaluations
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DemoError(f"无法读取 evaluation pack：{path.name}") from error
    if not isinstance(payload, dict) or payload.get("version") != "cairn.scenario-evals/v1":
        raise DemoError("evaluation pack version 必须是 cairn.scenario-evals/v1")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise DemoError("evaluation pack 至少需要一个 case")

    cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise DemoError("evaluation case 必须是 object")
        case_id = raw_case.get("id")
        question = raw_case.get("question")
        expected = raw_case.get("expect")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or not isinstance(question, str)
            or not question.strip()
        ):
            raise DemoError("evaluation case 需要非空字符串 id 和 question")
        if case_id in case_ids:
            raise DemoError(f"evaluation case id 重复：{case_id}")
        case_ids.add(case_id)
        if not isinstance(expected, dict):
            raise DemoError("evaluation case 需要 expect object")
        if expected.get("decision") not in {"plan", "clarification"}:
            raise DemoError("evaluation expect.decision 必须是 plan 或 clarification")
        if not isinstance(expected.get("evidenceRequired"), bool):
            raise DemoError("evaluation expect.evidenceRequired 必须是 boolean")
        expected_kind = expected.get("finalArtifactKind")
        if expected_kind is not None and not isinstance(expected_kind, str):
            raise DemoError("evaluation expect.finalArtifactKind 必须是字符串")
        cases.append(
            {
                "id": case_id,
                "question": question,
                "fixture": _fixture_path(project_root, scenario, raw_case.get("assetFixture")),
                "expect": expected,
            }
        )
    return cases


def _assert_expectation(run: dict[str, Any], expected: dict[str, Any]) -> None:
    decision = expected.get("decision")
    expected_status = "needs_input" if decision == "clarification" else "succeeded"
    if run["status"] != expected_status:
        raise DemoError(f"Run 状态不符合预期：{run['status']} != {expected_status}")
    expected_kind = expected.get("finalArtifactKind")
    artifacts = run["artifacts"]
    if expected_kind is not None and (not artifacts or artifacts[-1]["kind"] != expected_kind):
        raise DemoError(f"最终 Artifact 类型不符合预期：{expected_kind}")
    if expected.get("evidenceRequired") and "[artifact:" not in (run["answer"] or ""):
        raise DemoError("evaluation 要求回答包含 Artifact 证据引用")


def _run_case(
    service: DataAgentService,
    *,
    scenario: ScenarioBundle,
    case: dict[str, Any],
) -> dict[str, Any]:
    project = service.create_project(
        ProjectCreate(name=f"离线评测 · {scenario.manifest.metadata.display_name}")
    )
    fixture: Path = case["fixture"]
    asset = service.ingest_asset(
        project_id=project["id"],
        filename=fixture.name,
        media_type=mimetypes.guess_type(fixture.name)[0] or "application/octet-stream",
        content=fixture.read_bytes(),
    )
    run = service.ask(
        project["id"],
        AskRequest.model_validate(
            {
                "scenarioName": scenario.manifest.metadata.name,
                "question": case["question"],
                "assetIds": [asset["id"]],
                "conversationId": project["defaultConversationId"],
            }
        ),
    )
    _assert_expectation(run, case["expect"])
    return run


def main() -> None:
    resource_root = built_in_resources_root()
    with tempfile.TemporaryDirectory(prefix="cairn-data-agent-demo-") as temporary:
        runtime_root = Path(temporary)
        settings = Settings(
            model_mode="fake",
            database_url=f"sqlite:///{runtime_root / 'demo.db'}",
            storage_root=runtime_root,
            scenarios_root=resource_root / "scenarios",
            skills_root=resource_root / "skills",
        )
        service = build_service(settings)
        service.database.create_schema()
        try:
            _run_demo(service, resource_root)
        finally:
            service.database.engine.dispose()


def _run_demo(service: DataAgentService, resource_root: Path) -> None:
    summaries: list[dict[str, Any]] = []
    scenarios = service.scenarios.list()
    if not scenarios:
        raise DemoError("离线 Demo 未发现任何 Scenario；内置资源可能缺失")
    for scenario in scenarios:
        for case in _evaluation_cases(resource_root, scenario):
            run = _run_case(service, scenario=scenario, case=case)
            summaries.append(
                {
                    "scenario": run["scenario"]["name"],
                    "case": case["id"],
                    "status": run["status"],
                    "artifactCount": len(run["artifacts"]),
                    "finalArtifactKind": (
                        run["artifacts"][-1]["kind"] if run["artifacts"] else None
                    ),
                    "answer": run["answer"],
                }
            )

    if not summaries:
        raise DemoError("离线 Demo 未发现任何 evaluation case")

    print(
        json.dumps(
            {"version": "cairn.demo-result/v1", "mode": "offline", "runs": summaries},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
