import type { Artifact } from "../types";
import { shortHash } from "../ui";

interface AnswerTextProps {
  text: string;
  artifacts: Artifact[];
  onSelect: (artifact: Artifact) => void;
}

interface StructuredRows {
  prefix: string;
  suffix: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
}

function parseStructuredRows(value: string): StructuredRows | null {
  const start = value.indexOf("[{");
  const end = value.lastIndexOf("}]");
  if (start < 0 || end < start) return null;
  try {
    const parsed: unknown = JSON.parse(value.slice(start, end + 2));
    if (
      !Array.isArray(parsed) ||
      parsed.length === 0 ||
      !parsed.every((row) => typeof row === "object" && row !== null && !Array.isArray(row))
    )
      return null;
    const rows = parsed as Array<Record<string, unknown>>;
    const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    if (columns.length === 0) return null;
    return {
      prefix: value.slice(0, start).trim(),
      suffix: value.slice(end + 2).trim(),
      columns,
      rows,
    };
  } catch {
    return null;
  }
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function evidenceMetadata(value: string): { citation: string; sha256: string | null } | null {
  const trimmed = value.trim();
  if (!trimmed.startsWith("证据：")) return null;
  const match = /（SHA-256:\s*([a-fA-F0-9]{32,})）\s*$/.exec(trimmed);
  return {
    citation: trimmed
      .slice("证据：".length, match?.index ?? trimmed.length)
      .trim()
      .replace(/[。；;]+$/, ""),
    sha256: match?.[1] ?? null,
  };
}

function InlineAnswer({
  text,
  artifacts,
  onSelect,
}: {
  text: string;
  artifacts: Artifact[];
  onSelect: (artifact: Artifact) => void;
}) {
  const pieces = text.split(/(\[artifact:[^\]]+\])/g);
  return pieces.map((piece, index) => {
    const match = /^\[artifact:([^\]]+)\]$/.exec(piece);
    const artifact = match ? artifacts.find((item) => item.id === match[1]) : undefined;
    return artifact ? (
      <button
        className="citation-link"
        type="button"
        key={`${artifact.id}-${index}`}
        onClick={() => onSelect(artifact)}
      >
        [证据 · {artifact.stepId}]
      </button>
    ) : (
      <span key={index}>{piece}</span>
    );
  });
}

export function AnswerText({ text, artifacts, onSelect }: AnswerTextProps) {
  const paragraphs = text.split(/\n{2,}/).filter((paragraph) => paragraph.trim().length > 0);
  return (
    <div className="answer-text">
      {paragraphs.map((paragraph, index) => {
        if (paragraph.trim().startsWith("回答口径："))
          return (
            <details className="answer-method" key={index}>
              <summary>回答依据与口径</summary>
              <p>{paragraph.trim().slice("回答口径：".length)}</p>
            </details>
          );
        const evidence = evidenceMetadata(paragraph);
        if (evidence)
          return (
            <div className="answer-source" key={index}>
              <span className="answer-source-label">
                <i aria-hidden="true" /> Evidence
              </span>
              <span>
                <InlineAnswer text={evidence.citation} artifacts={artifacts} onSelect={onSelect} />
              </span>
              {evidence.sha256 && (
                <code title={evidence.sha256}>SHA {shortHash(evidence.sha256)}</code>
              )}
            </div>
          );
        const structured = parseStructuredRows(paragraph);
        if (!structured)
          return (
            <p className="answer-paragraph" key={index}>
              <InlineAnswer text={paragraph} artifacts={artifacts} onSelect={onSelect} />
            </p>
          );
        return (
          <div className="answer-result" key={index}>
            {structured.prefix && (
              <p className="answer-paragraph">
                <InlineAnswer text={structured.prefix} artifacts={artifacts} onSelect={onSelect} />
              </p>
            )}
            <div className="answer-data">
              <header>
                <strong>结构化结果</strong>
                <span>{structured.rows.length} 行</span>
              </header>
              <div className="answer-data-scroll">
                <table aria-label="回答中的结构化结果">
                  <thead>
                    <tr>
                      {structured.columns.map((column) => (
                        <th scope="col" key={column}>
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {structured.rows.slice(0, 12).map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {structured.columns.map((column) => (
                          <td key={column}>{displayValue(row[column])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {structured.rows.length > 12 && (
                <small>仅展示前 12 行，完整结果请查看 Artifact。</small>
              )}
            </div>
            {structured.suffix && (
              <p className="answer-paragraph">
                <InlineAnswer text={structured.suffix} artifacts={artifacts} onSelect={onSelect} />
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
