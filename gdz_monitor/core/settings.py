"""
Configurações globais do GDZ Monitor (SMTP, e-mail, início com Windows).
"""

import json
import os
import sys

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), "herosaga_monitor_settings.json")

DEFAULT_SETTINGS = {
    "notify_email": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_use_tls": True,
    "alert_interval_seconds": 300,
    "start_with_windows": False,
    "ui_theme": "dark",
    # Home (Buscar): colunas horizontais por categoria — largura mínima (px) e
    # quantas colunas tentar «caber» na largura da janela (afecta o redimensionamento).
    "monitor_home_col_min_width": 260,
    "monitor_home_min_visible_cols": 3,
    "last_build_sim_saved_id": "",
    "primary_build_sim_saved_id": "",
    # Divine Pride — https://www.divine-pride.net/api (opcional)
    "divine_pride_api_key": "",
    # iRO = International RO (inglês + dados internacionais na API). Outros: bRO, etc.
    "divine_pride_server": "iRO",
    # Hero Saga — sessão Discord (cookie fluxSessionData após login em rpgherosaga.com)
    "herosaga_session_cookie": "",
    "herosaga_session_saved_at": "",
    # Som ao terminar contagem MVP (tocado pelo frontend)
    "mvp_alert_sound_path": r"C:\Users\Ricardo\Desktop\Som\Alerta de Som.mp3",
}


def load_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                out.update(data)
        except Exception:
            pass
    try:
        out["smtp_port"] = int(out.get("smtp_port") or 587)
    except (TypeError, ValueError):
        out["smtp_port"] = 587
    try:
        out["alert_interval_seconds"] = max(60, int(out.get("alert_interval_seconds") or 300))
    except (TypeError, ValueError):
        out["alert_interval_seconds"] = 300
    out["smtp_use_tls"] = bool(out.get("smtp_use_tls", True))
    out["start_with_windows"] = bool(out.get("start_with_windows", False))
    ut = (out.get("ui_theme") or "dark").strip().lower()
    out["ui_theme"] = "light" if ut == "light" else "dark"
    try:
        mw = int(out.get("monitor_home_col_min_width") or 260)
    except (TypeError, ValueError):
        mw = 260
    out["monitor_home_col_min_width"] = max(160, min(600, mw))
    try:
        mv = int(out.get("monitor_home_min_visible_cols") or 3)
    except (TypeError, ValueError):
        mv = 3
    out["monitor_home_min_visible_cols"] = max(1, min(8, mv))
    out["last_build_sim_saved_id"] = str(out.get("last_build_sim_saved_id") or "").strip()
    out["primary_build_sim_saved_id"] = str(out.get("primary_build_sim_saved_id") or "").strip()
    out["divine_pride_api_key"] = str(out.get("divine_pride_api_key") or "").strip()
    dp_srv = str(out.get("divine_pride_server") or "").strip()
    out["divine_pride_server"] = dp_srv if dp_srv else "iRO"
    out["mvp_alert_sound_path"] = str(out.get("mvp_alert_sound_path") or "").strip()
    out["herosaga_session_cookie"] = str(out.get("herosaga_session_cookie") or "").strip()
    out["herosaga_session_saved_at"] = str(out.get("herosaga_session_saved_at") or "").strip()
    return out


def save_settings(settings: dict) -> None:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)


def _autostart_command() -> str:
    """Linha de comando para colocar no Registro (Windows)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    py = sys.executable
    return f'"{py}" "{script}"'


from typing import Tuple


def set_windows_autostart(enable: bool) -> Tuple[bool, str]:
    """
    Regista ou remove entrada em HKCU ... Run.
    Devolve (ok, mensagem).
    """
    if sys.platform != "win32":
        return False, "Disponível apenas no Windows."

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "GDZMonitor"

    try:
        import winreg

        if enable:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE
            )
            try:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, _autostart_command())
            finally:
                winreg.CloseKey(key)
            return True, "O programa será iniciado com o Windows."
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE
        )
        try:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        finally:
            winreg.CloseKey(key)
        return True, "Início automático desativado."
    except Exception as e:
        return False, str(e)
