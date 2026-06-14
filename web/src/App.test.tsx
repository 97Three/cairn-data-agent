import { StrictMode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { api, ApiError } from "./api";
import { App } from "./App";
import type { Artifact, Asset, Project, Run, Scenario } from "./types";

vi.mock("./api", () => ({
  API_BASE_URL: "http://127.0.0.1:8000",
  ApiError: class ApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
  api: {
    listScenarios: vi.fn(),
    createProject: vi.fn(),
    getProject: vi.fn(),
    uploadAsset: vi.fn(),
    getAssetPreview: vi.fn(),
    ask: vi.fn(),
    getRun: vi.fn(),
    getArtifact: vi.fn(),
  },
}));

const scenario: Scenario = {
  name: "travel-budget",
  version: "0.1.0",
  displayName: "旅行预算分析",
  description: "比较计划预算与实际花费。",
  supportedAssetTypes: ["csv", "xlsx"],
  exampleQuestions: ["哪些旅行费用类别超出了预算？"],
};

const stockScenario: Scenario = {
  name: "stock-research",
  version: "0.1.0",
  displayName: "股票历史研究",
  description: "分析公开或合成的历史行情。",
  supportedAssetTypes: ["csv", "xlsx"],
  exampleQuestions: ["比较各标的的历史均价和成交量。"],
};

const conversation = {
  id: "conversation-1",
  projectId: "project-1",
  title: "默认对话",
  createdAt: "2026-08-31T10:00:00",
};

const asset: Asset = {
  id: "asset-1",
  projectId: "project-1",
  filename: "travel.csv",
  mediaType: "text/csv",
  kind: "csv",
  sha256: "f".repeat(64),
  byteSize: 48,
  profile: {
    kind: "table",
    columns: [
      { name: "category", type: "String" },
      { name: "actual_cny", type: "Int64" },
    ],
    rows: [{ category: "住宿", actual_cny: 900 }],
    rowCount: 1,
    columnCount: 2,
    truncated: false,
  },
  createdAt: "2026-08-31T10:00:00",
};

const artifact: Artifact = {
  id: "artifact-1",
  projectId: "project-1",
  runId: "run-1",
  stepId: "by_category",
  kind: "table",
  mimeType: "application/json",
  sha256: "a".repeat(64),
  byteSize: 80,
  preview: {
    kind: "table",
    columns: [
      { name: "category", type: "String" },
      { name: "variance_cny", type: "Int64" },
    ],
    rows: [{ category: "住宿", variance_cny: 120 }],
    rowCount: 1,
    columnCount: 2,
    truncated: false,
  },
  lineage: {
    version: "cairn.lineage/v1",
    inputAssetIds: ["asset-1"],
    inputArtifactIds: [],
    step: { id: "by_category", kind: "aggregate" },
  },
  createdAt: "2026-08-31T10:01:00",
};

const succeededRun: Run = {
  id: "run-1",
  projectId: "project-1",
  conversationId: conversation.id,
  scenario: { name: scenario.name, version: scenario.version },
  question: scenario.exampleQuestions[0] ?? "预算问题",
  status: "succeeded",
  contextSnapshot: { question: scenario.exampleQuestions[0], assets: [{ id: asset.id }] },
  plan: {
    version: "cairn.data-plan/v1",
    goal: "按类别汇总预算偏差",
    asset_ids: [asset.id],
    steps: [
      {
        id: "by_category",
        kind: "aggregate",
        input: "asset:asset-1",
        group_by: ["category"],
        metrics: [{ column: "actual_cny", operation: "sum", alias: "actual_cny" }],
      },
    ],
    answer_instruction: "只根据 Artifact 回答。",
  },
  clarification: null,
  answer: "住宿超支 120 元。[artifact:artifact-1]",
  steps: [
    {
      id: "by_category",
      kind: "aggregate",
      status: "succeeded",
      position: 0,
      detail: { artifactId: artifact.id, sha256: artifact.sha256 },
    },
  ],
  artifacts: [artifact],
  createdAt: "2026-08-31T10:00:30",
  completedAt: "2026-08-31T10:01:00",
};

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "project-1",
    name: "教学分析",
    createdAt: "2026-08-31T10:00:00",
    defaultConversationId: conversation.id,
    conversations: [conversation],
    assets: [],
    messages: [],
    runs: [],
    ...overrides,
  };
}

function setupNewProject() {
  vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
  vi.mocked(api.createProject).mockResolvedValue({
    id: "project-1",
    name: "教学分析",
    createdAt: "2026-08-31T10:00:00",
    defaultConversationId: conversation.id,
  });
  vi.mocked(api.getProject).mockResolvedValue(project());
}

