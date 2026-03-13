from fastapi.testclient import TestClient

from backend.app import app


def test_frontend_integration_endpoints_are_reachable():
    """Smoke test core endpoints used by the frontend integration."""
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["docs"] == "/docs"

        health = client.get("/api/health")
        assert health.status_code == 200
        health_json = health.json()
        assert health_json["status"] == "ok"
        assert "version" in health_json

        sentiment = client.get("/api/news/sentiment")
        assert sentiment.status_code == 200
        assert "btc_sentiment" in sentiment.json()

        latest_news = client.get("/api/news/latest")
        assert latest_news.status_code == 200
        assert "articles" in latest_news.json()

        btc_news = client.get("/api/news/bitcoin")
        assert btc_news.status_code == 200
        assert "articles" in btc_news.json()

        safety_status = client.get("/api/safety/status")
        assert safety_status.status_code == 200
        assert "circuit_breaker" in safety_status.json()

        reset_breaker = client.post("/api/safety/reset-breaker")
        assert reset_breaker.status_code == 200
        assert reset_breaker.json()["success"] is True

        sessions = client.get("/api/scratchpad/sessions")
        assert sessions.status_code == 200
        sessions_json = sessions.json()
        assert "sessions" in sessions_json

        if sessions_json["sessions"]:
            first = sessions_json["sessions"][0]
            detail = client.get(f"/api/scratchpad/{first}")
            assert detail.status_code == 200
            assert detail.json()["session_id"] == first
