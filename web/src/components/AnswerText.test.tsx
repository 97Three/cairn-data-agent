import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Artifact } from "../types";
import { AnswerText } from "./AnswerText";

const artifact: Artifact = {
  id: "artifact-1",
  projectId: "project-1",
  runId: "run-1",
  stepId: "by_category",
  kind: "table",
  mimeType: "application/json",
  sha256: "a".repeat(64),
  byteSize: 80,
  preview: {},
  lineage: {},
  createdAt: "2026-08-31T10:01:00",
};

describe("AnswerText", () => {
  it("turns an embedded JSON result into a compact table and keeps citations interactive", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <AnswerText
        text={
          '确定性计算得到 2 行结果。结果预览：[{"category":"food","variance":94},{"category":"transport","variance":20}]\n\n证据：[artifact:artifact-1]'
        }
        artifacts={[artifact]}
        onSelect={onSelect}
      />,
    );

    const table = screen.getByRole("table", { name: "回答中的结构化结果" });
    expect(within(table).getByRole("columnheader", { name: "category" })).toBeInTheDocument();
    expect(within(table).getByText("food")).toBeInTheDocument();
    expect(screen.queryByText(/\[\{"category"/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "[证据 · by_category]" }));
    expect(onSelect).toHaveBeenCalledWith(artifact);
  });

  it("leaves malformed JSON-like prose readable", () => {
    render(<AnswerText text={'结果预览：[{"broken":]'} artifacts={[]} onSelect={vi.fn()} />);

    expect(screen.getByText('结果预览：[{"broken":]')).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("collapses answer instructions and shortens technical evidence metadata", () => {
    const sha256 = "a".repeat(64);
    render(
      <AnswerText
        text={`先给出面向用户的结论。\n\n回答口径：只根据持久化证据回答。\n\n证据：[artifact:artifact-1]（SHA-256: ${sha256}）`}
        artifacts={[artifact]}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("先给出面向用户的结论。")).toBeInTheDocument();
    expect(screen.getByText("回答依据与口径")).toBeInTheDocument();
    expect(screen.getByText("SHA aaaaaaa…aaaaa")).toHaveAttribute("title", sha256);
    expect(screen.queryByText(sha256)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "[证据 · by_category]" })).toBeInTheDocument();
  });
});
