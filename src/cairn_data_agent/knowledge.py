from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

KNOWLEDGE_TOP_K = 4
KNOWLEDGE_MAX_CHUNK_CHARS = 1_000
KNOWLEDGE_MAX_TOTAL_CHARS = 4_000

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_CJK_STOP_TERMS = frozenset(
    {
        "一个",
        "什么",
        "以及",
        "可以",
        "哪些",
        "如何",
        "是否",
        "请问",
        "进行",
        "这个",
    }
)


@dataclass(frozen=True)
class KnowledgeChunk:
    source: str
    chunk_id: str
    line_start: int
    line_end: int
    text: str


@dataclass(frozen=True)
class KnowledgeHit:
    chunk: KnowledgeChunk
    score: int
    matched_terms: tuple[str, ...]

    def as_context_item(self) -> dict[str, object]:
        return {
            "source": self.chunk.source,
            "chunkId": self.chunk.chunk_id,
            "lineStart": self.chunk.line_start,
            "lineEnd": self.chunk.line_end,
            "text": self.chunk.text,
            "score": self.score,
            "matchedTerms": list(self.matched_terms),
        }


def _stable_chunk_id(
    *, source: str, line_start: int, line_end: int, text: str, character_start: int = 0
) -> str:
    payload = json.dumps(
        [source, line_start, line_end, character_start, text],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"knowledge:{hashlib.sha256(payload).hexdigest()}"


def _paragraphs(content: str) -> list[tuple[int, list[str]]]:
    paragraphs: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start_line = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        if line.strip():
            if not current:
                start_line = line_number
            current.append(line)
        elif current:
            paragraphs.append((start_line, current))
            current = []
    if current:
        paragraphs.append((start_line, current))
    return paragraphs


def _bounded_paragraphs(
    *, source: str, start_line: int, lines: list[str], max_chars: int
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    buffered: list[str] = []
    buffered_start = start_line

    def append_buffer() -> None:
        if not buffered:
            return
        text = "\n".join(buffered)
        line_end = buffered_start + len(buffered) - 1
        chunks.append(
            KnowledgeChunk(
                source=source,
                chunk_id=_stable_chunk_id(
                    source=source,
                    line_start=buffered_start,
                    line_end=line_end,
                    text=text,
                ),
                line_start=buffered_start,
                line_end=line_end,
                text=text,
            )
        )
        buffered.clear()

    for offset, line in enumerate(lines):
        line_number = start_line + offset
        if len(line) > max_chars:
            append_buffer()
            for position in range(0, len(line), max_chars):
                text = line[position : position + max_chars]
                chunks.append(
                    KnowledgeChunk(
                        source=source,
                        chunk_id=_stable_chunk_id(
                            source=source,
                            line_start=line_number,
                            line_end=line_number,
                            text=text,
                            character_start=position,
                        ),
                        line_start=line_number,
                        line_end=line_number,
                        text=text,
                    )
                )
            buffered_start = line_number + 1
            continue

        candidate_size = sum(len(item) for item in buffered) + len(buffered) + len(line)
        if buffered and candidate_size > max_chars:
            append_buffer()
            buffered_start = line_number
        elif not buffered:
            buffered_start = line_number
        buffered.append(line)

    append_buffer()
    return chunks


def chunk_knowledge(
    knowledge: tuple[tuple[str, str], ...],
    *,
    max_chunk_chars: int = KNOWLEDGE_MAX_CHUNK_CHARS,
) -> tuple[KnowledgeChunk, ...]:
    """Split Markdown into deterministic, line-addressable, bounded chunks."""

    if max_chunk_chars < 1:
        raise ValueError("max_chunk_chars must be positive")

    chunks: list[KnowledgeChunk] = []
    seen_ids: set[str] = set()
    for source, content in sorted(knowledge, key=lambda item: item[0]):
        for start_line, lines in _paragraphs(content):
            for chunk in _bounded_paragraphs(
                source=source,
                start_line=start_line,
                lines=lines,
                max_chars=max_chunk_chars,
            ):
                if chunk.chunk_id not in seen_ids:
                    chunks.append(chunk)
                    seen_ids.add(chunk.chunk_id)
    return tuple(chunks)


def _lexical_terms(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    terms = {
        token
        for token in _LATIN_OR_NUMBER.findall(normalized)
        if len(token) >= 2 or token.isdigit()
    }
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            terms.add(run)
            continue
        for width in (2, 3):
            terms.update(run[index : index + width] for index in range(len(run) - width + 1))
    return frozenset(terms - _CJK_STOP_TERMS)


def _term_weight(term: str) -> int:
    if _CJK_RUN.fullmatch(term):
        return len(term) * 2
    return min(len(term), 8)


def retrieve_knowledge(
    knowledge: tuple[tuple[str, str], ...],
    question: str,
    *,
    top_k: int = KNOWLEDGE_TOP_K,
    max_chunk_chars: int = KNOWLEDGE_MAX_CHUNK_CHARS,
    max_total_chars: int = KNOWLEDGE_MAX_TOTAL_CHARS,
) -> list[dict[str, object]]:
    """Return deterministic lexical hits without network or external indexes."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    if max_total_chars < 1:
        raise ValueError("max_total_chars must be positive")

    query_terms = _lexical_terms(question)
    if not query_terms:
        return []

    effective_chunk_limit = min(max_chunk_chars, max_total_chars)
    candidates: list[KnowledgeHit] = []
    for chunk in chunk_knowledge(knowledge, max_chunk_chars=effective_chunk_limit):
        matched_terms = tuple(
            sorted(query_terms & _lexical_terms(chunk.text), key=lambda term: (-len(term), term))
        )
        if not matched_terms:
            continue
        candidates.append(
            KnowledgeHit(
                chunk=chunk,
                score=sum(_term_weight(term) for term in matched_terms),
                matched_terms=matched_terms,
            )
        )

    candidates.sort(
        key=lambda hit: (
            -hit.score,
            hit.chunk.source,
            hit.chunk.line_start,
            hit.chunk.line_end,
            hit.chunk.chunk_id,
        )
    )
    selected: list[dict[str, object]] = []
    used_chars = 0
    for hit in candidates:
        if len(selected) >= top_k:
            break
        text_size = len(hit.chunk.text)
        if used_chars + text_size > max_total_chars:
            continue
        selected.append(hit.as_context_item())
        used_chars += text_size
    return selected
