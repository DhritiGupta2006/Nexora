"""Data models for corpus documents, sections, and chunks."""

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Dict, List, Optional


def sanitize_id(val: str) -> str:
    """Sanitize section/doc names to alphanumeric with underscores and hyphens."""
    cleaned = re.sub(r"[^\w\-]+", "_", val.strip()).strip("_")
    return cleaned if cleaned else "sec"


@dataclass
class Section:
    title: str
    text: str
    section_id: str = ""

    def __post_init__(self):
        if not self.section_id:
            self.section_id = sanitize_id(self.title)


@dataclass
class Document:
    doc_id: str
    title: str
    sections: List[Section] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.doc_id = sanitize_id(self.doc_id)
        if not self.sections and "text" in self.metadata:
            self.sections.append(Section(title="main", text=self.metadata["text"]))


@dataclass
class Chunk:
    chunk_id: str  # Format: Doc_ID§Section or Doc_ID§Section_N
    doc_id: str
    section_id: str
    section_title: str
    text: str
    token_count: int
    char_start: int
    char_end: int
    chunk_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_hash(self) -> str:
        payload = f"{self.chunk_id}:{self.text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "text": self.text,
            "token_count": self.token_count,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
            "chunk_hash": self.chunk_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        return cls(
            chunk_id=data["chunk_id"],
            doc_id=data["doc_id"],
            section_id=data["section_id"],
            section_title=data.get("section_title", ""),
            text=data["text"],
            token_count=data["token_count"],
            char_start=data.get("char_start", 0),
            char_end=data.get("char_end", len(data["text"])),
            chunk_index=data.get("chunk_index", 0),
            metadata=data.get("metadata", {}),
        )
