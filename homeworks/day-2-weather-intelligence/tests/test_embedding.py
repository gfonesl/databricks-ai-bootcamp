import unittest

from embedding import chunk_text, vector_literal


class EmbeddingTests(unittest.TestCase):
    def test_chunk_text_preserves_text_and_applies_overlap(self):
        text = "one two three four five six seven eight nine ten"
        chunks = chunk_text(text, chunk_size=18, overlap=5)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(chunks[0].split()), "one two three four")
        self.assertTrue(chunks[1].startswith("four"))
        self.assertTrue(all(len(chunk) <= 18 for chunk in chunks))

    def test_chunk_text_rejects_invalid_parameters(self):
        with self.assertRaises(ValueError):
            chunk_text("weather", chunk_size=0)
        with self.assertRaises(ValueError):
            chunk_text("weather", chunk_size=10, overlap=10)

    def test_vector_literal_is_pgvector_compatible(self):
        self.assertEqual(vector_literal([0.5, -0.25]), "[0.5,-0.25]")


if __name__ == "__main__":
    unittest.main()
