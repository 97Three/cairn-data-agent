import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError, API_BASE_URL } from "./api";
import { AssetsPanel } from "./components/AssetsPanel";
import { ConversationPanel } from "./components/ConversationPanel";
import { PreviewRenderer } from "./components/PreviewRenderer";
import { QuestionComposer } from "./components/QuestionComposer";
import { RunPanel } from "./components/RunPanel";
import { ScenarioPicker } from "./components/ScenarioPicker";
import type { Asset, Artifact, Preview, Project, Run, Scenario } from "./types";
import { ASSET_KIND_LABELS, errorMessage, shortHash } from "./ui";

const PROJECT_STORAGE_KEY = "cairn-data-agent.project-id";
const TRANSIENT_RUN_STATUSES = new Set(["planning", "running"]);
const UPLOAD_SUFFIXES = [".csv", ".xlsx", ".md", ".markdown"];
const POLL_MAX_FAILURES = 5;

function newProjectName(): string {
  const timestamp = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());
  return `教学分析 · ${timestamp}`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function storedProjectId(): string | null {
  try {
    return window.localStorage.getItem(PROJECT_STORAGE_KEY);
  } catch {
    return null;
  }
}

function rememberProject(projectId: string): void {
  try {
    window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId);
  } catch {
    // The workbench still works when storage is disabled.
  }
}

function forgetProject(): void {
  try {
    window.localStorage.removeItem(PROJECT_STORAGE_KEY);
  } catch {
    // Unavailable storage cannot affect this browser session.
  }
}

