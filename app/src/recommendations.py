"""Recommendations service, plus a small fault-injection hook used by chaos experiment E3.

Faults are stored in a file so that every gunicorn worker in the container sees the same
setting. The /admin/fault endpoint only exists when FAULTS_ENABLED=1.
"""
import json
import os
import random
import time
import zlib

from flask import Blueprint, abort, jsonify, request

from . import db

bp = Blueprint("recommendations", __name__)

FAULT_FILE = os.environ.get("FAULT_FILE", "/tmp/minix_fault.json")
FAULTS_ENABLED = os.environ.get("FAULTS_ENABLED", "0") == "1"


def favourite_genre(user):
    # Deterministic "taste profile" so results are repeatable between runs.
    return db.GENRES[zlib.crc32(user.encode()) % len(db.GENRES)]


def compute(user):
    genre = favourite_genre(user)
    return db.query("SELECT id, title, genre, rating FROM movies WHERE genre = %s ORDER BY rating DESC, id LIMIT 10",
                    (genre,))


def popular():
    return db.query("SELECT id, title, genre, rating FROM movies ORDER BY rating DESC, id LIMIT 10")


def _current_fault():
    try:
        with open(FAULT_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@bp.get("/recommendations/<user>")
def recommend(user):
    if FAULTS_ENABLED:
        fault = _current_fault()
        if fault.get("latency_ms"):
            time.sleep(fault["latency_ms"] / 1000)
        if random.random() < float(fault.get("error_rate", 0)):
            abort(500)
    return jsonify(user=user, genre=favourite_genre(user), recommendations=compute(user))


@bp.route("/admin/fault", methods=["GET", "POST", "DELETE"])
def fault():
    if not FAULTS_ENABLED:
        abort(404)
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        setting = {"latency_ms": int(body.get("latency_ms", 0)), "error_rate": float(body.get("error_rate", 0))}
        with open(FAULT_FILE, "w") as f:
            json.dump(setting, f)
    elif request.method == "DELETE":
        try:
            os.remove(FAULT_FILE)
        except FileNotFoundError:
            pass
    return jsonify(_current_fault())
