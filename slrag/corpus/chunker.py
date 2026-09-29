"""Deterministic section-preserving document chunker."""

import re
from typing import List
from slrag.config import ChunkerConfig, DEFAULT_CONFIG
from slrag.corpus.models import Chunk, Document, Section


def count_tokens(text: str) -> int:
    """Approximate token count using word boundaries and punctuation splits."""
    # A standard heuristic: words + punctuation splits closely matches subword tokenizers
    tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
    return len(tokens)


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences while preserving sentence boundaries."""
    # Split on periods, newlines, exclamation, questions followed by space or newline
    raw_sentences = re.split(r"(?<=[.!?\n])\s+", text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    return sentences if sentences else [text.strip()]


class SectionAwareChunker:
    """Chunks documents while preserving logical section boundaries.
    
    Produces chunks strictly in the range [min_tokens, max_tokens] where possible,
    and assigns deterministic, reproducible IDs:
      - Single chunk in section: Doc_ID§Section
      - Multiple chunks in section: Doc_ID§Section_0, Doc_ID§Section_1, ...
    """

    def __init__(self, config: ChunkerConfig = DEFAULT_CONFIG.chunker):
        self.config = config

    def chunk_section(self, doc_id: str, section: Section) -> List[Chunk]:
        sec_text = section.text.strip()
        if not sec_text:
            return []

        total_tokens = count_tokens(sec_text)

        # If the entire section fits within max_tokens, emit exactly one chunk
        if total_tokens <= self.config.max_tokens:
            chunk_id = f"{doc_id}§{section.section_id}"
            return [
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    section_id=section.section_id,
                    section_title=section.title,
                    text=sec_text,
                    token_count=total_tokens,
                    char_start=0,
                    char_end=len(sec_text),
                    chunk_index=0,
                    metadata={"section_title": section.title},
                )
            ]

        # Otherwise, split across sentences/paragraphs with overlap
        sentences = split_into_sentences(sec_text)
        chunks: List[Chunk] = []

        current_sentences: List[str] = []
        current_token_count = 0
        char_cursor = 0
        chunk_idx = 0

        i = 0
        while i < len(sentences):
            sent = sentences[i]
            sent_tokens = count_tokens(sent)

            # If a single sentence exceeds max_tokens, split it by words
            if sent_tokens > self.config.max_tokens:
                words = sent.split()
                w_chunk = []
                w_tokens = 0
                for w in words:
                    w_chunk.append(w)
                    w_tokens += 1
                    if w_tokens >= self.config.max_tokens:
                        c_text = " ".join(w_chunk)
                        c_id = f"{doc_id}§{section.section_id}_{chunk_idx}"
                        start_pos = sec_text.find(c_text, char_cursor)
                        if start_pos == -1:
                            start_pos = char_cursor
                        end_pos = start_pos + len(c_text)
                        chunks.append(
                            Chunk(
                                chunk_id=c_id,
                                doc_id=doc_id,
                                section_id=section.section_id,
                                section_title=section.title,
                                text=c_text,
                                token_count=w_tokens,
                                char_start=start_pos,
                                char_end=end_pos,
                                chunk_index=chunk_idx,
                                metadata={"section_title": section.title},
                            )
                        )
                        chunk_idx += 1
                        char_cursor = end_pos
                        w_chunk = []
                        w_tokens = 0
                if w_chunk:
                    sent = " ".join(w_chunk)
                    sent_tokens = count_tokens(sent)
                else:
                    i += 1
                    continue

            if current_token_count + sent_tokens > self.config.max_tokens and current_sentences:
                # Flush current chunk
                chunk_text = " ".join(current_sentences)
                c_id = f"{doc_id}§{section.section_id}_{chunk_idx}"
                start_pos = sec_text.find(current_sentences[0], char_cursor)
                if start_pos == -1:
                    start_pos = char_cursor
                end_pos = start_pos + len(chunk_text)
                chunks.append(
                    Chunk(
                        chunk_id=c_id,
                        doc_id=doc_id,
                        section_id=section.section_id,
                        section_title=section.title,
                        text=chunk_text,
                        token_count=current_token_count,
                        char_start=start_pos,
                        char_end=end_pos,
                        chunk_index=chunk_idx,
                        metadata={"section_title": section.title},
                    )
                )
                chunk_idx += 1
                char_cursor = start_pos

                # Implement overlap: carry forward sentences matching overlap_tokens
                overlap_sentences: List[str] = []
                overlap_tokens = 0
                for prev_sent in reversed(current_sentences):
                    t = count_tokens(prev_sent)
                    if overlap_tokens + t <= self.config.overlap_tokens:
                        overlap_sentences.insert(0, prev_sent)
                        overlap_tokens += t
                    else:
                        break

                current_sentences = overlap_sentences
                current_token_count = overlap_tokens

            current_sentences.append(sent)
            current_token_count += sent_tokens
            i += 1

        if current_sentences:
            chunk_text = " ".join(current_sentences)
            c_id = f"{doc_id}§{section.section_id}_{chunk_idx}" if chunk_idx > 0 else f"{doc_id}§{section.section_id}"
            start_pos = sec_text.find(current_sentences[0], char_cursor)
            if start_pos == -1:
                start_pos = char_cursor
            end_pos = start_pos + len(chunk_text)
            chunks.append(
                Chunk(
                    chunk_id=c_id,
                    doc_id=doc_id,
                    section_id=section.section_id,
                    section_title=section.title,
                    text=chunk_text,
                    token_count=current_token_count,
                    char_start=start_pos,
                    char_end=end_pos,
                    chunk_index=chunk_idx,
                    metadata={"section_title": section.title},
                )
            )

        return chunks

    def chunk_document(self, doc: Document) -> List[Chunk]:
        """Chunk all sections in a document."""
        chunks: List[Chunk] = []
        for sec in doc.sections:
            chunks.extend(self.chunk_section(doc.doc_id, sec))
        return chunks

    def chunk_documents(self, docs: List[Document]) -> List[Chunk]:
        """Chunk a list of documents."""
        all_chunks: List[Chunk] = []
        for doc in docs:
            all_chunks.extend(self.chunk_document(doc))
        return all_chunks
