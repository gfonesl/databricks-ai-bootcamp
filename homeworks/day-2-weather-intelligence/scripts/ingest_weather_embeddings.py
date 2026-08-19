"""Manually generate Lakebase pgvector embeddings after a weather sync."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from embedding import chunk_text, embed_texts  # noqa: E402
from lakebase import WeatherRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Embed new or changed weather documents in Lakebase."
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Maximum documents to embed (default: 100)."
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    repository = WeatherRepository()
    # The Databricks App owns and initializes the schema during its first startup.
    documents = repository.documents_needing_embeddings(args.limit)
    embedded_documents = 0
    embedded_chunks = 0

    for document in documents:
        text = f"{document['headline']}\n\n{document['narrative_text']}"
        chunks = chunk_text(text)
        vectors = embed_texts(chunks)
        embedded_chunks += repository.replace_embeddings(
            document["id"], document["content_hash"], zip(chunks, vectors)
        )
        embedded_documents += 1

    print(
        json.dumps(
            {
                "documents_considered": len(documents),
                "documents_embedded": embedded_documents,
                "chunks_embedded": embedded_chunks,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
