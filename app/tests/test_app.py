import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def make_client(tmp_path, monkeypatch, service, **env):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SERVICE", service)
    monkeypatch.setenv("FAULT_FILE", str(tmp_path / "fault.json"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Modules read their settings at import time, so reload them for each configuration.
    for name in ["src.db", "src.recommendations", "src.auth", "src.catalogue", "src.main"]:
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from src import main
    return main.create_app().test_client()


def test_monolith_endpoints(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch, "monolith")
    assert c.get("/health").json["status"] == "ok"
    assert len(c.get("/movies").json["movies"]) == 20
    assert c.get("/movies/7").json["id"] == 7
    assert c.get("/movies/99999").status_code == 404
    home = c.get("/?user=user5").json
    assert home["recommendations_source"] == "personal" and len(home["recommendations"]) == 10
    assert c.post("/login", json={"username": "user5", "password": "password"}).status_code == 200
    assert c.post("/login", json={"username": "user5", "password": "nope"}).status_code == 401
    assert "X-Served-By" in c.get("/health").headers


def test_seed_is_idempotent(tmp_path, monkeypatch):
    make_client(tmp_path, monkeypatch, "monolith")
    from src import db
    db.init()
    assert db.query("SELECT COUNT(*) AS n FROM movies", one=True)["n"] == db.N_MOVIES


def test_breaker_on_falls_back_when_recs_down(tmp_path, monkeypatch):
    # Nothing listens on port 9 -> connection refused, like a stopped recommendations container.
    c = make_client(tmp_path, monkeypatch, "catalogue", RECS_URL="http://127.0.0.1:9", BREAKER="on")
    for _ in range(8):  # enough calls to open the breaker
        r = c.get("/?user=user1")
        assert r.status_code == 200
        assert r.json["recommendations_source"] == "fallback"


def test_breaker_off_propagates_error(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch, "catalogue", RECS_URL="http://127.0.0.1:9", BREAKER="off")
    assert c.get("/?user=user1").status_code == 502


def test_fault_injection(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch, "recommendations", FAULTS_ENABLED="1")
    assert c.post("/admin/fault", json={"error_rate": 1}).json["error_rate"] == 1
    assert c.get("/recommendations/user1").status_code == 500
    c.delete("/admin/fault")
    assert c.get("/recommendations/user1").status_code == 200


def test_fault_endpoint_hidden_by_default(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch, "recommendations", FAULTS_ENABLED="0")
    assert c.post("/admin/fault", json={"latency_ms": 1}).status_code == 404
