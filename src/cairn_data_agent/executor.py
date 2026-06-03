from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import polars as pl
from sqlalchemy.orm import Session

from .assets import AssetService, frame_preview
from .contracts import (
    AggregateStep,
    DataPlan,
    DeriveStep,
    FilterStep,
    JoinStep,
    LimitStep,
    Metric,
    Predicate,
    RetrieveStep,
    SelectStep,
    SkillStep,
    SortStep,
)
from .database import ArtifactRecord, AssetRecord, StepRecord, utc_now
from .previews import ARTIFACT_PREVIEW_MAX_BYTES, bounded_preview
from .skill_runner import TrustedSkillRunner
from .storage import LocalBlobStore


class ExecutionError(ValueError):
    pass


ARTIFACT_CONTENT_MAX_BYTES = 25 * 1024 * 1024
TABLE_OUTPUT_MAX_ROWS = 10_000


@dataclass(frozen=True)
class ExecutionResult:
    artifacts: list[ArtifactRecord]


def _ensure_columns(frame: pl.DataFrame, names: list[str]) -> None:
    missing = sorted(set(names) - set(frame.columns))
    if missing:
        raise ExecutionError(f"字段不存在：{', '.join(missing)}")


def _predicate_expression(predicate: Predicate) -> pl.Expr:
    column = pl.col(predicate.column)
    match predicate.operator:
        case "eq":
            return column == predicate.value
        case "neq":
            return column != predicate.value
        case "gt":
            return column > predicate.value
        case "gte":
            return column >= predicate.value
        case "lt":
            return column < predicate.value
        case "lte":
            return column <= predicate.value
        case "contains":
            return column.cast(pl.String).str.contains(str(predicate.value), literal=True)
        case "in":
            if not isinstance(predicate.value, list):
                raise ExecutionError("in 操作的 value 必须是数组")
            return column.is_in(predicate.value)
        case "is_null":
            return column.is_null()
        case "is_not_null":
            return column.is_not_null()
    raise ExecutionError("不支持的过滤操作")


def _metric_expression(metric: Metric) -> pl.Expr:
    column = pl.col(metric.column)
    match metric.operation:
        case "count":
            return column.count().alias(metric.alias)
        case "sum":
            return column.sum().alias(metric.alias)
        case "mean":
            return column.mean().alias(metric.alias)
        case "min":
            return column.min().alias(metric.alias)
        case "max":
            return column.max().alias(metric.alias)
        case "median":
            return column.median().alias(metric.alias)
    raise ExecutionError("不支持的聚合操作")


def _table_payload(frame: pl.DataFrame) -> dict[str, Any]:
    if frame.height > TABLE_OUTPUT_MAX_ROWS:
        raise ExecutionError("步骤输出超过 10,000 行；请先聚合或 limit")
    return frame_preview(frame, row_limit=frame.height)


def _temporary_column_name(frames: tuple[pl.DataFrame, ...], stem: str) -> str:
    used = {column for frame in frames for column in frame.columns}
    candidate = stem
    while candidate in used:
        candidate = f"_{candidate}"
    return candidate


def _estimate_join_output_rows(
    left: pl.DataFrame,
    right: pl.DataFrame,
    step: JoinStep,
    *,
    stop_after: int = TABLE_OUTPUT_MAX_ROWS,
) -> int:
    """Count join rows from key multiplicities without materializing the expanded join.

    The count frames contain one row per distinct key, so their join cannot create the
    many-to-many expansion that this guard is intended to reject.
    """
    if step.how == "left" and left.height > stop_after:
        return left.height

    left_count_name = _temporary_column_name((left, right), "__cairn_left_count")
    right_count_name = _temporary_column_name((left, right), f"{left_count_name}_right")
    left_counts = left.group_by(step.left_on).len(name=left_count_name)
    right_counts = right.group_by(step.right_on).len(name=right_count_name)
    matched_counts = left_counts.join(
        right_counts,
        left_on=step.left_on,
        right_on=step.right_on,
        how=step.how,
        nulls_equal=False,
        maintain_order="left",
    )

    total = 0
    for left_count, right_count in matched_counts.select(
        left_count_name, right_count_name
    ).iter_rows():
        right_multiplier = right_count
        if right_multiplier is None:
            right_multiplier = 1 if step.how == "left" else 0
        total += int(left_count) * int(right_multiplier)
        if total > stop_after:
            return total
    return total


def _markdown_paragraphs(text: str) -> list[tuple[int, int, str]]:
    paragraphs: list[tuple[int, int, str]] = []
    buffered: list[str] = []
    line_start = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not buffered:
                line_start = line_number
            buffered.append(line)
            continue
        if buffered:
            paragraphs.append((line_start, line_number - 1, "\n".join(buffered)))
            buffered = []

    if buffered:
        paragraphs.append((line_start, line_start + len(buffered) - 1, "\n".join(buffered)))
    return paragraphs


