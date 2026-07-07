from __future__ import annotations

import gzip
import json
import re
import zlib
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

SALES_RETENTION_DAYS = 30
SALES_PERIOD_HOURS = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24}


def group_sales_by_type(sales: list) -> dict:
    """Agrupa vendas por tipo de moeda (ROPS, ZENY, RMT)."""
    grouped = {"rops": [], "zeny": [], "rmt": []}
    for sale in sales:
        sale_type = (sale.get("sale_type") or "").lower()
        if "rmt" in sale_type:
            grouped["rmt"].append(sale)
        elif "rops" in sale_type:
            grouped["rops"].append(sale)
        elif "zeny" in sale_type or not sale_type:
            grouped["zeny"].append(sale)
        else:
            grouped["zeny"].append(sale)
    return grouped


def sale_timestamp_str(sale: dict) -> str:
    return str(sale.get("sale_date") or sale.get("timestamp") or "").strip()


def parse_sale_datetime(sale: dict) -> Optional[datetime]:
    raw = sale_timestamp_str(sale)
    if not raw:
        return None
    normalized = raw.replace("T", " ").strip()
    for fmt, size in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(normalized[:size], fmt)
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", normalized)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    m_br = re.match(r"(\d{2})/(\d{2})/(\d{4})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?", normalized)
    if m_br:
        time_part = m_br.group(4) or "00:00:00"
        if len(time_part) == 5:
            time_part += ":00"
        try:
            return datetime.strptime(f"{m_br.group(3)}-{m_br.group(2)}-{m_br.group(1)} {time_part}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    if normalized.isdigit():
        try:
            ts = int(normalized)
            if ts > 1_000_000_000_000:
                ts //= 1000
            if ts > 1_000_000_000:
                return datetime.fromtimestamp(ts)
        except (ValueError, OSError, OverflowError):
            pass
    return None


def normalize_sale_record(sale: dict) -> dict:
    ts = sale_timestamp_str(sale)
    if not ts:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        price = float(sale.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    try:
        quantity = int(sale.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    return {
        "timestamp": ts,
        "price": price,
        "seller_name": str(sale.get("seller_name") or "Shop"),
        "buyer_name": str(sale.get("buyer_name") or "Comprador"),
        "quantity": quantity,
        "sale_type": str(sale.get("sale_type") or ""),
    }


def sale_dedup_key(sale: dict) -> tuple:
    norm = normalize_sale_record(sale)
    ts = norm["timestamp"][:19]
    st = (norm["sale_type"] or "").lower()
    return (ts, st, norm["price"], norm["seller_name"], norm["buyer_name"], norm["quantity"])


def local_sale_to_api(sale: dict) -> dict:
    norm = normalize_sale_record(sale)
    return {
        "sale_date": norm["timestamp"],
        "price": norm["price"],
        "seller_name": norm["seller_name"],
        "buyer_name": norm["buyer_name"],
        "quantity": norm["quantity"],
        "sale_type": norm["sale_type"],
    }


def prune_sales_older_than(
    sales: list,
    *,
    days: int = SALES_RETENTION_DAYS,
    now: Optional[datetime] = None,
) -> list:
    """Remove vendas com data anterior a ``days`` dias (retenção máxima)."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    kept = []
    for s in sales or []:
        dt = parse_sale_datetime(s)
        if dt is None or dt >= cutoff:
            kept.append(s)
    return kept


def merge_sales_history(
    existing: list,
    incoming: list,
    *,
    retention_days: int = SALES_RETENTION_DAYS,
) -> list:
    """Funde vendas locais com novas entradas, deduplica e aplica retenção."""
    combined = []
    seen: set[tuple] = set()
    for raw in list(existing or []) + list(incoming or []):
        norm = normalize_sale_record(raw)
        key = sale_dedup_key(norm)
        if key in seen:
            continue
        seen.add(key)
        combined.append(norm)
    combined.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return prune_sales_older_than(combined, days=retention_days)


def filter_sales_by_period(
    sales: list,
    period: str,
    *,
    now: Optional[datetime] = None,
) -> list:
    """Filtra vendas dentro da janela ``24h``, ``7d`` ou ``30d``."""
    now = now or datetime.now()
    hours = SALES_PERIOD_HOURS.get(str(period or "30d").lower(), 30 * 24)
    cutoff = now - timedelta(hours=hours)
    out = []
    for s in sales or []:
        dt = parse_sale_datetime(s)
        if dt is None:
            out.append(s)
        elif dt >= cutoff:
            out.append(s)
    return out


def calculate_stats(sales: list) -> dict:
    """Calcula estatísticas de preço para uma lista de vendas."""
    if not sales:
        return {"último": 0, "mínimo": 0, "máximo": 0, "média": 0, "total": 0, "quantidade": len(sales)}

    ordered = sorted(sales, key=sale_timestamp_str, reverse=True)
    prices = [s.get("price", 0) for s in ordered]
    prices = [p for p in prices if p > 0]

    if not prices:
        return {"último": 0, "mínimo": 0, "máximo": 0, "média": 0, "total": 0, "quantidade": len(sales)}

    return {
        "último": prices[0],
        "mínimo": min(prices),
        "máximo": max(prices),
        "média": int(sum(prices) / len(prices)),
        "total": sum(prices),
        "quantidade": len(sales),
    }


def alert_min_refinement(alert: dict):
    """Refino mínimo configurado no alerta (int) ou None = qualquer refino."""
    want = alert.get("refinement") if isinstance(alert, dict) else None
    if want is None or want == "":
        return None
    try:
        return int(want)
    except (TypeError, ValueError):
        return None


def sale_min_prices_from_stores(stores: list, *, min_refinement=None) -> dict:
    """Menor preço por moeda nas lojas (zeny, rops, rmt, hero_points)."""
    best: dict = {}
    for store in stores or []:
        if min_refinement is not None:
            try:
                ref = int(store.get("refinement") or store.get("refine") or store.get("enhancement") or 0)
            except (TypeError, ValueError):
                ref = 0
            if ref < int(min_refinement):
                continue
        st = (store.get("sale_type") or "zeny").lower()
        if "hero" in st and "point" in st:
            key = "hero_points"
        elif "hero" in st:
            continue
        elif st in ("rmt", "rm", "rm$", "m") or "rmt" in st:
            key = "rmt"
        elif "rops" in st or st in ("rp", "r$"):
            key = "rops"
        elif st in ("zeny", "z", "z$"):
            key = "zeny"
        else:
            key = "zeny"
        try:
            price = float(store.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if key not in best or price < best[key]:
            best[key] = price
    return best


def format_home_min_prices_for_monitored(m: dict, *, fmt_price_stores: Callable[[object], str]) -> str:
    mp = m.get("min_prices") or {}
    if isinstance(mp, dict) and len(mp) > 0:
        parts = []
        if "zeny" in mp:
            parts.append(f"{fmt_price_stores(mp['zeny'])} Z")
        if "rops" in mp:
            parts.append(f"{fmt_price_stores(mp['rops'])} R$ ROPS")
        if "rmt" in mp:
            parts.append(f"{fmt_price_stores(mp['rmt'])} R$ RMT")
        if "hero_points" in mp:
            parts.append(f"{fmt_price_stores(mp['hero_points'])} HP")
        return "Menores agora: " + "  ·  ".join(parts)
    if m.get("home_prices_updated_at"):
        return "Sem lojas online neste momento."
    lp = m.get("last_price")
    try:
        if lp is not None and float(lp) > 0:
            return f"Último preço guardado: {fmt_price_stores(lp)} Z"
    except (TypeError, ValueError):
        pass
    return "Preços: clique em «Atualizar Preços»"


def monitored_static_incomplete(m: dict) -> bool:
    if not str(m.get("name") or "").strip():
        return True
    if m.get("id") is None:
        return True
    if not str(m.get("item_icon_url") or "").strip():
        return True
    return False


def mh_last_prices_update_label(monitored: list) -> str:
    latest = None
    for m in monitored or []:
        raw = m.get("home_prices_updated_at")
        if not raw:
            continue
        try:
            if isinstance(raw, str) and len(raw) >= 16:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00")[:19])
            else:
                continue
        except (TypeError, ValueError):
            continue
        if latest is None or dt > latest:
            latest = dt
    if latest is None:
        return "Ainda sem atualização de preços"
    return f"Atualizado às {latest.strftime('%H:%M')}"


def item_matches_search(entry: dict, query: str, *, mvp_catalog_matches_search_fn: Callable[[dict, str], bool]) -> bool:
    """Filtro por nome ou ID com a mesma regra usada no Timer MVP."""
    if not isinstance(entry, dict):
        return False
    stub = {
        "id": entry.get("id") if entry.get("id") is not None else entry.get("item_id"),
        "name": (entry.get("name") or entry.get("item_name") or ""),
    }
    return mvp_catalog_matches_search_fn(stub, query)


def clean_json_response(text: str, content: bytes = None, *, logger=None) -> str:
    """Remove compressão, BOM e caracteres inválidos do início da resposta."""
    if content:
        if content[:1] == b"\x78" or content[:2] == b"\x78\x9c":
            if logger:
                logger.info("Detectado conteúdo deflate, decompactando...")
            try:
                decompressed = zlib.decompress(content)
                text = decompressed.decode("utf-8")
                if logger:
                    logger.info("Deflate decompactado com sucesso")
            except Exception as e:
                if logger:
                    logger.warning(f"Falha ao descomprimir deflate: {e}")
        elif content[:2] == b"\x1f\x8b":
            if logger:
                logger.info("Detectado conteúdo gzip, decompactando...")
            try:
                decompressed = gzip.decompress(content)
                text = decompressed.decode("utf-8")
                if logger:
                    logger.info("Gzip decompactado com sucesso")
            except Exception as e:
                if logger:
                    logger.warning(f"Falha ao descomprimir gzip: {e}")
        elif content[0] < 32 and content[0] != ord("\n"):
            if logger:
                logger.warning(f"Bytes estranhos detectados no início: {content[:10]}")
            for i, byte in enumerate(content):
                if chr(byte) in "{[":
                    if logger:
                        logger.info(f"Encontrado JSON válido no byte {i}, usando dali em diante")
                    text = content[i:].decode("utf-8", errors="ignore")
                    break

    text = text.lstrip("\ufeff").strip()
    return text
