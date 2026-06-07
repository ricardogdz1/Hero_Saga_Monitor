from __future__ import annotations

import gzip
import json
import zlib
from datetime import datetime
from typing import Callable, Dict, Optional


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


def calculate_stats(sales: list) -> dict:
    """Calcula estatísticas de preço para uma lista de vendas."""
    if not sales:
        return {"último": 0, "mínimo": 0, "máximo": 0, "média": 0, "total": 0, "quantidade": len(sales)}

    prices = [s.get("price", 0) for s in sales]
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
