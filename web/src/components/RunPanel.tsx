import { useEffect, useState } from "react";
import type { Artifact, Run, RunStep } from "../types";
import {
  artifactCitationCount,
  formatBytes,
  formatDate,
  RUN_STATUS_LABELS,
  shortHash,
  summarizeAnswer,
} from "../ui";
import { JsonBlock, PreviewRenderer } from "./PreviewRenderer";

interface RunPanelProps {
  run: Run | null;
  selectedArtifact: Artifact | null;
  artifactFocusToken: number;
  artifactLoading: boolean;
  onArtifactSelect: (artifact: Artifact) => void;
  onClarificationChoice: (question: string) => void;
}
type InspectorTab = "run" | "plan" | "artifacts";
const STEP_LABELS: Record<string, string> = {
  inspect: "检查数据画像",
  filter: "筛选记录",
  select: "选择字段",
  derive: "派生字段",
  aggregate: "聚合计算",
  join: "关联数据",
  sort: "排序结果",
  limit: "限制行数",
  retrieve: "检索文档证据",
  skill: "运行受信 Skill",
};

function StepDetail({ step }: { step: RunStep }) {
  if (step.status === "failed" && typeof step.detail.error === "string")
    return <small className="step-error">{step.detail.error}</small>;
  if (typeof step.detail.sha256 === "string")
    return <small>SHA {shortHash(step.detail.sha256)}</small>;
  return <small>{step.status === "running" ? "执行中" : "等待执行"}</small>;
}

function finalTimelineState(run: Run): { className: string; label: string } {
  if (run.status === "failed") return { className: "is-failed", label: "Run 已终止" };
  if (run.status === "needs_input") return { className: "is-waiting", label: "等待用户补充" };
  return { className: `is-${run.status}`, label: "生成证据回答" };
}

export function RunPanel({
  run,
  selectedArtifact,
  artifactFocusToken,
  artifactLoading,
  onArtifactSelect,
  onClarificationChoice,
}: RunPanelProps) {
  const [tab, setTab] = useState<InspectorTab>("run");
  useEffect(() => {
    setTab("run");
  }, [run?.id]);
  useEffect(() => {
    if (selectedArtifact) setTab("artifacts");
  }, [artifactFocusToken]);
  const selectArtifact = (artifact: Artifact) => {
    setTab("artifacts");
    onArtifactSelect(artifact);
  };
  return (
    <div className="inspector-shell">
      <header className="inspector-header">
        <div>
          <p className="eyebrow">Execution inspector</p>
          <h2>{run ? `Run · ${run.id.slice(0, 8)}` : "运行检查器"}</h2>
        </div>
        {run && (
          <span className={`run-status run-status--${run.status}`}>
            <i aria-hidden="true" />
            {RUN_STATUS_LABELS[run.status]}
          </span>
        )}
      </header>
      <div className="inspector-tabs" role="tablist" aria-label="运行检查视图">
        {(["run", "plan", "artifacts"] as const).map((item) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={tab === item ? "is-active" : undefined}
            onClick={() => setTab(item)}
            key={item}
          >
            {item === "run" ? "Run" : item === "plan" ? "Plan" : "Artifacts"}
            {item === "artifacts" && run?.artifacts.length ? (
              <span>{run.artifacts.length}</span>
            ) : null}
          </button>
        ))}
      </div>
      <div className="inspector-scroll data-scrollbar">
        {!run ? (
          <div className="empty-run">
            <span className="empty-run-mark" aria-hidden="true">
              ◇
            </span>
            <p className="eyebrow">No active run</p>
            <h2>答案会沿着证据链生成</h2>
            <p>提交问题后，在这里检查计划、步骤状态、Artifact 和血缘。</p>
          </div>
        ) : tab === "run" ? (
          <RunView run={run} onClarificationChoice={onClarificationChoice} />
        ) : tab === "plan" ? (
          <PlanView run={run} />
        ) : (
          <ArtifactView
            run={run}
            selectedArtifact={selectedArtifact}
            artifactLoading={artifactLoading}
            onSelect={selectArtifact}
          />
        )}
      </div>
    </div>
  );
}

