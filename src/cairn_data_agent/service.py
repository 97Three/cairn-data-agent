from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .assets import AssetError, AssetService
from .context import build_context
from .contracts import AskRequest, Clarification, ConversationCreate, ProjectCreate
from .database import (
    ArtifactRecord,
    AssetRecord,
    ConversationRecord,
    Database,
    MessageRecord,
    ProjectRecord,
    RunRecord,
    StepRecord,
    utc_isoformat,
    utc_now,
)
from .executor import ExecutionError, PlanExecutor
from .model import (
    AgentModel,
    AnswerEvidenceError,
    ModelAdapterError,
    cited_evidence,
)
from .policy import PlanPolicyError, validate_plan
from .registry import RegistryError, ScenarioRegistry, SkillRegistry

logger = logging.getLogger(__name__)


class ServiceError(ValueError):
    pass


class NotFoundError(ServiceError):
    """Raised when a directly addressed API resource does not exist."""


EXPECTED_RUN_ERRORS = (
    AnswerEvidenceError,
    AssetError,
    ExecutionError,
    ModelAdapterError,
    PlanPolicyError,
    RegistryError,
    ServiceError,
)


def _run_failure_answer(error: Exception) -> str:
    if isinstance(error, EXPECTED_RUN_ERRORS):
        return f"执行失败：{error}"
    return "执行失败：内部错误，请查看服务日志。"


def _rollback_without_masking(session: Session, run_id: str) -> None:
    """Best-effort rollback while preserving the exception already being handled."""

    try:
        session.rollback()
    except Exception:
        logger.exception("run.rollback_failed", extra={"run_id": run_id})


def project_json(project: ProjectRecord) -> dict[str, Any]:
    return {"id": project.id, "name": project.name, "createdAt": utc_isoformat(project.created_at)}


def conversation_json(conversation: ConversationRecord) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "projectId": conversation.project_id,
        "title": conversation.title,
        "createdAt": utc_isoformat(conversation.created_at),
    }


def asset_json(asset: Any) -> dict[str, Any]:
    return {
        "id": asset.id,
        "projectId": asset.project_id,
        "filename": asset.filename,
        "mediaType": asset.media_type,
        "kind": asset.kind,
        "sha256": asset.blob_sha256,
        "byteSize": asset.byte_size,
        "profile": asset.profile,
        "createdAt": utc_isoformat(asset.created_at),
    }


def artifact_json(artifact: ArtifactRecord) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "projectId": artifact.project_id,
        "runId": artifact.run_id,
        "stepId": artifact.step_id,
        "kind": artifact.kind,
        "mimeType": artifact.mime_type,
        "sha256": artifact.blob_sha256,
        "byteSize": artifact.byte_size,
        "preview": artifact.preview,
        "lineage": artifact.lineage,
        "createdAt": utc_isoformat(artifact.created_at),
    }


def run_json(session: Session, run: RunRecord) -> dict[str, Any]:
    steps = session.scalars(
        select(StepRecord).where(StepRecord.run_id == run.id).order_by(StepRecord.position)
    ).all()
    artifacts = session.scalars(
        select(ArtifactRecord)
        .where(ArtifactRecord.run_id == run.id)
        .order_by(ArtifactRecord.created_at)
    ).all()
    return {
        "id": run.id,
        "projectId": run.project_id,
        "conversationId": run.conversation_id,
        "scenario": {"name": run.scenario_name, "version": run.scenario_version},
        "question": run.question,
        "status": run.status,
        "contextSnapshot": run.context_snapshot,
        "plan": run.plan,
        "clarification": run.clarification,
        "answer": run.answer,
        "steps": [
            {
                "id": step.step_id,
                "kind": step.kind,
                "status": step.status,
                "position": step.position,
                "detail": step.detail,
            }
            for step in steps
        ],
        "artifacts": [artifact_json(item) for item in artifacts],
        "createdAt": utc_isoformat(run.created_at),
        "completedAt": utc_isoformat(run.completed_at) if run.completed_at else None,
    }


