import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient


def _isolated_main(monkeypatch, directory):
    from app import main
    root = Path(directory)
    monkeypatch.setenv("LOCAL_IPTV_HOME", str(root))
    main.DATA_DIR = root
    main.CONFIG_FILE = root / "config.me"
    main.KEY_FILE = root / "key.me"
    main.STATE_FILE = root / "state.me"
    main.CATALOG_CACHE_DIR = root / "cache"
    main.SESSIONS.clear()
    main.FAILED_ATTEMPTS = 0
    main.LOCKED_UNTIL = 0
    return main


def test_health_and_initial_state(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        main = _isolated_main(monkeypatch, d)
        client = TestClient(main.app)
        assert client.get("/api/health").json()["status"] == "ok"
        state = client.get("/api/state").json()
        assert state["password_configured"] is False
        assert state["profiles"] == []


def test_catalog_is_cached_and_favorites_persist(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        main = _isolated_main(monkeypatch, d)
        config = main._load_config()
        profile = {"id": "profile123", "nickname": "Test", "method": "xtream", "url": "http://provider.invalid",
                   "username": "user", "password": "pass", "status": "configured", "expiry": None}
        config["profiles"] = [profile]
        config["active_profile"] = profile["id"]
        main._save_config(config)
        calls = []

        def fake_fetch(_profile, media_type):
            calls.append(media_type)
            item = {"stream_id": "42", "name": "Example Channel", "category_id": "1", "category_name": "News"}
            return {"categories": [{"category_id": "1", "category_name": "News"}], "items": [item], "media_type": media_type}

        monkeypatch.setattr(main, "_fetch_catalog", fake_fetch)
        client = TestClient(main.app)
        first = client.get("/api/catalog/live?profile_id=profile123")
        second = client.get("/api/catalog/live?profile_id=profile123")
        assert first.status_code == second.status_code == 200
        assert first.json()["items"][0]["name"] == "Example Channel"
        assert calls == ["live"]
        assert list((Path(d) / "cache").glob("profile123-live.json"))

        payload = {"profile_id": "profile123", "media_type": "live", "item": first.json()["items"][0]}
        added = client.post("/api/favorites", json=payload)
        assert added.status_code == 200 and added.json()["favorited"] is True
        listed = client.get("/api/favorites/live?profile_id=profile123")
        assert listed.json()["items"][0]["name"] == "Example Channel"
        removed = client.post("/api/favorites", json=payload)
        assert removed.status_code == 200 and removed.json()["favorited"] is False


def test_continue_watching_progress_persists_per_profile(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        main = _isolated_main(monkeypatch, d)
        config = main._load_config()
        profile = {"id": "profile123", "nickname": "Test", "method": "xtream", "url": "http://provider.invalid",
                   "username": "user", "password": "pass", "status": "configured", "expiry": None}
        config["profiles"] = [profile]
        config["active_profile"] = profile["id"]
        main._save_config(config)
        client = TestClient(main.app)
        payload = {"profile_id": "profile123", "media_type": "movies",
                   "item": {"stream_id": "99", "name": "A Movie", "container_extension": "mkv"},
                   "navigation": {"type": "movies", "categoryId": "12"},
                   "position": 123.5, "duration": 3600}
        saved = client.post("/api/recent", json=payload)
        assert saved.status_code == 200
        loaded = client.get("/api/recent?profile_id=profile123")
        assert loaded.status_code == 200
        assert loaded.json()["items"][0]["item"]["name"] == "A Movie"
        assert loaded.json()["items"][0]["position"] == 123.5
        assert loaded.json()["items"][0]["duration"] == 3600
        assert loaded.json()["items"][0]["navigation"] == {"type": "movies", "categoryId": "12"}
        # Saving the same item updates its progress rather than creating duplicates.
        payload["position"] = 240
        client.post("/api/recent", json=payload)
        loaded = client.get("/api/recent?profile_id=profile123").json()["items"]
        assert len(loaded) == 1 and loaded[0]["position"] == 240


def test_refresh_profile_stores_xtream_expiry(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        main = _isolated_main(monkeypatch, d)
        profile = {"id": "profile123", "nickname": "Home", "method": "xtream",
                   "url": "http://provider.invalid", "username": "user", "password": "pass",
                   "status": "configured", "expiry": None}
        config = main._load_config()
        config["profiles"] = [profile]
        config["active_profile"] = profile["id"]
        main._save_config(config)
        monkeypatch.setattr(main, "_xtream_api", lambda _profile: {
            "user_info": {"exp_date": "1798761600", "status": "Active"}
        })
        client = TestClient(main.app)
        response = client.post("/api/profile/refresh")
        assert response.status_code == 200
        assert response.json()["profile"]["expiry"] == main._expiry("1798761600")
        assert response.json()["profile"]["status"] == "Active"
        assert main._load_config()["profiles"][0]["expiry"] == main._expiry("1798761600")