function renderApp() {
  return render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

describe("App workbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("automatically creates a project, uploads a compatible asset, and shows evidence", async () => {
    const user = userEvent.setup();
    setupNewProject();
    vi.mocked(api.uploadAsset).mockResolvedValue(asset);
    vi.mocked(api.getAssetPreview).mockResolvedValue({ asset, preview: asset.profile });
    vi.mocked(api.ask).mockResolvedValue(succeededRun);
    vi.mocked(api.getArtifact).mockResolvedValue(artifact);

    renderApp();

    expect(await screen.findByRole("heading", { name: "选择分析场景" })).toBeInTheDocument();
    expect(api.createProject).toHaveBeenCalledTimes(1);
    expect(api.getProject).toHaveBeenCalledTimes(1);
    expect(api.getProject).toHaveBeenCalledWith("project-1", expect.any(AbortSignal));
    expect(screen.getByText("当前 Conversation · 默认对话")).toBeInTheDocument();
    expect(screen.getAllByText("旅行预算分析").length).toBeGreaterThan(0);

    const file = new File(["category,actual_cny\n住宿,900"], "travel.csv", {
      type: "text/csv",
    });
    await user.upload(screen.getByTestId("asset-upload"), file);

    expect(await screen.findByLabelText("选择 travel.csv")).toBeChecked();
    await user.click(screen.getByRole("button", { name: scenario.exampleQuestions[0] }));
    await user.click(screen.getByRole("button", { name: /开始分析/ }));

    await waitFor(() => {
      expect(api.ask).toHaveBeenCalledWith("project-1", {
        scenarioName: "travel-budget",
        question: scenario.exampleQuestions[0],
        assetIds: ["asset-1"],
        conversationId: conversation.id,
      });
    });
    expect((await screen.findAllByText(/住宿超支 120 元/)).length).toBeGreaterThan(0);
    const citation = screen.getByRole("button", { name: "[证据 · by_category]" });
    expect(citation).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "分析问题" })).toHaveValue("");
    expect(screen.getByRole("tab", { name: "Run" })).toHaveAttribute("aria-selected", "true");
    expect(api.getArtifact).toHaveBeenCalledWith("artifact-1");

    await user.click(screen.getByRole("tab", { name: "Plan" }));
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: true })),
    );
    await user.click(citation);
    expect(screen.getByRole("tab", { name: /Artifacts/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("table · 80 B")).toBeInTheDocument();
    await waitFor(() =>
      expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "start",
      }),
    );
  });

  it("restores a saved project and turns a clarification option into the next question", async () => {
    const user = userEvent.setup();
    const clarificationRun: Run = {
      id: "run-needs-input",
      projectId: "project-1",
      conversationId: conversation.id,
      scenario: { name: scenario.name, version: scenario.version },
      question: "帮我分析一下",
      status: "needs_input",
      contextSnapshot: { question: "帮我分析一下", assets: [{ id: asset.id }] },
      plan: null,
      clarification: {
        version: "cairn.clarification/v1",
        question: "请选择一个更具体的分析目标。",
        reason: "离线模型只运行 Scenario 声明的可复现示例。",
        options: [{ id: "budget", label: "哪些旅行费用类别超出了预算？" }],
      },
      answer: null,
      steps: [],
      artifacts: [],
      createdAt: "2026-08-31T10:00:00",
      completedAt: "2026-08-31T10:00:01",
    };
    window.localStorage.setItem("cairn-data-agent.project-id", "project-1");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
    vi.mocked(api.getProject).mockResolvedValue(
      project({ assets: [asset], runs: [clarificationRun] }),
    );

    renderApp();

    expect(await screen.findByText("请选择一个更具体的分析目标。")).toBeInTheDocument();
    expect(api.createProject).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByLabelText("澄清选项")).getByRole("button", {
        name: /哪些旅行费用类别超出了预算？/,
      }),
    );
    expect(screen.getByLabelText("分析问题")).toHaveValue("哪些旅行费用类别超出了预算？");
  });

  it("clears a previous Run as soon as a new ask starts and keeps it cleared on failure", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("cairn-data-agent.project-id", "project-1");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
    vi.mocked(api.getProject).mockResolvedValue(project({ assets: [asset], runs: [succeededRun] }));
    vi.mocked(api.getArtifact).mockResolvedValue(artifact);
    vi.mocked(api.ask).mockRejectedValue(new Error("后端暂时不可用"));

    renderApp();

    expect((await screen.findAllByText(/住宿超支 120 元/)).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: scenario.exampleQuestions[0] }));
    await user.click(screen.getByRole("button", { name: /开始分析/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("后端暂时不可用");
    expect(screen.queryByText(/住宿超支 120 元/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "答案会沿着证据链生成" })).toBeInTheDocument();
  });

  it("replaces a stale saved Project only after a confirmed 404", async () => {
    window.localStorage.setItem("cairn-data-agent.project-id", "stale-project");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
    vi.mocked(api.getProject)
      .mockRejectedValueOnce(new ApiError("Project 不存在", 404))
      .mockResolvedValueOnce(project());
    vi.mocked(api.createProject).mockResolvedValue({
      id: "project-1",
      name: "教学分析",
      createdAt: "2026-08-31T10:00:00",
      defaultConversationId: conversation.id,
    });

    renderApp();

    expect(await screen.findByText("当前 Conversation · 默认对话")).toBeInTheDocument();
    expect(api.createProject).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem("cairn-data-agent.project-id")).toBe("project-1");
  });

  it("keeps a saved Project id when restoration fails transiently", async () => {
    window.localStorage.setItem("cairn-data-agent.project-id", "saved-project");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
    vi.mocked(api.getProject).mockRejectedValue(new ApiError("服务暂时不可用", 503));

    renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent("服务暂时不可用");
    expect(api.createProject).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("cairn-data-agent.project-id")).toBe("saved-project");
  });

  it("keeps restored assistant Artifact citations interactive", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("cairn-data-agent.project-id", "project-1");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
    vi.mocked(api.getProject).mockResolvedValue(
      project({
        assets: [asset],
        runs: [succeededRun],
        messages: [
          {
            id: "message-user",
            conversationId: conversation.id,
            role: "user",
            content: succeededRun.question,
            evidence: [],
            createdAt: succeededRun.createdAt,
          },
          {
            id: "message-assistant",
            conversationId: conversation.id,
            role: "assistant",
            content: succeededRun.answer ?? "",
            evidence: [{ artifactId: artifact.id }],
            createdAt: succeededRun.completedAt ?? succeededRun.createdAt,
          },
        ],
      }),
    );
    vi.mocked(api.getArtifact).mockResolvedValue(artifact);

    renderApp();

    const citation = await screen.findByRole("button", { name: "[证据 · by_category]" });
    await user.click(citation);
    expect(api.getArtifact).toHaveBeenCalledWith(artifact.id);
  });

  it("clears asset selection when switching Scenarios with the same file type", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("cairn-data-agent.project-id", "project-1");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario, stockScenario]);
    vi.mocked(api.getProject).mockResolvedValue(project({ assets: [asset], runs: [succeededRun] }));
    vi.mocked(api.getArtifact).mockResolvedValue(artifact);

    renderApp();

    expect(await screen.findByLabelText("选择 travel.csv")).toBeChecked();
    await user.click(screen.getByRole("radio", { name: /股票历史研究/ }));
    expect(screen.getByLabelText("选择 travel.csv")).not.toBeChecked();
    expect(screen.getByText("0 个资产已纳入")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "答案会沿着证据链生成" })).toBeInTheDocument();
  });

  it("retries a transient Run polling failure and clears the recovered error", async () => {
    const runningRun: Run = {
      ...succeededRun,
      status: "running",
      answer: null,
      artifacts: [],
      completedAt: null,
      steps: succeededRun.steps.map((step) => ({ ...step, status: "running" })),
    };
    window.localStorage.setItem("cairn-data-agent.project-id", "project-1");
    vi.mocked(api.listScenarios).mockResolvedValue([scenario]);
    vi.mocked(api.getProject).mockResolvedValue(project({ assets: [asset], runs: [runningRun] }));
    vi.mocked(api.getRun)
      .mockRejectedValueOnce(new Error("连接短暂中断"))
      .mockResolvedValueOnce(succeededRun);
    vi.mocked(api.getArtifact).mockResolvedValue(artifact);

    renderApp();

    expect(await screen.findByText("正在执行")).toBeInTheDocument();
    expect(await screen.findByRole("alert", {}, { timeout: 2_000 })).toHaveTextContent(
      "Run 状态刷新失败，正在重试：连接短暂中断",
    );
    expect(await screen.findByText("分析完成", {}, { timeout: 3_500 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(api.getRun).toHaveBeenCalledTimes(2);
  }, 6_000);
});
