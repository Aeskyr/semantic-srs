import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


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
        self.assertEqual(
            set(result),
            {
                "review_id",
                "card_id",
                "mastery_score",
                "hidden_rating",
                "due_at",
                "new_version",
                "followup_was_advisable",
            },
        )
        self.assertGreater(
            datetime.fromisoformat(result["due_at"]), datetime.now(timezone.utc)
        )
        ended = server.srs_end_session(session["session_id"])
        self.assertEqual(ended["reviewed_count"], 1)
        stats = server.srs_deck_stats(deck["deck_id"])
        self.assertEqual(stats["reviews"]["reviews"], 1)
        self.assertEqual(stats["reviews"]["easy"], 1)

    def test_supplemental_multiplier_exposure_streak_and_correctness(self):
        exposures = [
            server.supplemental_multiplier([0.90] * count)
            for count in range(1, 6)
        ]
        for actual, expected in zip(exposures[:4], [0.25, 0.575, 0.975, 1.45]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(exposures[4], 1.60)
        streaks = [
            server.supplemental_multiplier(scores)
            for scores in (
                [0.9333333333333333, 0.9333333333333333, 0.9333333333333333, 0.80],
                [0.90, 0.90, 0.80, 1.00],
                [0.90, 0.70, 1.00, 1.00],
                [0.60, 1.00, 1.00, 1.00],
                [0.90, 0.90, 0.90, 0.90],
            )
        ]
        self.assertEqual(streaks, [0.8, 1.0, 1.15, 1.30, 1.45])
        self.assertEqual(
            server.supplemental_multiplier([0.90] * 5),
            server.supplemental_multiplier([0.90] * 8),
        )
        self.assertEqual(server.supplemental_multiplier([0.90, 0.89]), 0.3977777777777778)
        self.assertLess(
            server.supplemental_multiplier([0.50] * 4),
            server.supplemental_multiplier([0.99] * 4),
        )
        self.assertEqual(server.supplemental_multiplier([1.0] * 4), 1.595)

    def test_supplemental_interval_preserves_subday_and_fsrs_memory(self):
        reviewed_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
        card = server.FSRSCard()
        card.due = reviewed_at + timedelta(hours=12)
        before = card.to_json()
        server.apply_supplemental_interval(card, reviewed_at, [0.96])
        self.assertEqual(card.to_json(), before)
        card.due = reviewed_at + timedelta(days=8)
        card.stability = 12.5
        card.difficulty = 4.2
        server.apply_supplemental_interval(card, reviewed_at, [0.96])
        self.assertAlmostEqual((card.due - reviewed_at).total_seconds() / 86400, 2.1333, places=3)
        self.assertEqual((card.stability, card.difficulty), (12.5, 4.2))

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
        self.assertEqual(
            set(corrected),
            {"review_id", "card_id", "hidden_rating", "due_at", "new_version"},
        )
        with server.connection() as db:
            event = db.execute(
                "SELECT * FROM review_events WHERE id=?", (corrected["review_id"],)
            ).fetchone()
            card_row = db.execute(
                "SELECT * FROM cards WHERE id=?", (card["card_id"],)
            ).fetchone()
        self.assertEqual(event["fsrs_after_json"], card_row["fsrs_json"])

    def test_current_epoch_reset_and_deterministic_rescheduling(self):
        _, card = self.create_active_card()
        first = server.srs_record_review(
            card["card_id"], card["version"], "Old", "Answer", 0.95, 0.95
        )
        current = server.dashboard_cards(status="active")[0]
        server.reset_edit_card(
            current["card_id"],
            current["version"],
            "New objective",
            "New question?",
            ["new"],
            [],
            [],
            current["source_ids"],
            True,
        )
        reset_card = server.dashboard_cards(status="active")[0]
        second = server.srs_record_review(
            reset_card["card_id"], reset_card["version"], "New", "Answer", 0.95, 0.95
        )
        with server.connection(write=True) as db:
            row = db.execute(
                "SELECT * FROM cards WHERE id=?", (card["card_id"],)
            ).fetchone()
            review = db.execute(
                """SELECT * FROM review_events
                   WHERE card_id=? AND scheduling_epoch=1""",
                (card["card_id"],),
            ).fetchone()
            baseline, _ = server.scheduler().review_card(
                server.FSRSCard.from_json(row["initial_fsrs_json"]),
                server.Rating(review["hidden_rating"]),
                review_datetime=server.parse_time(review["reviewed_at"]),
                review_duration=review["duration_ms"],
            )
            db.execute(
                "UPDATE review_events SET fsrs_before_json=?,fsrs_after_json=? WHERE id=?",
                (row["initial_fsrs_json"], baseline.to_json(), review["id"]),
            )
            db.execute(
                "UPDATE cards SET fsrs_json=?,due_at=? WHERE id=?",
                (baseline.to_json(), baseline.due.isoformat(), card["card_id"]),
            )
        dry_run = server.reschedule_supplemental_policy()
        changed = next(x for x in dry_run["cards"] if x["card_id"] == card["card_id"])
        self.assertTrue(changed["changed"])
        self.assertNotEqual(changed["new_due_at"], baseline.due.isoformat())
        applied = server.reschedule_supplemental_policy(apply=True)
        self.assertGreaterEqual(applied["changed_cards"], 1)
        rerun = server.reschedule_supplemental_policy(apply=True)
        self.assertEqual(rerun["changed_cards"], 0)
        with server.connection() as db:
            audits = db.execute(
                """SELECT details_json FROM audit_events
                   WHERE event_type='supplemental_policy_rescheduled'
                     AND entity_id=?""",
                (card["card_id"],),
            ).fetchall()
            epochs = db.execute(
                "SELECT scheduling_epoch FROM review_events WHERE card_id=? ORDER BY reviewed_at,id",
                (card["card_id"],),
            ).fetchall()
        self.assertEqual(len(audits), 1)
        self.assertEqual([row[0] for row in epochs], [0, 1])
        self.assertEqual(server.loads(audits[0][0], {})["policy_version"], "supplemental-v1")
        self.assertNotEqual(first["review_id"], second["review_id"])

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
