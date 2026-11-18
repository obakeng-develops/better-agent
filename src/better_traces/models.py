from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceSession:
    """A session normalized from a source tool, before storage."""

    source: str  # 'claude-code' | 'opencode'
    source_id: str  # session id in the source tool
    project: str | None
    branch: str | None
    title: str | None
    model: str | None
    created_at: int | None  # unix ms
    updated_at: int | None  # unix ms
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw_meta: dict = field(default_factory=dict)
    auto_links: list[tuple[str, str]] = field(default_factory=list)  # (target source_id, link type)


@dataclass
class SourceMessage:
    """A message normalized from a source tool, before storage."""

    id: str  # message id in the source tool
    role: str  # 'user' | 'assistant'
    parent_id: str | None
    is_sidechain: bool
    model: str | None
    created_at: int | None  # unix ms
    parts: list[dict]  # [{type: text|thinking|tool_use|tool_result, ...}]
    text: str  # extracted plain text for FTS + display
