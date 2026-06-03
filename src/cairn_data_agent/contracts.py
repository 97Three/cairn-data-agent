from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metric(StrictModel):
    column: str
    operation: Literal["count", "sum", "mean", "min", "max", "median"]
    alias: str


class Predicate(StrictModel):
    column: str
    operator: Literal[
        "eq", "neq", "gt", "gte", "lt", "lte", "contains", "in", "is_null", "is_not_null"
    ]
    value: Any | None = None


class BaseStep(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: str

    def input_references(self) -> list[str]:
        return []


class InspectStep(BaseStep):
    kind: Literal["inspect"]
    asset_id: str


class FilterStep(BaseStep):
    kind: Literal["filter"]
    input: str
    predicates: list[Predicate] = Field(min_length=1, max_length=20)

    def input_references(self) -> list[str]:
        return [self.input]


class SelectStep(BaseStep):
    kind: Literal["select"]
    input: str
    columns: list[str] = Field(min_length=1, max_length=100)

    def input_references(self) -> list[str]:
        return [self.input]


class DeriveStep(BaseStep):
    kind: Literal["derive"]
    input: str
    output_column: str
    operation: Literal["add", "subtract", "multiply", "divide"]
    left_column: str
    right_column: str | None = None
    right_value: float | None = None

    @model_validator(mode="after")
    def exactly_one_right_operand(self) -> DeriveStep:
        if (self.right_column is None) == (self.right_value is None):
            raise ValueError("derive requires exactly one of right_column or right_value")
        return self

    def input_references(self) -> list[str]:
        return [self.input]


class AggregateStep(BaseStep):
    kind: Literal["aggregate"]
    input: str
    group_by: list[str] = Field(default_factory=list, max_length=20)
    metrics: list[Metric] = Field(min_length=1, max_length=20)

    def input_references(self) -> list[str]:
        return [self.input]


class JoinStep(BaseStep):
    kind: Literal["join"]
    left: str
    right: str
    left_on: list[str] = Field(min_length=1, max_length=10)
    right_on: list[str] = Field(min_length=1, max_length=10)
    how: Literal["inner", "left"] = "inner"

    @model_validator(mode="after")
    def key_lengths_match(self) -> JoinStep:
        if len(self.left_on) != len(self.right_on):
            raise ValueError("join key lists must have equal length")
        return self

    def input_references(self) -> list[str]:
        return [self.left, self.right]


class SortColumn(StrictModel):
    column: str
    descending: bool = False


class SortStep(BaseStep):
    kind: Literal["sort"]
    input: str
    by: list[SortColumn] = Field(min_length=1, max_length=10)

    def input_references(self) -> list[str]:
        return [self.input]


class LimitStep(BaseStep):
    kind: Literal["limit"]
    input: str
    count: int = Field(ge=1, le=10_000)

    def input_references(self) -> list[str]:
        return [self.input]


class RetrieveStep(BaseStep):
    kind: Literal["retrieve"]
    asset_ids: list[str] = Field(min_length=1, max_length=20)
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SkillStep(BaseStep):
    kind: Literal["skill"]
    skill: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
    input: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    def input_references(self) -> list[str]:
        return [self.input] if self.input else []


PlanStep = Annotated[
    InspectStep
    | FilterStep
    | SelectStep
    | DeriveStep
    | AggregateStep
    | JoinStep
    | SortStep
    | LimitStep
    | RetrieveStep
    | SkillStep,
    Field(discriminator="kind"),
]


class DataPlan(StrictModel):
    version: Literal["cairn.data-plan/v1"]
    goal: str = Field(min_length=1, max_length=2000)
    asset_ids: list[str] = Field(min_length=1, max_length=20)
    steps: list[PlanStep] = Field(min_length=1, max_length=32)
    answer_instruction: str = Field(default="基于全部结果给出简洁结论。", max_length=1000)


class ClarificationOption(StrictModel):
    id: str
    label: str


class Clarification(StrictModel):
    version: Literal["cairn.clarification/v1"] = "cairn.clarification/v1"
    question: str
    reason: str
    options: list[ClarificationOption] = Field(default_factory=list, max_length=5)


class ScenarioMetadata(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
    display_name: str = Field(alias="displayName")
    description: str


class ScenarioExample(StrictModel):
    id: str
    question: str
    match: list[str] = Field(default_factory=list, max_length=20)
    plan: dict[str, Any]


class ScenarioManifest(StrictModel):
    api_version: Literal["cairn.data-agent/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Scenario"]
    metadata: ScenarioMetadata
    supported_asset_types: list[Literal["csv", "xlsx", "markdown"]] = Field(
        alias="supportedAssetTypes", min_length=1, max_length=3
    )
    instructions: str = Field(min_length=1, max_length=8000)
    knowledge: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=20)
    examples: str
    evaluations: str


class SkillPermissions(StrictModel):
    network: bool = False
    filesystem: Literal["none", "bound-inputs"] = "none"


class SkillMetadata(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
    description: str


class SkillManifest(StrictModel):
    api_version: Literal["cairn.data-agent/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Skill"]
    metadata: SkillMetadata
    mode: Literal["instruction", "executable"]
    effect: Literal["read", "write"]
    entrypoint: str | None = None
    input_schema: str = Field(alias="inputSchema")
    output_schema: str = Field(alias="outputSchema")
    permissions: SkillPermissions
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=300)
    max_output_bytes: int = Field(alias="maxOutputBytes", ge=1, le=25 * 1024 * 1024)

    @model_validator(mode="after")
    def entrypoint_matches_mode(self) -> SkillManifest:
        if self.mode == "executable" and not self.entrypoint:
            raise ValueError("executable Skill 必须声明 entrypoint")
        if self.mode == "instruction" and self.entrypoint is not None:
            raise ValueError("instruction Skill 不得声明 entrypoint")
        return self


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class ConversationCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)


class AskRequest(StrictModel):
    scenario_name: str = Field(alias="scenarioName")
    question: str = Field(min_length=1, max_length=4000)
    asset_ids: list[str] = Field(alias="assetIds", min_length=1, max_length=20)
    conversation_id: str | None = Field(default=None, alias="conversationId")
