"""
Janela PyWebView para login Discord no site Hero Saga e captura do cookie de sessão.
"""

from __future__ import annotations

import logging
import threading
import time

import webview

from adapters.herosaga_session import (
    LOGIN_URL,
    SESSION_COOKIE_NAME,
    find_flux_session_cookie,
    save_session_cookie,
    verify_session,
)
from adapters.network import scraper

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SEC = 0.35
_LOGIN_TIMEOUT_SEC = 300
_STARTUP_DELAY_SEC = 0.8


def _flux_from_document_cookie(raw: str) -> str:
    for part in str(raw or "").split(";"):
        part = part.strip()
        if part.startswith(f"{SESSION_COOKIE_NAME}="):
            return part.split("=", 1)[1].strip()
    return ""


def _login_success(url: str, flux_cookie: str) -> bool:
    if not flux_cookie or len(flux_cookie) < 8:
        return False
    u = (url or "").lower()
    if "discord.com" in u:
        return False
    if "rpgherosaga.com" in u or "herosaga.com.br" in u:
        if "module=discord" in u and "action=login" in u:
            return False
        return True
    # Cookie válido guardado pelo domínio — aceitar se a verificação HTTP passar
    return True


def _try_capture_session(win, result: dict) -> bool:
    """Tenta ler cookie da janela de login. Devolve True se sessão guardada."""
    try:
        url = win.get_current_url() or ""
        cookies = win.get_cookies() or []
        flux = find_flux_session_cookie(cookies)

        if not flux:
            try:
                doc_cookie = win.evaluate_js("document.cookie") or ""
                flux = _flux_from_document_cookie(doc_cookie)
            except Exception as exc:
                logger.debug("document.cookie fallback: %s", exc)

        logger.info(
            "Discord login check url=%r flux=%s cookies=%d",
            url[:120] if url else "",
            bool(flux),
            len(cookies),
        )

        if not flux or not _login_success(url, flux):
            return False

        save_session_cookie(flux)
        probe = verify_session(scraper=scraper)
        if not probe.get("connected"):
            logger.warning("Cookie capturado mas verificação falhou: %s", probe)
            return False

        result["ok"] = True
        result["connected"] = True
        result["message"] = probe.get("message") or "Discord conectado com sucesso."
        result["verify"] = probe
        return True
    except Exception as exc:
        logger.warning("try_capture_session: %s", exc, exc_info=True)
        return False


def open_discord_login_window() -> dict:
    """
    Abre janela de login e bloqueia até concluir OAuth ou o utilizador fechar.
    Devolve ``{ok, connected, error, message}``.
    """
    result: dict = {
        "ok": False,
        "connected": False,
        "error": None,
        "message": "",
    }
    finished = threading.Event()
    user_closed = threading.Event()
    win_holder: dict = {"win": None}

    def finish_success() -> None:
        finished.set()

    def on_closed() -> None:
        user_closed.set()
        win = win_holder.get("win")
        if win and not result["ok"]:
            if _try_capture_session(win, result):
                try:
                    win.destroy()
                except Exception:
                    pass
        if not result["ok"] and not result.get("error"):
            result["error"] = "Login cancelado ou não concluído."
        finished.set()

    def on_loaded() -> None:
        win = win_holder.get("win")
        if not win or result["ok"] or user_closed.is_set():
            return
        if _try_capture_session(win, result):
            finish_success()
            try:
                win.destroy()
            except Exception:
                pass

    try:
        win = webview.create_window(
            "Conectar Discord — Hero Saga",
            url=LOGIN_URL,
            width=520,
            height=760,
            resizable=True,
            background_color="#5865F2",
        )
        win_holder["win"] = win
    except Exception as exc:
        logger.exception("Falha ao abrir janela Discord")
        result["error"] = str(exc)
        return result

    win.events.closed += on_closed
    win.events.loaded += on_loaded

    def poll_login() -> None:
        time.sleep(_STARTUP_DELAY_SEC)
        deadline = time.time() + _LOGIN_TIMEOUT_SEC
        win = win_holder.get("win")
        while (
            win
            and time.time() < deadline
            and not finished.is_set()
            and not user_closed.is_set()
        ):
            if _try_capture_session(win, result):
                finish_success()
                try:
                    win.destroy()
                except Exception:
                    pass
                return
            time.sleep(_POLL_INTERVAL_SEC)

        if not result["ok"] and not user_closed.is_set():
            result["error"] = result.get("error") or "Tempo esgotado. Tente conectar novamente."
        finished.set()

    threading.Thread(target=poll_login, daemon=True, name="discord-login-poll").start()
    finished.wait(_LOGIN_TIMEOUT_SEC + 30)

    if result["ok"]:
        return result
    if not result.get("error"):
        result["error"] = "Não foi possível concluir o login."
    return result