function RunView({
  run,
  onClarificationChoice,
}: {
  run: Run;
  onClarificationChoice: (question: string) => void;
}) {
  const steps = [...run.steps].sort((a, b) => a.position - b.position);
  const finalState = finalTimelineState(run);
  const planningState = run.plan ? "is-done" : run.status === "failed" ? "is-failed" : "is-active";
  return (
    <div className="run-view">
      <section className="inspector-card run-question">
        <p className="card-label">用户问题</p>
        <h3>{run.question}</h3>
        <div className="run-meta">
          <span>{formatDate(run.createdAt)}</span>
          <span>
            {run.scenario.name} · v{run.scenario.version}
          </span>
        </div>
      </section>
      {run.clarification && (
        <section className="clarification-card">
          <span className="clarification-icon" aria-hidden="true">
            ?
          </span>
          <div>
            <p className="card-label">需要澄清</p>
            <h3>{run.clarification.question}</h3>
            <p>{run.clarification.reason}</p>
            <div className="clarification-options" aria-label="澄清选项">
              {run.clarification.options.map((option) => (
                <button
                  type="button"
                  key={option.id}
                  onClick={() => onClarificationChoice(option.label)}
                >
                  {option.label}
                  <span aria-hidden="true">→</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      )}
      <section className="inspector-card">
        <div className="card-heading">
          <p className="card-label">执行时间线</p>
          <span>{steps.length} steps</span>
        </div>
        <ol className="timeline">
          <li className={`timeline-item ${planningState}`}>
            <span className="timeline-dot" />
            <div>
              <strong>生成并校验 DataPlan</strong>
              <small>
                {run.plan?.goal ??
                  (run.status === "failed"
                    ? "计划未通过校验或执行提前终止"
                    : "等待问题边界变得明确")}
              </small>
            </div>
          </li>
          {steps.map((step) => (
            <li className={`timeline-item is-${step.status}`} key={step.id}>
              <span className="timeline-dot" />
              <div>
                <strong>
                  {String(step.position + 1).padStart(2, "0")} ·{" "}
                  {STEP_LABELS[step.kind] ?? step.kind}
                </strong>
                <StepDetail step={step} />
              </div>
            </li>
          ))}
          {run.completedAt && (
            <li className={`timeline-item ${finalState.className}`}>
              <span className="timeline-dot" />
              <div>
                <strong>{finalState.label}</strong>
                <small>完成于 {formatDate(run.completedAt)}</small>
              </div>
            </li>
          )}
        </ol>
      </section>
      {run.answer && (
        <section className="inspector-card answer-summary">
          <p className="card-label">Answer</p>
          <p>{summarizeAnswer(run.answer)}</p>
          <span>
            {run.status === "failed"
              ? "未生成可引用 Artifact"
              : `${artifactCitationCount(run.answer)} 个证据引用 · ${run.artifacts.length} 个 Artifact`}
          </span>
        </section>
      )}
    </div>
  );
}

function PlanView({ run }: { run: Run }) {
  return (
    <div className="plan-view">
      {run.plan ? (
        <>
          <section className="inspector-card plan-summary">
            <p className="card-label">目标</p>
            <h3>{run.plan.goal}</h3>
            <dl>
              <div>
                <dt>Contract</dt>
                <dd>{run.plan.version}</dd>
              </div>
              <div>
                <dt>Assets</dt>
                <dd>{run.plan.asset_ids.length}</dd>
              </div>
              <div>
                <dt>Steps</dt>
                <dd>{run.plan.steps.length}</dd>
              </div>
            </dl>
          </section>
          <details className="code-details" open>
            <summary>
              <span>DataPlan JSON</span>
              <span>{run.plan.steps.length} steps</span>
            </summary>
            <JsonBlock value={run.plan} label="DataPlan JSON" />
          </details>
          {run.contextSnapshot && (
            <details className="code-details">
              <summary>
                <span>Bounded context</span>
                <span>检查上下文</span>
              </summary>
              <JsonBlock value={run.contextSnapshot} label="有界上下文 JSON" />
            </details>
          )}
        </>
      ) : (
        <div className="empty-inline">当前 Run 没有生成执行计划。</div>
      )}
    </div>
  );
}

function ArtifactView({
  run,
  selectedArtifact,
  artifactLoading,
  onSelect,
}: {
  run: Run;
  selectedArtifact: Artifact | null;
  artifactLoading: boolean;
  onSelect: (artifact: Artifact) => void;
}) {
  if (run.artifacts.length === 0)
    return (
      <div className="empty-run compact">
        <span className="empty-run-mark">□</span>
        <h2>尚无 Artifact</h2>
        <p>成功的执行步骤会在此生成不可变证据。</p>
      </div>
    );
  return (
    <div className="artifact-view">
      <div className="artifact-list" aria-label="执行证据">
        {run.artifacts.map((artifact, index) => (
          <button
            type="button"
            className={selectedArtifact?.id === artifact.id ? "is-selected" : undefined}
            key={artifact.id}
            onClick={() => onSelect(artifact)}
          >
            <span className="artifact-sequence">{String(index + 1).padStart(2, "0")}</span>
            <span>
              <strong>{artifact.stepId}</strong>
              <small>
                {artifact.kind} · {formatBytes(artifact.byteSize)}
              </small>
            </span>
            <span className="artifact-check" aria-hidden="true">
              ✓
            </span>
          </button>
        ))}
      </div>
      {artifactLoading && !selectedArtifact ? (
        <div className="loading-panel">正在读取 Artifact…</div>
      ) : (
        selectedArtifact && (
          <section className="artifact-preview">
            <header>
              <div>
                <p className="card-label">Evidence preview</p>
                <h3>{selectedArtifact.stepId}</h3>
              </div>
              <span className="immutable-badge">SHA {shortHash(selectedArtifact.sha256)}</span>
            </header>
            <PreviewRenderer preview={selectedArtifact.preview} />
            <details className="code-details lineage-details">
              <summary>
                <span>血缘与步骤参数</span>
                <span>Lineage</span>
              </summary>
              <JsonBlock value={selectedArtifact.lineage} label="Artifact 血缘 JSON" />
            </details>
          </section>
        )
      )}
    </div>
  );
}
