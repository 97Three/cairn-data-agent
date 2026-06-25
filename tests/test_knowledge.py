from __future__ import annotations

from cairn_data_agent.context import build_context
from cairn_data_agent.database import AssetRecord
from cairn_data_agent.knowledge import chunk_knowledge, retrieve_knowledge
from cairn_data_agent.registry import ScenarioRegistry


def test_markdown_paragraphs_have_stable_ids_and_source_lines() -> None:
    knowledge = (
        (
            "knowledge/rules.md",
            "# 预算规则\n\n预算需要记录。\n实际支出需要核对。\n\n引用必须带行号。\n",
        ),
    )

    first = chunk_knowledge(knowledge)
    second = chunk_knowledge(knowledge)

    assert first == second
    assert [(item.line_start, item.line_end) for item in first] == [(1, 1), (3, 4), (6, 6)]
    assert all(item.chunk_id.startswith("knowledge:") for item in first)
    assert len({item.chunk_id for item in first}) == 3


def test_long_markdown_lines_are_split_at_the_strict_chunk_limit() -> None:
    chunks = chunk_knowledge(
        (
            (
                "knowledge/long.md",
                f"短行\n{'预算' * 12}\n末行",
            ),
        ),
        max_chunk_chars=10,
    )

    assert all(len(item.text) <= 10 for item in chunks)
    long_line_chunks = [item for item in chunks if item.line_start == 2]
    assert len(long_line_chunks) == 3
    assert all(item.line_end == 2 for item in long_line_chunks)


def test_retrieval_is_relevant_stable_and_bounded() -> None:
    knowledge = (
        ("knowledge/z.md", "预算偏差需要核对。\n\n预算偏差需要解释。"),
        ("knowledge/a.md", "预算偏差必须引用实际支出。\n\n完全无关的段落。"),
    )

    first = retrieve_knowledge(
        knowledge,
        "如何解释预算偏差？",
        top_k=2,
        max_chunk_chars=14,
        max_total_chars=24,
    )
    second = retrieve_knowledge(
        tuple(reversed(knowledge)),
        "如何解释预算偏差？",
        top_k=2,
        max_chunk_chars=14,
        max_total_chars=24,
    )

    assert first == second
    assert 0 < len(first) <= 2
    assert all(len(str(item["text"])) <= 14 for item in first)
    assert sum(len(str(item["text"])) for item in first) <= 24
    assert all(item["score"] for item in first)
    assert all(item["matchedTerms"] for item in first)
    assert all({"chunkId", "lineStart", "lineEnd"} <= item.keys() for item in first)


def test_retrieval_returns_no_irrelevant_or_empty_query_hits() -> None:
    knowledge = (("knowledge/rules.md", "预算偏差需要核对。"),)

    assert retrieve_knowledge(knowledge, "天文观测") == []
    assert retrieve_knowledge(knowledge, " ") == []


def test_retrieval_rejects_invalid_bounds() -> None:
    knowledge = (("knowledge/rules.md", "预算规则"),)

    for arguments in (
        {"top_k": 0},
        {"max_chunk_chars": 0},
        {"max_total_chars": 0},
    ):
        try:
            retrieve_knowledge(knowledge, "预算", **arguments)
        except ValueError as error:
            assert "positive" in str(error)
        else:
            raise AssertionError("invalid retrieval bounds must fail")


def test_build_context_keeps_signature_and_injects_only_retrieved_chunks(project_root) -> None:
    scenario = ScenarioRegistry(project_root / "scenarios").get("travel-budget")

    context = build_context(
        scenario=scenario,
        question="预算偏差如何计算？",
        assets=[],
        skills=[],
    )

    hits = context["scenario"]["knowledge"]
    assert hits
    assert all("预算" in hit["text"] or "偏差" in hit["text"] for hit in hits)
    assert all(hit["source"] == "knowledge/budget-rules.md" for hit in hits)
    assert all(hit["chunkId"].startswith("knowledge:") for hit in hits)


def test_context_bounds_conversation_history_and_asset_profile(project_root) -> None:
    scenario = ScenarioRegistry(project_root / "scenarios").get("travel-budget")
    column_names = [f"column-{index}-{'x' * 150}" for index in range(45)]
    asset = AssetRecord(
        id="asset-1",
        project_id="project-1",
        filename="f" * 300,
        media_type="text/csv",
        kind="csv",
        blob_sha256="a" * 64,
        byte_size=10,
        profile={
            "kind": "table",
            "columns": [{"name": name, "type": "String"} for name in column_names],
            "rows": [{name: "v" * 500 for name in column_names} for _ in range(4)],
            "rowCount": 4,
            "columnCount": 45,
            "truncated": False,
        },
    )
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": str(index) * 2_000}
        for index in range(8)
    ]

    context = build_context(
        scenario=scenario,
        question="预算偏差如何计算？",
        assets=[asset],
        skills=[],
        conversation_id="conversation-1",
        history=history,
    )

    bounded_history = context["conversation"]["history"]
    assert context["conversation"]["id"] == "conversation-1"
    assert len(bounded_history) <= 6
    assert all(len(item["content"]) <= 1_000 for item in bounded_history)
    assert sum(len(item["content"]) for item in bounded_history) <= 4_000
    assert bounded_history[-1]["content"].startswith("7")

    bounded_asset = context["assets"][0]
    profile = bounded_asset["profile"]
    assert len(bounded_asset["filename"]) == 255
    assert len(profile["columns"]) == 40
    assert len(profile["rows"]) == 2
    assert profile["truncated"] is True
    assert all(len(str(value)) <= 120 for row in profile["rows"] for value in row.values())
