"""
Sessão autenticada do site Hero Saga (cookie fluxSessionData após login Discord).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import requests

from app_settings import load_settings, save_settings
from core.constants import BASE_URL

logger = logging.getLogger(__name__)

LOGIN_URL = f"{BASE_URL}/?module=discord&action=login"
SESSION_COOKIE_NAME = "fluxSessionData"
_HEROSAGA_HOSTS = ("rpgherosaga.com", "herosaga.com.br")


class HerosagaAuthRequired(Exception):
    """O site exige sessão Discord válida (cookie fluxSessionData)."""


def is_herosaga_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _HEROSAGA_HOSTS)


def _cookie_value(cookie: Any) -> str:
    if cookie is None:
        return ""
    if isinstance(cookie, dict):
        return str(cookie.get("value") or "").strip()
    # pywebview devolve http.cookies.SimpleCookie (um nome por item)
    try:
        from http.cookies import SimpleCookie

        if isinstance(cookie, SimpleCookie):
            for key in cookie.keys():
                if key == SESSION_COOKIE_NAME:
                    return str(cookie[key].value or "").strip()
    except Exception:
        pass
    return str(getattr(cookie, "value", "") or "").strip()


def _cookie_name(cookie: Any) -> str:
    if isinstance(cookie, dict):
        return str(cookie.get("name") or "")
    try:
        from http.cookies import SimpleCookie

        if isinstance(cookie, SimpleCookie):
            keys = list(cookie.keys())
            if len(keys) == 1:
                return str(keys[0])
            if SESSION_COOKIE_NAME in cookie:
                return SESSION_COOKIE_NAME
    except Exception:
        pass
    return str(getattr(cookie, "name", "") or "")


def find_flux_session_cookie(cookies: Iterable[Any]) -> Optional[str]:
    for c in cookies or []:
        try:
            from http.cookies import SimpleCookie

            if isinstance(c, SimpleCookie):
                if SESSION_COOKIE_NAME in c:
                    val = str(c[SESSION_COOKIE_NAME].value or "").strip()
                    if val:
                        return val
                continue
        except Exception:
            pass
        if _cookie_name(c) == SESSION_COOKIE_NAME:
            val = _cookie_value(c)
            if val:
                return val
    return None


def get_stored_session_cookie() -> str:
    return str(load_settings().get("herosaga_session_cookie") or "").strip()


def has_stored_session() -> bool:
    return bool(get_stored_session_cookie())


def save_session_cookie(value: str) -> None:
    val = str(value or "").strip()
    data = load_settings()
    data["herosaga_session_cookie"] = val
    data["herosaga_session_saved_at"] = (
        datetime.now(timezone.utc).isoformat() if val else ""
    )
    save_settings(data)
    logger.info("Sessão Hero Saga %s", "guardada" if val else "removida")


def clear_session_cookie() -> None:
    save_session_cookie("")


def apply_session_to_scraper(scraper) -> None:
    cookie = get_stored_session_cookie()
    if not cookie:
        return
    try:
        scraper.cookies.set(SESSION_COOKIE_NAME, cookie, domain="rpgherosaga.com", path="/")
    except Exception:
        pass
    try:
        scraper.cookies.set(SESSION_COOKIE_NAME, cookie, domain=".rpgherosaga.com", path="/")
    except Exception:
        pass


def _location_indicates_discord_auth(location: str) -> bool:
    loc = (location or "").lower()
    return "module=discord" in loc and ("action=login" in loc or "action=callback" in loc)


def response_requires_auth(response) -> bool:
    if response is None:
        return False
    status = int(getattr(response, "status_code", 0) or 0)
    if status in (301, 302, 303, 307, 308):
        loc = response.headers.get("Location") or response.headers.get("location") or ""
        if _location_indicates_discord_auth(loc):
            return True
    if status == 401:
        return True
    text = (getattr(response, "text", "") or "")[:1200].lower()
    if "discord.com/oauth" in text or "discord.com/api/oauth2" in text:
        return True
    if status == 200 and "module=discord" in text and "action=login" in text:
        return True
    return False


def check_response_auth(response) -> None:
    if response_requires_auth(response):
        raise HerosagaAuthRequired(
            "Sessão Discord expirada ou ausente. Conecte novamente para consultar o site."
        )


def auth_error_payload(message: str | None = None) -> dict:
    msg = message or "Conecte sua conta Discord para consultar o site Hero Saga."
    return {
        "ok": False,
        "discord_auth_required": True,
        "connected": False,
        "error": msg,
    }


def verify_session(*, scraper, timeout: float = 15.0) -> dict:
    """Testa se a sessão guardada consegue aceder ao vending search."""
    if not has_stored_session():
        return {
            "ok": True,
            "connected": False,
            "auth_required": True,
            "message": "Nenhuma sessão Discord guardada.",
        }
    apply_session_to_scraper(scraper)
    url = f"{BASE_URL}/?module=vending&action=search&item_search=elunium"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/",
    }
    try:
        response = scraper.get(url, headers=headers, timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "connected": False,
            "error": f"Erro de rede: {exc}",
            "message": f"Erro de rede: {exc}",
        }
    if response_requires_auth(response):
        return {
            "ok": True,
            "connected": False,
            "auth_required": True,
            "message": "Sessão expirada. Conecte o Discord novamente.",
        }
    if response.status_code != 200:
        return {
            "ok": False,
            "connected": False,
            "error": f"Site respondeu HTTP {response.status_code}.",
            "message": f"Site respondeu HTTP {response.status_code}.",
        }
    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "connected": False,
            "error": "Resposta inválida do site (não é JSON).",
            "message": "Resposta inválida do site.",
        }
    if not isinstance(payload, dict):
        return {"ok": False, "connected": False, "error": "Resposta inesperada.", "message": "Resposta inesperada."}
    return {
        "ok": True,
        "connected": True,
        "auth_required": False,
        "message": "Conexão com o site Hero Saga OK.",
        "sample_results": len(payload.get("results") or []),
    }


def get_discord_status(*, scraper, probe: bool = True) -> dict:
    saved_at = str(load_settings().get("herosaga_session_saved_at") or "").strip()
    if not has_stored_session():
        return {
            "ok": True,
            "connected": False,
            "has_session": False,
            "saved_at": saved_at,
            "message": "Discord não conectado.",
        }
    if not probe:
        return {
            "ok": True,
            "connected": True,
            "has_session": True,
            "saved_at": saved_at,
            "message": "Sessão guardada (não verificada).",
        }
    probe_result = verify_session(scraper=scraper)
    return {
        "ok": probe_result.get("ok", True),
        "connected": bool(probe_result.get("connected")),
        "has_session": True,
        "auth_required": bool(probe_result.get("auth_required")),
        "saved_at": saved_at,
        "message": probe_result.get("message") or "",
        "error": probe_result.get("error"),
        "sample_results": probe_result.get("sample_results"),
    }
