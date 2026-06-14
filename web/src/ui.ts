import type { AssetKind, RunStatus } from "./types";

export const ASSET_KIND_LABELS: Record<AssetKind, string> = {
  csv: "CSV",
  xlsx: "XLSX",
  markdown: "Markdown",
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  planning: "正在规划",
  running: "正在执行",
  needs_input: "等待澄清",
  succeeded: "分析完成",
  failed: "执行失败",
};

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function shortHash(value: string): string {
  return value.length > 12 ? `${value.slice(0, 7)}…${value.slice(-5)}` : value;
}

export function artifactCitationCount(value: string): number {
  return new Set([...value.matchAll(/\[artifact:([^\]]+)\]/g)].map((match) => match[1])).size;
}

export function summarizeAnswer(value: string, maxLength = 180): string {
  const firstParagraph = value.split(/\n{2,}/)[0] ?? value;
  const structuredStart = firstParagraph.indexOf("[{");
  const withoutStructured =
    structuredStart >= 0 ? firstParagraph.slice(0, structuredStart) : firstParagraph;
  const cleaned = withoutStructured
    .replace(/\[artifact:[^\]]+\]/g, "")
    .replace(/(?:结果)?预览[：:]?\s*$/, "")
    .trim();
  if (cleaned.length <= maxLength) return cleaned;
  return `${cleaned.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误，请稍后重试。";
}
