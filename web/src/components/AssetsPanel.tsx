import type { ChangeEvent } from "react";
import type { Asset, AssetKind } from "../types";
import { ASSET_KIND_LABELS, formatBytes, shortHash } from "../ui";

interface AssetsPanelProps {
  assets: Asset[];
  supportedKinds: AssetKind[];
  selectedIds: Set<string>;
  previewedAssetId: string | null;
  uploading: boolean;
  onFiles: (files: File[]) => void;
  onToggle: (assetId: string) => void;
  onPreview: (asset: Asset) => void;
}

function assetSummary(asset: Asset): string {
  const profile = asset.profile;
  if ("rowCount" in profile && typeof profile.rowCount === "number")
    return `${profile.rowCount} 行${typeof profile.columnCount === "number" ? ` · ${profile.columnCount} 列` : ""}`;
  if ("lineCount" in profile && typeof profile.lineCount === "number")
    return `${profile.lineCount} 行`;
  return formatBytes(asset.byteSize);
}

export function AssetsPanel({
  assets,
  supportedKinds,
  selectedIds,
  previewedAssetId,
  uploading,
  onFiles,
  onToggle,
  onPreview,
}: AssetsPanelProps) {
  const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length > 0) onFiles(files);
  };
  return (
    <section className="rail-section assets-section" aria-labelledby="assets-heading">
      <div className="section-title section-title--with-action">
        <span>02</span>
        <div>
          <p className="eyebrow">Assets</p>
          <h2 id="assets-heading">数据资产</h2>
        </div>
        <label className={`upload-action${uploading ? " is-busy" : ""}`}>
          <input
            data-testid="asset-upload"
            type="file"
            accept=".csv,.xlsx,.md,.markdown"
            multiple
            disabled={uploading}
            onChange={handleFiles}
          />
          <span aria-hidden="true">＋</span>
          {uploading ? "解析中" : "上传"}
        </label>
      </div>
      <p className="section-note">CSV、XLSX、Markdown · 可多选</p>
      {assets.length === 0 ? (
        <label className="asset-dropzone">
          <input
            data-testid="asset-upload-empty"
            type="file"
            accept=".csv,.xlsx,.md,.markdown"
            multiple
            disabled={uploading}
            onChange={handleFiles}
          />
          <span aria-hidden="true">⇧</span>
          <strong>{uploading ? "正在建立数据画像…" : "拖入或选择数据文件"}</strong>
          <small>文件仅进入当前教学 Project</small>
        </label>
      ) : (
        <ul className="asset-list" aria-label="已上传资产">
          {assets.map((asset) => {
            const compatible = supportedKinds.includes(asset.kind);
            const selected = selectedIds.has(asset.id);
            return (
              <li
                className={`${!compatible ? "is-incompatible" : ""}${previewedAssetId === asset.id ? " is-previewed" : ""}`}
                key={asset.id}
              >
                <label className="asset-select">
                  <input
                    type="checkbox"
                    checked={selected}
                    disabled={!compatible}
                    onChange={() => onToggle(asset.id)}
                    aria-label={`选择 ${asset.filename}`}
                  />
                  <span aria-hidden="true">✓</span>
                </label>
                <button
                  className="asset-main"
                  type="button"
                  onClick={() => onPreview(asset)}
                  aria-label={`预览 ${asset.filename}`}
                >
                  <span className={`file-kind file-kind--${asset.kind}`}>
                    {ASSET_KIND_LABELS[asset.kind]}
                  </span>
                  <span className="asset-copy">
                    <strong title={asset.filename}>{asset.filename}</strong>
                    <small>
                      {assetSummary(asset)} · {shortHash(asset.sha256)}
                    </small>
                    {!compatible && <em>当前场景不支持</em>}
                  </span>
                  <span className="asset-arrow" aria-hidden="true">
                    ›
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {selectedIds.size > 1 && (
        <p className="multi-asset-note" role="status">
          <span aria-hidden="true">i</span>
          <span>
            已选 {selectedIds.size} 个资产。请明确关联、对比或检索关系；未被计划实际消费的资产会被
            Policy 拒绝。
          </span>
        </p>
      )}
    </section>
  );
}
