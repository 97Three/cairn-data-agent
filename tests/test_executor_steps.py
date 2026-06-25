from __future__ import annotations

import polars as pl
import pytest
from sqlalchemy.orm import Session

import cairn_data_agent.executor as executor_module
from cairn_data_agent.bootstrap import build_service
from cairn_data_agent.config import Settings
from cairn_data_agent.contracts import DataPlan, ProjectCreate
from cairn_data_agent.database import RunRecord
from cairn_data_agent.executor import ExecutionError, _markdown_paragraphs
from cairn_data_agent.policy import validate_plan


def test_all_tabular_primitives_share_one_executor(settings: Settings) -> None:
    service = build_service(settings)
    service.database.create_schema()
    project = service.create_project(ProjectCreate(name="执行器测试"))
    left = service.ingest_asset(
        project_id=project["id"],
        filename="values.csv",
        media_type="text/csv",
        content=b"id,category,amount\n1,A,4\n2,A,8\n3,B,12\n",
    )
    right = service.ingest_asset(
        project_id=project["id"],
        filename="rates.csv",
        media_type="text/csv",
        content=b"id,rate\n1,2\n2,3\n3,4\n",
    )
    plan = DataPlan.model_validate(
        {
            "version": "cairn.data-plan/v1",
            "goal": "覆盖通用表格原语",
            "asset_ids": [left["id"], right["id"]],
            "steps": [
                {"id": "inspect_input", "kind": "inspect", "asset_id": left["id"]},
                {
                    "id": "filtered",
                    "kind": "filter",
                    "input": f"asset:{left['id']}",
                    "predicates": [{"column": "amount", "operator": "gte", "value": 8}],
                },
                {
                    "id": "selected",
                    "kind": "select",
                    "input": "step:filtered",
                    "columns": ["id", "category", "amount"],
                },
                {
                    "id": "joined",
                    "kind": "join",
                    "left": "step:selected",
                    "right": f"asset:{right['id']}",
                    "left_on": ["id"],
                    "right_on": ["id"],
                    "how": "left",
                },
                {
                    "id": "derived",
                    "kind": "derive",
                    "input": "step:joined",
                    "output_column": "weighted",
                    "operation": "multiply",
                    "left_column": "amount",
                    "right_column": "rate",
                },
                {
                    "id": "grouped",
                    "kind": "aggregate",
                    "input": "step:derived",
                    "group_by": ["category"],
                    "metrics": [{"column": "weighted", "operation": "sum", "alias": "total"}],
                },
                {
                    "id": "sorted",
                    "kind": "sort",
                    "input": "step:grouped",
                    "by": [{"column": "total", "descending": True}],
                },
                {"id": "limited", "kind": "limit", "input": "step:sorted", "count": 1},
            ],
        }
    )
    validate_plan(plan, {left["id"], right["id"]})

    with service.database.session_factory() as session:
        run = RunRecord(
            project_id=project["id"],
            conversation_id=project["defaultConversationId"],
            scenario_name="test",
            scenario_version="0.1.0",
            question="test",
            status="running",
        )
        session.add(run)
        session.commit()
        records = _assets(session, left["id"], right["id"])
        result = service.executor.execute(
            session,
            project_id=project["id"],
            run_id=run.id,
            plan=plan,
            asset_records=records,
        )
    assert len(result.artifacts) == 8
    assert result.artifacts[0].kind == "profile"
    assert result.artifacts[-1].preview["rows"] == [{"category": "B", "total": 48}]


def _assets(session: Session, *asset_ids: str) -> dict[str, object]:
    from cairn_data_agent.database import AssetRecord

    records = [session.get(AssetRecord, asset_id) for asset_id in asset_ids]
    assert all(record is not None for record in records)
    return {record.id: record for record in records if record is not None}


