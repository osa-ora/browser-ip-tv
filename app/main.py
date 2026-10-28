from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_NAME = "Local IPTV"
DATA_DIR = Path(os.environ.get("LOCAL_IPTV_HOME", str(Path.home() / ".local-iptv"))).expanduser()
CONFIG_FILE = DATA_DIR / "config.me"
KEY_FILE = DATA_DIR / "key.me"
STATE_FILE = DATA_DIR / "state.me"
CATALOG_CACHE_DIR = DATA_DIR / "cache"
CATALOG_TTL_SECONDS = 24 * 60 * 60
MAX_RESPONSE = 32 * 1024 * 1024
LOCK = threading.RLock()
FAILED_ATTEMPTS = 0
LOCKED_UNTIL = 0.0
SESSIONS: dict[str, float] = {}
SESSION_TTL = 12 * 60 * 60

app = FastAPI(title=APP_NAME, version="0.2.7")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(secrets.token_bytes(32))
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass


def _key() -> bytes:
    _ensure_data_dir()
    return KEY_FILE.read_bytes()


def _xor_obfuscate(raw: bytes, key: bytes) -> bytes:
    # Lightweight obfuscation for the local registry; not cryptographic encryption.
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))


def _load_config() -> dict[str, Any]:
    _ensure_data_dir()
    if not CONFIG_FILE.exists():
        return {"version": 1, "app_password": None, "profiles": [], "active_profile": None,
                "settings": {"theme": "dark", "home_order": ["continue", "movies", "series", "live"],
                             "show_expiry": True}}
    try:
        payload = base64.b64decode(CONFIG_FILE.read_bytes(), validate=True)
        data = json.loads(_xor_obfuscate(payload, _key()).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid config")
        data.setdefault("version", 1)
        data.setdefault("profiles", [])
        data.setdefault("settings", {})
        data.setdefault("favorites", {})
        data.setdefault("recent", {})
        return data
    except Exception:
        raise RuntimeError("Configuration file is unreadable. Restore a valid backup of config.me and key.me.")


def _save_config(config: dict[str, Any]) -> None:
    _ensure_data_dir()
    raw = json.dumps(config, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_bytes(base64.b64encode(_xor_obfuscate(raw, _key())))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return base64.b64encode(salt + digest).decode("ascii")


def _verify_password(password: str, encoded: str) -> bool:
    try:
        raw = base64.b64decode(encoded)
        salt, expected = raw[:16], raw[16:]
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _cache_file(profile_id: str, media_type: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", profile_id)
    CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CATALOG_CACHE_DIR, 0o700)
    except OSError:
        pass
    return CATALOG_CACHE_DIR / f"{safe_id}-{media_type}.json"


def _read_catalog_cache(profile_id: str, media_type: str) -> tuple[dict[str, Any] | None, float | None]:
    path = _cache_file(profile_id, media_type)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("catalog"), float(data.get("fetched_at", 0))
    except (OSError, ValueError, TypeError):
        return None, None


def _write_catalog_cache(profile_id: str, media_type: str, catalog: dict[str, Any]) -> None:
    path = _cache_file(profile_id, media_type)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": time.time(), "catalog": catalog}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _safe_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {k: profile.get(k) for k in ("id", "nickname", "method", "url", "username", "expiry", "status")
            if profile.get(k) is not None}


def _session(request: FastAPIRequest, config: dict[str, Any]) -> None:
    if not config.get("app_password"):
        return
    token = request.cookies.get("iptv_session", "")
    expires = SESSIONS.get(token, 0)
    if not token or expires < time.time():
        SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="Application password required")


def _provider_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise HTTPException(400, "Server URL is required")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "Server URL must start with http:// or https://")
    return url.rstrip("/")


