import os
from pathlib import Path
import tempfile
import threading
import unittest


TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["SEMANTIC_SRS_DATA_DIR"] = TEST_ROOT.name
os.environ["SEMANTIC_SRS_DASHBOARD_TOKEN"] = "test-token"
os.environ["SEMANTIC_SRS_DASHBOARD_PORT"] = "8765"

import dashboard
import server
from launch_dashboard import available_port
from starlette.testclient import TestClient


class DashboardServiceTest(unittest.TestCase):
    def setUp(self):
        server.DB_PATH = server.DATA_DIR / "semantic-srs.sqlite3"
        if server.DB_PATH.exists():
            server.DB_PATH.unlink()
        server.initialize()
        server.initialize()  # migrations are idempotent
        self.deck = server.srs_create_deck("Dashboard")
        self.source = server.srs_add_source_snapshot(
            self.deck["deck_id"], "file://dashboard", "Stable evidence"
        )
        self.card = server.srs_add_draft_card(
            self.deck["deck_id"],
            "Explain stable evidence.",
            "What makes the evidence stable?",
            ["stable evidence"],
            ["It remains fixed."],
            ["It changes silently."],
            [self.source["source_id"]],
        )

    def activate(self):
        server.srs_set_draft_status([self.card["card_id"]], "active")
        return server.dashboard_cards(status="active")[0]

    def test_migrations_and_dashboard_statistics(self):
        with server.connection() as db:
            deck_columns = {row[1] for row in db.execute("PRAGMA table_info(decks)")}
            card_columns = {row[1] for row in db.execute("PRAGMA table_info(cards)")}
            audit_columns = {row[1] for row in db.execute("PRAGMA table_info(audit_events)")}
        self.assertTrue({"status", "version"} <= deck_columns)
        self.assertIn("scheduling_epoch", card_columns)
        self.assertIn("actor", audit_columns)
        summary = server.dashboard_overview()
        self.assertEqual(summary["cards"]["draft"], 1)
        self.assertEqual(len(summary["forecast"]), 14)

    def test_draft_suspension_archival_and_conflicts(self):
        active = self.activate()
        suspended = server.set_card_suspension(
            [active["card_id"]], True, {active["card_id"]: active["version"]}
        )
        self.assertEqual(suspended["status"], "suspended")
        with self.assertRaisesRegex(ValueError, "Version conflict"):
            server.set_card_suspension(
                [active["card_id"]], False, {active["card_id"]: active["version"]}
            )
        deck = server.srs_list_decks()[0]
        archived = server.archive_deck(deck["id"], True, deck["version"])
        self.assertEqual(archived["status"], "archived")
        with self.assertRaisesRegex(ValueError, "Version conflict"):
            server.archive_deck(deck["id"], False, deck["version"])

    def test_active_edit_preserves_history_and_resets_schedule(self):
        active = self.activate()
        server.srs_record_review(
            active["card_id"], active["version"], "Question", "Answer", 0.8, 0.95
        )
        current = server.dashboard_cards(status="active")[0]
        result = server.reset_edit_card(
            current["card_id"],
            current["version"],
            "Updated objective",
            "Updated question?",
            ["updated"],
            [],
            [],
            [self.source["source_id"]],
            True,
        )
        self.assertTrue(result["history_preserved"])
        self.assertEqual(result["scheduling_epoch"], 1)
        updated = server.dashboard_cards(status="active")[0]
        self.assertEqual(updated["review_count"], 0)
        self.assertEqual(len(server.dashboard_reviews(updated["card_id"])), 1)

    def test_concurrent_optimistic_write_allows_one_winner(self):
        active = self.activate()
        outcomes = []

        def write():
            try:
                server.set_card_suspension(
                    [active["card_id"]], True, {active["card_id"]: active["version"]}
                )
                outcomes.append("ok")
            except ValueError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=write) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["conflict", "ok"])

    def test_port_selection(self):
        port = available_port()
        self.assertGreaterEqual(port, 8765)

    def test_launcher_flushes_tokenized_url_for_wrappers(self):
        launcher = (
            Path(__file__).parents[1] / "launch_dashboard.py"
        ).read_text(encoding="utf-8")
        self.assertIn('print(f"Semantic SRS dashboard: {url}", flush=True)', launcher)


class DashboardAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dashboard.TOKEN = "test-token"
        dashboard.PORT = 8765
        cls.client = TestClient(dashboard.app, base_url="http://127.0.0.1:8765")
        if not server.srs_list_decks():
            server.srs_create_deck("API export")

    def test_token_host_and_origin_security(self):
        self.assertEqual(self.client.get("/api/overview").status_code, 401)
        good = self.client.get(
            "/api/overview", headers={"Authorization": "Bearer test-token"}
        )
        self.assertEqual(good.status_code, 200)
        bad_origin = self.client.get(
            "/api/overview",
            headers={
                "Authorization": "Bearer test-token",
                "Origin": "https://example.com",
            },
        )
        self.assertEqual(bad_origin.status_code, 403)
        bad_host = self.client.get(
            "/api/overview",
            headers={"Authorization": "Bearer test-token", "Host": "example.com"},
        )
        self.assertEqual(bad_host.status_code, 400)

    def test_offline_assets_and_export(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        decks = self.client.get(
            "/api/decks", headers={"Authorization": "Bearer test-token"}
        ).json()
        response = self.client.get(
            f"/api/export/{decks[0]['id']}",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])

    def test_card_answers_are_minimal_and_preserve_disclosure_state(self):
        script = (Path(__file__).parents[1] / "web" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("<summary>Answer</summary>", script)
        self.assertNotIn("Rubric & sources", script)
        self.assertNotIn("<p>Required:", script)
        self.assertNotIn("<code>${c.source_ids", script)
        self.assertIn('data-card-id="${esc(c.card_id)}"', script)
        self.assertIn("function captureAnswerState()", script)
        self.assertIn("answerState.set(x.dataset.cardId,x.open)", script)
        self.assertIn('const open=answerState.get(c.card_id)?" open":""', script)
        self.assertLess(
            script.index("captureAnswerState();"),
            script.index('document.querySelector("#card-list").innerHTML=decks.map'),
        )

    def test_cards_are_grouped_by_deck_and_preserve_disclosure_state(self):
        script = (Path(__file__).parents[1] / "web" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const cardDeckState=new Map()", script)
        self.assertIn("cards.forEach(c=>{if(grouped.has(c.deck_id))", script)
        self.assertIn('<details class="card-deck" data-deck-id="${esc(d.id)}"', script)
        self.assertIn('<summary>${esc(d.name)}</summary><div class="card-items">', script)
        self.assertIn("captureCardDeckState()", script)
        self.assertIn("cardDeckState.set(x.dataset.deckId,x.open)", script)
        self.assertIn('cardDeckState.get(d.id)?" open":""', script)
        self.assertIn("if(!currentDecks.has(id))cardDeckState.delete(id)", script)
        self.assertIn("No cards match.", script)
        self.assertNotIn('<details class="card-deck" open', script)
        self.assertIn(
            "await loadDecks();await Promise.all([loadOverview(),loadCards()",
            script,
        )

    def test_dynamic_actions_do_not_require_inline_script_csp(self):
        script = (Path(__file__).parents[1] / "web" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(" onclick=", script)
        self.assertIn('data-action="draft"', script)
        self.assertIn('data-action="suspend"', script)
        self.assertIn('data-action="edit"', script)
        self.assertIn('data-action="archive"', script)
        self.assertIn('data-action="export"', script)
        self.assertIn(
            'document.querySelector("#card-list").addEventListener("click"', script
        )
        self.assertIn(
            'document.querySelector("#deck-list").addEventListener("click"', script
        )
        self.assertIn('if(action==="draft")draft(cardId,status)', script)
        self.assertIn('suspended==="true"', script)
        self.assertIn('archived==="true"', script)

    def test_sources_are_grouped_by_deck_and_preserve_disclosure_state(self):
        script = (Path(__file__).parents[1] / "web" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const sourceDeckState=new Map()", script)
        self.assertIn("new Map(decks.map(d=>[d.id,[]]))", script)
        self.assertIn("grouped.get(s.deck_id).push(s)", script)
        self.assertIn('data-deck-id="${esc(d.id)}"', script)
        self.assertIn("<summary>${esc(d.name)}</summary>", script)
        self.assertIn("No source snapshots.", script)
        self.assertIn('sourceDeckState.get(d.id)?" open":""', script)
        self.assertIn("sourceDeckState.set(x.dataset.deckId,x.open)", script)
        self.assertIn("if(!currentDecks.has(id))sourceDeckState.delete(id)", script)
        self.assertNotIn('<details class="source-deck" open', script)
        self.assertIn(
            's.title.replace(/\\s+(?:—|-)\\s+intent\\s*$/i,"")',
            script,
        )
        self.assertIn("${esc(sourceTitle(s))}", script)
        self.assertIn(
            "await loadDecks();await Promise.all([loadOverview(),loadCards(),"
            "loadHistory(),loadSources()])",
            script,
        )

    def test_web_source_uris_are_secure_links_with_plain_text_fallback(self):
        script = (Path(__file__).parents[1] / "web" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const parsed=new URL(value)", script)
        self.assertIn(
            'parsed.protocol==="http:"||parsed.protocol==="https:"', script
        )
        self.assertIn('value.replace(/^https?:\\/\\//i,"")', script)
        self.assertIn('href="${esc(value)}"', script)
        self.assertIn('target="_blank" rel="noopener noreferrer"', script)
        self.assertIn("${esc(label)}</a>", script)
        self.assertIn("catch{}return esc(value)", script)
        self.assertIn("<code>${sourceUriHtml(s.source_uri)}</code>", script)
        self.assertNotIn("<code>${esc(s.source_uri)}</code>", script)

    def test_review_skill_can_discover_and_launch_dashboard(self):
        skill = (
            Path(__file__).parents[1]
            / "skills"
            / "conduct-semantic-review"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("open the local dashboard", skill)
        self.assertIn("Semantic SRS dashboard", skill)
        self.assertIn("## Open the dashboard", skill)
        self.assertIn("SemanticSRS\\apps\\current\\semantic-srs", skill)
        self.assertIn("launch-dashboard.ps1", skill)
        self.assertIn("Start-Process powershell.exe", skill)
        self.assertIn("setup.ps1", skill)

    def test_sources_endpoint_includes_deck_ids_and_archived_decks_remain_listed(self):
        headers = {"Authorization": "Bearer test-token"}
        deck = self.client.get("/api/decks", headers=headers).json()[0]
        if deck["status"] != "archived":
            response = self.client.post(
                "/api/actions/archive",
                headers=headers,
                json={
                    "deck_id": deck["id"],
                    "archived": True,
                    "expected_version": deck["version"],
                },
            )
            self.assertEqual(response.status_code, 200)
        refreshed = self.client.get("/api/decks", headers=headers).json()
        archived_ids = {item["id"] for item in refreshed if item["status"] == "archived"}
        self.assertIn(deck["id"], archived_ids)
        sources = self.client.get("/api/sources", headers=headers).json()
        self.assertTrue(all("deck_id" in source for source in sources))


if __name__ == "__main__":
    unittest.main()
