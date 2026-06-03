from __future__ import annotations

import json
from typing import Any

ARTIFACT_PREVIEW_MAX_BYTES = 64 * 1024
MODEL_PREVIEW_MAX_BYTES = 16 * 1024
_MAX_DEPTH = 6
_MAX_DICT_ITEMS = 100
_MAX_LIST_ITEMS = 50
_MAX_STRING_CHARS = 8_000


def _clip(value: Any, depth: int = 0) -> tuple[Any, bool]:
    if depth >= _MAX_DEPTH:
        return "<depth-limit>", True
    if isinstance(value, str):
        return value[:_MAX_STRING_CHARS], len(value) > _MAX_STRING_CHARS
    if value is None or isinstance(value, int | float | bool):
        return value, False
    if isinstance(value, list):
        clipped_items: list[Any] = []
        was_clipped = len(value) > _MAX_LIST_ITEMS
        for item in value[:_MAX_LIST_ITEMS]:
            clipped_item, item_was_clipped = _clip(item, depth + 1)
            clipped_items.append(clipped_item)
            was_clipped |= item_was_clipped
        return clipped_items, was_clipped
    if isinstance(value, dict):
        clipped_mapping: dict[str, Any] = {}
        was_clipped = len(value) > _MAX_DICT_ITEMS
        for key, item in list(value.items())[:_MAX_DICT_ITEMS]:
            key_text = str(key)
            clipped_item, item_was_clipped = _clip(item, depth + 1)
            clipped_mapping[key_text[:200]] = clipped_item
            was_clipped |= len(key_text) > 200 or item_was_clipped
        return clipped_mapping, was_clipped
    text = str(value)
    return text[:_MAX_STRING_CHARS], len(text) > _MAX_STRING_CHARS


def bounded_preview(preview: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    """Keep previews useful while enforcing a hard serialized-size boundary."""

    if max_bytes < 1_024:
        raise ValueError("preview max_bytes must be at least 1024")
    clipped, was_clipped = _clip(preview)
    if not isinstance(clipped, dict):  # pragma: no cover - dict input guarantees this
        raise TypeError("preview must be an object")
    if was_clipped:
        clipped["previewTruncated"] = True
    encoded = json.dumps(
        clipped, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) <= max_bytes:
        return clipped

    excerpt_chars = max(1, max_bytes // 8)
    bounded: dict[str, Any] = {
        "kind": str(preview.get("kind", "json"))[:100],
        "truncated": True,
        "candidatePreviewBytes": len(encoded),
        "jsonExcerpt": encoded.decode("utf-8", errors="replace")[:excerpt_chars],
    }
    final_size = len(
        json.dumps(bounded, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    if final_size > max_bytes:  # defensive for unusually escape-heavy excerpts
        bounded["jsonExcerpt"] = bounded["jsonExcerpt"][: max(1, excerpt_chars // 2)]
    return bounded
