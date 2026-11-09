"""v4 memory & documents: embeddings, semantic memory, preference learning, knowledge base (RAG)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import tests._stubs  # noqa: F401
from engine.embeddings import Embedder, hash_embed, cosine_similarity, top_k_similar
from engine.semantic_memory import SemanticMemory, extract_preference
from engine.knowledge import KnowledgeBase, chunk_text, keyword_score
from engine.file_ops import FileOperationsManager
from safety.permissions import FileAccessManager


def local_embedder():
    return Embedder({"memory": {"embedding_provider": "local"}})


class TestEmbeddings(unittest.TestCase):
    def test_vectorized_cosine_similarity_and_top_k(self):
        docs = hash_embed(["python programming code", "grocery list items", "python machine learning"])
        q = hash_embed(["write python script"])[0]
        scores = cosine_similarity(q, docs)
        self.assertEqual(len(scores), 3)
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[2], scores[1])

        ranked = top_k_similar(q, docs, k=2)
        self.assertEqual(len(ranked), 2)
        top_indices = [idx for idx, _ in ranked]
        self.assertIn(0, top_indices)
        self.assertIn(2, top_indices)
        self.assertNotIn(1, top_indices)

        empty_scores = cosine_similarity(q, np.zeros((0, 512)))
        self.assertEqual(len(empty_scores), 0)
        self.assertEqual(top_k_similar(q, np.zeros((0, 512))), [])

    def test_hash_embed_is_stable_normalized_and_semantic_ish(self):
        a, b, c = hash_embed(["python code editor", "python code editor", "grocery shopping list"])
        self.assertTrue(np.allclose(a, b))
        self.assertAlmostEqual(float(np.linalg.norm(a)), 1.0, places=5)
        q = hash_embed(["which code editor"])[0]
        self.assertGreater(float(q @ a), float(q @ c))

    def test_auto_prefers_ollama_when_running(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"embeddings": [[0.1, 0.2]]}
        with patch("engine.embeddings.requests.post", return_value=ok):
            emb = Embedder({"memory": {"embedding_provider": "auto"}})
            self.assertEqual(emb.provider, "ollama")
            self.assertEqual(emb.space, "ollama:nomic-embed-text")

    def test_auto_falls_back_to_local_and_never_uses_cloud_implicitly(self):
        with patch("engine.embeddings.requests.post", side_effect=ConnectionError("no ollama")):
            emb = Embedder({"memory": {"embedding_provider": "auto"}})
            self.assertEqual(emb.provider, "local")
            self.assertEqual(emb.embed(["hello"]).shape, (1, 512))

    def test_provider_failure_degrades_gracefully(self):
        emb = Embedder({"memory": {"embedding_provider": "nvidia"}})
        with patch("engine.embeddings.CredentialsManager.get_nvidia_api_key", return_value=""):
            vecs = emb.embed(["a", "b"])
        self.assertEqual(vecs.shape, (2, 512))
        self.assertEqual(emb.provider, "local")

    def test_nvidia_uses_query_and_passage_types(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": [{"embedding": [1.0, 0.0]}]}
        resp.raise_for_status = lambda: None
        emb = Embedder({"memory": {"embedding_provider": "nvidia"}})
        with patch("engine.embeddings.CredentialsManager.get_nvidia_api_key", return_value="k"), \
                patch("engine.embeddings.requests.post", return_value=resp) as post:
            emb.embed(["what is x"], kind="query")
        self.assertEqual(post.call_args.kwargs["json"]["input_type"], "query")


class TestPreferences(unittest.TestCase):
    def test_extract(self):
        good = ["I prefer short answers", "my favourite editor is VS Code", "call me S10", "I'm a final year AI student",
                "I live in Bengaluru", "I use Arch Linux at home"]
        for text in good:
            self.assertIsNotNone(extract_preference(text), text)
        bad = ["what is my name?", "my bank account number is 1234", "my password is hunter2", "open chrome",
               "I'm going out, remind me at 6", "my laptop is slow, check the system", "can you open notepad",
               "I like this song play the next one"]
        for text in bad:
            self.assertIsNone(extract_preference(text), text)


class TestSemanticMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "legacy.json").write_text(json.dumps(["Gate code is 1234", "Mom's birthday is 12 March"]))
        self.mem = SemanticMemory(self.base / "m.db", local_embedder(), legacy_json=self.base / "legacy.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_import_once(self):
        self.assertEqual(self.mem.count(), 2)
        again = SemanticMemory(self.base / "m.db", local_embedder(), legacy_json=self.base / "legacy.json")
        self.assertEqual(again.count(), 2)

    def test_add_dedupe_search_forget(self):
        self.assertTrue(self.mem.add("I use VS Code for all my Python work", "preference"))
        self.assertFalse(self.mem.add("i use vs code for all my python work"))
        self.mem.add("My manager is Ravi Kumar")
        self.assertEqual(self.mem.recall_texts("who is my manager", 1), ["My manager is Ravi Kumar"])
        self.assertIn("VS Code", self.mem.recall_texts("which code editor do I use", 1)[0])
        removed = self.mem.forget("Ravi")
        self.assertEqual(removed, ["My manager is Ravi Kumar"])
        self.assertNotIn("My manager is Ravi Kumar", [t for t, _ in self.mem.list_all()])

    def test_reembeds_when_provider_changes(self):
        self.mem.add("I like dark mode")
        other = Embedder({"memory": {"embedding_provider": "local", "hash_dim": 256}})
        mem2 = SemanticMemory(self.base / "m.db", other, legacy_json=self.base / "none.json")
        self.assertTrue(mem2.recall_texts("dark mode", 1))

    def test_learn_from_utterance(self):
        self.assertEqual(self.mem.learn_from_utterance("I prefer answers in Kannada"), "I prefer answers in Kannada")
        self.assertIsNone(self.mem.learn_from_utterance("my pin is 4321"))


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def chat(self, system, user, max_tokens=None, json_mode=True, image_png=None):
        self.prompts.append(user)
        return "The final submission deadline is 15 December 2026 [1]."


class TestKnowledgeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.notes = self.base / "notes"
        (self.notes / "sub").mkdir(parents=True)
        (self.notes / "sih_plan.md").write_text("# SIH 2026 plan\n\nThe final submission deadline is 15 December 2026.\n\n"
                                                "Team Alpha uploads the demo video and PPT.")
        (self.notes / "sub" / "groceries.txt").write_text("Buy milk, eggs, rice and dal.")
        (self.notes / "image.png").write_bytes(b"\x89PNG")
        self.kb = KnowledgeBase(self.base / "k.db", local_embedder())

    def tearDown(self):
        self.tmp.cleanup()

    def test_chunking(self):
        text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(12))
        chunks = chunk_text(text, size=500, overlap=80)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 500 + 81 for c in chunks))
        self.assertEqual(chunk_text(""), [])
        self.assertAlmostEqual(keyword_score("deadline submission", "the submission deadline is"), 1.0)

    def test_index_search_answer_with_sources(self):
        stats = self.kb.index_folder(self.notes)
        self.assertEqual((stats["indexed"], stats["skipped"]), (2, 0))
        hits = self.kb.search("when is the SIH submission deadline")
        self.assertTrue(hits[0]["path"].endswith("sih_plan.md"))
        llm = FakeLLM()
        answer = self.kb.answer("when is the SIH submission deadline", llm)
        self.assertIn("15 December 2026", answer)
        self.assertIn("Sources: sih_plan.md", answer)
        self.assertIn("[1] (sih_plan.md)", llm.prompts[0])

    def test_incremental_and_removal(self):
        self.kb.index_folder(self.notes)
        again = self.kb.index_folder(self.notes)
        self.assertEqual((again["indexed"], again["unchanged"]), (0, 2))
        (self.notes / "sub" / "groceries.txt").unlink()
        third = self.kb.index_folder(self.notes)
        self.assertEqual(third["removed"], 1)
        self.assertIn("1 documents", self.kb.status())

    def test_respects_file_permissions(self):
        fam = FileAccessManager(store_path=self.base / "p.json", default_roots=[self.base / "elsewhere"], protected_roots=[])
        kb = KnowledgeBase(self.base / "k2.db", local_embedder(), file_ops=FileOperationsManager(access=fam))
        self.assertIn("don't have access", kb.index_folder(self.notes)["error"])
        fam.grant(str(self.notes))
        self.assertEqual(kb.index_folder(self.notes)["indexed"], 2)

    def test_nothing_found_and_forget(self):
        self.assertIn("couldn't find", self.kb.answer("anything", FakeLLM()))
        self.kb.index_folder(self.notes)
        self.assertIn("Removed 2 documents", self.kb.forget_folder(str(self.notes)))
        self.assertIn("No folders", self.kb.status())


if __name__ == "__main__":
    unittest.main()
