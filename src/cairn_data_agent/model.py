from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from .config import Settings
from .contracts import Clarification, ClarificationOption, DataPlan
from .database import ArtifactRecord, AssetRecord
from .previews import MODEL_PREVIEW_MAX_BYTES, bounded_preview
from .registry import ScenarioBundle

PlannerDecision = DataPlan | Clarification
ARTIFACT_CITATION_PATTERN = re.compile(r"\[artifact:([A-Za-z0-9-]+)\]")


@dataclass(frozen=True)
class AnswerResult:
    text: str
    evidence: list[dict[str, Any]]


class AnswerEvidenceError(ValueError):
    """Raised when an answer cites evidence it was not allowed to inspect."""


class ModelAdapterError(RuntimeError):
    """Raised for stable, user-safe model adapter failures."""


class AgentModel(Protocol):
    def plan(
        self,
        *,
        context: dict[str, Any],
        scenario: ScenarioBundle,
        assets: list[AssetRecord],
    ) -> PlannerDecision: ...

    def answer(
        self,
        *,
        question: str,
        instruction: str,
        artifacts: list[ArtifactRecord],
    ) -> AnswerResult: ...


def _replace_placeholders(value: Any, assets: list[AssetRecord], question: str) -> Any:
    tabular = [asset.id for asset in assets if asset.kind in {"csv", "xlsx"}]
    documents = [asset.id for asset in assets if asset.kind == "markdown"]
    selected = [asset.id for asset in assets]

    if isinstance(value, dict):
        return {
            key: _replace_placeholders(nested, assets, question) for key, nested in value.items()
        }
    if isinstance(value, list):
        list_result: list[Any] = []
        for item in value:
            if item == "$selected":
                list_result.extend(selected)
            elif item == "$documents":
                list_result.extend(documents)
            elif item == "$tabular":
                list_result.extend(tabular)
            else:
                list_result.append(_replace_placeholders(item, assets, question))
        return list_result
    if isinstance(value, str):
        replacements: dict[str, str] = {
            "$question": question,
            "$tabular": tabular[0] if tabular else "",
            "$document": documents[0] if documents else "",
        }
        string_result = value
        for placeholder, replacement in replacements.items():
            string_result = string_result.replace(placeholder, replacement)
        return string_result
    return value


def _evidence(artifacts: list[ArtifactRecord]) -> list[dict[str, Any]]:
    return [
        {
            "artifactId": artifact.id,
            "stepId": artifact.step_id,
            "sha256": artifact.blob_sha256,
            "kind": artifact.kind,
        }
        for artifact in artifacts
    ]


def cited_evidence(text: str, artifacts: list[ArtifactRecord]) -> list[dict[str, Any]]:
    """Build evidence only from citations present in ``text`` and available to the answerer."""

    available = {artifact.id: artifact for artifact in artifacts}
    citation_ids = list(dict.fromkeys(ARTIFACT_CITATION_PATTERN.findall(text)))
    if not citation_ids:
        raise AnswerEvidenceError("Answer 必须至少引用一个可核验 Artifact")
    unknown = [artifact_id for artifact_id in citation_ids if artifact_id not in available]
    if unknown:
        raise AnswerEvidenceError(
            "Answer 引用了未提供给 Answerer 的 Artifact：" + ", ".join(unknown)
        )
    return _evidence([available[artifact_id] for artifact_id in citation_ids])


