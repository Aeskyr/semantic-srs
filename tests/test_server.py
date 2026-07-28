import os
import tempfile
import unittest
from datetime import datetime, timezone


TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["SEMANTIC_SRS_DATA_DIR"] = TEST_ROOT.name

import server


class SemanticSRSTest(unittest.TestCase):
    def setUp(self):
        if server.DB_PATH.exists():
            server.DB_PATH.unlink()
        server.initialize()

    def create_active_card(self):
        deck = server.srs_create_deck("Biology")
        source = server.srs_add_source_snapshot(
            deck["deck_id"], "rag://biology/cell", "Mitochondria generate ATP."
        )
        card = server.srs_add_draft_card(
            deck["deck_id"],
            "Explain the main role of mitochondria.",
            "What do mitochondria mainly do?",
            ["generate ATP", "support cellular energy"],
            ["They produce usable cellular energy."],
            ["Mitochondria are merely storage organelles."],
            [source["source_id"]],
        )
        server.srs_set_draft_status([card["card_id"]], "active")
        due = server.srs_get_due_cards(deck["deck_id"])
        return deck, due[0]

    def test_score_boundaries_and_followup(self):
        self.assertEqual(server.hidden_rating(0.44).name, "Again")
        self.assertEqual(server.hidden_rating(0.45).name, "Hard")
        self.assertEqual(server.hidden_rating(0.70).name, "Good")
        self.assertEqual(server.hidden_rating(0.90).name, "Easy")
        self.assertTrue(server.needs_followup(0.69, 0.95))
        self.assertTrue(server.needs_followup(0.80, 0.50))
        self.assertFalse(server.needs_followup(0.80, 0.90))

    def test_draft_approval_and_review(self):
        deck, card = self.create_active_card()
        session = server.srs_start_session(deck["deck_id"])
        result = server.srs_record_review(
            card["card_id"],
            card["version"],
            "How do mitochondria support a cell?",
            "They make ATP, which provides usable energy.",
            0.93,
            0.96,
            ["generate ATP", "support cellular energy"],
            [],
            [],
            "Correct.",
            False,
            12000,
            session["session_id"],
        )
        self.assertEqual(result["hidden_rating"], "easy")
        self.assertGreater(
            datetime.fromisoformat(result["due_at"]), datetime.now(timezone.utc)
        )
        ended = server.srs_end_session(session["session_id"])
        self.assertEqual(ended["reviewed_count"], 1)
        stats = server.srs_deck_stats(deck["deck_id"])
        self.assertEqual(stats["reviews"]["reviews"], 1)
        self.assertEqual(stats["reviews"]["easy"], 1)

    def test_optimistic_lock_and_correction(self):
        _, card = self.create_active_card()
        result = server.srs_record_review(
            card["card_id"], card["version"], "Question", "Answer", 0.40, 0.90
        )
        with self.assertRaisesRegex(ValueError, "Version conflict"):
            server.srs_record_review(
                card["card_id"],
                card["version"],
                "Question",
                "Answer",
                0.80,
                0.90,
            )
        corrected = server.srs_correct_latest_review(
            card["card_id"], 0.80, 0.95, "The answer covered the required meaning."
        )
        self.assertEqual(result["hidden_rating"], "again")
        self.assertEqual(corrected["hidden_rating"], "good")

    def test_source_deduplication_and_export(self):
        deck = server.srs_create_deck("History")
        first = server.srs_add_source_snapshot(
            deck["deck_id"], "file://notes", "Evidence"
        )
        second = server.srs_add_source_snapshot(
            deck["deck_id"], "file://notes", "Evidence"
        )
        self.assertEqual(first["source_id"], second["source_id"])
        self.assertFalse(second["created"])
        exported = server.srs_export_deck(deck["deck_id"])
        self.assertEqual(exported["format"], "semantic-srs-export")
        self.assertEqual(len(exported["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
