from embedding import chunk_text, vector_literal


def test_chunking_preserves_content_and_overlap():
    text = "word " * 400
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert chunks[0].split()[-1] in chunks[1]


def test_vector_literal():
    assert vector_literal([0.1, 2]) == "[0.1,2]"