class FakeAgentModel:
    """Offline model double whose behavior lives in Scenario example packs."""

    def plan(
        self,
        *,
        context: dict[str, Any],
        scenario: ScenarioBundle,
        assets: list[AssetRecord],
    ) -> PlannerDecision:
        question = str(context["question"])
        lowered = question.casefold()
        ranked = sorted(
            scenario.examples,
            key=lambda example: sum(token.casefold() in lowered for token in example.match),
            reverse=True,
        )
        if not ranked:
            return Clarification(question="你希望分析什么？", reason="当前 Scenario 没有离线示例。")
        best = ranked[0]
        score = sum(token.casefold() in lowered for token in best.match)
        if best.match and score == 0:
            return Clarification(
                question="请选择一个更具体的分析目标。",
                reason="离线模型只运行 Scenario 声明的可复现示例。",
                options=[
                    ClarificationOption(id=example.id, label=example.question)
                    for example in scenario.examples[:3]
                ],
            )
        resolved = _replace_placeholders(best.plan, assets, question)
        try:
            return DataPlan.model_validate(resolved)
        except ValidationError as error:
            return Clarification(
                question="请确认已选择该示例需要的数据类型。",
                reason=f"示例计划无法绑定当前资产：{error.errors()[0]['msg']}",
            )

    def answer(
        self,
        *,
        question: str,
        instruction: str,
        artifacts: list[ArtifactRecord],
    ) -> AnswerResult:
        if not artifacts:
            return AnswerResult(text="没有可用于回答的执行证据。", evidence=[])
        final = artifacts[-1]
        preview = bounded_preview(final.preview, max_bytes=MODEL_PREVIEW_MAX_BYTES)
        if final.kind == "evidence":
            hits = preview.get("hits", [])
            if not hits:
                body = "没有在所选文档中找到足够相关的段落。"
            else:
                excerpts = [
                    f"- {hit['quote']}【{hit['filename']}:L{hit['lineStart']}-L{hit['lineEnd']}】"
                    for hit in hits[:5]
                ]
                body = "从所选文档中检索到以下证据：\n" + "\n".join(excerpts)
        else:
            rows = preview.get("rows", [])
            body = (
                f"确定性计算得到 {preview.get('rowCount', len(rows))} 行结果。"
                f"结果预览：{json.dumps(rows[:5], ensure_ascii=False)}"
            )
        if instruction:
            body += f"\n\n回答口径：{instruction}"
        body += f"\n\n证据：[artifact:{final.id}]（SHA-256: {final.blob_sha256}）"
        return AnswerResult(text=body, evidence=cited_evidence(body, [final]))


class OpenAICompatibleAgentModel:
    def __init__(self, settings: Settings):
        self._endpoint = settings.model_base_url.rstrip("/") + "/chat/completions"
        self._model = settings.model_id
        self._api_key = settings.model_api_key

    def _complete(self, messages: list[dict[str, str]]) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    self._endpoint,
                    headers=headers,
                    json={"model": self._model, "messages": messages, "temperature": 0},
                )
                response.raise_for_status()
                payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise ModelAdapterError("模型服务调用失败或响应格式无效") from error

    @staticmethod
    def _json_content(content: str) -> Any:
        stripped = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
        return json.loads(fenced.group(1) if fenced else stripped)

    def plan(
        self,
        *,
        context: dict[str, Any],
        scenario: ScenarioBundle,
        assets: list[AssetRecord],
    ) -> PlannerDecision:
        schema = {
            "plan": DataPlan.model_json_schema(),
            "clarification": Clarification.model_json_schema(),
        }
        content = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "你是受控 Data Agent Planner。只能返回一个 JSON 对象：DataPlan 或 "
                        "Clarification。不得输出 SQL、shell、路径或未选资产。契约："
                        + json.dumps(schema, ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ]
        )
        try:
            raw = self._json_content(content)
            if isinstance(raw, dict) and raw.get("version") == "cairn.clarification/v1":
                return Clarification.model_validate(raw)
            return DataPlan.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise ModelAdapterError("Planner 返回内容不符合 DataPlan/Clarification 契约") from error

    def answer(
        self,
        *,
        question: str,
        instruction: str,
        artifacts: list[ArtifactRecord],
    ) -> AnswerResult:
        visible_artifacts = artifacts[-8:]
        bounded = [
            {
                "artifactId": artifact.id,
                "stepId": artifact.step_id,
                "sha256": artifact.blob_sha256,
                "preview": bounded_preview(artifact.preview, max_bytes=MODEL_PREVIEW_MAX_BYTES),
            }
            for artifact in visible_artifacts
        ]
        text = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "只根据给定 Artifact 回答。每个事实结论都引用 [artifact:<id>]；"
                        "证据不足就明确说明。不要引入外部事实。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "instruction": instruction, "artifacts": bounded},
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        return AnswerResult(text=text, evidence=cited_evidence(text, visible_artifacts))


def create_model(settings: Settings) -> AgentModel:
    if settings.model_mode == "openai-compatible":
        return OpenAICompatibleAgentModel(settings)
    return FakeAgentModel()
