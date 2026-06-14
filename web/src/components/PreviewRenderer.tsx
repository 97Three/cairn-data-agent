import type { Preview, TableColumn } from "../types";

interface PreviewRendererProps {
  preview: Preview;
  compact?: boolean;
}

interface JsonBlockProps {
  value: unknown;
  label?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function textCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function tableShape(preview: Preview): {
  columns: TableColumn[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  truncated: boolean;
} | null {
  if (!isRecord(preview) || !Array.isArray(preview.rows)) return null;
  const rows = preview.rows.filter(isRecord);
  const declaredColumns = Array.isArray(preview.columns)
    ? preview.columns
        .filter(isRecord)
        .filter((column) => typeof column.name === "string")
        .map((column) => ({
          name: String(column.name),
          type: typeof column.type === "string" ? column.type : "unknown",
        }))
    : [];
  const inferredColumns = rows[0]
    ? Object.keys(rows[0]).map((name) => ({ name, type: "unknown" }))
    : [];
  return {
    columns: declaredColumns.length > 0 ? declaredColumns : inferredColumns,
    rows,
    rowCount: typeof preview.rowCount === "number" ? preview.rowCount : rows.length,
    truncated: preview.truncated === true,
  };
}

export function JsonBlock({ value, label = "JSON" }: JsonBlockProps) {
  return (
    <pre className="json-block" aria-label={label}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function PreviewRenderer({ preview, compact = false }: PreviewRendererProps) {
  const table = tableShape(preview);
  if (table) {
    const renderLimit = compact ? 20 : 200;
    const visibleRows = table.rows.slice(0, renderLimit);
    const locallyTruncated = table.rows.length > renderLimit;
    return (
      <div className="data-preview">
        <div className="preview-meta">
          <span>{table.rowCount.toLocaleString("zh-CN")} 行</span>
          <span>{table.columns.length} 列</span>
          {(table.truncated || locallyTruncated) && <span className="warm-label">预览已截断</span>}
        </div>
        {table.rows.length === 0 ? (
          <p className="empty-inline">结果表为空。</p>
        ) : (
          <div className={`table-scroll${compact ? " table-scroll--compact" : ""}`}>
            <table>
              <caption className="sr-only">数据预览</caption>
              <thead>
                <tr>
                  {table.columns.map((column) => (
                    <th key={column.name} scope="col">
                      <span>{column.name}</span>
                      {column.type !== "unknown" && <small>{column.type}</small>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {table.columns.map((column) => (
                      <td key={column.name}>{textCell(row[column.name])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  if (isRecord(preview) && typeof preview.text === "string") {
    return (
      <div className="document-preview">
        <div className="preview-meta">
          {typeof preview.lineCount === "number" && <span>{preview.lineCount} 行</span>}
          {typeof preview.characterCount === "number" && (
            <span>{preview.characterCount.toLocaleString("zh-CN")} 字符</span>
          )}
          {preview.truncated === true && <span className="warm-label">预览已截断</span>}
        </div>
        <pre>{preview.text}</pre>
      </div>
    );
  }

  if (isRecord(preview) && Array.isArray(preview.hits)) {
    const hits = preview.hits.filter(isRecord);
    return (
      <div className="evidence-preview">
        {typeof preview.query === "string" && (
          <p className="evidence-query">
            <span>检索词</span>
            {preview.query}
          </p>
        )}
        {hits.length === 0 ? (
          <p className="empty-inline">所选文档中没有找到相关证据。</p>
        ) : (
          <ol className="evidence-list">
            {hits.map((hit, index) => (
              <li key={`${String(hit.assetId)}-${String(hit.lineStart)}-${index}`}>
                <div className="evidence-location">
                  <strong>{String(hit.filename ?? "未命名文档")}</strong>
                  <span>
                    L{String(hit.lineStart ?? "?")}–L{String(hit.lineEnd ?? "?")}
                  </span>
                </div>
                <blockquote>{String(hit.quote ?? "")}</blockquote>
              </li>
            ))}
          </ol>
        )}
      </div>
    );
  }

  return <JsonBlock value={preview} label="预览 JSON" />;
}
