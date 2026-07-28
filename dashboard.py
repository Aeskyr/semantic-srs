from __future__ import annotations

import hmac
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

import service


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
TOKEN = os.environ.get("SEMANTIC_SRS_DASHBOARD_TOKEN", "")
PORT = int(os.environ.get("SEMANTIC_SRS_DASHBOARD_PORT", "8765"))


def _allowed_host(request: Request) -> bool:
    host = request.headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _allowed_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    parsed = urlsplit(origin)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.port == PORT
    )


def _authorized(request: Request) -> bool:
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    supplied = supplied or request.query_params.get("token", "")
    return bool(TOKEN) and hmac.compare_digest(supplied, TOKEN)


async def security_middleware(request: Request, call_next):
    if not _allowed_host(request):
        return JSONResponse({"error": "Invalid Host header"}, status_code=400)
    if request.url.path.startswith("/api/"):
        if not _allowed_origin(request):
            return JSONResponse({"error": "Invalid Origin header"}, status_code=403)
        if not _authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    )
    return response


def _json_error(exc: Exception) -> JSONResponse:
    message = str(exc)
    status = 409 if "Version conflict" in message else 400
    return JSONResponse({"error": message}, status_code=status)


async def index(request: Request) -> Response:
    return FileResponse(WEB / "index.html")


async def asset(request: Request) -> Response:
    name = request.path_params["name"]
    if name not in {"app.js", "styles.css"}:
        return Response(status_code=404)
    return FileResponse(WEB / name, media_type=mimetypes.guess_type(name)[0])


async def overview(request: Request) -> Response:
    return JSONResponse(service.dashboard_overview(request.query_params.get("deck_id")))


async def decks(request: Request) -> Response:
    return JSONResponse(service.srs_list_decks())


async def cards(request: Request) -> Response:
    return JSONResponse(
        service.dashboard_cards(
            request.query_params.get("deck_id"),
            request.query_params.get("status"),
            request.query_params.get("q", ""),
        )
    )


async def sources(request: Request) -> Response:
    return JSONResponse(service.dashboard_sources(request.query_params.get("deck_id")))


async def sessions(request: Request) -> Response:
    return JSONResponse(service.dashboard_sessions(request.query_params.get("deck_id")))


async def reviews(request: Request) -> Response:
    return JSONResponse(service.dashboard_reviews(request.query_params.get("card_id")))


async def mutate(request: Request) -> Response:
    try:
        body = await request.json()
        action = request.path_params["action"]
        if action == "draft-status":
            result = service.srs_set_draft_status(body["card_ids"], body["status"])
        elif action == "draft-edit":
            result = service.srs_update_draft_card(
                body["card_id"], body["learning_objective"], body["suggested_question"],
                body["required_concepts"], body.get("acceptable_answers", []),
                body.get("misconceptions", []), body.get("source_ids", []),
            )
        elif action == "suspension":
            result = service.set_card_suspension(
                body["card_ids"], body["suspended"], body.get("expected_versions")
            )
        elif action == "archive":
            result = service.archive_deck(
                body["deck_id"], body["archived"], body["expected_version"]
            )
        elif action == "reset-edit":
            result = service.reset_edit_card(**body)
        else:
            return JSONResponse({"error": "Unknown action"}, status_code=404)
        return JSONResponse(result)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return _json_error(exc)


async def export(request: Request) -> Response:
    try:
        payload = service.srs_export_deck(request.path_params["deck_id"])
        name = "".join(c for c in payload["deck"]["name"] if c.isalnum() or c in "-_ ")[:80]
        return JSONResponse(
            payload,
            headers={
                "Content-Disposition": f'attachment; filename="{name or "deck"}.json"'
            },
        )
    except ValueError as exc:
        return _json_error(exc)


routes = [
    Route("/", index),
    Route("/assets/{name}", asset),
    Route("/api/overview", overview),
    Route("/api/decks", decks),
    Route("/api/cards", cards),
    Route("/api/sources", sources),
    Route("/api/sessions", sessions),
    Route("/api/reviews", reviews),
    Route("/api/actions/{action}", mutate, methods=["POST"]),
    Route("/api/export/{deck_id}", export),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(BaseHTTPMiddleware, dispatch=security_middleware)],
)
service.initialize()
