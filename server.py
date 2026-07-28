from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field


DATA_DIR = Path(
    os.environ.get("SEMANTIC_SRS_DATA_DIR", Path(__file__).resolve().parent / "data")
).expanduser()
DB_PATH = DATA_DIR / "semantic-srs.sqlite3"
DESIRED_RETENTION = 0.9
SCORE_THRESHOLDS = (0.45, 0.70, 0.90)

mcp = FastMCP(
    "semantic-srs",
    instructions=(
        "Use these tools as the exact source of truth for decks, cards, review history, "
        "and due dates. Never invent or manually calculate a due date. Keep answer rubrics "
        "private until the learner answers. Grade meaning and concept coverage, not wording."
    ),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def scheduler() -> Scheduler:
    return Scheduler(desired_retention=DESIRED_RETENTION, enable_fuzzing=False)


def hidden_rating(score: float) -> Rating:
    if not 0.0 <= score <= 1.0:
        raise ValueError("mastery_score must be between 0.0 and 1.0")
    if score < SCORE_THRESHOLDS[0]:
        return Rating.Again
    if score < SCORE_THRESHOLDS[1]:
        return Rating.Hard
    if score < SCORE_THRESHOLDS[2]:
        return Rating.Good
    return Rating.Easy


def needs_followup(score: float, confidence: float) -> bool:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")
    return confidence < 0.70 or any(
        abs(score - boundary) <= 0.05 for boundary in SCORE_THRESHOLDS
    )


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def initialize() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    try:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS decks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_snapshots (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                source_uri TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                excerpt TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(deck_id, source_uri, content_hash)
            );

            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK(status IN ('draft','active','rejected','suspended')),
                learning_objective TEXT NOT NULL,
                suggested_question TEXT NOT NULL,
                required_concepts_json TEXT NOT NULL,
                acceptable_answers_json TEXT NOT NULL,
                misconceptions_json TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                initial_fsrs_json TEXT NOT NULL,
                fsrs_json TEXT NOT NULL,
                due_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                lapse_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS cards_due_idx
                ON cards(status, due_at, deck_id);

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                reviewed_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS review_events (
                id TEXT PRIMARY KEY,
                card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                reviewed_at TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                mastery_score REAL NOT NULL,
                confidence REAL NOT NULL,
                hidden_rating INTEGER NOT NULL,
                covered_json TEXT NOT NULL,
                missing_json TEXT NOT NULL,
                contradictions_json TEXT NOT NULL,
                feedback TEXT NOT NULL,
                followup_used INTEGER NOT NULL,
                duration_ms INTEGER,
                fsrs_before_json TEXT NOT NULL,
                fsrs_after_json TEXT NOT NULL,
                corrected_at TEXT,
                correction_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS reviews_card_time_idx
                ON review_events(card_id, reviewed_at);

            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Non-destructive, idempotent migrations for dashboard-managed state.
        columns = {
            table: {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for table in ("decks", "cards", "audit_events")
        }
        migrations = (
            ("decks", "status", "TEXT NOT NULL DEFAULT 'active'"),
            ("decks", "version", "INTEGER NOT NULL DEFAULT 0"),
            ("cards", "scheduling_epoch", "INTEGER NOT NULL DEFAULT 0"),
            ("audit_events", "actor", "TEXT NOT NULL DEFAULT 'system'"),
        )
        for table, column, declaration in migrations:
            if column not in columns[table]:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        db.commit()
    finally:
        db.close()


@contextmanager
def connection(*, write: bool = False):
    initialize()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if write:
        db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        if write:
            db.commit()
    except Exception:
        if write:
            db.rollback()
        raise
    finally:
        db.close()


def require_row(
    db: sqlite3.Connection, query: str, params: tuple[Any, ...], label: str
) -> sqlite3.Row:
    row = db.execute(query, params).fetchone()
    if row is None:
        raise ValueError(f"{label} not found")
    return row


def public_card(row: sqlite3.Row, *, include_rubric: bool = True) -> dict[str, Any]:
    result = {
        "card_id": row["id"],
        "deck_id": row["deck_id"],
        "status": row["status"],
        "learning_objective": row["learning_objective"],
        "suggested_question": row["suggested_question"],
        "source_ids": loads(row["source_ids_json"], []),
        "due_at": row["due_at"],
        "version": row["version"],
        "review_count": row["review_count"],
        "lapse_count": row["lapse_count"],
        "scheduling_epoch": row["scheduling_epoch"],
    }
    if include_rubric:
        result.update(
            {
                "required_concepts": loads(row["required_concepts_json"], []),
                "acceptable_answers": loads(row["acceptable_answers_json"], []),
                "misconceptions": loads(row["misconceptions_json"], []),
            }
        )
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_status() -> dict[str, Any]:
    """Return database readiness, locations, scheduler settings, and object counts."""
    with connection() as db:
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("decks", "source_snapshots", "cards", "review_events")
        }
    return {
        "ready": True,
        "database": str(DB_PATH),
        "scheduler": "FSRS 6",
        "desired_retention": DESIRED_RETENTION,
        "score_thresholds": {
            "again": [0.0, 0.45],
            "hard": [0.45, 0.70],
            "good": [0.70, 0.90],
            "easy": [0.90, 1.0],
        },
        "counts": counts,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def srs_create_deck(
    name: Annotated[str, Field(min_length=1, max_length=200)],
    description: Annotated[str, Field(max_length=2000)] = "",
) -> dict[str, Any]:
    """Create a deck that owns source snapshots, cards, sessions, and review history."""
    deck_id = new_id("deck")
    now = iso()
    try:
        with connection(write=True) as db:
            db.execute(
                "INSERT INTO decks(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
                (deck_id, name.strip(), description.strip(), now, now),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"A deck named {name!r} already exists") from exc
    return {"deck_id": deck_id, "name": name.strip(), "description": description.strip()}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_list_decks() -> list[dict[str, Any]]:
    """List decks with active, draft, and currently due card counts."""
    with connection() as db:
        rows = db.execute(
            """
            SELECT d.id, d.name, d.description, d.status, d.version,
                   SUM(CASE WHEN c.status='active' THEN 1 ELSE 0 END) active_cards,
                   SUM(CASE WHEN c.status='draft' THEN 1 ELSE 0 END) draft_cards,
                   SUM(CASE WHEN c.status='active' AND c.due_at<=? THEN 1 ELSE 0 END) due_cards
            FROM decks d LEFT JOIN cards c ON c.deck_id=d.id
            GROUP BY d.id ORDER BY d.name COLLATE NOCASE
            """,
            (iso(),),
        ).fetchall()
    return [dict(row) for row in rows]


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def srs_add_source_snapshot(
    deck_id: str,
    source_uri: Annotated[str, Field(min_length=1, max_length=2000)],
    excerpt: Annotated[str, Field(min_length=1, max_length=50000)],
    title: Annotated[str, Field(max_length=500)] = "",
) -> dict[str, Any]:
    """Store stable source evidence from pasted text, a file, or Local RAG."""
    digest = source_hash(excerpt)
    with connection(write=True) as db:
        require_row(db, "SELECT id FROM decks WHERE id=?", (deck_id,), "Deck")
        existing = db.execute(
            "SELECT id FROM source_snapshots WHERE deck_id=? AND source_uri=? AND content_hash=?",
            (deck_id, source_uri, digest),
        ).fetchone()
        if existing:
            return {
                "source_id": existing["id"],
                "content_hash": digest,
                "created": False,
            }
        source_id = new_id("src")
        db.execute(
            """
            INSERT INTO source_snapshots(id,deck_id,source_uri,title,excerpt,content_hash,created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (source_id, deck_id, source_uri, title.strip(), excerpt, digest, iso()),
        )
    return {"source_id": source_id, "content_hash": digest, "created": True}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def srs_add_draft_card(
    deck_id: str,
    learning_objective: Annotated[str, Field(min_length=1, max_length=2000)],
    suggested_question: Annotated[str, Field(min_length=1, max_length=2000)],
    required_concepts: Annotated[list[str], Field(min_length=1, max_length=20)],
    acceptable_answers: Annotated[list[str], Field(max_length=20)] = [],
    misconceptions: Annotated[list[str], Field(max_length=20)] = [],
    source_ids: Annotated[list[str], Field(max_length=50)] = [],
) -> dict[str, Any]:
    """Add one generated or manually-authored card to the approval queue."""
    card_id = new_id("card")
    fsrs_card = FSRSCard()
    fsrs_json = fsrs_card.to_json()
    now = iso()
    with connection(write=True) as db:
        require_row(db, "SELECT id FROM decks WHERE id=?", (deck_id,), "Deck")
        if source_ids:
            placeholders = ",".join("?" * len(source_ids))
            found = db.execute(
                f"SELECT id FROM source_snapshots WHERE deck_id=? AND id IN ({placeholders})",
                (deck_id, *source_ids),
            ).fetchall()
            if len(found) != len(set(source_ids)):
                raise ValueError("One or more source_ids do not belong to this deck")
        db.execute(
            """
            INSERT INTO cards(
                id,deck_id,status,learning_objective,suggested_question,
                required_concepts_json,acceptable_answers_json,misconceptions_json,
                source_ids_json,initial_fsrs_json,fsrs_json,due_at,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                card_id,
                deck_id,
                "draft",
                learning_objective.strip(),
                suggested_question.strip(),
                dumps(required_concepts),
                dumps(acceptable_answers),
                dumps(misconceptions),
                dumps(source_ids),
                fsrs_json,
                fsrs_json,
                fsrs_card.due.isoformat(),
                now,
                now,
            ),
        )
    return {"card_id": card_id, "status": "draft"}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_list_drafts(deck_id: str) -> list[dict[str, Any]]:
    """List complete draft rubrics so the learner can approve, edit, or reject them."""
    with connection() as db:
        require_row(db, "SELECT id FROM decks WHERE id=?", (deck_id,), "Deck")
        rows = db.execute(
            "SELECT * FROM cards WHERE deck_id=? AND status='draft' ORDER BY created_at",
            (deck_id,),
        ).fetchall()
    return [public_card(row) for row in rows]


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def srs_update_draft_card(
    card_id: str,
    learning_objective: Annotated[str, Field(min_length=1, max_length=2000)],
    suggested_question: Annotated[str, Field(min_length=1, max_length=2000)],
    required_concepts: Annotated[list[str], Field(min_length=1, max_length=20)],
    acceptable_answers: Annotated[list[str], Field(max_length=20)] = [],
    misconceptions: Annotated[list[str], Field(max_length=20)] = [],
    source_ids: Annotated[list[str], Field(max_length=50)] = [],
) -> dict[str, Any]:
    """Replace the content and rubric of a card while it remains a draft."""
    with connection(write=True) as db:
        row = require_row(db, "SELECT * FROM cards WHERE id=?", (card_id,), "Card")
        if row["status"] != "draft":
            raise ValueError("Only draft cards can be edited")
        if source_ids:
            placeholders = ",".join("?" * len(source_ids))
            found = db.execute(
                f"SELECT id FROM source_snapshots WHERE deck_id=? AND id IN ({placeholders})",
                (row["deck_id"], *source_ids),
            ).fetchall()
            if len(found) != len(set(source_ids)):
                raise ValueError("One or more source_ids do not belong to this deck")
        db.execute(
            """
            UPDATE cards SET learning_objective=?,suggested_question=?,
                required_concepts_json=?,acceptable_answers_json=?,misconceptions_json=?,
                source_ids_json=?,version=version+1,updated_at=? WHERE id=?
            """,
            (
                learning_objective.strip(),
                suggested_question.strip(),
                dumps(required_concepts),
                dumps(acceptable_answers),
                dumps(misconceptions),
                dumps(source_ids),
                iso(),
                card_id,
            ),
        )
    return {"card_id": card_id, "status": "draft", "updated": True}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def srs_set_draft_status(
    card_ids: Annotated[list[str], Field(min_length=1, max_length=200)],
    status: Literal["active", "rejected"],
) -> dict[str, Any]:
    """Approve draft cards into the live queue or reject them."""
    now = iso()
    with connection(write=True) as db:
        placeholders = ",".join("?" * len(card_ids))
        rows = db.execute(
            f"SELECT id,status FROM cards WHERE id IN ({placeholders})", tuple(card_ids)
        ).fetchall()
        if len(rows) != len(set(card_ids)):
            raise ValueError("One or more card_ids were not found")
        if any(row["status"] != "draft" for row in rows):
            raise ValueError("Every selected card must still be a draft")
        db.execute(
            f"UPDATE cards SET status=?,due_at=?,version=version+1,updated_at=? "
            f"WHERE id IN ({placeholders})",
            (status, now, now, *card_ids),
        )
    return {"status": status, "updated_count": len(card_ids)}


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def srs_start_session(deck_id: str) -> dict[str, Any]:
    """Start a review session for one deck."""
    session_id = new_id("session")
    with connection(write=True) as db:
        require_row(db, "SELECT id FROM decks WHERE id=?", (deck_id,), "Deck")
        db.execute(
            "INSERT INTO sessions(id,deck_id,started_at) VALUES(?,?,?)",
            (session_id, deck_id, iso()),
        )
    return {"session_id": session_id, "deck_id": deck_id}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_get_due_cards(
    deck_id: str, limit: Annotated[int, Field(ge=1, le=20)] = 1
) -> list[dict[str, Any]]:
    """Get due cards and private rubrics. Do not reveal rubric fields before the learner answers."""
    with connection() as db:
        require_row(db, "SELECT id FROM decks WHERE id=?", (deck_id,), "Deck")
        rows = db.execute(
            """
            SELECT * FROM cards
            WHERE deck_id=? AND status='active' AND due_at<=?
            ORDER BY due_at,created_at LIMIT ?
            """,
            (deck_id, iso(), limit),
        ).fetchall()
        results = []
        for row in rows:
            item = public_card(row)
            history = db.execute(
                "SELECT question FROM review_events WHERE card_id=? "
                "ORDER BY reviewed_at DESC LIMIT 5",
                (row["id"],),
            ).fetchall()
            item["recent_questions"] = [entry["question"] for entry in history]
            results.append(item)
    return results


def _apply_review(
    db: sqlite3.Connection,
    *,
    card_row: sqlite3.Row,
    question: str,
    answer: str,
    mastery_score: float,
    confidence: float,
    covered: list[str],
    missing: list[str],
    contradictions: list[str],
    feedback: str,
    followup_used: bool,
    duration_ms: int | None,
    session_id: str | None,
    reviewed_at: datetime,
) -> dict[str, Any]:
    rating = hidden_rating(mastery_score)
    before_json = card_row["fsrs_json"]
    current = FSRSCard.from_json(before_json)
    updated, _ = scheduler().review_card(
        current,
        rating,
        review_datetime=reviewed_at,
        review_duration=duration_ms,
    )
    event_id = new_id("review")
    after_json = updated.to_json()
    lapse_increment = (
        1 if rating == Rating.Again and card_row["review_count"] > 0 else 0
    )
    db.execute(
        """
        INSERT INTO review_events(
            id,card_id,session_id,reviewed_at,question,answer,mastery_score,confidence,
            hidden_rating,covered_json,missing_json,contradictions_json,feedback,
            followup_used,duration_ms,fsrs_before_json,fsrs_after_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            card_row["id"],
            session_id,
            reviewed_at.isoformat(),
            question,
            answer,
            mastery_score,
            confidence,
            int(rating),
            dumps(covered),
            dumps(missing),
            dumps(contradictions),
            feedback,
            int(followup_used),
            duration_ms,
            before_json,
            after_json,
        ),
    )
    db.execute(
        """
        UPDATE cards SET fsrs_json=?,due_at=?,version=version+1,
            review_count=review_count+1,lapse_count=lapse_count+?,updated_at=? WHERE id=?
        """,
        (
            after_json,
            updated.due.isoformat(),
            lapse_increment,
            iso(),
            card_row["id"],
        ),
    )
    if session_id:
        changed = db.execute(
            "UPDATE sessions SET reviewed_count=reviewed_count+1 "
            "WHERE id=? AND ended_at IS NULL",
            (session_id,),
        ).rowcount
        if not changed:
            raise ValueError("Session not found or already ended")
    return {
        "review_id": event_id,
        "card_id": card_row["id"],
        "mastery_score": mastery_score,
        "hidden_rating": rating.name.lower(),
        "due_at": updated.due.isoformat(),
        "new_version": card_row["version"] + 1,
        "followup_was_advisable": needs_followup(mastery_score, confidence),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def srs_record_review(
    card_id: str,
    expected_version: Annotated[int, Field(ge=0)],
    question: Annotated[str, Field(min_length=1, max_length=4000)],
    answer: Annotated[str, Field(min_length=1, max_length=20000)],
    mastery_score: Annotated[float, Field(ge=0.0, le=1.0)],
    confidence: Annotated[float, Field(ge=0.0, le=1.0)],
    covered_concepts: Annotated[list[str], Field(max_length=30)] = [],
    missing_concepts: Annotated[list[str], Field(max_length=30)] = [],
    contradictions: Annotated[list[str], Field(max_length=30)] = [],
    feedback: Annotated[str, Field(max_length=4000)] = "",
    followup_used: bool = False,
    duration_ms: Annotated[int | None, Field(ge=0, le=86400000)] = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Atomically record an evaluated answer and let FSRS calculate the next due date."""
    with connection(write=True) as db:
        row = require_row(db, "SELECT * FROM cards WHERE id=?", (card_id,), "Card")
        if row["status"] != "active":
            raise ValueError("Only active cards can be reviewed")
        if row["version"] != expected_version:
            raise ValueError(
                f"Version conflict: expected {expected_version}, current version is {row['version']}"
            )
        return _apply_review(
            db,
            card_row=row,
            question=question,
            answer=answer,
            mastery_score=mastery_score,
            confidence=confidence,
            covered=covered_concepts,
            missing=missing_concepts,
            contradictions=contradictions,
            feedback=feedback,
            followup_used=followup_used,
            duration_ms=duration_ms,
            session_id=session_id,
            reviewed_at=utc_now(),
        )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )
)
def srs_correct_latest_review(
    card_id: str,
    mastery_score: Annotated[float, Field(ge=0.0, le=1.0)],
    confidence: Annotated[float, Field(ge=0.0, le=1.0)],
    reason: Annotated[str, Field(min_length=1, max_length=2000)],
) -> dict[str, Any]:
    """Correct the latest semantic grade for a card and recompute its FSRS state."""
    with connection(write=True) as db:
        card = require_row(db, "SELECT * FROM cards WHERE id=?", (card_id,), "Card")
        review = require_row(
            db,
            "SELECT * FROM review_events WHERE card_id=? "
            "ORDER BY reviewed_at DESC,id DESC LIMIT 1",
            (card_id,),
            "Review",
        )
        old = {
            "mastery_score": review["mastery_score"],
            "confidence": review["confidence"],
            "hidden_rating": review["hidden_rating"],
            "fsrs_after_json": review["fsrs_after_json"],
        }
        rating = hidden_rating(mastery_score)
        before = FSRSCard.from_json(review["fsrs_before_json"])
        updated, _ = scheduler().review_card(
            before,
            rating,
            review_datetime=parse_time(review["reviewed_at"]),
            review_duration=review["duration_ms"],
        )
        after_json = updated.to_json()
        db.execute(
            """
            UPDATE review_events SET mastery_score=?,confidence=?,hidden_rating=?,
                fsrs_after_json=?,corrected_at=?,correction_reason=? WHERE id=?
            """,
            (
                mastery_score,
                confidence,
                int(rating),
                after_json,
                iso(),
                reason,
                review["id"],
            ),
        )
        lapse_count = db.execute(
            """
            SELECT COUNT(*) FROM review_events
            WHERE card_id=? AND hidden_rating=? AND id != (
                SELECT id FROM review_events
                WHERE card_id=? ORDER BY reviewed_at,id LIMIT 1
            )
            """,
            (card_id, int(Rating.Again), card_id),
        ).fetchone()[0]
        db.execute(
            """
            UPDATE cards SET fsrs_json=?,due_at=?,version=version+1,
                lapse_count=?,updated_at=? WHERE id=?
            """,
            (after_json, updated.due.isoformat(), lapse_count, iso(), card_id),
        )
        db.execute(
            "INSERT INTO audit_events(id,event_type,entity_id,details_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                new_id("audit"),
                "review_corrected",
                review["id"],
                dumps(
                    {
                        "before": old,
                        "after_score": mastery_score,
                        "reason": reason,
                    }
                ),
                iso(),
            ),
        )
    return {
        "review_id": review["id"],
        "card_id": card_id,
        "hidden_rating": rating.name.lower(),
        "due_at": updated.due.isoformat(),
        "new_version": card["version"] + 1,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def srs_end_session(session_id: str) -> dict[str, Any]:
    """End a review session and return its duration and review count."""
    ended = iso()
    with connection(write=True) as db:
        row = require_row(db, "SELECT * FROM sessions WHERE id=?", (session_id,), "Session")
        if row["ended_at"] is None:
            db.execute("UPDATE sessions SET ended_at=? WHERE id=?", (ended, session_id))
        else:
            ended = row["ended_at"]
    seconds = max(
        0, int((parse_time(ended) - parse_time(row["started_at"])).total_seconds())
    )
    return {
        "session_id": session_id,
        "reviewed_count": row["reviewed_count"],
        "duration_seconds": seconds,
        "ended_at": ended,
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_deck_stats(deck_id: str) -> dict[str, Any]:
    """Return due counts, score/rating summaries, sessions, and a seven-day forecast."""
    now = utc_now()
    with connection() as db:
        deck = require_row(db, "SELECT * FROM decks WHERE id=?", (deck_id,), "Deck")
        card_counts = dict(
            db.execute(
                """
                SELECT COUNT(*) total,
                  SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) active,
                  SUM(CASE WHEN status='draft' THEN 1 ELSE 0 END) drafts,
                  SUM(CASE WHEN status='active' AND due_at<=? THEN 1 ELSE 0 END) due
                FROM cards WHERE deck_id=?
                """,
                (now.isoformat(), deck_id),
            ).fetchone()
        )
        review_summary = dict(
            db.execute(
                """
                SELECT COUNT(*) reviews, AVG(mastery_score) average_score,
                    SUM(CASE WHEN hidden_rating=1 THEN 1 ELSE 0 END) again,
                    SUM(CASE WHEN hidden_rating=2 THEN 1 ELSE 0 END) hard,
                    SUM(CASE WHEN hidden_rating=3 THEN 1 ELSE 0 END) good,
                    SUM(CASE WHEN hidden_rating=4 THEN 1 ELSE 0 END) easy
                FROM review_events r JOIN cards c ON c.id=r.card_id WHERE c.deck_id=?
                """,
                (deck_id,),
            ).fetchone()
        )
        sessions = dict(
            db.execute(
                """
                SELECT COUNT(*) sessions, COALESCE(SUM(reviewed_count),0) reviewed_in_sessions
                FROM sessions WHERE deck_id=?
                """,
                (deck_id,),
            ).fetchone()
        )
        forecast = []
        for day in range(7):
            start = now + timedelta(days=day)
            end = start + timedelta(days=1)
            count = db.execute(
                """
                SELECT COUNT(*) FROM cards
                WHERE deck_id=? AND status='active' AND due_at>? AND due_at<=?
                """,
                (deck_id, start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            forecast.append({"date": start.date().isoformat(), "due": count})
    if review_summary["average_score"] is not None:
        review_summary["average_score"] = round(review_summary["average_score"], 3)
    return {
        "deck": {"deck_id": deck["id"], "name": deck["name"]},
        "cards": card_counts,
        "reviews": review_summary,
        "sessions": sessions,
        "seven_day_forecast": forecast,
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_export_deck(deck_id: str) -> dict[str, Any]:
    """Export one deck, its source snapshots, cards, and review history as JSON data."""
    with connection() as db:
        deck = require_row(db, "SELECT * FROM decks WHERE id=?", (deck_id,), "Deck")
        sources = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM source_snapshots WHERE deck_id=? ORDER BY created_at",
                (deck_id,),
            )
        ]
        cards = []
        for row in db.execute(
            "SELECT * FROM cards WHERE deck_id=? ORDER BY created_at", (deck_id,)
        ):
            item = dict(row)
            for key in (
                "required_concepts_json",
                "acceptable_answers_json",
                "misconceptions_json",
                "source_ids_json",
                "initial_fsrs_json",
                "fsrs_json",
            ):
                item[key.removesuffix("_json")] = loads(item.pop(key), {})
            item["reviews"] = [
                dict(review)
                for review in db.execute(
                    "SELECT * FROM review_events WHERE card_id=? ORDER BY reviewed_at",
                    (row["id"],),
                )
            ]
            cards.append(item)
    return {
        "format": "semantic-srs-export",
        "version": 1,
        "exported_at": iso(),
        "deck": dict(deck),
        "sources": sources,
        "cards": cards,
    }


def dashboard_overview(deck_id: str | None = None) -> dict[str, Any]:
    """Return cross-deck counts, mastery/rating trends, weak cards, and workload."""
    now = utc_now()
    params: tuple[Any, ...] = ()
    card_filter = ""
    review_filter = ""
    if deck_id:
        card_filter = " WHERE deck_id=?"
        review_filter = " WHERE c.deck_id=?"
        params = (deck_id,)
    with connection() as db:
        counts = dict(
            db.execute(
                f"""
                SELECT COUNT(*) total,
                  SUM(status='active') active,
                  SUM(status='draft') draft,
                  SUM(status='suspended') suspended,
                  SUM(status='rejected') rejected,
                  SUM(status='active' AND due_at<=?) due,
                  SUM(status='active' AND due_at<?) overdue
                FROM cards{card_filter}
                """,
                (now.isoformat(), (now - timedelta(days=1)).isoformat(), *params),
            ).fetchone()
        )
        ratings = dict(
            db.execute(
                f"""
                SELECT COUNT(*) reviews, ROUND(AVG(mastery_score),3) average_score,
                  SUM(hidden_rating=1) again, SUM(hidden_rating=2) hard,
                  SUM(hidden_rating=3) good, SUM(hidden_rating=4) easy
                FROM review_events r JOIN cards c ON c.id=r.card_id{review_filter}
                """,
                params,
            ).fetchone()
        )
        trend = [
            dict(row)
            for row in db.execute(
                f"""
                SELECT substr(reviewed_at,1,10) date, ROUND(AVG(mastery_score),3) score,
                       COUNT(*) reviews
                FROM review_events r JOIN cards c ON c.id=r.card_id{review_filter}
                GROUP BY substr(reviewed_at,1,10) ORDER BY date DESC LIMIT 30
                """,
                params,
            )
        ][::-1]
        weak = [
            public_card(row)
            for row in db.execute(
                f"""SELECT * FROM cards{card_filter}
                    ORDER BY lapse_count DESC, review_count DESC LIMIT 10""",
                params,
            )
            if row["lapse_count"] or row["review_count"]
        ]
        forecast = []
        for offset in range(14):
            start = (now + timedelta(days=offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end = start + timedelta(days=1)
            clause = " AND deck_id=?" if deck_id else ""
            due = db.execute(
                f"""SELECT COUNT(*) FROM cards WHERE status='active'
                    AND due_at>=? AND due_at<?{clause}""",
                (start.isoformat(), end.isoformat(), *params),
            ).fetchone()[0]
            forecast.append({"date": start.date().isoformat(), "due": due})
    return {
        "generated_at": now.isoformat(),
        "cards": counts,
        "ratings": ratings,
        "mastery_trend": trend,
        "weak_cards": weak,
        "forecast": forecast,
    }


def dashboard_cards(
    deck_id: str | None = None,
    status: str | None = None,
    query: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if deck_id:
        clauses.append("c.deck_id=?")
        params.append(deck_id)
    if status:
        clauses.append("c.status=?")
        params.append(status)
    if query:
        clauses.append(
            "(c.learning_objective LIKE ? OR c.suggested_question LIKE ? OR d.name LIKE ?)"
        )
        term = f"%{query}%"
        params.extend((term, term, term))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connection() as db:
        rows = db.execute(
            f"""SELECT c.*,d.name deck_name FROM cards c JOIN decks d ON d.id=c.deck_id
                {where} ORDER BY c.updated_at DESC LIMIT ?""",
            (*params, max(1, min(limit, 1000))),
        ).fetchall()
    return [{**public_card(row), "deck_name": row["deck_name"]} for row in rows]


def dashboard_sources(deck_id: str | None = None) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM source_snapshots"
            + (" WHERE deck_id=?" if deck_id else "")
            + " ORDER BY created_at DESC",
            (deck_id,) if deck_id else (),
        ).fetchall()
    return [dict(row) for row in rows]


def dashboard_sessions(deck_id: str | None = None) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            """SELECT s.*,d.name deck_name FROM sessions s JOIN decks d ON d.id=s.deck_id"""
            + (" WHERE s.deck_id=?" if deck_id else "")
            + " ORDER BY started_at DESC LIMIT 200",
            (deck_id,) if deck_id else (),
        ).fetchall()
    return [dict(row) for row in rows]


def dashboard_reviews(card_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM review_events"
            + (" WHERE card_id=?" if card_id else "")
            + " ORDER BY reviewed_at DESC LIMIT ?",
            ((card_id,) if card_id else ()) + (max(1, min(limit, 2000)),),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("covered_json", "missing_json", "contradictions_json"):
            item[key.removesuffix("_json")] = loads(item.pop(key), [])
        item["hidden_rating"] = Rating(item["hidden_rating"]).name.lower()
        result.append(item)
    return result


def set_card_suspension(
    card_ids: list[str], suspended: bool, expected_versions: dict[str, int] | None = None
) -> dict[str, Any]:
    target = "suspended" if suspended else "active"
    expected_versions = expected_versions or {}
    with connection(write=True) as db:
        rows = db.execute(
            f"SELECT * FROM cards WHERE id IN ({','.join('?' * len(card_ids))})",
            tuple(card_ids),
        ).fetchall()
        if len(rows) != len(set(card_ids)):
            raise ValueError("One or more card_ids were not found")
        for row in rows:
            if row["id"] in expected_versions and row["version"] != expected_versions[row["id"]]:
                raise ValueError(
                    f"Version conflict: expected {expected_versions[row['id']]}, "
                    f"current version is {row['version']}"
                )
            if suspended and row["status"] != "active":
                raise ValueError("Only active cards can be suspended")
            if not suspended and row["status"] != "suspended":
                raise ValueError("Only suspended cards can be restored")
        now = iso()
        db.execute(
            f"UPDATE cards SET status=?,version=version+1,updated_at=? "
            f"WHERE id IN ({','.join('?' * len(card_ids))})",
            (target, now, *card_ids),
        )
        for card_id in card_ids:
            db.execute(
                "INSERT INTO audit_events(id,event_type,entity_id,details_json,created_at,actor) "
                "VALUES(?,?,?,?,?,?)",
                (new_id("audit"), f"card_{target}", card_id, "{}", now, "dashboard"),
            )
    return {"status": target, "updated_count": len(card_ids)}


def archive_deck(deck_id: str, archived: bool, expected_version: int) -> dict[str, Any]:
    status = "archived" if archived else "active"
    with connection(write=True) as db:
        row = require_row(db, "SELECT * FROM decks WHERE id=?", (deck_id,), "Deck")
        if row["version"] != expected_version:
            raise ValueError(
                f"Version conflict: expected {expected_version}, current version is {row['version']}"
            )
        db.execute(
            "UPDATE decks SET status=?,version=version+1,updated_at=? WHERE id=?",
            (status, iso(), deck_id),
        )
        db.execute(
            "INSERT INTO audit_events(id,event_type,entity_id,details_json,created_at,actor) "
            "VALUES(?,?,?,?,?,?)",
            (new_id("audit"), f"deck_{status}", deck_id, "{}", iso(), "dashboard"),
        )
    return {"deck_id": deck_id, "status": status, "version": expected_version + 1}


def reset_edit_card(
    card_id: str,
    expected_version: int,
    learning_objective: str,
    suggested_question: str,
    required_concepts: list[str],
    acceptable_answers: list[str],
    misconceptions: list[str],
    source_ids: list[str],
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("Active-card reset edits require explicit confirmation")
    with connection(write=True) as db:
        row = require_row(db, "SELECT * FROM cards WHERE id=?", (card_id,), "Card")
        if row["status"] != "active":
            raise ValueError("Only active cards use schedule-reset editing")
        if row["version"] != expected_version:
            raise ValueError(
                f"Version conflict: expected {expected_version}, current version is {row['version']}"
            )
        fresh = FSRSCard()
        now = iso()
        before = public_card(row)
        db.execute(
            """UPDATE cards SET learning_objective=?,suggested_question=?,
               required_concepts_json=?,acceptable_answers_json=?,misconceptions_json=?,
               source_ids_json=?,initial_fsrs_json=?,fsrs_json=?,due_at=?,
               review_count=0,lapse_count=0,scheduling_epoch=scheduling_epoch+1,
               version=version+1,updated_at=? WHERE id=?""",
            (
                learning_objective.strip(), suggested_question.strip(),
                dumps(required_concepts), dumps(acceptable_answers),
                dumps(misconceptions), dumps(source_ids), fresh.to_json(),
                fresh.to_json(), fresh.due.isoformat(), now, card_id,
            ),
        )
        db.execute(
            "INSERT INTO audit_events(id,event_type,entity_id,details_json,created_at,actor) "
            "VALUES(?,?,?,?,?,?)",
            (
                new_id("audit"), "active_card_reset_edit", card_id,
                dumps({"before": before, "preserved_review_history": True}), now, "dashboard",
            ),
        )
    return {
        "card_id": card_id,
        "version": expected_version + 1,
        "scheduling_epoch": row["scheduling_epoch"] + 1,
        "history_preserved": True,
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def srs_dashboard_summary(deck_id: str | None = None) -> dict[str, Any]:
    """Return dashboard overview statistics across all decks or one deck."""
    return dashboard_overview(deck_id)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
)
def srs_set_card_suspension(
    card_ids: list[str], suspended: bool
) -> dict[str, Any]:
    """Suspend active cards or restore suspended cards without deleting history."""
    return set_card_suspension(card_ids, suspended)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
    )
)
def srs_archive_deck(
    deck_id: str, archived: bool, expected_version: int
) -> dict[str, Any]:
    """Archive or restore a deck using optimistic version checking."""
    return archive_deck(deck_id, archived, expected_version)


if __name__ == "__main__":
    initialize()
    mcp.run()
