import type {
  AskInput,
  Asset,
  AssetPreviewResponse,
  Artifact,
  Project,
  ProjectSummary,
  Run,
  Scenario,
} from "./types";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const rawBody = await response.text();
  if (response.ok) {
    return JSON.parse(rawBody) as T;
  }

  let message = `请求失败（HTTP ${response.status}）`;
  try {
    const body = JSON.parse(rawBody) as { detail?: unknown };
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (Array.isArray(body.detail)) {
      const details = body.detail
        .map((item) => {
          if (typeof item !== "object" || item === null) return null;
          const validation = item as { loc?: unknown; msg?: unknown };
          const location = Array.isArray(validation.loc) ? validation.loc.join(".") : "请求";
          return typeof validation.msg === "string" ? `${location}: ${validation.msg}` : null;
        })
        .filter((item): item is string => item !== null);
      if (details.length > 0) message = details.join("；");
    }
  } catch {
    if (rawBody.trim()) message = rawBody.trim();
  }
  throw new ApiError(message, response.status);
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  return parseResponse<T>(response);
}

export const api = {
  listScenarios(signal?: AbortSignal): Promise<Scenario[]> {
    return jsonRequest<Scenario[]>("/api/scenarios", { signal });
  },

  createProject(name: string, signal?: AbortSignal): Promise<ProjectSummary> {
    return jsonRequest<ProjectSummary>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
      signal,
    });
  },

  getProject(projectId: string, signal?: AbortSignal): Promise<Project> {
    return jsonRequest<Project>(`/api/projects/${encodeURIComponent(projectId)}`, { signal });
  },

  async uploadAsset(projectId: string, file: File): Promise<Asset> {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(
      `${API_BASE_URL}/api/projects/${encodeURIComponent(projectId)}/assets`,
      { method: "POST", body: form },
    );
    return parseResponse<Asset>(response);
  },

  getAssetPreview(assetId: string, signal?: AbortSignal): Promise<AssetPreviewResponse> {
    return jsonRequest<AssetPreviewResponse>(`/api/assets/${encodeURIComponent(assetId)}/preview`, {
      signal,
    });
  },

  ask(projectId: string, input: AskInput): Promise<Run> {
    return jsonRequest<Run>(`/api/projects/${encodeURIComponent(projectId)}/ask`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  getRun(runId: string, signal?: AbortSignal): Promise<Run> {
    return jsonRequest<Run>(`/api/runs/${encodeURIComponent(runId)}`, { signal });
  },

  getArtifact(artifactId: string, signal?: AbortSignal): Promise<Artifact> {
    return jsonRequest<Artifact>(`/api/artifacts/${encodeURIComponent(artifactId)}`, { signal });
  },
};