def _http_json(url: str, timeout: int = 18) -> Any:
    req = Request(url, headers={"User-Agent": "LocalIPTV/0.1", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise HTTPException(502, "Provider response is too large")
            return json.loads(data.decode("utf-8-sig"))
    except HTTPException:
        raise
    except HTTPError as exc:
        raise HTTPException(502, f"Provider returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(502, "Could not reach the IPTV provider or parse its response") from exc


def _xtream_api(profile: dict[str, Any], params: dict[str, Any] | None = None) -> Any:
    base = _provider_url(profile["url"])
    query = {"username": profile["username"], "password": profile["password"]}
    if params:
        query.update(params)
    return _http_json(f"{base}/player_api.php?{urlencode(query)}")


def _m3u_catalog(profile: dict[str, Any]) -> list[dict[str, Any]]:
    url = profile.get("playlist_url") or profile["url"]
    req = Request(url, headers={"User-Agent": "LocalIPTV/0.1"})
    try:
        with urlopen(req, timeout=25) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise HTTPException(502, "Playlist is too large (maximum 32 MB)")
        content = raw.decode("utf-8-sig", errors="replace")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Could not retrieve the M3U playlist") from exc
    entries: list[dict[str, Any]] = []
    pending: dict[str, str] | None = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            title = line.rsplit(",", 1)[-1].strip() if "," in line else "Untitled"
            group = re.search(r'group-title="([^"]*)"', line, re.I)
            logo = re.search(r'tvg-logo="([^"]*)"', line, re.I)
            tvg = re.search(r'tvg-id="([^"]*)"', line, re.I)
            pending = {"name": title or "Untitled", "category_name": group.group(1) if group else "All channels",
                       "stream_icon": logo.group(1) if logo else "", "epg_channel_id": tvg.group(1) if tvg else ""}
        elif pending and line and not line.startswith("#"):
            entries.append({**pending, "stream_id": str(len(entries) + 1), "stream_url": line,
                            "stream_type": "live", "category_id": pending["category_name"]})
            pending = None
    return entries


def _get_profile(config: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
    profile_id = profile_id or config.get("active_profile")
    for profile in config.get("profiles", []):
        if profile.get("id") == profile_id:
            return profile
    raise HTTPException(404, "IPTV profile not found")


class PasswordPayload(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ProfilePayload(BaseModel):
    nickname: str = Field(min_length=1, max_length=80)
    method: str = Field(pattern="^(xtream|m3u)$")
    url: str = Field(min_length=1, max_length=2048)
    username: str = Field(default="", max_length=512)
    password: str = Field(default="", max_length=512)
    playlist_url: str = Field(default="", max_length=2048)


class FavoritePayload(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    media_type: str = Field(pattern="^(live|movies|series)$")
    item: dict[str, Any]


class RecentPayload(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    media_type: str = Field(pattern="^(live|movies|series)$")
    item: dict[str, Any]
    navigation: dict[str, Any] | None = None
    position: float = Field(default=0, ge=0, le=100000000)
    duration: float = Field(default=0, ge=0, le=100000000)


class SettingsPayload(BaseModel):
    theme: str = Field(default="dark", pattern="^(dark|light|system)$")
    home_order: list[str] = Field(default_factory=lambda: ["continue", "movies", "series", "live"])
    show_expiry: bool = True


class ProfileUpdatePayload(ProfilePayload):
    pass


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/api/state")
def get_state(request: FastAPIRequest):
    config = _load_config()
    token = request.cookies.get("iptv_session", "")
    session_expiry = SESSIONS.get(token, 0) if token else 0
    authenticated = not bool(config.get("app_password")) or session_expiry >= time.time()
    if token and session_expiry < time.time():
        SESSIONS.pop(token, None)
    return {
        "password_configured": bool(config.get("app_password")),
        "authenticated": authenticated,
        "profiles": [_safe_profile(p) for p in config.get("profiles", [])],
        "active_profile": config.get("active_profile"),
        "settings": config.get("settings", {}),
        "lockout_seconds": max(0, int(LOCKED_UNTIL - time.time())),
    }


@app.post("/api/password")
def set_password(payload: PasswordPayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    if len(payload.password) < 8:
        raise HTTPException(400, "Use at least 8 characters for the application password")
    config["app_password"] = _hash_password(payload.password)
    _save_config(config)
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = time.time() + SESSION_TTL
    response = JSONResponse({"ok": True})
    response.set_cookie("iptv_session", token, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=SESSION_TTL, path="/")
    return response


@app.delete("/api/password")
def remove_password(request: FastAPIRequest, payload: PasswordPayload):
    config = _load_config()
    _session(request, config)
    stored = config.get("app_password")
    if stored and not _verify_password(payload.password, stored):
        raise HTTPException(403, "Incorrect application password")
    config["app_password"] = None
    _save_config(config)
    response = JSONResponse({"ok": True})
    response.delete_cookie("iptv_session", path="/")
    return response


@app.post("/api/login")
def login(payload: PasswordPayload, request: FastAPIRequest):
    global FAILED_ATTEMPTS, LOCKED_UNTIL
    if time.time() < LOCKED_UNTIL:
        raise HTTPException(429, f"Too many failed attempts. Try again in {int(LOCKED_UNTIL-time.time())} seconds.")
    config = _load_config()
    stored = config.get("app_password")
    if not stored or _verify_password(payload.password, stored):
        FAILED_ATTEMPTS, LOCKED_UNTIL = 0, 0
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = time.time() + SESSION_TTL
        response = JSONResponse({"ok": True})
        response.set_cookie("iptv_session", token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=SESSION_TTL, path="/")
        return response
    FAILED_ATTEMPTS += 1
    if FAILED_ATTEMPTS >= 3:
        LOCKED_UNTIL = time.time() + 300
        FAILED_ATTEMPTS = 0
    raise HTTPException(401, "Incorrect application password")


@app.post("/api/logout")
def logout(request: FastAPIRequest):
    token = request.cookies.get("iptv_session", "")
    SESSIONS.pop(token, None)
    response = JSONResponse({"ok": True})
    response.delete_cookie("iptv_session", path="/")
    return response


@app.get("/api/profiles")
def profiles(request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    return {"profiles": [_safe_profile(p) for p in config.get("profiles", [])],
            "active_profile": config.get("active_profile")}


@app.post("/api/profiles/test")
def test_profile(payload: ProfilePayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    if payload.method == "xtream":
        base = _provider_url(payload.url)
        if not payload.username or not payload.password:
            raise HTTPException(400, "Xtream requires username and password")
        profile = {"url": base, "username": payload.username, "password": payload.password}
        result = _xtream_api(profile)
        user_info = result.get("user_info", {}) if isinstance(result, dict) else {}
        if not user_info or str(user_info.get("auth", "1")) == "0":
            raise HTTPException(400, "Provider did not authenticate these credentials")
        expiry = user_info.get("exp_date")
        return {"ok": True, "expiry": _expiry(expiry), "message": "Connection successful"}
    _provider_url(payload.playlist_url or payload.url)
    temporary = {"url": payload.url, "playlist_url": payload.playlist_url or payload.url}
    catalog = _m3u_catalog(temporary)
    return {"ok": True, "channels": len(catalog), "message": f"Playlist loaded ({len(catalog)} entries)"}


def _expiry(value: Any) -> str | None:
    try:
        n = int(value)
        if n <= 0:
            return None
        return time.strftime("%Y-%m-%d", time.localtime(n))
    except (TypeError, ValueError, OverflowError):
        return None


@app.post("/api/profiles")
def add_profile(payload: ProfilePayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    nickname = payload.nickname.strip()
    if any(p["nickname"].casefold() == nickname.casefold() for p in config.get("profiles", [])):
        raise HTTPException(409, "A profile with this nickname already exists")
    if payload.method == "xtream":
        _provider_url(payload.url)
        if not payload.username.strip() or not payload.password:
            raise HTTPException(400, "Xtream requires username and password")
        profile = {"id": uuid.uuid4().hex, "nickname": nickname, "method": "xtream",
                   "url": payload.url.rstrip("/"), "username": payload.username, "password": payload.password,
                   "status": "configured", "expiry": None}
    else:
        playlist = payload.playlist_url.strip() or payload.url.strip()
        _provider_url(playlist)
        profile = {"id": uuid.uuid4().hex, "nickname": nickname, "method": "m3u",
                   "url": playlist, "playlist_url": playlist, "username": "", "password": "",
                   "status": "configured", "expiry": None}
    config.setdefault("profiles", []).append(profile)
    if not config.get("active_profile"):
        config["active_profile"] = profile["id"]
    _save_config(config)
    return {"ok": True, "profile": _safe_profile(profile)}


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: str, payload: ProfileUpdatePayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    old = _get_profile(config, profile_id)
    nickname = payload.nickname.strip()
    if any(p["id"] != profile_id and p["nickname"].casefold() == nickname.casefold()
           for p in config.get("profiles", [])):
        raise HTTPException(409, "A profile with this nickname already exists")
    if payload.method == "xtream":
        _provider_url(payload.url)
        username = payload.username.strip() or old.get("username", "")
        password = payload.password or old.get("password", "")
        if not username or not password:
            raise HTTPException(400, "Xtream requires username and password")
        new = {"id": profile_id, "nickname": nickname, "method": "xtream", "url": payload.url.rstrip("/"),
               "username": username, "password": password, "status": "configured", "expiry": old.get("expiry")}
    else:
        playlist = payload.playlist_url.strip() or payload.url.strip()
        _provider_url(playlist)
        new = {"id": profile_id, "nickname": nickname, "method": "m3u", "url": playlist,
               "playlist_url": playlist, "username": "", "password": "", "status": "configured", "expiry": None}
    config["profiles"] = [new if p["id"] == profile_id else p for p in config["profiles"]]
    for media_type in ("live", "movies", "series"):
        try: _cache_file(profile_id, media_type).unlink(missing_ok=True)
        except OSError: pass
    _save_config(config)
    return {"ok": True, "profile": _safe_profile(new)}


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    _get_profile(config, profile_id)
    config["profiles"] = [p for p in config["profiles"] if p["id"] != profile_id]
    config.get("favorites", {}).pop(profile_id, None)
    for media_type in ("live", "movies", "series"):
        try: _cache_file(profile_id, media_type).unlink(missing_ok=True)
        except OSError: pass
    if config.get("active_profile") == profile_id:
        config["active_profile"] = config["profiles"][0]["id"] if config["profiles"] else None
    _save_config(config)
    return {"ok": True, "active_profile": config["active_profile"]}


@app.post("/api/profiles/{profile_id}/activate")
def activate_profile(profile_id: str, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    _get_profile(config, profile_id)
    config["active_profile"] = profile_id
    _save_config(config)
    return {"ok": True, "active_profile": profile_id}


@app.get("/api/settings")
def get_settings(request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    return config.get("settings", {})


@app.put("/api/settings")
def update_settings(payload: SettingsPayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    allowed = {"continue", "movies", "series", "live"}
    order = [item for item in payload.home_order if item in allowed]
    for item in allowed:
        if item not in order:
            order.append(item)
    config["settings"] = {"theme": payload.theme, "home_order": order, "show_expiry": payload.show_expiry}
    _save_config(config)
    return {"ok": True, "settings": config["settings"]}


def _fetch_catalog(profile: dict[str, Any], media_type: str) -> dict[str, Any]:
    if profile["method"] == "m3u":
        if media_type != "live":
            return {"categories": [], "items": [], "media_type": media_type}
        entries = _m3u_catalog(profile)
        groups = {}
        for entry in entries:
            groups.setdefault(str(entry["category_id"]), {"category_id": str(entry["category_id"]),
                "category_name": str(entry["category_name"]), "parent_id": 0})
        return {"categories": list(groups.values()), "items": entries, "media_type": media_type}
    if media_type == "live":
        categories = _xtream_api(profile, {"action": "get_live_categories"})
        items = _xtream_api(profile, {"action": "get_live_streams"})
    elif media_type == "movies":
        categories = _xtream_api(profile, {"action": "get_vod_categories"})
        items = _xtream_api(profile, {"action": "get_vod_streams"})
    else:
        categories = _xtream_api(profile, {"action": "get_series_categories"})
        items = _xtream_api(profile, {"action": "get_series"})
    return {"categories": categories if isinstance(categories, list) else [],
            "items": items if isinstance(items, list) else [], "media_type": media_type}


def _item_key(item: dict[str, Any]) -> str:
    # Stream URLs are stable for M3U playlists even when playlist order changes.
    value = item.get("stream_url") or item.get("stream_id") or item.get("series_id") or item.get("id")
    return str(value if value is not None else item.get("name") or item.get("title") or "")


@app.get("/api/catalog/{media_type}")
def catalog(media_type: str, request: FastAPIRequest, profile_id: str | None = None,
            category_id: str | None = None, refresh: bool = False):
    if media_type not in ("live", "movies", "series"):
        raise HTTPException(400, "Unknown media type")
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, profile_id)
    cached, fetched_at = _read_catalog_cache(profile["id"], media_type)
    stale = not cached or not fetched_at or time.time() - fetched_at >= CATALOG_TTL_SECONDS
    if refresh or stale:
        try:
            cached = _fetch_catalog(profile, media_type)
            _write_catalog_cache(profile["id"], media_type, cached)
            fetched_at = time.time()
            stale = False
        except HTTPException:
            if not cached:
                raise
            # If the provider is temporarily unavailable, keep the last working local copy.
    if not isinstance(cached, dict):
        cached = {"categories": [], "items": [], "media_type": media_type}
    categories = cached.get("categories", [])
    items = cached.get("items", [])
    if category_id is not None:
        items = [item for item in items if str(item.get("category_id", "")) == str(category_id)]
    return {"categories": categories, "items": items, "media_type": media_type,
            "cached": True, "fetched_at": fetched_at, "stale": bool(stale)}


@app.get("/api/favorites/{media_type}")
def get_favorites(media_type: str, request: FastAPIRequest, profile_id: str | None = None):
    if media_type not in ("live", "movies", "series"):
        raise HTTPException(400, "Unknown media type")
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, profile_id)
    favorites = config.get("favorites", {}).get(profile["id"], {}).get(media_type, [])
    return {"items": favorites if isinstance(favorites, list) else []}


@app.post("/api/favorites")
def toggle_favorite(payload: FavoritePayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, payload.profile_id)
    key = _item_key(payload.item)
    if not key:
        raise HTTPException(400, "Cannot favorite an item without an ID")
    favorites = config.setdefault("favorites", {}).setdefault(profile["id"], {}).setdefault(payload.media_type, [])
    existing = next((item for item in favorites if _item_key(item) == key), None)
    if existing is not None:
        favorites.remove(existing)
        favorited = False
    else:
        favorites.append(payload.item)
        favorited = True
    _save_config(config)
    return {"ok": True, "favorited": favorited, "items": favorites}


@app.get("/api/recent")
def get_recent(request: FastAPIRequest, profile_id: str | None = None):
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, profile_id)
    items = config.get("recent", {}).get(profile["id"], [])
    return {"items": items if isinstance(items, list) else []}


@app.post("/api/recent")
def save_recent(payload: RecentPayload, request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, payload.profile_id)
    recent_by_profile = config.setdefault("recent", {})
    items = recent_by_profile.setdefault(profile["id"], [])
    key = _item_key(payload.item)
    now = int(time.time())
    record = {"profileId": profile["id"], "type": payload.media_type, "item": payload.item,
              "navigation": payload.navigation, "position": payload.position, "duration": payload.duration, "updated_at": now}
    items[:] = [entry for entry in items if not (
        entry.get("type") == payload.media_type and
        _item_key(entry.get("item", {})) == key
    )]
    # Do not keep completed titles in Continue Watching; retain live channels as recently watched.
    if payload.media_type == "live" or payload.duration <= 0 or payload.position < max(0, payload.duration - 45):
        items.insert(0, record)
    items[:] = items[:50]
    _save_config(config)
    return {"ok": True, "items": items}


@app.get("/api/series/{series_id}")
def series_info(series_id: str, request: FastAPIRequest, profile_id: str | None = None):
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, profile_id)
    if profile["method"] != "xtream":
        raise HTTPException(400, "Series episodes require an Xtream provider")
    data = _xtream_api(profile, {"action": "get_series_info", "series_id": series_id})
    return data


@app.get("/api/stream-url/{media_type}/{stream_id}")
def stream_url(media_type: str, stream_id: str, request: FastAPIRequest, profile_id: str | None = None,
               extension: str | None = None):
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config, profile_id)
    if profile["method"] == "m3u":
        entry = next((e for e in _m3u_catalog(profile) if e["stream_id"] == stream_id), None)
        if not entry:
            raise HTTPException(404, "Stream not found in playlist")
        return {"url": entry["stream_url"]}
    base = _provider_url(profile["url"])
    if media_type == "live":
        path = f"/live/{profile['username']}/{profile['password']}/{stream_id}.{extension or 'm3u8'}"
    elif media_type == "movies":
        path = f"/movie/{profile['username']}/{profile['password']}/{stream_id}.{extension or 'mp4'}"
    elif media_type == "series":
        path = f"/series/{profile['username']}/{profile['password']}/{stream_id}.{extension or 'mp4'}"
    else:
        raise HTTPException(400, "Unknown media type")
    return {"url": base + path}


@app.post("/api/profile/refresh")
def refresh_profile(request: FastAPIRequest):
    config = _load_config()
    _session(request, config)
    profile = _get_profile(config)
    if profile["method"] == "xtream":
        data = _xtream_api(profile)
        info = data.get("user_info", {}) if isinstance(data, dict) else {}
        profile["expiry"] = _expiry(info.get("exp_date"))
        profile["status"] = str(info.get("status") or "unknown")
        _save_config(config)
        return {"profile": _safe_profile(profile)}
    return {"profile": _safe_profile(profile)}


@app.get("/api/health")
def health():
    return {"status": "ok", "application": APP_NAME, "version": app.version}
