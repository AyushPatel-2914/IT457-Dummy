"""Catalogue service: movie list, movie detail and the home page (the steady-state request)."""
import os

import requests
from flask import Blueprint, abort, jsonify, request

from . import db, recommendations

bp = Blueprint("catalogue", __name__)

PAGE_SIZE = 20


@bp.get("/movies")
def list_movies():
    page = max(int(request.args.get("page", 1)), 1)
    genre = request.args.get("genre")
    if genre:
        rows = db.query("SELECT * FROM movies WHERE genre = %s ORDER BY rating DESC, id LIMIT %s OFFSET %s",
                        (genre, PAGE_SIZE, (page - 1) * PAGE_SIZE))
    else:
        rows = db.query("SELECT * FROM movies ORDER BY id LIMIT %s OFFSET %s", (PAGE_SIZE, (page - 1) * PAGE_SIZE))
    return jsonify(page=page, movies=rows)


@bp.get("/movies/<int:movie_id>")
def get_movie(movie_id):
    row = db.query("SELECT * FROM movies WHERE id = %s", (movie_id,), one=True)
    if row is None:
        abort(404)
    return jsonify(row)


@bp.get("/")
def home():
    user = request.args.get("user", "user1")
    trending = db.query("SELECT id, title, genre, rating FROM movies ORDER BY rating DESC, id LIMIT 10")
    recs, source = _recommendations_for(user)
    resp = jsonify(user=user, trending=trending, recommendations=recs, recommendations_source=source)
    resp.headers["X-Recs-Source"] = source
    return resp


# --- How the home page gets recommendations -------------------------------------------------
# Monolith (S0/S1): an in-process function call, so it fails only if the whole app fails.
# Services (S2): an HTTP call to the recommendations service. With BREAKER=on the call has a
# short timeout, a circuit breaker and a fallback (graceful degradation, as Hystrix did at
# Netflix). With BREAKER=off it is a naive call: long timeout, no fallback, errors propagate.

SERVICE = os.environ.get("SERVICE", "monolith")
RECS_URL = os.environ.get("RECS_URL", "http://127.0.0.1:5002")
BREAKER_ON = os.environ.get("BREAKER", "on").lower() == "on"
RECS_TIMEOUT = float(os.environ.get("RECS_TIMEOUT", "0.25" if BREAKER_ON else "5"))

_session = requests.Session()
_breaker = None
if BREAKER_ON:
    import pybreaker
    _breaker = pybreaker.CircuitBreaker(fail_max=int(os.environ.get("BREAKER_FAIL_MAX", "5")),
                                        reset_timeout=int(os.environ.get("BREAKER_RESET_S", "10")))


class RecommendationsUnavailable(Exception):
    pass


def _fetch_remote(user):
    resp = _session.get(f"{RECS_URL}/recommendations/{user}", timeout=RECS_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["recommendations"]


def _recommendations_for(user):
    if SERVICE == "monolith":
        return recommendations.compute(user), "personal"
    if _breaker is None:
        try:
            return _fetch_remote(user), "personal"
        except requests.RequestException as exc:
            raise RecommendationsUnavailable(str(exc)) from exc
    try:
        return _breaker.call(_fetch_remote, user), "personal"
    except Exception:
        # Fallback: a generic popular list instead of an error page.
        return recommendations.popular(), "fallback"


@bp.app_errorhandler(RecommendationsUnavailable)
def _recs_down(exc):
    return jsonify(error="recommendations unavailable", detail=str(exc)), 502
