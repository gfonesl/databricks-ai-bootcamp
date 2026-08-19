from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
)


class EmbeddingError(RuntimeError):
    """The local embedding model is unavailable."""


@lru_cache(maxsize=1)
def get_embedding_model():
    """Load the shared encoder once per App or job process."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(EMBEDDING_MODEL, revision=EMBEDDING_MODEL_REVISION)
    except Exception as error:  # pragma: no cover - depends on runtime image/network
        raise EmbeddingError("Unable to load the Tripwise embedding model.") from error


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size")
    if len(normalized) <= chunk_size:
        return [normalized]
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized) and not normalized[end].isspace():
            boundary = normalized.rfind(" ", start + 1, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def embed_texts(texts: Iterable[str], model=None) -> list[list[float]]:
    values = list(texts)
    if not values:
        return []
    try:
        vectors = (model or get_embedding_model()).encode(
            values, normalize_embeddings=True, show_progress_bar=False
        )
        result = [vector.tolist() for vector in vectors]
        if any(len(vector) != EMBEDDING_DIMENSIONS for vector in result):
            raise EmbeddingError("Embedding model returned an unexpected vector dimension.")
        return result
    except EmbeddingError:
        raise
    except Exception as error:  # pragma: no cover - delegates to model implementation
        raise EmbeddingError("Unable to create Tripwise embeddings.") from error


def vector_literal(vector: Iterable[float]) -> str:
    return "[" + ",".join(format(float(value), ".10g") for value in vector) + "]"
