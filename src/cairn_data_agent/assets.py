from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import fastexcel
import polars as pl
from sqlalchemy.orm import Session

from .config import Settings
from .database import AssetRecord
from .previews import ARTIFACT_PREVIEW_MAX_BYTES, bounded_preview
from .storage import LocalBlobStore

SUPPORTED_SUFFIXES = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".md": "markdown",
    ".markdown": "markdown",
}


class AssetError(ValueError):
    pass


def asset_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        return SUPPORTED_SUFFIXES[suffix]
    except KeyError as error:
        raise AssetError("仅支持 CSV、XLSX 和 Markdown 文件") from error


def read_table(content: bytes, kind: str) -> pl.DataFrame:
    try:
        if kind == "csv":
            frame = pl.read_csv(io.BytesIO(content), try_parse_dates=True)
            if frame.columns:
                frame = frame.filter(
                    ~pl.all_horizontal([pl.col(column).is_null() for column in frame.columns])
                )
            return frame
        if kind == "xlsx":
            workbook = fastexcel.read_excel(content)
            if len(workbook.sheet_names) != 1:
                raise AssetError(
                    "XLSX 必须且只能包含一个工作表；"
                    f"当前检测到 {len(workbook.sheet_names)} 个工作表"
                )
            return workbook.load_sheet(0).to_polars()
    except AssetError:
        raise
    except Exception as error:  # library errors are normalized at the boundary
        raise AssetError(f"无法解析表格：{error}") from error
    raise AssetError("资产不是表格")


def read_markdown(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AssetError("Markdown 必须使用 UTF-8 编码") from error


def _json_scalar(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def frame_preview(frame: pl.DataFrame, row_limit: int) -> dict[str, Any]:
    rows = [
        {column: _json_scalar(value) for column, value in row.items()}
        for row in frame.head(row_limit).to_dicts()
    ]
    return {
        "kind": "table",
        "columns": [{"name": name, "type": str(dtype)} for name, dtype in frame.schema.items()],
        "rows": rows,
        "rowCount": frame.height,
        "columnCount": frame.width,
        "truncated": frame.height > row_limit,
    }


def markdown_preview(text: str, character_limit: int = 4000) -> dict[str, Any]:
    lines = text.splitlines()
    return {
        "kind": "document",
        "text": text[:character_limit],
        "lineCount": len(lines),
        "characterCount": len(text),
        "truncated": len(text) > character_limit,
    }


class AssetService:
    def __init__(self, settings: Settings, blobs: LocalBlobStore):
        self._settings = settings
        self._blobs = blobs

    def ingest(
        self,
        session: Session,
        *,
        project_id: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> AssetRecord:
        safe_filename = Path(filename).name
        kind = asset_kind(safe_filename)
        if not content:
            raise AssetError("文件不能为空")
        if len(content) > self._settings.max_upload_bytes:
            raise AssetError(f"文件超过 {self._settings.max_upload_bytes} 字节教学版上限")

        if kind in {"csv", "xlsx"}:
            profile = bounded_preview(
                frame_preview(read_table(content, kind), min(self._settings.preview_rows, 10)),
                max_bytes=ARTIFACT_PREVIEW_MAX_BYTES,
            )
        else:
            profile = bounded_preview(
                markdown_preview(read_markdown(content), character_limit=1000),
                max_bytes=ARTIFACT_PREVIEW_MAX_BYTES,
            )

        blob = self._blobs.put(content)
        asset = AssetRecord(
            project_id=project_id,
            filename=safe_filename,
            media_type=media_type or "application/octet-stream",
            kind=kind,
            blob_sha256=blob.sha256,
            byte_size=blob.byte_size,
            profile=profile,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset

    def preview(self, asset: AssetRecord) -> dict[str, Any]:
        content = self._content(asset)
        if asset.kind in {"csv", "xlsx"}:
            preview = frame_preview(read_table(content, asset.kind), self._settings.preview_rows)
        else:
            preview = markdown_preview(read_markdown(content))
        return bounded_preview(preview, max_bytes=ARTIFACT_PREVIEW_MAX_BYTES)

    def load_table(self, asset: AssetRecord) -> pl.DataFrame:
        return read_table(self._content(asset), asset.kind)

    def load_document(self, asset: AssetRecord) -> str:
        if asset.kind != "markdown":
            raise AssetError("资产不是 Markdown 文档")
        return read_markdown(self._content(asset))

    def _content(self, asset: AssetRecord) -> bytes:
        content = self._blobs.get(asset.blob_sha256)
        if len(content) != asset.byte_size:
            raise AssetError("资产字节数与登记信息不一致")
        return content
