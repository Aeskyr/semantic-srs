from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


TEST_HOME = tempfile.TemporaryDirectory()
os.environ["LOCAL_RAG_DATA_DIR"] = os.path.join(TEST_HOME.name, "qdrant")
os.environ["LOCAL_RAG_MODEL_DIR"] = os.path.join(TEST_HOME.name, "models")

import server


class LocalRagTest(unittest.TestCase):
    def setUp(self):
        server._client = None
        server._embedder = None

    def test_chunks_overlap_and_cover_text(self):
        values = list(server.chunks("one two three four five", size=10, overlap=2))
        self.assertGreater(len(values), 1)
        self.assertEqual(values[0], "one two")
        self.assertIn("five", values[-1])

    def test_stable_id_is_repeatable(self):
        self.assertEqual(server.stable_id("source", 1, "text"), server.stable_id("source", 1, "text"))
        self.assertNotEqual(server.stable_id("source", 1, "text"), server.stable_id("source", 2, "text"))

    def test_index_document_uses_mocked_embedding_and_database(self):
        embedding = MagicMock()
        embedding.tolist.return_value = [0.0] * server.VECTOR_SIZE
        fake_embedder = MagicMock()
        fake_embedder.embed.return_value = [embedding]
        fake_client = MagicMock()
        with patch.object(server, "embedder", return_value=fake_embedder), patch.object(server, "client", return_value=fake_client):
            count = server.index_document("memory://test", "short content")
        self.assertEqual(count, 1)
        fake_client.upsert.assert_called_once()

    def test_search_uses_mocked_query_embedding(self):
        embedding = MagicMock()
        embedding.tolist.return_value = [0.0] * server.VECTOR_SIZE
        fake_embedder = MagicMock()
        fake_embedder.query_embed.return_value = iter([embedding])
        point = MagicMock(score=0.91, payload={"source": "x", "chunk": 0, "text": "result"})
        fake_client = MagicMock()
        fake_client.query_points.return_value = MagicMock(points=[point])
        with patch.object(server, "embedder", return_value=fake_embedder), patch.object(server, "client", return_value=fake_client):
            result = server.rag_search("query", 1)
        self.assertEqual(result[0]["source"], "x")
        self.assertEqual(result[0]["score"], 0.91)


if __name__ == "__main__":
    unittest.main()
