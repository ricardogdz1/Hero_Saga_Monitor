"""
Alerta sonoro do timer MVP (respawn). No Windows reproduz MP3 via MCI (sem dependências extra).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Caminho por omissão; pode ser alterado em herosaga_monitor_settings.json («mvp_alert_sound_path»).
DEFAULT_MVP_ALERT_SOUND_PATH = r"C:\Users\Ricardo\Desktop\Som\Alerta de Som.mp3"

_MCI_ALIAS = "hs_mvp_alert"


def _fallback_system_beep() -> None:
    try:
        import winsound

        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # type: ignore
        except Exception:
            pass


def _play_mp3_mci_windows(path: str) -> bool:
    """Reproduz MP3 de forma assíncrona (MCI)."""
    try:
        import ctypes

        winmm = ctypes.windll.winmm
        winmm.mciSendStringW(f"close {_MCI_ALIAS}", None, 0, None)
        # Caminho absoluto entre aspas (espaços no nome do ficheiro).
        abs_path = os.path.abspath(path)
        err = winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias {_MCI_ALIAS}', None, 0, None)
        if err != 0:
            logger.debug("mci open falhou (%s): %s", err, abs_path)
            return False
        err = winmm.mciSendStringW(f"play {_MCI_ALIAS}", None, 0, None)
        if err != 0:
            logger.debug("mci play falhou (%s)", err)
            return False
        return True
    except Exception as ex:
        logger.debug("mci mp3: %s", ex)
        return False


def play_mvp_spawn_alert_sound(path: Optional[str] = None) -> None:
    """Toca o MP3 configurado; se falhar, beep do sistema."""
    fp = (path or "").strip() or DEFAULT_MVP_ALERT_SOUND_PATH
    if not os.path.isfile(fp):
        logger.warning("Ficheiro de alerta MVP inexistente: %s", fp)
        _fallback_system_beep()
        return
    if sys.platform == "win32" and _play_mp3_mci_windows(fp):
        return
    _fallback_system_beep()
