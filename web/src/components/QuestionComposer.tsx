import type { FormEvent, KeyboardEvent } from "react";
import type { Scenario } from "../types";

interface QuestionComposerProps {
  scenario: Scenario | null;
  question: string;
  selectedAssetCount: number;
  asking: boolean;
  onQuestionChange: (value: string) => void;
  onAsk: () => void;
}

export function QuestionComposer({
  scenario,
  question,
  selectedAssetCount,
  asking,
  onQuestionChange,
  onAsk,
}: QuestionComposerProps) {
  const canAsk = Boolean(scenario && selectedAssetCount > 0 && question.trim() && !asking);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canAsk) onAsk();
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canAsk) {
      event.preventDefault();
      onAsk();
    }
  };
  return (
    <section className="composer-shell" aria-labelledby="question-heading">
      <div className="composer-context">
        <span>
          <i aria-hidden="true" /> {scenario?.displayName ?? "请选择 Scenario"}
        </span>
        <span>{selectedAssetCount} 个资产已纳入</span>
      </div>
      <form onSubmit={submit} className="composer-box">
        <label className="sr-only" htmlFor="analysis-question">
          分析问题
        </label>
        <textarea
          id="analysis-question"
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            scenario
              ? `问问你的数据，例如：${scenario.exampleQuestions[0] ?? "请根据所选数据给出分析结论"}`
              : "请先选择一个 Scenario"
          }
          rows={2}
          maxLength={4000}
          disabled={!scenario || asking}
        />
        <div className="composer-footer">
          <div className="example-questions" aria-label="示例问题">
            {scenario?.exampleQuestions.slice(0, 2).map((example) => (
              <button
                type="button"
                key={example}
                onClick={() => onQuestionChange(example)}
                title={example}
              >
                {example}
              </button>
            ))}
          </div>
          <span className="keyboard-hint">Ctrl ↵</span>
          <button
            className="send-action"
            type="submit"
            disabled={!canAsk}
            aria-label={asking ? "正在分析" : "开始分析"}
          >
            {asking ? (
              <span className="button-spinner" aria-hidden="true" />
            ) : (
              <span aria-hidden="true">↑</span>
            )}
          </button>
        </div>
      </form>
      {selectedAssetCount === 0 && (
        <p className="composer-hint" role="status">
          选择至少一个兼容资产后即可开始。
        </p>
      )}
      <h2 id="question-heading" className="sr-only">
        提出分析问题
      </h2>
    </section>
  );
}
