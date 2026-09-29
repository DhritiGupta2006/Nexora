"""Corpus loaders for JSON, JSONL, Markdown, and raw text formats."""

import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Union

from slrag.corpus.models import Document, Section, sanitize_id


def parse_markdown_to_sections(content: str, default_title: str = "main") -> List[Section]:
    """Parse Markdown content into Sections based on header hierarchy."""
    lines = content.splitlines()
    sections: List[Section] = []
    current_title = default_title
    current_lines: List[str] = []

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            # Header found
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append(Section(title=current_title, text=text, section_id=sanitize_id(current_title)))
                current_lines = []
            current_title = match.group(2).strip()
        else:
            current_lines.append(line)

    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(Section(title=current_title, text=text, section_id=sanitize_id(current_title)))

    if not sections:
        sections.append(Section(title=default_title, text=content.strip(), section_id=sanitize_id(default_title)))

    return sections


class CorpusLoader:
    """Loader to ingest various document formats and normalize into structured Documents."""

    @classmethod
    def load_dict(cls, data: Dict[str, Any]) -> Document:
        doc_id = str(data.get("doc_id") or data.get("id") or "doc_unknown")
        title = str(data.get("title") or doc_id)
        sections: List[Section] = []

        if "sections" in data and isinstance(data["sections"], list):
            for s in data["sections"]:
                if isinstance(s, dict):
                    sec_title = s.get("title", "section")
                    sec_text = s.get("text") or s.get("content") or ""
                    sec_id = s.get("section_id") or sanitize_id(sec_title)
                    sections.append(Section(title=sec_title, text=sec_text, section_id=sec_id))
                elif isinstance(s, str):
                    sections.append(Section(title="sec", text=s, section_id=f"sec_{len(sections)}"))
        elif "content" in data or "text" in data:
            raw_text = str(data.get("content") or data.get("text"))
            sections = parse_markdown_to_sections(raw_text, default_title="main")
        else:
            sections.append(Section(title="main", text=json.dumps(data), section_id="main"))

        metadata = {k: v for k, v in data.items() if k not in ("doc_id", "id", "title", "sections")}
        return Document(doc_id=doc_id, title=title, sections=sections, metadata=metadata)

    @classmethod
    def load_file(cls, path: Union[str, Path]) -> List[Document]:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = file_path.suffix.lower()
        docs: List[Document] = []

        if suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, list):
                    for item in content:
                        docs.append(cls.load_dict(item))
                elif isinstance(content, dict):
                    docs.append(cls.load_dict(content))
        elif suffix == ".jsonl":
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        docs.append(cls.load_dict(json.loads(line)))
        elif suffix in (".md", ".markdown", ".txt"):
            doc_id = sanitize_id(file_path.stem)
            with open(file_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            sections = parse_markdown_to_sections(raw_text, default_title="main")
            docs.append(Document(doc_id=doc_id, title=file_path.stem, sections=sections))
        else:
            # Fallback text
            doc_id = sanitize_id(file_path.stem)
            with open(file_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            docs.append(Document(doc_id=doc_id, title=file_path.stem, sections=[Section(title="main", text=raw_text)]))

        return docs

    @classmethod
    def load_directory(cls, dir_path: Union[str, Path], recursive: bool = True) -> List[Document]:
        base = Path(dir_path)
        if not base.is_dir():
            raise NotADirectoryError(f"Directory not found: {dir_path}")

        docs: List[Document] = []
        pattern = "**/*" if recursive else "*"
        for p in base.glob(pattern):
            if p.is_file() and p.suffix.lower() in (".json", ".jsonl", ".md", ".txt"):
                docs.extend(cls.load_file(p))
        return docs