def test_join_cardinality_is_rejected_before_expanded_materialization(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = build_service(settings)
    service.database.create_schema()
    project = service.create_project(ProjectCreate(name="join 基数门禁"))
    repeated_rows = "".join(f"same,{index}\n" for index in range(101))
    left = service.ingest_asset(
        project_id=project["id"],
        filename="left.csv",
        media_type="text/csv",
        content=("key,left_value\n" + repeated_rows).encode(),
    )
    right = service.ingest_asset(
        project_id=project["id"],
        filename="right.csv",
        media_type="text/csv",
        content=("key,right_value\n" + repeated_rows).encode(),
    )
    plan = DataPlan.model_validate(
        {
            "version": "cairn.data-plan/v1",
            "goal": "拒绝过大的多对多连接",
            "asset_ids": [left["id"], right["id"]],
            "steps": [
                {
                    "id": "joined",
                    "kind": "join",
                    "left": f"asset:{left['id']}",
                    "right": f"asset:{right['id']}",
                    "left_on": ["key"],
                    "right_on": ["key"],
                }
            ],
        }
    )
    validate_plan(plan, {left["id"], right["id"]})

    original_join = pl.DataFrame.join
    join_input_heights: list[tuple[int, int]] = []

    def guarded_join(
        frame: pl.DataFrame, other: pl.DataFrame, *args: object, **kwargs: object
    ) -> pl.DataFrame:
        join_input_heights.append((frame.height, other.height))
        if frame.height > 1 and other.height > 1:
            pytest.fail("expanded join was materialized before the cardinality guard")
        return original_join(frame, other, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "join", guarded_join)
    with service.database.session_factory() as session:
        run = RunRecord(
            project_id=project["id"],
            conversation_id=project["defaultConversationId"],
            scenario_name="test",
            scenario_version="0.1.0",
            question="test",
            status="running",
        )
        session.add(run)
        session.commit()
        records = _assets(session, left["id"], right["id"])

        with pytest.raises(ExecutionError, match="join 预估输出超过 10,000 行"):
            service.executor.execute(
                session,
                project_id=project["id"],
                run_id=run.id,
                plan=plan,
                asset_records=records,
            )

    assert join_input_heights == [(1, 1)]


def test_markdown_paragraph_line_numbers_survive_consecutive_blank_lines() -> None:
    text = "first\nline\n\n\n\nsecond\nline\n\n\nlast"

    assert _markdown_paragraphs(text) == [
        (1, 2, "first\nline"),
        (6, 7, "second\nline"),
        (10, 10, "last"),
    ]


def test_aggregate_and_join_have_stable_artifact_order(settings: Settings) -> None:
    service = build_service(settings)
    service.database.create_schema()
    project = service.create_project(ProjectCreate(name="确定性顺序"))
    left = service.ingest_asset(
        project_id=project["id"],
        filename="left.csv",
        media_type="text/csv",
        content=b"id,category,amount\n3,B,1\n1,A,2\n2,B,3\n",
    )
    right = service.ingest_asset(
        project_id=project["id"],
        filename="right.csv",
        media_type="text/csv",
        content=b"category,label\nB,b-first\nA,a-only\nB,b-second\n",
    )
    plan = DataPlan.model_validate(
        {
            "version": "cairn.data-plan/v1",
            "goal": "验证稳定结果顺序",
            "asset_ids": [left["id"], right["id"]],
            "steps": [
                {
                    "id": "summary",
                    "kind": "aggregate",
                    "input": f"asset:{left['id']}",
                    "group_by": ["category"],
                    "metrics": [{"column": "amount", "operation": "sum", "alias": "total"}],
                },
                {
                    "id": "joined",
                    "kind": "join",
                    "left": f"asset:{left['id']}",
                    "right": f"asset:{right['id']}",
                    "left_on": ["category"],
                    "right_on": ["category"],
                    "how": "inner",
                },
            ],
        }
    )
    validate_plan(plan, {left["id"], right["id"]})

    executions = []
    with service.database.session_factory() as session:
        records = _assets(session, left["id"], right["id"])
        for _ in range(2):
            run = RunRecord(
                project_id=project["id"],
                conversation_id=project["defaultConversationId"],
                scenario_name="test",
                scenario_version="0.1.0",
                question="test",
                status="running",
            )
            session.add(run)
            session.commit()
            executions.append(
                service.executor.execute(
                    session,
                    project_id=project["id"],
                    run_id=run.id,
                    plan=plan,
                    asset_records=records,
                ).artifacts
            )

    assert executions[0][0].preview["rows"] == [
        {"category": "A", "total": 2},
        {"category": "B", "total": 4},
    ]
    assert [(row["id"], row["label"]) for row in executions[0][1].preview["rows"]] == [
        (3, "b-first"),
        (3, "b-second"),
        (1, "a-only"),
        (2, "b-first"),
        (2, "b-second"),
    ]
    assert [artifact.blob_sha256 for artifact in executions[0]] == [
        artifact.blob_sha256 for artifact in executions[1]
    ]


def test_artifact_content_size_is_limited(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = build_service(settings)
    service.database.create_schema()
    project = service.create_project(ProjectCreate(name="Artifact 大小边界"))
    asset = service.ingest_asset(
        project_id=project["id"],
        filename="values.csv",
        media_type="text/csv",
        content=b"id,value\n1,example\n",
    )
    plan = DataPlan.model_validate(
        {
            "version": "cairn.data-plan/v1",
            "goal": "检查输入",
            "asset_ids": [asset["id"]],
            "steps": [{"id": "inspect", "kind": "inspect", "asset_id": asset["id"]}],
        }
    )
    monkeypatch.setattr(executor_module, "ARTIFACT_CONTENT_MAX_BYTES", 10)

    with service.database.session_factory() as session:
        run = RunRecord(
            project_id=project["id"],
            conversation_id=project["defaultConversationId"],
            scenario_name="test",
            scenario_version="0.1.0",
            question="test",
            status="running",
        )
        session.add(run)
        session.commit()
        records = _assets(session, asset["id"])

        with pytest.raises(ExecutionError, match="25 MiB"):
            service.executor.execute(
                session,
                project_id=project["id"],
                run_id=run.id,
                plan=plan,
                asset_records=records,
            )
