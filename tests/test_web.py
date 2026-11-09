from fastapi.testclient import TestClient

from musicbuddy import config
from musicbuddy.web import app as web


def client():
    return TestClient(web.app)


def test_api_requires_login():
    c = client()
    for path in ("/api/me", "/api/lessons", "/api/lessons/20261107", "/api/profiles/keyu"):
        assert c.get(path).status_code == 401
    assert c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_login_flow_and_validation(monkeypatch):
    monkeypatch.setattr(config, "PASSCODE", "test-pass")
    web._attempts.clear()
    c = client()
    assert c.post("/api/login", json={"passcode": "nope"}).status_code == 401
    assert c.post("/api/login", json={"passcode": "TEST-PASS"}).status_code == 200
    assert c.get("/api/me").status_code == 200
    assert c.get("/api/lessons/2026").status_code == 400
    assert c.get("/api/lessons/20261107/audio/evil").status_code == 400
    assert c.get("/api/profiles/someone").status_code == 404
    assert c.get("/api/lessons/20261107/images/a.b").status_code in (400, 404)
    assert c.get("/api/lessons/20261107/images/" + "x" * 30).status_code == 400
    assert c.get("/api/lessons/20261107/kids/someone/checks").status_code == 404
    r = c.post("/api/chat", json={"messages": [{"role": "assistant", "content": "x"}]})
    assert r.status_code == 400


def test_login_rate_limit(monkeypatch):
    monkeypatch.setattr(config, "PASSCODE", "test-pass")
    web._attempts.clear()
    c = client()
    codes = [c.post("/api/login", json={"passcode": "bad"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[-1] == 429


def test_security_headers():
    r = client().get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