function revealArtifactOnNarrowScreen(): void {
  if (typeof window.matchMedia !== "function" || !window.matchMedia("(max-width: 700px)").matches)
    return;
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      const target = document.querySelector<HTMLElement>(".artifact-preview, .run-inspector");
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

async function loadOrCreateProject(signal: AbortSignal): Promise<Project> {
  const savedId = storedProjectId();
  if (savedId) {
    try {
      return await api.getProject(savedId, signal);
    } catch (error) {
      if (isAbortError(error)) throw error;
      // Only a confirmed missing Project authorizes replacement. A transient
      // network or server failure must never create a duplicate Project.
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      forgetProject();
    }
  }
  const created = await api.createProject(newProjectName(), signal);
  rememberProject(created.id);
  return api.getProject(created.id, signal);
}

function runAssetIds(run: Run | null): string[] {
  if (!run) return [];
  if (run.plan?.asset_ids.length) return run.plan.asset_ids;
  const snapshot = run.contextSnapshot;
  if (!snapshot || !Array.isArray(snapshot.assets)) return [];
  return snapshot.assets.flatMap((value) => {
    if (typeof value !== "object" || value === null) return [];
    const id = (value as Record<string, unknown>).id;
    return typeof id === "string" ? [id] : [];
  });
}

export function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedScenarioName, setSelectedScenarioName] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set());
  const [question, setQuestion] = useState("");
  const [currentRun, setCurrentRun] = useState<Run | null>(null);
  const [assetPreview, setAssetPreview] = useState<{ asset: Asset; preview: Preview } | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [booting, setBooting] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [artifactFocusToken, setArtifactFocusToken] = useState(0);
  const [pollFailures, setPollFailures] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const workspaceScope = useRef(0);
  const previewRequest = useRef(0);
  const artifactRequest = useRef(0);
  const askRequest = useRef(0);
  const pollRequest = useRef(0);

  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.name === selectedScenarioName) ?? null,
    [scenarios, selectedScenarioName],
  );
  const finalArtifact = currentRun?.artifacts.at(-1) ?? null;
  const activeConversation =
    project?.conversations.find((conversation) => conversation.id === conversationId) ?? null;

  useEffect(() => {
    const controller = new AbortController();
    const initialize = async () => {
      try {
        const availableScenarios = await api.listScenarios(controller.signal);
        if (controller.signal.aborted) return;
        const activeProject = await loadOrCreateProject(controller.signal);
        if (controller.signal.aborted) return;
        const lastRun = activeProject.runs.at(-1) ?? null;
        const initialScenario =
          availableScenarios.find((item) => item.name === lastRun?.scenario.name) ??
          availableScenarios[0] ??
          null;
        // A needs_input Run has no Plan. Its bounded Context is the source of
        // truth for recovery; selecting every compatible asset changes scope.
        const recoveredIds = new Set(runAssetIds(lastRun));
        const initialSelection = lastRun
          ? activeProject.assets
              .filter((asset) => initialScenario?.supportedAssetTypes.includes(asset.kind))
              .filter((asset) => recoveredIds.has(asset.id))
              .map((asset) => asset.id)
          : [];
        setScenarios(availableScenarios);
        setProject(activeProject);
        setAssets(activeProject.assets);
        setConversationId(
          lastRun?.conversationId ??
            activeProject.defaultConversationId ??
            activeProject.conversations[0]?.id ??
            "",
        );
        setSelectedScenarioName(initialScenario?.name ?? "");
        setSelectedAssetIds(new Set(initialSelection));
        setCurrentRun(lastRun);
      } catch (initializationError) {
        if (!isAbortError(initializationError)) setError(errorMessage(initializationError));
      } finally {
        if (!controller.signal.aborted) setBooting(false);
      }
    };
    void initialize();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!currentRun || !TRANSIENT_RUN_STATUSES.has(currentRun.status)) return;
    const controller = new AbortController();
    const requestId = ++pollRequest.current;
    const scopeId = workspaceScope.current;
    const runId = currentRun.id;
    const pollDelay = Math.min(800 * 2 ** pollFailures, 8_000);
    const timer = window.setTimeout(() => {
      api
        .getRun(runId, controller.signal)
        .then((run) => {
          if (
            !controller.signal.aborted &&
            requestId === pollRequest.current &&
            scopeId === workspaceScope.current &&
            run.id === runId
          ) {
            setPollFailures(0);
            setError(null);
            setCurrentRun(run);
          }
        })
        .catch((pollError: unknown) => {
          if (
            !isAbortError(pollError) &&
            requestId === pollRequest.current &&
            scopeId === workspaceScope.current
          ) {
            const nextFailureCount = pollFailures + 1;
            setError(
              nextFailureCount >= POLL_MAX_FAILURES
                ? `Run 状态刷新已暂停：${errorMessage(pollError)}`
                : `Run 状态刷新失败，正在重试：${errorMessage(pollError)}`,
            );
            if (nextFailureCount < POLL_MAX_FAILURES) setPollFailures(nextFailureCount);
          }
        });
    }, pollDelay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (requestId === pollRequest.current) pollRequest.current += 1;
    };
  }, [currentRun, pollFailures]);

  const chooseArtifact = useCallback(async (artifact: Artifact, focus = false) => {
    const requestId = ++artifactRequest.current;
    const scopeId = workspaceScope.current;
    if (focus) setArtifactFocusToken((current) => current + 1);
    setSelectedArtifact(artifact);
    if (focus) revealArtifactOnNarrowScreen();
    setArtifactLoading(true);
    try {
      const completeArtifact = await api.getArtifact(artifact.id);
      if (requestId === artifactRequest.current && scopeId === workspaceScope.current)
        setSelectedArtifact(completeArtifact);
    } catch (artifactError) {
      if (requestId === artifactRequest.current && scopeId === workspaceScope.current)
        setError(errorMessage(artifactError));
    } finally {
      if (requestId === artifactRequest.current && scopeId === workspaceScope.current)
        setArtifactLoading(false);
    }
  }, []);

  useEffect(() => {
    if (finalArtifact) void chooseArtifact(finalArtifact);
    else {
      artifactRequest.current += 1;
      setSelectedArtifact(null);
      setArtifactLoading(false);
    }
  }, [chooseArtifact, finalArtifact?.id]);

  const selectScenario = (name: string) => {
    workspaceScope.current += 1;
    askRequest.current += 1;
    previewRequest.current += 1;
    artifactRequest.current += 1;
    pollRequest.current += 1;
    setSelectedScenarioName(name);
    setSelectedAssetIds(new Set());
    setCurrentRun(null);
    setAssetPreview(null);
    setSelectedArtifact(null);
    setPreviewLoading(false);
    setArtifactLoading(false);
    setAsking(false);
    setPollFailures(0);
    setError(null);
  };

  const toggleAsset = (assetId: string) => {
    setSelectedAssetIds((current) => {
      const next = new Set(current);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  };

  const previewAsset = useCallback(async (asset: Asset) => {
    const requestId = ++previewRequest.current;
    const scopeId = workspaceScope.current;
    setAssetPreview({ asset, preview: asset.profile });
    setPreviewLoading(true);
    try {
      const response = await api.getAssetPreview(asset.id);
      if (requestId === previewRequest.current && scopeId === workspaceScope.current)
        setAssetPreview(response);
    } catch (previewError) {
      if (requestId === previewRequest.current && scopeId === workspaceScope.current)
        setError(errorMessage(previewError));
    } finally {
      if (requestId === previewRequest.current && scopeId === workspaceScope.current)
        setPreviewLoading(false);
    }
  }, []);

  const uploadFiles = async (files: File[]) => {
    if (!project) return;
    const scopeId = workspaceScope.current;
    const supportedFiles = files.filter((file) =>
      UPLOAD_SUFFIXES.some((suffix) => file.name.toLocaleLowerCase().endsWith(suffix)),
    );
    setError(
      supportedFiles.length !== files.length
        ? "已忽略不支持的文件；教学版只接受 CSV、XLSX 和 Markdown。"
        : null,
    );
    if (supportedFiles.length === 0) return;
    setUploading(true);
    let lastUploaded: Asset | null = null;
    try {
      for (const file of supportedFiles) {
        const uploaded = await api.uploadAsset(project.id, file);
        lastUploaded = uploaded;
        setAssets((current) => [...current, uploaded]);
        if (
          scopeId === workspaceScope.current &&
          selectedScenario?.supportedAssetTypes.includes(uploaded.kind)
        )
          setSelectedAssetIds((current) => new Set([...current, uploaded.id]));
      }
      if (lastUploaded && scopeId === workspaceScope.current) await previewAsset(lastUploaded);
    } catch (uploadError) {
      setError(errorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  };

  const askQuestion = async () => {
    if (
      !project ||
      !conversationId ||
      !selectedScenario ||
      !question.trim() ||
      selectedAssetIds.size === 0
    )
      return;
    const requestId = ++askRequest.current;
    const scopeId = workspaceScope.current;
    setAsking(true);
    setError(null);
    setCurrentRun(null);
    setSelectedArtifact(null);
    pollRequest.current += 1;
    setPollFailures(0);
    try {
      const run = await api.ask(project.id, {
        scenarioName: selectedScenario.name,
        question: question.trim(),
        assetIds: [...selectedAssetIds],
        conversationId,
      });
      if (requestId === askRequest.current && scopeId === workspaceScope.current) {
        setCurrentRun(run);
        if (run.status === "succeeded") setQuestion("");
        try {
          const refreshedProject = await api.getProject(project.id);
          if (requestId === askRequest.current && scopeId === workspaceScope.current) {
            setProject(refreshedProject);
            setAssets(refreshedProject.assets);
          }
        } catch (refreshError) {
          if (!isAbortError(refreshError)) {
            setError(`Run 已返回，但 Conversation 刷新失败：${errorMessage(refreshError)}`);
          }
        }
      }
    } catch (askError) {
      if (requestId === askRequest.current && scopeId === workspaceScope.current)
        setError(errorMessage(askError));
    } finally {
      if (requestId === askRequest.current && scopeId === workspaceScope.current) setAsking(false);
    }
  };

  const useClarification = (nextQuestion: string) => {
    setQuestion(nextQuestion);
    window.requestAnimationFrame(() => {
      const input = document.getElementById("analysis-question");
      input?.focus();
      if (typeof input?.scrollIntoView === "function")
        input.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#workspace" aria-label="Cairn Data Agent 工作台">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          <span className="brand-copy">
            <strong>Cairn Data Agent</strong>
            <small>TEACHING WORKBENCH</small>
          </span>
        </a>
        <div className="header-divider" aria-hidden="true" />
        <div className="workspace-title">
          <span>分析工作台</span>
          <small>{selectedScenario?.displayName ?? "载入 Scenario"}</small>
        </div>
        <div className="project-status" title={project?.id}>
          <span className={project ? "connection-dot" : "connection-dot is-offline"} />
          <span>
            <small>{project ? "本地服务已连接" : "等待本地服务"}</small>
            <strong>{project?.name ?? (booting ? "正在准备教学 Project…" : "未连接")}</strong>
          </span>
          {project && <code>{shortHash(project.id)}</code>}
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <span className="error-icon" aria-hidden="true">
            !
          </span>
          <p>{error}</p>
          <button type="button" onClick={() => setError(null)} aria-label="关闭错误提示">
            ×
          </button>
        </div>
      )}

      {booting ? (
        <main className="boot-state" aria-live="polite">
          <span className="boot-spinner" aria-hidden="true" />
          <div>
            <strong>正在准备分析工作台</strong>
            <p>读取 Scenario，并恢复上一次教学 Project…</p>
          </div>
        </main>
      ) : (
        <main id="workspace" className="workbench-grid">
          <aside className="control-rail" aria-label="场景与数据资产">
            <div className="rail-heading">
              <div>
                <p className="eyebrow">Workspace setup</p>
                <h1>分析上下文</h1>
              </div>
              <span>{selectedAssetIds.size} 个资产</span>
            </div>
            <div className="rail-scroll data-scrollbar">
              <ScenarioPicker
                scenarios={scenarios}
                selectedName={selectedScenarioName}
                onSelect={selectScenario}
              />
              <AssetsPanel
                assets={assets}
                supportedKinds={selectedScenario?.supportedAssetTypes ?? []}
                selectedIds={selectedAssetIds}
                previewedAssetId={assetPreview?.asset.id ?? null}
                uploading={uploading}
                onFiles={(files) => void uploadFiles(files)}
                onToggle={toggleAsset}
                onPreview={(asset) => void previewAsset(asset)}
              />
              {assetPreview && (
                <details className="asset-preview-panel" open>
                  <summary>
                    <span>
                      <small>资产预览</small>
                      <strong title={assetPreview.asset.filename}>
                        {assetPreview.asset.filename}
                      </strong>
                    </span>
                    <span className="file-kind">{ASSET_KIND_LABELS[assetPreview.asset.kind]}</span>
                  </summary>
                  {previewLoading && <div className="inline-loader">正在读取完整预览…</div>}
                  <PreviewRenderer preview={assetPreview.preview} compact />
                </details>
              )}
            </div>
          </aside>

          <section className="conversation-stage" aria-label="对话与提问">
            <ConversationPanel
              conversation={activeConversation}
              messages={project?.messages ?? []}
              runs={project?.runs ?? []}
              run={currentRun}
              asking={asking}
              onArtifactSelect={(artifact) => void chooseArtifact(artifact, true)}
            />
            <QuestionComposer
              scenario={selectedScenario}
              question={question}
              selectedAssetCount={selectedAssetIds.size}
              asking={asking}
              onQuestionChange={setQuestion}
              onAsk={() => void askQuestion()}
            />
          </section>

          <aside className="run-inspector" aria-label="Run、Plan 与 Artifact">
            <RunPanel
              run={currentRun}
              selectedArtifact={selectedArtifact}
              artifactFocusToken={artifactFocusToken}
              artifactLoading={artifactLoading}
              onArtifactSelect={(artifact) => void chooseArtifact(artifact)}
              onClarificationChoice={useClarification}
            />
          </aside>
        </main>
      )}

      <footer className="statusbar">
        <span>
          <i aria-hidden="true" /> Offline-first 教学模式
        </span>
        <span>Question → Typed Plan → Policy → Artifact → Answer</span>
        <span>
          API <code>{API_BASE_URL}</code>
        </span>
      </footer>
    </div>
  );
}