class PlanExecutor:
    def __init__(self, assets: AssetService, blobs: LocalBlobStore, skills: TrustedSkillRunner):
        self._assets = assets
        self._blobs = blobs
        self._skills = skills

    def execute(
        self,
        session: Session,
        *,
        project_id: str,
        run_id: str,
        plan: DataPlan,
        asset_records: dict[str, AssetRecord],
    ) -> ExecutionResult:
        values: dict[str, pl.DataFrame | dict[str, Any]] = {}
        artifact_by_step: dict[str, ArtifactRecord] = {}
        artifacts: list[ArtifactRecord] = []
        for position, step in enumerate(plan.steps):
            step_record = StepRecord(
                run_id=run_id,
                step_id=step.id,
                kind=step.kind,
                status="running",
                position=position,
                detail={},
            )
            session.add(step_record)
            session.commit()
            try:
                value = self._execute_step(step, values, asset_records)
                raw_preview = (
                    frame_preview(value, row_limit=50) if isinstance(value, pl.DataFrame) else value
                )
                preview = bounded_preview(raw_preview, max_bytes=ARTIFACT_PREVIEW_MAX_BYTES)
                lineage = self._lineage(step, asset_records, artifact_by_step)
                artifact = self._persist_artifact(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    step_id=step.id,
                    value=value,
                    preview=preview,
                    lineage=lineage,
                )
                values[step.id] = value
                artifact_by_step[step.id] = artifact
                artifacts.append(artifact)
                step_record.status = "succeeded"
                step_record.completed_at = utc_now()
                step_record.detail = {"artifactId": artifact.id, "sha256": artifact.blob_sha256}
                session.commit()
            except Exception as error:
                step_record.status = "failed"
                step_record.completed_at = utc_now()
                step_record.detail = {"error": str(error)}
                session.commit()
                if isinstance(error, ExecutionError):
                    raise
                raise ExecutionError(f"步骤 {step.id} 执行失败：{error}") from error
        return ExecutionResult(artifacts=artifacts)

    def _resolve_table(
        self,
        reference: str,
        values: dict[str, pl.DataFrame | dict[str, Any]],
        assets: dict[str, AssetRecord],
    ) -> pl.DataFrame:
        kind, identifier = reference.split(":", 1)
        if kind == "asset":
            asset = assets[identifier]
            if asset.kind not in {"csv", "xlsx"}:
                raise ExecutionError("表格步骤不能读取文档资产")
            return self._assets.load_table(asset)
        value = values[identifier]
        if not isinstance(value, pl.DataFrame):
            raise ExecutionError("表格步骤的上游不是表格")
        return value

    def _execute_step(
        self,
        step: Any,
        values: dict[str, pl.DataFrame | dict[str, Any]],
        assets: dict[str, AssetRecord],
    ) -> pl.DataFrame | dict[str, Any]:
        if step.kind == "inspect":
            return {**assets[step.asset_id].profile, "kind": "profile", "assetId": step.asset_id}
        if isinstance(step, FilterStep):
            frame = self._resolve_table(step.input, values, assets)
            _ensure_columns(frame, [predicate.column for predicate in step.predicates])
            expression = _predicate_expression(step.predicates[0])
            for predicate in step.predicates[1:]:
                expression &= _predicate_expression(predicate)
            return frame.filter(expression)
        if isinstance(step, SelectStep):
            frame = self._resolve_table(step.input, values, assets)
            _ensure_columns(frame, step.columns)
            return frame.select(step.columns)
        if isinstance(step, DeriveStep):
            frame = self._resolve_table(step.input, values, assets)
            needed = [step.left_column] + ([step.right_column] if step.right_column else [])
            _ensure_columns(frame, needed)
            left = pl.col(step.left_column)
            right = pl.col(step.right_column) if step.right_column else pl.lit(step.right_value)
            operations = {
                "add": left + right,
                "subtract": left - right,
                "multiply": left * right,
                "divide": left / right,
            }
            return frame.with_columns(operations[step.operation].alias(step.output_column))
        if isinstance(step, AggregateStep):
            frame = self._resolve_table(step.input, values, assets)
            columns = step.group_by + [metric.column for metric in step.metrics]
            _ensure_columns(frame, columns)
            expressions = [_metric_expression(metric) for metric in step.metrics]
            if step.group_by:
                return frame.group_by(step.group_by).agg(expressions).sort(step.group_by)
            return frame.select(expressions)
        if isinstance(step, JoinStep):
            left_frame = self._resolve_table(step.left, values, assets)
            right_frame = self._resolve_table(step.right, values, assets)
            _ensure_columns(left_frame, step.left_on)
            _ensure_columns(right_frame, step.right_on)
            estimated_rows = _estimate_join_output_rows(left_frame, right_frame, step)
            if estimated_rows > TABLE_OUTPUT_MAX_ROWS:
                raise ExecutionError("join 预估输出超过 10,000 行；请在 join 前过滤或聚合重复键")
            return left_frame.join(
                right_frame,
                left_on=step.left_on,
                right_on=step.right_on,
                how=step.how,
                nulls_equal=False,
                maintain_order="left_right",
            )
        if isinstance(step, SortStep):
            frame = self._resolve_table(step.input, values, assets)
            names = [item.column for item in step.by]
            _ensure_columns(frame, names)
            return frame.sort(names, descending=[item.descending for item in step.by])
        if isinstance(step, LimitStep):
            return self._resolve_table(step.input, values, assets).head(step.count)
        if isinstance(step, RetrieveStep):
            return self._retrieve(step, assets)
        if isinstance(step, SkillStep):
            input_value: pl.DataFrame | dict[str, Any] | None = None
            if step.input:
                kind, identifier = step.input.split(":", 1)
                if kind == "asset":
                    input_value = self._assets.load_table(assets[identifier])
                else:
                    input_value = values[identifier]
            if isinstance(input_value, pl.DataFrame):
                serialized_input: Any = _table_payload(input_value)
            else:
                serialized_input = input_value
            return self._skills.execute(
                step.skill,
                {"input": serialized_input, "arguments": step.arguments},
            )
        raise ExecutionError(f"执行器没有实现步骤：{step.kind}")

    def _retrieve(self, step: RetrieveStep, assets: dict[str, AssetRecord]) -> dict[str, Any]:
        tokens = {
            token.casefold() for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", step.query)
        }
        hits: list[dict[str, Any]] = []
        for asset_id in step.asset_ids:
            asset = assets[asset_id]
            text = self._assets.load_document(asset)
            for line_start, line_end, paragraph in _markdown_paragraphs(text):
                normalized = paragraph.casefold()
                score = sum(token in normalized for token in tokens)
                if score:
                    hits.append(
                        {
                            "assetId": asset.id,
                            "filename": asset.filename,
                            "lineStart": line_start,
                            "lineEnd": line_end,
                            "quote": paragraph.strip()[:500],
                            "score": score,
                        }
                    )
        hits.sort(key=lambda item: (-item["score"], item["filename"], item["lineStart"]))
        return {"kind": "evidence", "query": step.query, "hits": hits[: step.top_k]}

    def _lineage(
        self,
        step: Any,
        assets: dict[str, AssetRecord],
        artifacts: dict[str, ArtifactRecord],
    ) -> dict[str, Any]:
        asset_ids: list[str] = []
        artifact_ids: list[str] = []
        references = step.input_references()
        if step.kind == "inspect":
            asset_ids.append(step.asset_id)
        elif step.kind == "retrieve":
            asset_ids.extend(step.asset_ids)
        for reference in references:
            kind, identifier = reference.split(":", 1)
            if kind == "asset":
                asset_ids.append(identifier)
            else:
                artifact_ids.append(artifacts[identifier].id)
        return {
            "version": "cairn.lineage/v1",
            "inputAssetIds": asset_ids,
            "inputAssetSha256": [assets[item].blob_sha256 for item in asset_ids],
            "inputArtifactIds": artifact_ids,
            "step": step.model_dump(by_alias=True),
        }

    def _persist_artifact(
        self,
        session: Session,
        *,
        project_id: str,
        run_id: str,
        step_id: str,
        value: pl.DataFrame | dict[str, Any],
        preview: dict[str, Any],
        lineage: dict[str, Any],
    ) -> ArtifactRecord:
        payload = _table_payload(value) if isinstance(value, pl.DataFrame) else value
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(content) > ARTIFACT_CONTENT_MAX_BYTES:
            raise ExecutionError("Artifact 内容超过教学版 25 MiB 上限")
        stored = self._blobs.put(content)
        kind = "table" if isinstance(value, pl.DataFrame) else str(value.get("kind", "json"))
        artifact = ArtifactRecord(
            project_id=project_id,
            run_id=run_id,
            step_id=step_id,
            kind=kind,
            mime_type="application/json",
            blob_sha256=stored.sha256,
            byte_size=stored.byte_size,
            preview=preview,
            lineage=lineage,
        )
        session.add(artifact)
        session.flush()
        return artifact
