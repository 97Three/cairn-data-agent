import { render, screen } from "@testing-library/react";

import type { Run } from "../types";
import { RunPanel } from "./RunPanel";

function run(overrides: Partial<Run>): Run {
  return {
    id: "run-1",
    projectId: "project-1",
    conversationId: "conversation-1",
    scenario: { name: "travel-budget", version: "0.1.0" },
    question: "帮我分析一下",
    status: "failed",
    contextSnapshot: null,
    plan: null,
    clarification: null,
    answer: "执行失败：计划声明了未被任何步骤消费的资产。",
    steps: [],
    artifacts: [],
    createdAt: "2026-08-31T10:00:00",
    completedAt: "2026-08-31T10:00:01",
    ...overrides,
  };
}

function renderRun(candidate: Run) {
  return render(
    <RunPanel
      run={candidate}
      selectedArtifact={null}
      artifactFocusToken={0}
      artifactLoading={false}
      onArtifactSelect={vi.fn()}
      onClarificationChoice={vi.fn()}
    />,
  );
}

describe("RunPanel terminal states", () => {
  it("describes a failed plan as terminated rather than evidence generation", () => {
    renderRun(run({}));

    expect(screen.getByText("Run 已终止")).toBeInTheDocument();
    expect(screen.getByText("计划未通过校验或执行提前终止")).toBeInTheDocument();
    expect(screen.getByText("未生成可引用 Artifact")).toBeInTheDocument();
    expect(screen.queryByText("生成证据回答")).not.toBeInTheDocument();
  });

  it("marks clarification as waiting for user input", () => {
    renderRun(
      run({
        status: "needs_input",
        answer: null,
        clarification: {
          version: "cairn.clarification/v1",
          question: "请选择一个目标。",
          reason: "问题范围不足。",
          options: [{ id: "budget", label: "分析预算" }],
        },
      }),
    );

    expect(screen.getByText("等待用户补充")).toBeInTheDocument();
    expect(screen.queryByText("生成证据回答")).not.toBeInTheDocument();
  });
});
