"""Shared Semantic SRS service facade used by MCP and the local dashboard.

The existing MCP module remains import-compatible. New consumers should import this
module so persistence and scheduling behavior stay centralized.
"""

from server import (  # noqa: F401
    DB_PATH,
    SCORE_THRESHOLDS,
    archive_deck,
    dashboard_cards,
    dashboard_overview,
    dashboard_reviews,
    dashboard_sessions,
    dashboard_sources,
    initialize,
    reset_edit_card,
    set_card_suspension,
    srs_deck_stats,
    srs_export_deck,
    srs_list_decks,
    srs_set_draft_status,
    srs_update_draft_card,
)

