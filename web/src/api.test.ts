import { api } from "./api";

function mockResponse(status: number, body: unknown, contentType = "application/json"): Response {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "Content-Type": contentType }),
    text: vi.fn().mockResolvedValue(text),
  } as unknown as Response;
}

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the default API origin and parses scenario responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse(200, [
        {
          name: "travel-budget",
          version: "0.1.0",
          displayName: "旅行预算分析",
          description: "预算分析",
          supportedAssetTypes: ["csv"],
          exampleQuestions: ["哪些类别超支？"],
        },
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const scenarios = await api.listScenarios();

    expect(scenarios[0]?.name).toBe("travel-budget");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/scenarios",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("turns FastAPI validation arrays into a readable message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockResponse(422, {
          detail: [{ loc: ["body", "question"], msg: "Field required" }],
        }),
      ),
    );

    await expect(api.createProject("")).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "body.question: Field required",
    });
  });

  it("keeps a useful plain-text upstream error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(500, "Internal Server Error")));

    await expect(api.getRun("broken")).rejects.toThrow("Internal Server Error");
  });

  it("uploads with the required multipart field and no JSON content type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse(201, {
        id: "asset-1",
        projectId: "project-1",
        filename: "notes.md",
        mediaType: "text/markdown",
        kind: "markdown",
        sha256: "abc",
        byteSize: 4,
        profile: {
          kind: "document",
          text: "note",
          lineCount: 1,
          characterCount: 4,
          truncated: false,
        },
        createdAt: "2026-08-31T10:00:00",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["note"], "notes.md", { type: "text/markdown" });

    await api.uploadAsset("project-1", file);

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(request.body).toBeInstanceOf(FormData);
    expect((request.body as FormData).get("file")).toBe(file);
    expect(request.headers).toBeUndefined();
  });

  it("sends every ask inside an explicit Conversation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await api.ask("project-1", {
      scenarioName: "travel-budget",
      question: "哪些费用超支？",
      assetIds: ["asset-1"],
      conversationId: "conversation-1",
    });

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      scenarioName: "travel-budget",
      question: "哪些费用超支？",
      assetIds: ["asset-1"],
      conversationId: "conversation-1",
    });
  });
});
