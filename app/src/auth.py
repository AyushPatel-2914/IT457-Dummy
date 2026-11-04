"""Auth service: issues a signed token for the seeded test users (user1..user100, password "password")."""
import hashlib
import hmac
import os
import time

from flask import Blueprint, jsonify, request

from . import db

bp = Blueprint("auth", __name__)

TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "dev-only-secret").encode()


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username, password = body.get("username", ""), body.get("password", "")
    row = db.query("SELECT password_hash FROM users WHERE username = %s", (username,), one=True)
    if row is None or not hmac.compare_digest(row["password_hash"], db.hash_password(username, password)):
        return jsonify(error="invalid credentials"), 401
    payload = f"{username}:{int(time.time()) + 3600}"
    sig = hmac.new(TOKEN_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return jsonify(token=f"{payload}:{sig}")
