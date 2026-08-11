from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from config import CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_MODEL


class EmbeddingError(RuntimeError):
    """Raised when the sentence-transformer model cannot create vectors."""


@lru_cache(maxsize=1)
def get_embedding_model():
    """Load the shared embedding model once for the current Python process."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception as error:  # pragma: no cover - depends on the runtime model cache
        raise EmbeddingError(
            "Unable to load the embedding model. Verify outbound access to Hugging Face "
            "or make the model available in the runtime cache."
        ) from error


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping, mostly word-boundary-preserving chunks."""
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
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def embed_texts(texts: Iterable[str], model=None) -> list[list[float]]:
    """Embed text with normalized 384-dimensional vectors."""
    values = list(texts)
    if not values:
        return []
    active_model = model or get_embedding_model()
    try:
        vectors = active_model.encode(values, normalize_embeddings=True, show_progress_bar=False)
        return [vector.tolist() for vector in vectors]
    except Exception as error:  # pragma: no cover - delegates to the model runtime
        raise EmbeddingError("Unable to create weather embeddings.") from error


def vector_literal(vector: Iterable[float]) -> str:
    """Return pgvector's text representation without relying on a driver adapter."""
    return "[" + ",".join(format(float(value), ".10g") for value in vector) + "]"
