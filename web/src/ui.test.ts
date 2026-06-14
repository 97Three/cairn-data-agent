import { artifactCitationCount, summarizeAnswer } from "./ui";

describe("answer presentation helpers", () => {
  it("counts unique Artifact citations", () => {
    expect(
      artifactCitationCount("[artifact:first] 重复 [artifact:first]，另一个 [artifact:second]。"),
    ).toBe(2);
  });

  it("keeps the conclusion and removes an embedded result array from inspector summaries", () => {
    expect(
      summarizeAnswer(
        '确定性计算得到 2 行结果。结果预览：[{"category":"food"}]\n\n证据：[artifact:first]',
      ),
    ).toBe("确定性计算得到 2 行结果。");
  });

  it("bounds long plain-text summaries", () => {
    expect(summarizeAnswer("一".repeat(20), 8)).toBe("一一一一一一一…");
  });
});
