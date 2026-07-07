"""
Lógica de verificação de alertas de preço (filtro por moeda, condição, loja).
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Mesmo ficheiro que app_runtime (histórico de vendas/preços por item).
PRICES_HISTORY_FILE = os.path.join(os.path.expanduser("~"), "herosaga_prices_history.json")

FetchStoresFn = Callable[[int, str], Tuple[List[dict], dict]]


def _fmt_price(p) -> str:
    try:
        x = float(p)
        if abs(x - round(x)) < 1e-9:
            return f"{int(round(x)):,}".replace(",", ".")
        s = f"{x:.8f}".rstrip("0").rstrip(".")
        return s if s else "0"
    except Exception:
        return str(p)


def _refinement(s: dict) -> int:
    try:
        return int(s.get("refinement") or s.get("refine") or s.get("enhancement") or 0)
    except (TypeError, ValueError):
        return 0


def filter_stores_by_refinement(stores: List[dict], alert: dict) -> List[dict]:
    """Se o alerta define refinement (int), só considera lojas com refino >= a esse valor."""
    want = alert.get("refinement")
    if want is None or want == "":
        return stores
    try:
        want = int(want)
    except (TypeError, ValueError):
        return stores
    return [s for s in stores if _refinement(s) >= want]


def filter_history_entries_by_refinement(entries: List[dict], alert: dict) -> List[dict]:
    """Como filter_stores_by_refinement, mas entradas sem campo de refino no JSON mantêm-se (API antiga)."""
    want = alert.get("refinement")
    if want is None or want == "":
        return entries
    try:
        want = int(want)
    except (TypeError, ValueError):
        return entries
    out: List[dict] = []
    for e in entries:
        if not any(k in e for k in ("refinement", "refine", "enhancement")):
            out.append(e)
        elif _refinement(e) >= want:
            out.append(e)
    return out


def filter_stores_by_currency(stores: List[dict], wanted: str) -> List[dict]:
    w = (wanted or "zeny").lower()
    out: List[dict] = []
    for s in stores:
        st = (s.get("sale_type") or "zeny").lower()
        if w == "zeny" and st in ("zeny", "z", "z$"):
            out.append(s)
        elif w == "rops" and st in ("rops", "rp", "r$"):
            out.append(s)
        elif w == "rmt":
            if "hero" in st:
                continue
            if st in ("rmt", "rm", "rm$", "m") or "rmt" in st:
                out.append(s)
        elif w == "hero_points" and ("hero" in st and "point" in st):
            out.append(s)
    return out


def filter_history_entries_by_currency(entries: List[dict], wanted: str) -> List[dict]:
    """Filtra entradas do ficheiro de histórico pela mesma moeda do alerta (como nas lojas)."""
    w = (wanted or "zeny").lower()
    out: List[dict] = []
    for s in entries:
        st = (s.get("sale_type") or "").lower()
        if not st:
            if w == "zeny":
                out.append(s)
            continue
        if w == "zeny" and st in ("zeny", "z", "z$"):
            out.append(s)
        elif w == "rops" and st in ("rops", "rp", "r$"):
            out.append(s)
        elif w == "rmt":
            if "hero" in st:
                continue
            if st in ("rmt", "rm", "rm$", "m") or "rmt" in st:
                out.append(s)
        elif w == "hero_points" and ("hero" in st and "point" in st):
            out.append(s)
    return out


def _load_prices_history_raw() -> dict:
    if os.path.exists(PRICES_HISTORY_FILE):
        try:
            with open(PRICES_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.debug("Histórico de preços: leitura falhou: %s", e)
    return {}


def _history_entries_for_item(item_id: int) -> List[dict]:
    raw = _load_prices_history_raw().get(str(int(item_id)))
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _mean_positive(prices: List[float]) -> Optional[float]:
    vals = [p for p in prices if p and p > 0]
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def _listing_stats(filtered_stores: List[dict]) -> Tuple[Optional[float], int]:
    """Preço médio das ofertas que passam nos filtros e quantidade de ofertas."""
    prices = [_price(s) for s in filtered_stores if _price(s) > 0]
    m = _mean_positive(prices)
    return m, len(prices)


def _history_stats_for_alert(item_id: int, alert: dict) -> Dict[str, Any]:
    """
    Média e última venda a partir do histórico local (mesma moeda + refino do alerta,
    quando o campo refino existir na entrada; caso contrário a entrada conta para a média).
    """
    entries = _history_entries_for_item(item_id)
    entries = filter_history_entries_by_currency(entries, str(alert.get("sale_type") or "zeny"))
    entries = filter_history_entries_by_refinement(entries, alert)
    dated: List[Tuple[str, float]] = []
    for e in entries:
        p = _price(e)
        if p <= 0:
            continue
        dt = (e.get("timestamp") or e.get("sale_date") or "").strip()
        dated.append((dt, p))
    if not dated:
        return {"n": 0, "avg": None, "last": None, "last_dt": None}
    dated.sort(key=lambda x: x[0], reverse=True)
    last_dt, last_p = dated[0]
    avg = sum(p for _, p in dated) / float(len(dated))
    return {"n": len(dated), "avg": avg, "last": last_p, "last_dt": last_dt}


def _price(s: dict) -> float:
    try:
        v = s.get("price") or s.get("sell_price") or s.get("valor") or 0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def qualifying_stores_for_alert(alert: dict, filtered: List[dict]) -> List[dict]:
    """Ofertas que já cumprem o limiar do alerta (abaixo de / acima de), com preço > 0."""
    try:
        threshold = float(alert.get("price") or 0)
    except (TypeError, ValueError):
        threshold = 0.0
    kind = (alert.get("type") or "below").lower()
    out: List[dict] = []
    for s in filtered:
        p = _price(s)
        if p <= 0:
            continue
        if kind == "below":
            if p <= threshold:
                out.append(s)
        else:
            if p >= threshold:
                out.append(s)
    return out


def listing_fingerprint(store: dict) -> str:
    """Identifica uma listagem para não repetir notificação (loja + preço + refino + qtd + moeda)."""
    name = (store.get("char_name") or store.get("seller_name") or store.get("owner") or "").strip().lower()
    if not name:
        name = "?"
    ref = _refinement(store)
    try:
        amt = int(store.get("amount") or store.get("quantity") or 1)
    except (TypeError, ValueError):
        amt = 1
    p = _price(store)
    st = (store.get("sale_type") or "").lower()
    # Preço com estabilidade em JSON (evita 10.0000001 vs 10)
    try:
        if abs(p - round(p)) < 1e-6:
            ps = str(int(round(p)))
        else:
            ps = f"{p:.6f}".rstrip("0").rstrip(".")
    except Exception:
        ps = str(p)
    return f"{name}|r{ref}|q{amt}|p{ps}|{st}"


_MAX_SEEN_KEYS = 500


def condition_is_met(alert: dict, stores: List[dict]) -> bool:
    return len(qualifying_stores_for_alert(alert, stores)) > 0


def pick_store_for_notification(alert: dict, stores: List[dict]) -> Optional[dict]:
    if not stores:
        return None
    kind = (alert.get("type") or "below").lower()
    if kind == "below":
        return min(stores, key=_price)
    return max(stores, key=_price)


def build_email_body(alert: dict, store: dict, extra: Optional[Dict[str, Any]] = None) -> str:
    item_name = alert.get("item_name") or "Item"
    try:
        iid = int(alert.get("item_id") or 0)
    except (TypeError, ValueError):
        iid = 0
    shop = store.get("char_name") or store.get("seller_name") or "Loja"
    price = _price(store)
    ref = _refinement(store)
    sale = (store.get("sale_type") or "zeny").lower()
    ptxt = _fmt_price(price)
    ttxt = _fmt_price(alert.get("price", 0))
    cond = "cair abaixo de" if alert.get("type") == "below" else "subir acima de"
    lines = [
        "Alerta — GDZ Monitor",
        "",
        f"Item: {item_name}",
        f"ID do item: {iid}" if iid else "ID do item: —",
        f"Loja (oferta que disparou o alerta): {shop}",
        f"Preço dessa oferta: {ptxt}",
        f"Refino dessa oferta: +{ref}",
        f"Tipo de venda (oferta): {sale}",
        "",
        f"O seu alerta: {cond} {ttxt}.",
    ]
    rw = alert.get("refinement")
    if rw is not None and rw != "":
        try:
            lines.insert(-2, f"Filtro do alerta: refino +{int(rw)} ou superior.")
        except (TypeError, ValueError):
            pass

    if extra:
        lav = extra.get("listing_avg")
        ln = int(extra.get("listing_n") or 0)
        if lav is not None and ln > 0:
            lines.extend(
                [
                    "",
                    f"Preço médio nas lojas (ofertas que cumprem o filtro do alerta, n={ln}): {_fmt_price(lav)}",
                ]
            )
        hs = extra.get("history") or {}
        hn = int(hs.get("n") or 0)
        if hn > 0:
            lines.extend(
                [
                    "",
                    "Histórico local de vendas (mesmo tipo de moeda; refino do alerta só aplica quando a entrada tem refino):",
                    f"  · Preço médio das vendas (n={hn}): {_fmt_price(hs.get('avg'))}",
                    f"  · Última venda registada: {_fmt_price(hs.get('last'))}"
                    + (
                        f" em {hs.get('last_dt')}"
                        if (hs.get("last_dt") or "").strip()
                        else ""
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "Histórico local de vendas: ainda sem entradas para este item e tipo de moeda",
                    "(abra o item na app para carregar o histórico do site, se quiser ver médias/última venda).",
                ]
            )
    return "\n".join(lines)


def send_alert_email(
    settings: dict,
    to_addr: str,
    subject: str,
    body: str,
) -> tuple:
    to_addr = (to_addr or "").strip()
    host = (settings.get("smtp_host") or "").strip()
    if not to_addr:
        return False, "E-mail de destino vazio."
    if not host:
        return False, "SMTP não configurado (host vazio). Use Configurações."

    port = int(settings.get("smtp_port") or 587)
    user = (settings.get("smtp_user") or "").strip()
    password = (settings.get("smtp_password") or "").strip()
    use_tls = bool(settings.get("smtp_use_tls", True))
    from_addr = user or to_addr

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    try:
        if use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, [to_addr], msg.as_string())
        return True, ""
    except Exception as e:
        logger.exception("Falha ao enviar e-mail de alerta")
        return False, str(e)


def run_alert_pass(
    alerts: Dict[str, dict],
    settings: dict,
    fetch_stores: FetchStoresFn,
) -> Tuple[List[dict], Dict[str, dict]]:
    events: List[dict] = []
    state_updates: Dict[str, dict] = {}

    for key, alert in list(alerts.items()):
        try:
            item_id = int(alert.get("item_id", 0))
        except (TypeError, ValueError):
            continue
        if item_id <= 0:
            continue

        try:
            stores, _ = fetch_stores(item_id, str(alert.get("item_name") or ""))
        except Exception as e:
            logger.debug("Alerta %s: erro ao buscar lojas: %s", key, e)
            continue

        sale_want = alert.get("sale_type") or "zeny"
        filtered = filter_stores_by_currency(stores, sale_want)
        filtered = filter_stores_by_refinement(filtered, alert)
        qual = qualifying_stores_for_alert(alert, filtered)
        met = len(qual) > 0

        seen_raw = alert.get("notified_listing_keys", None)
        # Alertas antigos sem esta chave: uma vez sem notificação, preenche com o que já existe.
        if seen_raw is None:
            fps = [listing_fingerprint(s) for s in qual]
            if len(fps) > _MAX_SEEN_KEYS:
                fps = fps[-_MAX_SEEN_KEYS:]
            state_updates[key] = {"condition_met": met, "notified_listing_keys": fps}
            logger.debug(
                "Alerta %s: migração — %s ofertas já dentro do critério marcadas como vistas (sem pop-up).",
                key,
                len(fps),
            )
            continue

        seen_list = [x for x in seen_raw if isinstance(x, str)]
        seen_set = set(seen_list)
        new_seen = list(seen_list)

        listing_avg, listing_n = _listing_stats(filtered)
        hist = _history_stats_for_alert(item_id, alert)

        for store in qual:
            fp = listing_fingerprint(store)
            if fp in seen_set:
                continue
            seen_set.add(fp)
            new_seen.append(fp)
            events.append(
                {
                    "key": key,
                    "alert": alert,
                    "store": store,
                    "extra": {
                        "listing_avg": listing_avg,
                        "listing_n": listing_n,
                        "history": hist,
                    },
                }
            )
            logger.info(
                "Alerta %s: nova oferta dentro do critério — %s @ %s",
                key,
                fp.split("|")[0],
                _fmt_price(_price(store)),
            )

        if len(new_seen) > _MAX_SEEN_KEYS:
            new_seen = new_seen[-_MAX_SEEN_KEYS:]

        state_updates[key] = {"condition_met": met, "notified_listing_keys": new_seen}

    return events, state_updates
