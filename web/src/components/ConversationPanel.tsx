import { useEffect, useMemo, useRef } from "react";

import type { Artifact, Conversation, ProjectMessage, Run } from "../types";
import { artifactCitationCount, formatDate } from "../ui";
import { AnswerText } from "./AnswerText";

interface ConversationPanelProps {
  conversation: Conversation | null;
  messages: ProjectMessage[];
  runs: Run[];
  run: Run | null;
  asking: boolean;
  onArtifactSelect: (artifact: Artifact) => void;
}

export function ConversationPanel({
  conversation,
  messages,
  runs,
  run,
  asking,
  onArtifactSelect,
}: ConversationPanelProps) {
  const scoped = conversation
    ? messages.filter((message) => message.conversationId === conversation.id)
    : [];
  const hasQuestion = Boolean(
    run && scoped.some((message) => message.role === "user" && message.content === run.question),
  );
  const hasAnswer = Boolean(
    run?.answer &&
    scoped.some((message) => message.role === "assistant" && message.content === run.answer),
  );
  const messageStream = useRef<HTMLDivElement>(null);
  const artifacts = useMemo(() => {
    const byId = new Map<string, Artifact>();
    for (const candidateRun of [...runs, ...(run ? [run] : [])]) {
      for (const artifact of candidateRun.artifacts) byId.set(artifact.id, artifact);
    }
    return [...byId.values()];
  }, [run, runs]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const stream = messageStream.current;
      if (stream) stream.scrollTop = stream.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [asking, run?.id, run?.status, scoped.length]);

  return (
    <div className="conversation-panel">
      <header className="conversation-header">
        <div>
          <p>当前 Conversation · {conversation?.title ?? "默认对话"}</p>
          <small>
            {conversation ? `创建于 ${formatDate(conversation.createdAt)}` : "有界历史上下文"}
          </small>
        </div>
        <span className="conversation-mode">
          <i aria-hidden="true" /> Evidence grounded
        </span>
      </header>
      <div ref={messageStream} className="message-stream data-scrollbar" aria-live="polite">
        {scoped.length === 0 && !run && !asking && (
          <div className="conversation-empty">
            <span className="empty-orbit" aria-hidden="true">
              <i />
            </span>
            <p className="eyebrow">Ready when you are</p>
            <h2>从一个关于数据的问题开始</h2>
            <p>
              左侧选择 Scenario
              与资产。问题提交后，右侧会同步展示类型化计划、确定性步骤和不可变证据。
            </p>
            <div className="empty-flow" aria-hidden="true">
              <span>Question</span>
              <i>→</i>
              <span>Plan</span>
              <i>→</i>
              <span>Artifact</span>
              <i>→</i>
              <span>Answer</span>
            </div>
          </div>
        )}
        {scoped.map((message) => (
          <article className={`message message--${message.role}`} key={message.id}>
            <div className="message-avatar" aria-hidden="true">
              {message.role === "user" ? "你" : "M"}
            </div>
            <div className="message-body">
              <header>
                <strong>{message.role === "user" ? "你" : "Cairn Agent"}</strong>
                <time>{formatDate(message.createdAt)}</time>
              </header>
              {message.role === "assistant" ? (
                <AnswerText
                  text={message.content}
                  artifacts={artifacts}
                  onSelect={onArtifactSelect}
                />
              ) : (
                <p>{message.content}</p>
              )}
            </div>
          </article>
        ))}
        {run && !hasQuestion && (
          <article className="message message--user message--current">
            <div className="message-avatar" aria-hidden="true">
              你
            </div>
            <div className="message-body">
              <header>
                <strong>你</strong>
                <time>本次提问</time>
              </header>
              <p>{run.question}</p>
            </div>
          </article>
        )}
        {asking && (
          <article className="message message--assistant message--thinking">
            <div className="message-avatar" aria-hidden="true">
              M
            </div>
            <div className="message-body">
              <header>
                <strong>Cairn Agent</strong>
                <time>正在工作</time>
              </header>
              <p>
                <span className="thinking-dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>{" "}
                正在构建有界上下文并校验计划…
              </p>
            </div>
          </article>
        )}
        {run?.answer && !hasAnswer && (
          <article className="message message--assistant message--answer">
            <div className="message-avatar" aria-hidden="true">
              M
            </div>
            <div className="message-body">
              <header>
                <strong>Cairn Agent</strong>
                <time>{run.completedAt ? formatDate(run.completedAt) : "刚刚"}</time>
              </header>
              <AnswerText text={run.answer} artifacts={run.artifacts} onSelect={onArtifactSelect} />
              {artifactCitationCount(run.answer) > 0 && (
                <div className="answer-evidence-count">
                  已引用 {artifactCitationCount(run.answer)} 个持久化 Artifact
                </div>
              )}
            </div>
          </article>
        )}
      </div>
    </div>
  );
}
