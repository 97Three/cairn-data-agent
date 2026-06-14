import { render, screen, within } from "@testing-library/react";

import { PreviewRenderer } from "./PreviewRenderer";

describe("PreviewRenderer", () => {
  it("renders a bounded table instead of mounting every artifact row", () => {
    const rows = Array.from({ length: 240 }, (_, index) => ({
      category: `类别 ${index}`,
      amount: index,
    }));

    render(
      <PreviewRenderer
        preview={{
          kind: "table",
          columns: [
            { name: "category", type: "String" },
            { name: "amount", type: "Int64" },
          ],
          rows,
          rowCount: 240,
          columnCount: 2,
          truncated: false,
        }}
      />,
    );

    const table = screen.getByRole("table", { name: "数据预览" });
    expect(within(table).getAllByRole("row")).toHaveLength(201);
    expect(screen.getByText("预览已截断")).toBeInTheDocument();
    expect(screen.queryByText("类别 239")).not.toBeInTheDocument();
  });

  it("renders document metadata and source text", () => {
    render(
      <PreviewRenderer
        preview={{
          kind: "document",
          text: "# 主动回忆\n\n先合上笔记再尝试复述。",
          lineCount: 3,
          characterCount: 22,
          truncated: false,
        }}
      />,
    );

    expect(screen.getByText("3 行")).toBeInTheDocument();
    expect(screen.getByText(/先合上笔记/)).toBeInTheDocument();
  });

  it("renders evidence locations and handles an empty hit list", () => {
    const { rerender } = render(
      <PreviewRenderer
        preview={{
          kind: "evidence",
          query: "主动回忆",
          hits: [
            {
              assetId: "asset-notes",
              filename: "notes.md",
              lineStart: 4,
              lineEnd: 6,
              quote: "主动回忆比重复阅读更能暴露知识缺口。",
              score: 2,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("notes.md")).toBeInTheDocument();
    expect(screen.getByText("L4–L6")).toBeInTheDocument();
    expect(screen.getByText(/暴露知识缺口/)).toBeInTheDocument();

    rerender(<PreviewRenderer preview={{ kind: "evidence", query: "不存在", hits: [] }} />);
    expect(screen.getByText("所选文档中没有找到相关证据。")).toBeInTheDocument();
  });
});
