export type AssetKind = "csv" | "xlsx" | "markdown";

export interface Scenario {
  name: string;
  version: string;
  displayName: string;
  description: string;
  supportedAssetTypes: AssetKind[];
  exampleQuestions: string[];
}

export interface TableColumn {
  name: string;
  type: string;
}

export interface TablePreview {
  kind: "table";
  columns: TableColumn[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  columnCount: number;
  truncated: boolean;
}

export interface DocumentPreview {
  kind: "document";
  text: string;
  lineCount: number;
  characterCount: number;
  truncated: boolean;
}

export interface EvidenceHit {
  assetId: string;
  filename: string;
  lineStart: number;
  lineEnd: number;
  quote: string;
  score: number;
}

export interface EvidencePreview {
  kind: "evidence";
  query: string;
  hits: EvidenceHit[];
}

export type Preview = TablePreview | DocumentPreview | EvidencePreview | Record<string, unknown>;

export interface Asset {
  id: string;
  projectId: string;
  filename: string;
  mediaType: string;
  kind: AssetKind;
  sha256: string;
  byteSize: number;
  profile: Preview;
  createdAt: string;
}

export interface AssetPreviewResponse {
  asset: Asset;
  preview: Preview;
}

export interface Artifact {
  id: string;
  projectId: string;
  runId: string;
  stepId: string;
  kind: string;
  mimeType: string;
  sha256: string;
  byteSize: number;
  preview: Preview;
  lineage: Record<string, unknown>;
  createdAt: string;
}

export interface ClarificationOption {
  id: string;
  label: string;
}

export interface Clarification {
  version: "cairn.clarification/v1";
  question: string;
  reason: string;
  options: ClarificationOption[];
}

export type InputReference = `asset:${string}` | `step:${string}`;

export interface Predicate {
  column: string;
  operator:
    "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "in" | "is_null" | "is_not_null";
  value: unknown | null;
}

export interface Metric {
  column: string;
  operation: "count" | "sum" | "mean" | "min" | "max" | "median";
  alias: string;
}

export type PlanStep =
  | { id: string; kind: "inspect"; asset_id: string }
  | { id: string; kind: "filter"; input: InputReference; predicates: Predicate[] }
  | { id: string; kind: "select"; input: InputReference; columns: string[] }
  | {
      id: string;
      kind: "derive";
      input: InputReference;
      output_column: string;
      operation: "add" | "subtract" | "multiply" | "divide";
      left_column: string;
      right_column: string | null;
      right_value: number | null;
    }
  | { id: string; kind: "aggregate"; input: InputReference; group_by: string[]; metrics: Metric[] }
  | {
      id: string;
      kind: "join";
      left: InputReference;
      right: InputReference;
      left_on: string[];
      right_on: string[];
      how: "inner" | "left";
    }
  | {
      id: string;
      kind: "sort";
      input: InputReference;
      by: Array<{ column: string; descending: boolean }>;
    }
  | { id: string; kind: "limit"; input: InputReference; count: number }
  | { id: string; kind: "retrieve"; asset_ids: string[]; query: string; top_k: number }
  | {
      id: string;
      kind: "skill";
      skill: string;
      input?: InputReference | null;
      arguments: Record<string, unknown>;
    };

export interface DataPlan {
  version: "cairn.data-plan/v1";
  goal: string;
  asset_ids: string[];
  steps: PlanStep[];
  answer_instruction: string;
}

export interface RunStep {
  id: string;
  kind: string;
  status: string;
  position: number;
  detail: Record<string, unknown>;
}

export type RunStatus = "planning" | "running" | "needs_input" | "succeeded" | "failed";

export interface Run {
  id: string;
  projectId: string;
  conversationId: string;
  scenario: { name: string; version: string };
  question: string;
  status: RunStatus;
  contextSnapshot: Record<string, unknown> | null;
  plan: DataPlan | null;
  clarification: Clarification | null;
  answer: string | null;
  steps: RunStep[];
  artifacts: Artifact[];
  createdAt: string;
  completedAt: string | null;
}

export interface ProjectSummary {
  id: string;
  name: string;
  createdAt: string;
  defaultConversationId: string | null;
}

export interface Conversation {
  id: string;
  projectId: string;
  title: string;
  createdAt: string;
}

export interface ProjectMessage {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  content: string;
  evidence: Array<Record<string, unknown>> | null;
  createdAt: string;
}

export interface Project extends ProjectSummary {
  conversations: Conversation[];
  assets: Asset[];
  messages: ProjectMessage[];
  runs: Run[];
}

export interface AskInput {
  scenarioName: string;
  question: string;
  assetIds: string[];
  conversationId: string;
}