class DataAgentService:
    def __init__(
        self,
        database: Database,
        assets: AssetService,
        scenarios: ScenarioRegistry,
        skills: SkillRegistry,
        executor: PlanExecutor,
        model: AgentModel,
    ):
        self.database = database
        self.assets = assets
        self.scenarios = scenarios
        self.skills = skills
        self.executor = executor
        self.model = model

    def create_project(self, request: ProjectCreate) -> dict[str, Any]:
        with self.database.session_factory() as session:
            project = ProjectRecord(name=request.name)
            session.add(project)
            session.flush()
            conversation = ConversationRecord(project_id=project.id, title="默认对话")
            session.add(conversation)
            session.commit()
            session.refresh(project)
            session.refresh(conversation)
            return {
                **project_json(project),
                "defaultConversationId": conversation.id,
            }

    def create_conversation(self, project_id: str, request: ConversationCreate) -> dict[str, Any]:
        with self.database.session_factory() as session:
            if session.get(ProjectRecord, project_id) is None:
                raise NotFoundError("Project 不存在")
            conversation = ConversationRecord(project_id=project_id, title=request.title)
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation_json(conversation)

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.database.session_factory() as session:
            project = session.get(ProjectRecord, project_id)
            if project is None:
                raise NotFoundError("Project 不存在")
            conversations = session.scalars(
                select(ConversationRecord)
                .where(ConversationRecord.project_id == project_id)
                .order_by(ConversationRecord.created_at, ConversationRecord.id)
            ).all()
            assets = session.scalars(
                select(AssetRecord)
                .where(AssetRecord.project_id == project_id)
                .order_by(AssetRecord.created_at)
            ).all()
            messages = session.scalars(
                select(MessageRecord)
                .where(MessageRecord.project_id == project_id)
                .order_by(MessageRecord.created_at)
            ).all()
            runs = session.scalars(
                select(RunRecord)
                .where(RunRecord.project_id == project_id)
                .order_by(RunRecord.created_at)
            ).all()
            return {
                **project_json(project),
                "defaultConversationId": conversations[0].id if conversations else None,
                "conversations": [conversation_json(item) for item in conversations],
                "assets": [asset_json(item) for item in assets],
                "messages": [
                    {
                        "id": item.id,
                        "conversationId": item.conversation_id,
                        "role": item.role,
                        "content": item.content,
                        "evidence": item.evidence,
                        "createdAt": utc_isoformat(item.created_at),
                    }
                    for item in messages
                ],
                "runs": [run_json(session, item) for item in runs],
            }

    @staticmethod
    def _resolve_conversation(
        session: Session, project_id: str, conversation_id: str | None
    ) -> ConversationRecord:
        if conversation_id is not None:
            conversation = session.get(ConversationRecord, conversation_id)
            if conversation is None or conversation.project_id != project_id:
                raise ServiceError("Conversation 不存在或不属于当前 Project")
            return conversation

        conversation = session.scalars(
            select(ConversationRecord)
            .where(ConversationRecord.project_id == project_id)
            .order_by(ConversationRecord.created_at, ConversationRecord.id)
            .limit(1)
        ).first()
        if conversation is None:
            conversation = ConversationRecord(project_id=project_id, title="默认对话")
            session.add(conversation)
            session.flush()
        return conversation

    def list_scenarios(self) -> list[dict[str, Any]]:
        return [
            {
                "name": bundle.manifest.metadata.name,
                "version": bundle.manifest.metadata.version,
                "displayName": bundle.manifest.metadata.display_name,
                "description": bundle.manifest.metadata.description,
                "supportedAssetTypes": bundle.manifest.supported_asset_types,
                "exampleQuestions": [example.question for example in bundle.examples],
            }
            for bundle in self.scenarios.list()
        ]

    def ingest_asset(
        self, *, project_id: str, filename: str, media_type: str, content: bytes
    ) -> dict[str, Any]:
        with self.database.session_factory() as session:
            if session.get(ProjectRecord, project_id) is None:
                raise NotFoundError("Project 不存在")
            asset = self.assets.ingest(
                session,
                project_id=project_id,
                filename=filename,
                media_type=media_type,
                content=content,
            )
            return asset_json(asset)

    def preview_asset(self, asset_id: str) -> dict[str, Any]:
        with self.database.session_factory() as session:
            asset = session.get(AssetRecord, asset_id)
            if asset is None:
                raise NotFoundError("资产不存在")
            return {"asset": asset_json(asset), "preview": self.assets.preview(asset)}

    def _persist_failed_run(self, run_id: str, error: Exception) -> dict[str, Any]:
        """Persist a terminal failure without reusing the transaction that failed."""

        with self.database.session_factory() as failure_session:
            try:
                failed_run = failure_session.get(RunRecord, run_id)
                if failed_run is None:
                    raise RuntimeError(f"已创建的 Run 无法恢复：{run_id}")
                failed_run.status = "failed"
                failed_run.answer = _run_failure_answer(error)
                failed_run.completed_at = utc_now()
                failure_session.commit()
                failure_session.refresh(failed_run)
                return run_json(failure_session, failed_run)
            except Exception:
                _rollback_without_masking(failure_session, run_id)
                raise

    def ask(self, project_id: str, request: AskRequest) -> dict[str, Any]:
        with self.database.session_factory() as session:
            project = session.get(ProjectRecord, project_id)
            if project is None:
                raise NotFoundError("Project 不存在")
            conversation = self._resolve_conversation(session, project_id, request.conversation_id)
            scenario = self.scenarios.get(request.scenario_name)
            found_assets = list(
                session.scalars(
                    select(AssetRecord).where(AssetRecord.id.in_(request.asset_ids))
                ).all()
            )
            assets_by_id = {asset.id: asset for asset in found_assets}
            if len(request.asset_ids) != len(set(request.asset_ids)):
                raise ServiceError("资产选择不能包含重复项")
            if set(assets_by_id) != set(request.asset_ids) or any(
                asset.project_id != project_id for asset in found_assets
            ):
                raise ServiceError("选择中包含不存在或不属于当前 Project 的资产")
            assets = [assets_by_id[asset_id] for asset_id in request.asset_ids]
            unsupported = sorted(
                {asset.kind for asset in assets} - set(scenario.manifest.supported_asset_types)
            )
            if unsupported:
                raise ServiceError(f"Scenario 不支持资产类型：{', '.join(unsupported)}")

            history_records = list(
                session.scalars(
                    select(MessageRecord)
                    .where(MessageRecord.conversation_id == conversation.id)
                    .order_by(MessageRecord.created_at.desc(), MessageRecord.id.desc())
                    .limit(8)
                ).all()
            )
            history = [
                {"role": message.role, "content": message.content}
                for message in reversed(history_records)
            ]

            session.add(
                MessageRecord(
                    project_id=project_id,
                    conversation_id=conversation.id,
                    role="user",
                    content=request.question,
                )
            )
            run = RunRecord(
                project_id=project_id,
                conversation_id=conversation.id,
                scenario_name=scenario.manifest.metadata.name,
                scenario_version=scenario.manifest.metadata.version,
                question=request.question,
                status="planning",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id
            logger.info("run.created", extra={"run_id": run.id})
            try:
                context = build_context(
                    scenario=scenario,
                    question=request.question,
                    assets=assets,
                    skills=self.skills.resolve(scenario.manifest.skills),
                    conversation_id=conversation.id,
                    history=history,
                )
                run.context_snapshot = context
                session.commit()
                decision = self.model.plan(context=context, scenario=scenario, assets=assets)
                if isinstance(decision, Clarification):
                    run.status = "needs_input"
                    run.clarification = decision.model_dump(by_alias=True)
                    run.completed_at = utc_now()
                    session.add(
                        MessageRecord(
                            project_id=project_id,
                            conversation_id=conversation.id,
                            role="assistant",
                            content=decision.question,
                        )
                    )
                    session.commit()
                    logger.info("run.needs_input", extra={"run_id": run.id})
                    return run_json(session, run)

                validate_plan(
                    decision,
                    set(request.asset_ids),
                    allowed_skill_ids=set(scenario.manifest.skills),
                )
                run.plan = decision.model_dump(mode="json", by_alias=True)
                run.status = "running"
                session.commit()
                result = self.executor.execute(
                    session,
                    project_id=project_id,
                    run_id=run.id,
                    plan=decision,
                    asset_records={asset.id: asset for asset in assets},
                )
                answer = self.model.answer(
                    question=request.question,
                    instruction=decision.answer_instruction,
                    artifacts=result.artifacts,
                )
                expected_evidence = cited_evidence(answer.text, result.artifacts)
                if answer.evidence != expected_evidence:
                    raise AnswerEvidenceError("Answer 的结构化 evidence 与正文引用不一致")
                run.answer = answer.text
                run.status = "succeeded"
                run.completed_at = utc_now()
                session.add(
                    MessageRecord(
                        project_id=project_id,
                        conversation_id=conversation.id,
                        role="assistant",
                        content=answer.text,
                        evidence=expected_evidence,
                    )
                )
                session.commit()
                logger.info("run.succeeded", extra={"run_id": run.id})
                return run_json(session, run)
            except Exception as error:
                logger.exception("run.failed", extra={"run_id": run_id})
                _rollback_without_masking(session, run_id)
                return self._persist_failed_run(run_id, error)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.database.session_factory() as session:
            run = session.get(RunRecord, run_id)
            if run is None:
                raise NotFoundError("Run 不存在")
            return run_json(session, run)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.database.session_factory() as session:
            artifact = session.get(ArtifactRecord, artifact_id)
            if artifact is None:
                raise NotFoundError("Artifact 不存在")
            return artifact_json(artifact)
