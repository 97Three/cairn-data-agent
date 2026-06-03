from __future__ import annotations

from typing import Any

from .contracts import SkillManifest
from .database import AssetRecord
from .knowledge import retrieve_knowledge
from .registry import ScenarioBundle

CONVERSATION_MAX_MESSAGES = 6
CONVERSATION_MAX_MESSAGE_CHARS = 1_000
CONVERSATION_MAX_TOTAL_CHARS = 4_000
PROFILE_MAX_COLUMNS = 40
PROFILE_MAX_ROWS = 2
PROFILE_MAX_CELL_CHARS = 120


def _bounded_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    remaining = CONVERSATION_MAX_TOTAL_CHARS
    for message in reversed(history[-CONVERSATION_MAX_MESSAGES:]):
        if remaining <= 0:
            break
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = message.get("content", "")[: min(CONVERSATION_MAX_MESSAGE_CHARS, remaining)]
        selected.append({"role": role, "content": content})
        remaining -= len(content)
    selected.reverse()
    return selected


def _bounded_cell(value: Any) -> Any:
    if isinstance(value, str):
        return value[:PROFILE_MAX_CELL_CHARS]
    if value is None or isinstance(value, int | float | bool):
        return value
    return str(value)[:PROFILE_MAX_CELL_CHARS]


def _bounded_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("kind") == "document":
        return {
            "kind": "document",
            "text": str(profile.get("text", ""))[:1_000],
            "lineCount": profile.get("lineCount", 0),
            "characterCount": profile.get("characterCount", 0),
            "truncated": bool(profile.get("truncated")),
        }
    if profile.get("kind") == "table":
        raw_columns = profile.get("columns", [])
        columns = [
            {
                "name": str(column.get("name", ""))[:PROFILE_MAX_CELL_CHARS],
                "type": str(column.get("type", ""))[:PROFILE_MAX_CELL_CHARS],
            }
            for column in raw_columns[:PROFILE_MAX_COLUMNS]
            if isinstance(column, dict)
        ]
        allowed_names = {column["name"] for column in columns}
        raw_rows = profile.get("rows", [])
        rows = [
            {
                str(name)[:PROFILE_MAX_CELL_CHARS]: _bounded_cell(value)
                for name, value in row.items()
                if str(name)[:PROFILE_MAX_CELL_CHARS] in allowed_names
            }
            for row in raw_rows[:PROFILE_MAX_ROWS]
            if isinstance(row, dict)
        ]
        return {
            "kind": "table",
            "columns": columns,
            "rows": rows,
            "rowCount": profile.get("rowCount", 0),
            "columnCount": profile.get("columnCount", 0),
            "truncated": bool(profile.get("truncated"))
            or len(raw_columns) > len(columns)
            or len(raw_rows) > len(rows),
        }
    return {"kind": str(profile.get("kind", "unknown")), "summary": str(profile)[:1_000]}


def build_context(
    *,
    scenario: ScenarioBundle,
    question: str,
    assets: list[AssetRecord],
    skills: list[SkillManifest],
    conversation_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a bounded model context from platform-owned facts."""

    return {
        "version": "cairn.agent-context/v1",
        "scenario": {
            "name": scenario.manifest.metadata.name,
            "version": scenario.manifest.metadata.version,
            "instructions": scenario.manifest.instructions[:4000],
            "knowledge": retrieve_knowledge(scenario.knowledge, question),
            "authorizedSkills": [
                {
                    "name": skill.metadata.name,
                    "version": skill.metadata.version,
                    "description": skill.metadata.description[:1_000],
                    "mode": skill.mode,
                    "effect": skill.effect,
                    "permissions": skill.permissions.model_dump(mode="json"),
                }
                for skill in skills
            ],
        },
        "conversation": {
            "id": conversation_id,
            "history": _bounded_history(history or []),
        },
        "question": question,
        "assets": [
            {
                "id": asset.id,
                "filename": asset.filename[:255],
                "kind": asset.kind,
                "byteSize": asset.byte_size,
                "sha256": asset.blob_sha256,
                "profile": _bounded_profile(asset.profile),
            }
            for asset in assets
        ],
    }
