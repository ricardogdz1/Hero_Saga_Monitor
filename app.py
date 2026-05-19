"""
Herosaga Monitor — Aplicativo Desktop
Monitora preços e histórico de vendas do Hero Saga (herosaga.com.br)
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import threading
import time
import json
import os
from datetime import datetime
import logging
import zlib
import gzip
import sys
import re
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin
from collections import OrderedDict
from typing import Optional, Tuple

import requests
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import cloudscraper
from price_parse import parse_price_cell, coerce_price
from bs4 import BeautifulSoup

from alert_monitor import (
    run_alert_pass,
    send_alert_email,
    build_email_body,
    filter_stores_by_currency,
    filter_stores_by_refinement,
    qualifying_stores_for_alert,
    listing_fingerprint,
)
from app_settings import load_settings, save_settings, set_windows_autostart
from mvp_alert_sound import play_mvp_spawn_alert_sound
from item_icon_cache import read_item_icon_png_bytes
from build_simulator import (
    BUILD_SLOT_LEFT,
    BUILD_SLOT_RIGHT,
    SLOT_LABELS_PT,
    build_email_body_build_total,
    default_layer_state,
    default_slot_state,
    filter_stores_slot,
    item_meta_is_two_handed,
    load_builds_file,
    min_prices_from_stores,
    run_build_total_alerts,
    save_builds_file,
)

# ── NOVO: Importar módulo de scraping com BeautifulSoup ─────────────────────
try:
    from stores_scraper import (
        search_item_all_stores,
        get_herosaga_item_stores,
        HerosagaScraper,
        parse_item_card_from_soup,
    )
    SCRAPER_AVAILABLE = True
    logger_temp = logging.getLogger(__name__)
    logger_temp.info("✓ Módulo stores_scraper carregado com sucesso")
except ImportError as e:
    SCRAPER_AVAILABLE = False
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning(f"⚠️ Módulo stores_scraper não disponível: {e}")

    def parse_item_card_from_soup(soup):
        return {}

from divine_pride_api import fetch_monster
from image_loader import MvpImageLoader
from mvp_timer import (
    DIVINE_PRIDE_LIST_HEADERS,
    fetch_mvp_catalog_from_divine_pride,
    format_countdown_clock,
    build_mvp_map_click_mask_from_image,
    game_to_pixel_coords,
    mvp_map_display_layout,
    is_mvp_map_coord_clickable,
    load_mvp_catalog_cache,
    load_mvp_storage,
    monster_api_display_name,
    mvp_catalog_entry_skipped,
    mvp_catalog_matches_search,
    mvp_catalog_names_are_english_marked,
    mvp_dashboard_status_text,
    MVP_CATALOG_PORTABLE_FILE,
    MVP_DATA_FILE,
    MVP_MAPS_DIR,
    MVP_SPRITES_DIR,
    new_timer_entry,
    parse_user_datetime,
    pixel_to_game_coords,
    save_mvp_catalog_cache,
    resolve_map_image,
    save_mvp_storage,
    seconds_until_spawn,
    spawn_maps_from_monster,
    summarize_monster_for_timer,
)

# Minimapa MVP no diálogo «Editar»: área de visualização fixa (coordenadas nativas inalteradas).
_MVP_MAP_DISPLAY_BOX_W = 420
_MVP_MAP_DISPLAY_BOX_H = 420

_ITEM_CARD_KEYS = ("item_icon_url", "item_description", "item_weight", "item_card_title")

# Chaves alternativas em JSON antigo (ex.: «armadura» em vez de «armor»)
_BUILD_SIM_SLOT_LEGACY_SRC_KEYS = {
    "armor": ("armadura", "body", "chest", "coat"),
}


def _item_card_meta_from_details(details: dict) -> dict:
    if not details:
        return {}
    return {k: details[k] for k in _ITEM_CARD_KEYS if details.get(k)}

# ── Configuração de Logging ──────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.expanduser("~"), "herosaga_monitor.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("=" * 80)
logger.info("HEROSAGA MONITOR INICIADO")
logger.info(f"Arquivo de log: {LOG_FILE}")
logger.info("=" * 80)

# ── Configurações Atualizadas ────────────────────────────────────────────────
BASE_URL = "https://herosaga.com.br"


def _normalize_media_url(url) -> str:
    """Garante URL absoluta para ícones/imagens do site (evita falha no download)."""
    if not url:
        return ""
    u = str(url).strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE_URL + "/", u[1:])
    return u


DATA_FILE = os.path.join(os.path.expanduser("~"), "herosaga_monitor_data.json")

# Categorias padrão dos itens monitorados (home). «Gerais» não pode ser removida.
DEFAULT_MONITOR_CATEGORIES = (
    "Gerais",
    "Equipamentos",
    "Cartas",
    "Utilitários",
    "Consumíveis",
)

# Home monitorados: valores por omissão; a UI real usa ``load_settings()`` —
# ``monitor_home_col_min_width`` e ``monitor_home_min_visible_cols``.
MH_HOME_MIN_VISIBLE_CATEGORY_COLS = 3
MH_HOME_CATEGORY_COL_MIN_WIDTH = 260


def _ensure_monitor_structure(data: dict) -> dict:
    """Garante ``monitor_categories`` e ``category`` em cada item monitorado."""
    if not isinstance(data, dict):
        return {"monitored": [], "searches": [], "monitor_categories": list(DEFAULT_MONITOR_CATEGORIES)}
    if "searches" not in data:
        data["searches"] = []
    mc = data.get("monitor_categories")
    if not isinstance(mc, list) or not mc:
        data["monitor_categories"] = list(DEFAULT_MONITOR_CATEGORIES)
    else:
        cleaned = []
        seen = set()
        for x in mc:
            s = str(x).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        data["monitor_categories"] = cleaned if cleaned else list(DEFAULT_MONITOR_CATEGORIES)
    if "Gerais" not in data["monitor_categories"]:
        data["monitor_categories"].insert(0, "Gerais")
    valid = set(data["monitor_categories"])
    for m in data.get("monitored") or []:
        if not isinstance(m, dict):
            continue
        c = m.get("category")
        if not c or str(c).strip() not in valid:
            m["category"] = "Gerais"
        else:
            m["category"] = str(c).strip()
    return data
PRICES_HISTORY_FILE = os.path.join(os.path.expanduser("~"), "herosaga_prices_history.json")

# Headers mais completos para simular um navegador real
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://herosaga.com.br/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ── API COM SUPORTE ANTIBOT (CLOUDSCRAPER) ───────────────────────────────────
scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)

def api_search(name: str):
    """Busca items por nome no vending search."""
    url = f"{BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(name)}"
    
    try:
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://herosaga.com.br/'
        }
        
        response = scraper.get(url, headers=headers, timeout=15)

        if not response.text.strip():
            logger.warning(f"Empty response for search '{name}'")
            return []

        try:
            results = response.json().get("results", [])
            logger.info(f"Search '{name}' returned {len(results)} results")
            
            if results:
                logger.debug(f"Primeiro resultado: id={results[0].get('id')}, name={results[0].get('name')}")
            
            # ── NOVO: Para cada resultado, adiciona informação de lojas abertas ──
            if results:
                logger.info(f"🏪 Raspando informações de lojas abertas para {len(results)} itens...")
                for item in results[:10]:  # Apenas primeiros 10 para não sobrecarregar
                    try:
                        item_id = item.get('id')
                        if item_id:
                            stores, card_meta = get_stores_from_item_page(item_id, item.get('name', ''))
                            logger.debug(f"Card meta para {item.get('name')} ({item_id}): {card_meta}")
                            for _k, _v in card_meta.items():
                                if _v is not None and _v != "":
                                    item[_k] = _normalize_media_url(_v) if _k == "item_icon_url" else _v
                            if stores:
                                # Calcula preço mínimo das lojas abertas
                                prices_by_type = {}
                                for store in stores:
                                    sale_type = store.get('sale_type', 'zeny')
                                    price = store.get('price', 0)
                                    if sale_type not in prices_by_type or price < prices_by_type[sale_type]:
                                        prices_by_type[sale_type] = price
                                
                                # Adiciona ao resultado
                                item['online_stores'] = len(stores)
                                item['min_prices'] = prices_by_type
                                item['stores_list'] = stores  # NOVO: Guarda lista completa de lojas
                                logger.debug(f"✓ Item {item.get('name')}: {len(stores)} lojas, preços: {prices_by_type}")
                            else:
                                item['online_stores'] = 0
                                item['min_prices'] = {}
                                item['stores_list'] = []
                    except Exception as e:
                        import traceback
                        logger.debug(f"⚠️ Erro ao buscar lojas para item {item.get('id')} ({item.get('name')}): {str(e)}")
                        logger.debug(f"   Stacktrace: {traceback.format_exc()}")
                        item['online_stores'] = 0
                        item['min_prices'] = {}
                        item['stores_list'] = []
            
            return results
        except ValueError as e:
            logger.error(f"JSON decode error for '{name}': {str(e)}")
            return []
    
    except Exception as e:
        logger.error(f"Search error for '{name}': {str(e)}")
        return []


def api_search_item_names(query: str):
    """Resultados da busca vending só com metadados (sem raspar lojas). Útil para resolver nome por ID."""
    url = f"{BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(query)}"
    try:
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://herosaga.com.br/",
        }
        response = scraper.get(url, headers=headers, timeout=15)
        if not response.text.strip():
            return []
        return response.json().get("results", []) or []
    except Exception as e:
        logger.debug("api_search_item_names %r: %s", query, e)
        return []


def _sync_iwork_name_from_sources(iwork: dict, history_data) -> None:
    """Preenche ``iwork['name']`` a partir do card do site, histórico ou busca por ID (evita só «Item 123»)."""
    ct = (iwork.get("item_card_title") or "").strip()
    if ct:
        iwork["name"] = ct
        return
    cur = str(iwork.get("name") or "").strip()
    iid = iwork.get("id")
    try:
        iid_int = int(iid)
    except (TypeError, ValueError):
        iid_int = None
    generic = f"Item {iid_int}" if iid_int is not None else None
    if cur and generic and cur != generic and cur.lower() != generic.lower():
        return
    if isinstance(history_data, dict):
        for s in history_data.get("sales") or []:
            for key in ("item_name", "name"):
                n = (s.get(key) or "").strip()
                if n:
                    iwork["name"] = n
                    return
    if iid_int is None:
        return
    try:
        for it in api_search_item_names(str(iid_int)):
            if int(it.get("id", 0)) == iid_int and it.get("name"):
                iwork["name"] = str(it["name"]).strip()
                return
    except Exception as e:
        logger.debug("Resolver nome por ID %s: %s", iid_int, e)


def api_item_history(item_id: int):
    """
    Busca histórico de vendas/preços do item usando o endpoint correto.
    Tenta múltiplos tipos de venda: rops, zeny, rmt
    """
    logger.info(f"Fetching history for item ID: {item_id}")
    
    all_sales = []
    sale_types = ["rops", "zeny", "rmt"]
    
    for sale_type in sale_types:
        try:
            url = f"{BASE_URL}/?module=item&action=saleshistory&item_id={item_id}&sale_type={sale_type}"
            logger.info(f"Tentando {sale_type}: {url}")
            
            response = scraper.get(url, timeout=10)
            logger.debug(f"Status {sale_type}: {response.status_code}")
            
            if response.status_code == 200 and response.text.strip():
                try:
                    clean_text = clean_json_response(response.text, response.content)
                    data = json.loads(clean_text)
                    
                    if data.get("success") and data.get("sales"):
                        sales = data.get("sales", [])
                        logger.info(f"✓ {sale_type}: {len(sales)} vendas encontradas")
                        all_sales.extend(sales)
                        
                        logger.debug(f"Primeira venda de {sale_type}: {json.dumps(sales[0], ensure_ascii=False)}")
                except Exception as e:
                    logger.debug(f"Parse error para {sale_type}: {str(e)}")
        except Exception as e:
            logger.debug(f"Erro ao buscar {sale_type}: {str(e)}")
    
    if all_sales:
        logger.info(f"✓ Total de vendas encontradas: {len(all_sales)}")
        
        # Ordena por data (mais recentes primeiro)
        all_sales.sort(key=lambda x: x.get("sale_date", ""), reverse=True)
        
        # Armazena no histórico
        history = load_prices_history()
        history[str(item_id)] = []
        
        for sale in all_sales[:30]:  # Mantém últimas 30
            history[str(item_id)].append({
                "timestamp": sale.get("sale_date", datetime.now().isoformat()),
                "price": sale.get("price", 0),
                "seller_name": sale.get("seller_name", "Shop"),
                "buyer_name": sale.get("buyer_name", "Comprador"),
                "quantity": sale.get("quantity", 1),
                "sale_type": sale.get("sale_type", "")
            })
        
        save_prices_history(history)
        logger.info(f"✓ Histórico armazenado com {len(history[str(item_id)])} vendas")
        
        return {
            "success": True,
            "sales": all_sales,
            "item_id": item_id,
            "total_sales": len(all_sales)
        }
    else:
        logger.warning(f"Nenhuma venda encontrada para item {item_id}")
        return get_item_history(item_id)

def get_stores_from_item_page(item_id: int, item_name: str = "", *, force_refresh: bool = False):
    """
    Extrai lojas da página do item e metadados do card (ícone, descrição, peso).
    Retorna (lista_de_lojas, dict_metadados_card).
    ``force_refresh``: novo pedido HTTP (evita resposta em cache) — usar ao «Atualizar preços».
    """
    # Metadados do card vindos do scraper BS mesmo quando a lista de lojas vem vazia
    # (não devolver cedo — o parse HTML manual ainda pode encontrar a tabela de lojas).
    extra_meta_from_bs: dict = {}

    logger.info(f"🏪 Carregando lojas para item {item_id} ({item_name})...")
    
    # ── Tenta usar novo módulo com BeautifulSoup ────────────────────────────
    if SCRAPER_AVAILABLE:
        try:
            logger.info(f"📦 Usando stores_scraper (BeautifulSoup) para item {item_id}...")
            details = get_herosaga_item_stores(item_id, force_refresh=force_refresh)
            
            if details and "error" not in details:
                stores = details.get("stores") or []
                meta = _item_card_meta_from_details(details)
                logger.info(f"✓ {len(stores)} lojas (scraper); card meta: {bool(meta)}")
                if stores:
                    logger.debug(f"Lojas: {json.dumps(stores[:2], ensure_ascii=False)}")
                    return stores, meta
                if meta:
                    extra_meta_from_bs.update(meta)
            else:
                logger.warning(f"⚠️ Resposta inválida do stores_scraper: {details}")
        except Exception as e:
            logger.warning(f"⚠️ Erro com stores_scraper: {str(e)}")
            import traceback
            logger.debug(traceback.format_exc())
    
    # ── Fallback: Parse HTML manual ──────────────────────────────────────────
    logger.info(f"🔄 Usando fallback (parse HTML manual)...")
    
    stores = []
    card_meta = {}
    
    def _merge_card_meta(cm: dict) -> dict:
        out = dict(cm)
        for k, v in extra_meta_from_bs.items():
            if v and not out.get(k):
                out[k] = v
        return out

    try:
        # Carrega a página de detalhes do item (que contém a tabela de lojas)
        url = f"{BASE_URL}/?module=item&action=view&id={item_id}"
        if force_refresh:
            url += f"&_={int(datetime.now().timestamp() * 1000)}"
        get_kw = {"timeout": 15}
        if force_refresh:
            get_kw["headers"] = {
                **HEADERS,
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        logger.debug(f"URL: {url}")
        response = scraper.get(url, **get_kw)
        logger.debug(f"Status: {response.status_code}")
        
        if response.status_code != 200:
            logger.warning(f"❌ Página retornou status {response.status_code}")
            return [], _merge_card_meta({})
        
        # Salva HTML para debug
        html_debug_file = os.path.join(os.path.expanduser("~"), "herosaga_item_page.html")
        with open(html_debug_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        logger.debug(f"✓ HTML salvo em: {html_debug_file}")
        
        # Parse do HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        if SCRAPER_AVAILABLE:
            try:
                card_meta = parse_item_card_from_soup(soup)
            except Exception as e:
                logger.debug(f"Card meta fallback: {e}")
        
        # Procura por tabelas na página
        tables = soup.find_all('table')
        logger.info(f"🔍 Encontradas {len(tables)} tabelas na página")
        
        # Procura pela tabela de lojas
        stores_table = None
        for table in tables:
            headers = []
            for th in table.find_all('th'):
                headers.append(th.get_text(strip=True).lower())
            
            headers_text = ' '.join(headers)
            if any(keyword in headers_text for keyword in ['loja', 'shop', 'refinamento', 'refine', 'valor', 'price', 'qtd', 'quantity', 'vending', 'venda']):
                stores_table = table
                logger.info(f"✓ Encontrada tabela de lojas com headers: {headers}")
                break
        
        if not stores_table:
            logger.warning("⚠️ Nenhuma tabela com headers reconhecidos encontrada")
            logger.info("🔄 Tentando encontrar por número de colunas...")
            
            for table_idx, table in enumerate(tables):
                rows = table.find_all('tr')
                if rows:
                    first_row = rows[0]
                    cols = first_row.find_all(['td', 'th'])
                    logger.debug(f"Tabela {table_idx}: {len(rows)} linhas, {len(cols)} colunas")
                    
                    if len(cols) >= 4:
                        stores_table = table
                        logger.info(f"✓ Selecionada tabela {table_idx} com {len(cols)} colunas")
                        break
        
        if not stores_table:
            logger.error("❌ Nenhuma tabela adequada encontrada")
            return [], _merge_card_meta(card_meta)
        
        rows = stores_table.find_all("tr")[1:]
        logger.info(f"✓ Encontradas {len(rows)} linhas na tabela")

        try:
            from stores_scraper import parse_herosaga_item_stores_table as _parse_hs_stores

            stores = _parse_hs_stores(stores_table)
            for st in stores:
                st["char_name"] = clean_shop_name(st.get("char_name") or "")
        except Exception as _pe:
            logger.debug("parse_herosaga_item_stores_table: %s; usando parse legado", _pe)
            stores = []
            for row_idx, row in enumerate(rows):
                try:
                    cols = row.find_all("td")
                    if len(cols) < 4:
                        continue

                    col_texts = [col.get_text(strip=True) for col in cols]

                    shop_name = col_texts[0]
                    refinement = col_texts[1]
                    cards = col_texts[2]
                    price_text = col_texts[3]
                    quantity = col_texts[4] if len(col_texts) > 4 else "1"

                    try:
                        refinement = int("".join(filter(str.isdigit, refinement))) if refinement else 0
                    except Exception:
                        refinement = 0

                    try:
                        cards = int("".join(filter(str.isdigit, cards))) if cards else 0
                    except Exception:
                        cards = 0

                    try:
                        quantity = int("".join(filter(str.isdigit, quantity))) if quantity else 1
                    except Exception:
                        quantity = 1

                    venda_hint = col_texts[5] if len(col_texts) > 5 else ""
                    combined_hint = f"{price_text} {venda_hint}".lower().strip()

                    price = 0
                    sale_type = "zeny"
                    if price_text:
                        try:
                            price = parse_price_cell(price_text)
                        except Exception:
                            price = 0

                        if "refinamento" in combined_hint or "refin" in combined_hint:
                            sale_type = "zeny"
                        elif "hero point" in combined_hint or "heropoint" in combined_hint or "hero points" in combined_hint:
                            sale_type = "hero_points"
                        elif "rmt" in combined_hint or re.search(r"(rm(\$| |$)|r[\$\s]?m|rmt)", combined_hint):
                            sale_type = "rmt"
                        elif "rops" in combined_hint or re.search(r"(rp(\$| |$)|r\$(?!\s*m)|^\s*r\$)", combined_hint):
                            sale_type = "rops"
                        else:
                            sale_type = "zeny"

                    shop_name = clean_shop_name(shop_name)

                    store = {
                        "char_name": shop_name,
                        "refinement": refinement,
                        "cards": cards,
                        "price": price,
                        "amount": quantity,
                        "quantity": quantity,
                        "sale_type": sale_type,
                    }

                    stores.append(store)
                    logger.debug(
                        f"✓ Loja {row_idx+1}: {shop_name} - R:{refinement} C:{cards} P:{price} ({sale_type}) Q:{quantity}"
                    )

                except Exception as e:
                    logger.debug(f"Erro ao processar linha {row_idx}: {str(e)}")
                    continue

        stores.sort(key=lambda x: x.get("price", float("inf")))
        logger.info(f"✓ Extraídas {len(stores)} lojas com sucesso")

        return stores, _merge_card_meta(card_meta)
        
    except Exception as e:
        logger.error(f"❌ Erro ao fazer parse do HTML: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return [], _merge_card_meta({})

def api_vending_search(name: str):
    """
    Busca lojas abertas com o item à venda e retorna ordenado por preço.
    
    VERSÃO MELHORADA: Usa o módulo stores_scraper (BeautifulSoup) quando disponível,
    com fallback para o método anterior.
    """
    
    # ── Tenta usar novo módulo com BeautifulSoup ────────────────────────────
    if SCRAPER_AVAILABLE:
        try:
            logger.info(f"🔍 Buscando '{name}' com stores_scraper (BeautifulSoup)...")
            all_results = search_item_all_stores(name)
            herosaga_items = all_results.get("herosaga", [])
            
            if herosaga_items:
                logger.info(f"✓ {len(herosaga_items)} lojas encontradas com BeautifulSoup")
                
                # Retorna no formato esperado
                results = []
                for item in herosaga_items:
                    results.append({
                        "char_name": item.get("char_name", "Shop"),
                        "price": item.get("price", 0),
                        "amount": item.get("quantity", 1),
                        "refinement": item.get("refinement", 0),
                        "cards": item.get("cards", 0),
                        "sale_type": item.get("sale_type", "zeny"),
                    })
                
                return results
        except Exception as e:
            logger.warning(f"⚠️ Erro com stores_scraper, usando fallback: {str(e)}")
    
    # ── Fallback: Método antigo (API JSON) ──────────────────────────────────
    url = f"{BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(name)}"
    try:
        logger.info(f"🔍 Buscando '{name}' com API JSON (fallback)...")
        response = scraper.get(url, timeout=15)
        logger.debug(f"Status: {response.status_code}")
        
        results = response.json().get("results", [])
        
        if results:
            logger.info(f"✓ {len(results)} lojas encontradas com API JSON")
            logger.info(f"Estrutura do primeiro resultado:")
            logger.info(f"{json.dumps(results[0], ensure_ascii=False, indent=2)}")
            
            # Ordena por preço (do menor para maior)
            def get_price(store):
                price = store.get("price") or store.get("sell_price") or store.get("valor") or float('inf')
                if price == float('inf'):
                    return float('inf')
                try:
                    return coerce_price(price)
                except Exception:
                    return float('inf')
            
            results.sort(key=get_price)
            logger.info(f"✓ Ordenadas por preço (menor → maior)")
            
            for i, store in enumerate(results[:3]):
                price = get_price(store)
                logger.debug(f"  #{i+1}: {store.get('char_name', 'Shop')} - Preço: {price}")
        else:
            logger.warning(f"❌ Nenhuma loja encontrada para: {name}")
        
        return results
    except Exception as e:
        logger.error(f"❌ Erro na busca: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []

# ── Persistência ─────────────────────────────────────────────────────────────


def _dedupe_monitored_preserve_order(monitored):
    """Mantém a primeira ocorrência de cada ID na lista de monitorados."""
    if not isinstance(monitored, list):
        return []
    seen = set()
    out = []
    for m in monitored:
        if not isinstance(m, dict):
            continue
        try:
            pid = int(m["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        out.append(m)
    return out


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if not isinstance(raw, dict):
                    raw = {}
                data = _ensure_monitor_structure(raw)
                if isinstance(data.get("monitored"), list):
                    data["monitored"] = _dedupe_monitored_preserve_order(data["monitored"])
                return data
        except Exception:
            pass
    return _ensure_monitor_structure({"monitored": [], "searches": []})


def save_data(data):
    if isinstance(data, dict) and isinstance(data.get("monitored"), list):
        data["monitored"] = _dedupe_monitored_preserve_order(data["monitored"])
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Histórico de Preços ──────────────────────────────────────────────────────
def load_prices_history():
    """Carrega histórico de preços coletados."""
    if os.path.exists(PRICES_HISTORY_FILE):
        try:
            with open(PRICES_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_prices_history(history):
    """Salva histórico de preços."""
    with open(PRICES_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def collect_price(item_id: int, item_data: dict):
    """Coleta e armazena preço real do item do vending search."""
    # LOG DETALHADO PARA DIAGNÓSTICO
    logger.debug(f"Item data received: {json.dumps(item_data, ensure_ascii=False, indent=2)}")
    
    price = item_data.get("price")
    logger.info(f"Tentando campo 'price': {price}")
    
    # Se price estiver vazio/zero, tenta outros campos possíveis
    if not price or price == 0:
        # Tenta variações
        price = item_data.get("sell_price") or \
                item_data.get("venda_price") or \
                item_data.get("valor") or \
                item_data.get("preco")
        logger.info(f"Tentando campos alternativos: {price}")
    
    if not price or price == 0:
        logger.warning(f"Nenhum preço válido encontrado para item {item_id}. Campos disponíveis: {list(item_data.keys())}")
        return
    
    history = load_prices_history()
    item_id_str = str(item_id)
    
    if item_id_str not in history:
        history[item_id_str] = []
    
    # Armazena preço com timestamp
    sale_entry = {
        "timestamp": datetime.now().isoformat(),
        "price": price,
        "seller_name": item_data.get("char_name") or item_data.get("seller") or "Shop",
        "quantity": item_data.get("amount") or item_data.get("quantity") or 1
    }
    
    # Evita duplicatas do mesmo minuto
    now = datetime.now().strftime("%Y-%m-%d %H:%M:")
    if not any(s["timestamp"].startswith(now) for s in history[item_id_str]):
        history[item_id_str].append(sale_entry)
        # Mantém apenas últimas 30 vendas
        history[item_id_str] = history[item_id_str][-30:]
        save_prices_history(history)
        logger.debug(f"✓ Preço coletado para item {item_id}: {price} ZENY")

def get_item_history(item_id: int) -> dict:
    """Retorna histórico de preços coletados para um item."""
    history = load_prices_history()
    item_id_str = str(item_id)
    
    if item_id_str not in history or not history[item_id_str]:
        return {
            "sales": [],
            "sale_type": "ZENY",
            "item_id": item_id,
            "message": "Nenhum preço coletado ainda. Continue buscando!"
        }
    
    # Converte timestamp ISO para timestamp float para ordenação
    sales = sorted(history[item_id_str], key=lambda x: x.get("timestamp", ""), reverse=True)
    
    # Formata para o formato esperado pela UI
    formatted_sales = []
    for i, sale in enumerate(sales):
        formatted_sales.append({
            "sale_date": sale.get("timestamp", ""),
            "seller_name": sale.get("seller_name", "Shop"),
            "buyer_name": safe_get(sale, "buyer_name", "—"),
            "price": sale.get("price", 0),
            "quantity": sale.get("quantity", 1)
        })
    
    return {
        "sales": formatted_sales,
        "sale_type": "ZENY",
        "item_id": item_id,
        "total_sales": len(formatted_sales)
    }

# ── Utilitários para Análise ─────────────────────────────────────────────────
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
        return {
            "último": 0, "mínimo": 0, "máximo": 0, "média": 0,
            "total": 0, "quantidade": len(sales)
        }
    
    prices = [s.get("price", 0) for s in sales]
    prices = [p for p in prices if p > 0]
    
    if not prices:
        return {"último": 0, "mínimo": 0, "máximo": 0, "média": 0,
                "total": 0, "quantidade": len(sales)}
    
    return {
        "último": prices[0],
        "mínimo": min(prices),
        "máximo": max(prices),
        "média": int(sum(prices) / len(prices)),
        "total": sum(prices),
        "quantidade": len(sales)
    }

# ── Alertas ──────────────────────────────────────────────────────────────────
ALERTS_FILE = os.path.join(os.path.expanduser("~"), "herosaga_alerts.json")
# RLock: load_alerts/save_alerts tomam o lock; código que já o segura (ex.: refresh da UI
# de Alertas, tick do monitor) precisa voltar a chamar load/save sem deadlock.
_ALERTS_IO_LOCK = threading.RLock()


def load_alerts():
    """Carrega alertas de preço configurados."""
    with _ALERTS_IO_LOCK:
        if os.path.exists(ALERTS_FILE):
            try:
                with open(ALERTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def save_alerts(alerts):
    """Salva alertas de preço."""
    with _ALERTS_IO_LOCK:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)

# ── Paleta de cores (tema escuro / claro) ───────────────────────────────────
PALETTE_DARK = {
    "bg": "#0a0a0a",
    "bg2": "#111111",
    "bg3": "#1a1a1a",
    "card": "#151515",
    "border": "#2a2a2a",
    "border2": "#3a3a3a",
    "purple": "#8b5cf6",
    "purple2": "#a78bfa",
    "purple3": "#ddd6fe",
    "accent": "#a855f7",
    "text": "#ececec",
    "text2": "#b0b0b0",
    "text3": "#737373",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#f59e0b",
    "rmt": "#c084fc",
    "zeny": "#fbbf24",
    "rops": "#60a5fa",
    "hero_points": "#f472b6",
    "column_rim": "#2d2d2d",
    "column_face": "#121212",
    "column_hdr": "#181818",
    "column_hdr_fg": "#ddd6fe",
    "btn_danger_bg": "#7f1d1d",
    "btn_danger_fg": "#fecaca",
    "btn_danger_hover": "#991b1b",
    "btn_success_bg": "#14532d",
    "btn_success_fg": "#bbf7d0",
    "btn_success_hover": "#166534",
    "build_slot_bg": "#16142a",
    "build_slot_rim": "#3d2f5c",
    "build_slot_entry_bg": "#120f1d",
    # Scrollbar: trilho e polegar com contraste explícito (ttk + ModernScrollbar).
    "sb_trough": "#2a2a2a",
    "sb_thumb": "#5c5c5c",
    "sb_thumb_hover": "#707070",
    "sb_thumb_active": "#8b5cf6",
}

PALETTE_LIGHT = {
    "bg": "#f4f4f5",
    "bg2": "#e4e4e7",
    "bg3": "#d4d4d8",
    "card": "#ffffff",
    "border": "#d4d4d8",
    "border2": "#e4e4e7",
    "purple": "#6d28d9",
    "purple2": "#7c3aed",
    "purple3": "#4c1d95",
    "accent": "#7c3aed",
    "text": "#18181b",
    "text2": "#3f3f46",
    "text3": "#71717a",
    "green": "#16a34a",
    "red": "#dc2626",
    "yellow": "#d97706",
    "rmt": "#7c3aed",
    "zeny": "#ca8a04",
    "rops": "#2563eb",
    "hero_points": "#db2777",
    "column_rim": "#d4d4d8",
    "column_face": "#fafafa",
    "column_hdr": "#f4f4f5",
    "column_hdr_fg": "#5b21b6",
    "btn_danger_bg": "#fef2f2",
    "btn_danger_fg": "#b91c1c",
    "btn_danger_hover": "#fee2e2",
    "btn_success_bg": "#ecfdf5",
    "btn_success_fg": "#047857",
    "btn_success_hover": "#d1fae5",
    "build_slot_bg": "#faf8ff",
    "build_slot_rim": "#c4b5fd",
    "build_slot_entry_bg": "#ffffff",
    "sb_trough": "#e4e4e7",
    "sb_thumb": "#909096",
    "sb_thumb_hover": "#71717a",
    "sb_thumb_active": "#6d28d9",
}

C = {}


def apply_palette(theme=None):
    """Actualiza o dict global ``C`` (cores da interface)."""
    t = (theme or "dark").strip().lower()
    chosen = PALETTE_LIGHT if t == "light" else PALETTE_DARK
    C.clear()
    C.update(chosen)


apply_palette(load_settings().get("ui_theme", "dark"))

# Card do item (estilo painel claro do site)
ITEM_CARD_UI = {
    "bg": "#f5f0e8",
    "border": "#c9a227",
    "title": "#1a1528",
    "desc_bg": "#ffffff",
    "desc_fg": "#3d3550",
    "muted": "#6b5a8a",
    "weight_bg": "#fff8dc",
    "weight_fg": "#5c4a2e",
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def item_emoji(name: str) -> str:
    if not name:
        return "📦"
    n = name.lower()
    if any(x in n for x in ["espada", "sword", "sabre"]): return "⚔"
    if "mana" in n: return "💜"
    if any(x in n for x in ["poção", "pocao", "elixir"]): return "🧪"
    if "escudo" in n: return "🛡"
    if "arco" in n: return "🏹"
    if any(x in n for x in ["cajado", "staff", "varinha"]): return "🪄"
    if any(x in n for x in ["elmo", "capacete", "helm"]): return "🪖"
    if any(x in n for x in ["anel", "ring"]): return "💍"
    if any(x in n for x in ["bota", "sapato", "boot"]): return "👢"
    if "carta" in n: return "🃏"
    return "🗡"

def fmt_price(p) -> str:
    try:
        return f"{int(p):,}".replace(",", ".")
    except Exception:
        return str(p)


def fmt_price_stores(p) -> str:
    """
    Preço para lojas online: mantém todas as casas decimais (não trunca como int).
    Inteiros: separador de milhar em ponto (igual fmt_price). Com decimais: ponto
    como separador decimal, sem agrupar milhares (evita ambiguidade com vários pontos).
    """
    if p is None:
        return "0"
    try:
        raw = str(p).strip().replace(",", ".")
        d = Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        try:
            d = Decimal(str(float(p)))
        except (InvalidOperation, ValueError, TypeError):
            return str(p)
    if d == d.to_integral_value():
        return fmt_price(int(d))
    s = format(d, "f")
    if "." in s:
        a, b = s.split(".", 1)
        b = b.rstrip("0")
        if not b:
            try:
                return fmt_price(int(Decimal(a)))
            except (InvalidOperation, ValueError):
                return s.rstrip("0").rstrip(".")
        s = f"{a}.{b}"
    return s


def _alert_min_refinement(alert: dict):
    """Refino mínimo configurado no alerta (int) ou None = qualquer refino."""
    want = alert.get("refinement") if isinstance(alert, dict) else None
    if want is None or want == "":
        return None
    try:
        return int(want)
    except (TypeError, ValueError):
        return None


def _sale_min_prices_from_stores(stores: list, *, min_refinement=None) -> dict:
    """Menor preço por moeda nas lojas (zeny, rops, rmt, hero_points).

    Se *min_refinement* for int, só contam listagens com refino >= esse valor.
    """
    best: dict = {}
    for store in stores or []:
        if min_refinement is not None:
            try:
                ref = int(
                    store.get("refinement")
                    or store.get("refine")
                    or store.get("enhancement")
                    or 0
                )
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


def _format_home_min_prices_for_monitored(m: dict) -> str:
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


def _monitored_static_incomplete(m: dict) -> bool:
    if not str(m.get("name") or "").strip():
        return True
    if m.get("id") is None:
        return True
    if not str(m.get("item_icon_url") or "").strip():
        return True
    return False


def _mh_last_prices_update_label(monitored: list) -> str:
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


_LIST_SEARCH_DEBOUNCE_MS = 300


def item_matches_search(entry: dict, query: str) -> bool:
    """Filtro por nome ou ID (mesma lógica que a busca do Timer MVP)."""
    if not isinstance(entry, dict):
        return False
    stub = {
        "id": entry.get("id") if entry.get("id") is not None else entry.get("item_id"),
        "name": (entry.get("name") or entry.get("item_name") or ""),
    }
    return mvp_catalog_matches_search(stub, query)


def safe_get(d: dict, key: str, default: str = "N/A") -> str:
    """Extrai valor seguro de dicionário, convertendo None para default"""
    value = d.get(key, default)
    if value is None:
        return default
    return str(value)

def clean_shop_name(name: str) -> str:
    """
    Limpa nome da loja removendo caracteres especiais, controle e espaços extras.
    Mantém apenas letras, números, espaços e caracteres latinos.
    """
    if not name:
        return "Shop"
    
    import re
    
    # Remove caracteres de controle e especiais problemáticos
    # Mantém: letras (a-z, A-Z), números (0-9), espaços, e alguns caracteres latinos acentuados
    name = re.sub(r'[^\w\s\-\.\(\)]', '', name, flags=re.UNICODE)
    
    # Remove múltiplos espaços
    name = re.sub(r'\s+', ' ', name)
    
    # Remove espaços no início/fim
    name = name.strip()
    
    # Se ficou vazio, retorna padrão
    if not name or len(name) < 2:
        return "Shop"
    
    return name

def clean_json_response(text: str, content: bytes = None) -> str:
    """Remove compressão, BOM e caracteres inválidos do início da resposta"""
    # Se temos o conteúdo em bytes, tenta descompactar
    if content:
        # Detecta deflate (começa com 0x78)
        if content[:1] == b'\x78' or content[:2] == b'\x78\x9c':
            logger.info("Detectado conteúdo deflate, decompactando...")
            try:
                decompressed = zlib.decompress(content)
                text = decompressed.decode('utf-8')
                logger.info("Deflate decompactado com sucesso")
            except Exception as e:
                logger.warning(f"Falha ao descomprimir deflate: {e}")
        # Detecta gzip (começa com 0x1f 0x8b)
        elif content[:2] == b'\x1f\x8b':
            logger.info("Detectado conteúdo gzip, decompactando...")
            try:
                decompressed = gzip.decompress(content)
                text = decompressed.decode('utf-8')
                logger.info("Gzip decompactado com sucesso")
            except Exception as e:
                logger.warning(f"Falha ao descomprimir gzip: {e}")
        # Detecta outros bytes estranhos no início
        elif content[0] < 32 and content[0] != ord('\n'):
            logger.warning(f"Bytes estranhos detectados no início: {content[:10]}")
            # Tenta encontrar o primeiro { ou [
            for i, byte in enumerate(content):
                if chr(byte) in '{[':
                    logger.info(f"Encontrado JSON válido no byte {i}, usando dali em diante")
                    text = content[i:].decode('utf-8', errors='ignore')
                    break
    
    # Remove BOM (Byte Order Mark) e espaços
    text = text.lstrip('\ufeff').strip()
    return text

def sale_type_color(st: str) -> str:
    st = (st or "").lower()
    if "rmt" in st:  return C["rmt"]
    if "zeny" in st: return C["zeny"]
    if "rops" in st: return C["rops"]
    if "hero" in st: return C["hero_points"]
    return C["text2"]


def _store_badge_label(sale_type: str) -> tuple:
    """Texto e cor do rótulo 'Venda por' (estilo site)."""
    st = (sale_type or "zeny").lower()
    if "rmt" in st:
        return "RMT", C["rmt"]
    if "rops" in st or st in ("rp", "r$"):
        return "ROPS", C["rops"]
    if "hero" in st and "point" in st:
        return "HERO PTS", C["hero_points"]
    return "ZENY", C["zeny"]


def _format_store_price_display(price: float, sale_type: str) -> tuple:
    """Texto e cor do preço na coluna VALOR."""
    st = (sale_type or "zeny").lower()
    try:
        p = fmt_price_stores(price) if price is not None else "0"
    except (TypeError, ValueError):
        p = "0"
    if "rmt" in st:
        return f"{p} RMT", C["rmt"]
    if "rops" in st or st in ("rp", "r$"):
        return f"{p} R$", C["rops"]
    if "hero" in st and "point" in st:
        return f"{p} HP", C["hero_points"]
    return f"{p}z", C["zeny"]

# ════════════════════════════════════════════════════════════════════════════
# WIDGETS CUSTOMIZADOS (cantos arredondados — Canvas)
# ════════════════════════════════════════════════════════════════════════════


def _tk_widget_bg(widget, default=None):
    d = default if default is not None else C.get("bg", "#0a0a0a")
    w = widget
    for _ in range(10):
        if w is None:
            return d
        try:
            return w.cget("bg")
        except tk.TclError:
            pass
        w = getattr(w, "master", None)
    return d


try:
    from PIL import Image, ImageDraw, ImageTk

    _HAS_PIL_ROUND = True
except ImportError:
    _HAS_PIL_ROUND = False


def _hex_rgb_tuple(h):
    s = (h or "#000000").strip().lstrip("#")
    if len(s) >= 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return (0, 0, 0)


def _pil_round_solid(w, h, r, fill_hex, scale=2):
    """Bitmap RGBA com cantos suaves (superamostragem + LANCZOS)."""
    sw = max(1, int(w * scale))
    sh = max(1, int(h * scale))
    rs = int(min(max(2, r * scale), sw // 2 - 1, sh // 2 - 1))
    im = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    t = _hex_rgb_tuple(fill_hex) + (255,)
    dr.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=rs, fill=t)
    if scale > 1 and (sw != w or sh != h):
        im = im.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)
    return im


def _pil_knockout_near_white_rgba(im, thresh: int = 246):
    """
    Torna transparentes os pixels quase brancos (fundo típico de ícones PNG/JPEG).
    *thresh* 220–255: mais alto = só branco «puro»; mais baixo = remove mais cinza-claro.
    """
    try:
        from PIL import Image
    except ImportError:
        return im
    try:
        im = im.convert("RGBA")
    except Exception:
        return im
    t = min(255, max(220, int(thresh)))
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r >= t and g >= t and b >= t:
                px[x, y] = (r, g, b, 0)
    return im


def _canvas_round_fill_vector(canvas, x1, y1, x2, y2, r, fill, tag="rr"):
    """Fallback vectorial (sem antialiasing)."""
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError):
        return
    if x2 <= x1 + 2 or y2 <= y1 + 2:
        return
    r = int(min(max(2, r), (x2 - x1) // 2 - 1, (y2 - y1) // 2 - 1))
    canvas.create_rectangle(
        x1 + r, y1, x2 - r, y2, fill=fill, outline="", width=0, tags=(tag,)
    )
    canvas.create_rectangle(
        x1, y1 + r, x2, y2 - r, fill=fill, outline="", width=0, tags=(tag,)
    )
    canvas.create_arc(
        x1, y1, x1 + 2 * r, y1 + 2 * r,
        start=90, extent=90, fill=fill, outline="", style="pieslice", tags=(tag,),
    )
    canvas.create_arc(
        x2 - 2 * r, y1, x2, y1 + 2 * r,
        start=0, extent=90, fill=fill, outline="", style="pieslice", tags=(tag,),
    )
    canvas.create_arc(
        x1, y2 - 2 * r, x1 + 2 * r, y2,
        start=180, extent=90, fill=fill, outline="", style="pieslice", tags=(tag,),
    )
    canvas.create_arc(
        x2 - 2 * r, y2 - 2 * r, x2, y2,
        start=270, extent=90, fill=fill, outline="", style="pieslice", tags=(tag,),
    )


def _canvas_round_fill(canvas, x1, y1, x2, y2, r, fill, tag="rr", holder=None):
    """
    Rectângulo com cantos arredondados. Com Pillow: imagem antialiased.
    *holder* guarda PhotoImage (evita o GC apagar a imagem).
    """
    holder = holder if holder is not None else canvas
    try:
        canvas.delete(tag)
    except tk.TclError:
        pass
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError):
        return
    W = int(x2 - x1)
    H = int(y2 - y1)
    if W < 3 or H < 3:
        return
    r = int(min(max(2, r), W // 2 - 1, H // 2 - 1))
    if _HAS_PIL_ROUND and W >= 4 and H >= 4:
        sc = 3 if max(W, H) <= 130 else 2
        if max(W, H) * sc > 3600:
            sc = 2
        try:
            img = _pil_round_solid(W, H, r, fill, scale=sc)
            ph = ImageTk.PhotoImage(img, master=canvas.winfo_toplevel())
            if not hasattr(holder, "_aa_photos"):
                holder._aa_photos = {}
            holder._aa_photos[tag] = ph
            canvas.create_image(int(x1), int(y1), anchor="nw", image=ph, tags=(tag,))
            return
        except Exception:
            pass
    _canvas_round_fill_vector(canvas, x1, y1, x2, y2, r, fill, tag)


class DarkButton(tk.Canvas):
    """Botão com cantos arredondados (substitui ``tk.Button`` na maior parte da UI)."""

    _radius = 11

    def __init__(
        self,
        parent,
        style="primary",
        command=None,
        text="",
        font=None,
        padx=10,
        pady=4,
        text_anchor="center",
        **kwargs,
    ):
        if "font" in kwargs:
            font = kwargs.pop("font")
        if "padx" in kwargs:
            padx = kwargs.pop("padx")
        if "pady" in kwargs:
            pady = kwargs.pop("pady")
        if "command" in kwargs:
            command = kwargs.pop("command")
        if "text" in kwargs:
            text = kwargs.pop("text")
        if "text_anchor" in kwargs:
            text_anchor = kwargs.pop("text_anchor")
        if "style" in kwargs:
            style = kwargs.pop("style")
        self._command = command
        self._text = text
        self._font = font or ("Segoe UI", 9, "bold")
        self._padx = padx
        self._pady = pady
        self._style_name = style
        self._text_anchor = text_anchor
        self._hover = False
        self._pressed = False
        self._disabled = False
        self._min_width = int(kwargs.pop("width", 0) or 0)
        ckw = {k: v for k, v in kwargs.items() if k in ("cursor", "takefocus", "highlightthickness")}
        for k in ("cursor", "takefocus", "highlightthickness"):
            kwargs.pop(k, None)
        cur = ckw.get("cursor", "hand2")
        super().__init__(
            parent,
            highlightthickness=ckw.get("highlightthickness", 0),
            cursor=cur,
            takefocus=ckw.get("takefocus", 0),
        )
        self.configure(bg=_tk_widget_bg(parent))
        self._db_cfg_job = None
        self.bind("<Configure>", self._on_configure_resize)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        fnt = tkfont.Font(font=self._font)
        self._min_h = max(28, int(fnt.metrics("linespace") + 2 * self._pady + 12))
        self._min_w = max(self._min_width, int(fnt.measure(self._text) + 2 * self._padx + 24))
        self.configure(height=self._min_h, width=self._min_w)
        self.after_idle(self._draw)

    def _on_configure_resize(self, _event=None):
        """Redimensionar a janela dispara centenas de Configure/s; agrega redesenhos."""
        if self._db_cfg_job is not None:
            try:
                self.after_cancel(self._db_cfg_job)
            except tk.TclError:
                pass
        self._db_cfg_job = self.after(32, self._draw_after_resize_coalesce)

    def _draw_after_resize_coalesce(self):
        self._db_cfg_job = None
        self._draw()

    def _colors(self):
        if self._disabled:
            return {
                "bg": C["bg3"],
                "fg": C["text3"],
                "hover": C["bg3"],
            }
        st = self._style_name
        if st == "primary":
            return {"bg": C["purple"], "fg": "#ffffff", "hover": C["accent"]}
        if st == "ghost":
            return {"bg": C["bg3"], "fg": C["text2"], "hover": C["border2"]}
        if st == "danger":
            return {
                "bg": C["btn_danger_bg"],
                "fg": C["btn_danger_fg"],
                "hover": C["btn_danger_hover"],
            }
        if st == "success":
            return {
                "bg": C["btn_success_bg"],
                "fg": C["btn_success_fg"],
                "hover": C["btn_success_hover"],
            }
        if st == "mh_refresh":
            return {"bg": "#2d7a2d", "fg": "#ffffff", "hover": "#3a9e3a"}
        return {"bg": C["bg3"], "fg": C["text2"], "hover": C["border2"]}

    def _face(self):
        c = self._colors()
        bg = c["hover"] if (self._hover or self._pressed) and not self._disabled else c["bg"]
        return bg, c["fg"]

    def _draw(self, event=None):
        w = max(int(self.winfo_width()), 8)
        h = max(int(self.winfo_height()), 8)
        self.delete("fill", "txt")
        bg, fg = self._face()
        rr = min(self._radius, h // 2 - 1, w // 2 - 1)
        _canvas_round_fill(self, 1, 1, w - 1, h - 1, rr, bg, tag="fill", holder=self)
        fnt = tkfont.Font(font=self._font)
        if self._text_anchor == "w":
            tx = self._padx + 6
            anc = "w"
        else:
            tx = w // 2
            anc = "center"
        ty = h // 2
        self.create_text(tx, ty, text=self._text, anchor=anc, fill=fg, font=self._font, tags=("txt",))

    def _enter(self, _e=None):
        if self._disabled:
            return
        self._hover = True
        self._draw()

    def _leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _press(self, _e=None):
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _release(self, event=None):
        if self._disabled:
            return
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self._command and event is not None:
            try:
                x, y = event.x, event.y
                if 0 <= x < int(self.winfo_width()) and 0 <= y < int(self.winfo_height()):
                    self._command()
            except tk.TclError:
                pass

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        if "text" in kw:
            self._text = kw.pop("text")
            fnt = tkfont.Font(font=self._font)
            self._min_w = max(self._min_width, int(fnt.measure(self._text) + 2 * self._padx + 24))
            try:
                super().configure(width=self._min_w)
            except tk.TclError:
                pass
        if "command" in kw:
            self._command = kw.pop("command")
        if kw.get("state") == "disabled":
            self._disabled = True
        elif "state" in kw:
            self._disabled = str(kw.get("state")) == "disabled"
        if "style" in kw:
            self._style_name = kw.pop("style")
        if "bg" in kw:
            kw.pop("bg", None)
            super().configure(bg=_tk_widget_bg(self.master))
        if kw:
            super().configure(**kw)
        self.after_idle(self._draw)

    config = configure


class DarkCheckbutton(tk.Frame):
    """Caixa de opção desenhada (contraste claro marcado / desmarcado no Windows)."""

    _BOX = 20

    def __init__(self, parent, text="", variable=None, command=None, font=("Segoe UI", 9), **kw):
        bg = kw.pop("bg", None) or _tk_widget_bg(parent)
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self._bg = bg
        self._var = variable if variable is not None else tk.BooleanVar(value=False)
        self._command = command
        self._text = text
        self._font = font
        self._disabled = False
        self._c = tk.Canvas(
            self,
            width=self._BOX,
            height=self._BOX,
            highlightthickness=0,
            bg=bg,
            cursor="hand2",
        )
        self._c.pack(side="left", padx=(0, 8))
        self._lbl = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=C["text3"],
            font=font,
            anchor="w",
            justify="left",
            cursor="hand2",
        )
        self._lbl.pack(side="left", fill="x", expand=True)
        for w in (self, self._c, self._lbl):
            w.bind("<Button-1>", self._on_click)
        self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        self._redraw()

    def _on_click(self, _event=None):
        if self._disabled:
            return
        self._var.set(not bool(self._var.get()))
        if self._command:
            self._command()

    def _redraw(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        checked = bool(self._var.get())
        c = self._c
        c.delete("all")
        pad = 2
        x1, y1, x2, y2 = pad, pad, self._BOX - pad, self._BOX - pad
        if self._disabled:
            c.create_rectangle(x1, y1, x2, y2, outline=C["border"], fill=C["bg3"], width=2)
            self._lbl.configure(fg=C["text3"])
            return
        if checked:
            c.create_rectangle(x1, y1, x2, y2, outline=C["purple2"], fill=C["purple"], width=2)
            c.create_line(5, 10, 8, 14, 15, 6, fill="#ffffff", width=2, capstyle="round", joinstyle="round")
            self._lbl.configure(fg=C["text"], font=self._font)
        else:
            c.create_rectangle(x1, y1, x2, y2, outline=C["border2"], fill=C["card"], width=2)
            self._lbl.configure(fg=C["text2"], font=self._font)

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        if "text" in kw:
            self._text = kw.pop("text")
            self._lbl.configure(text=self._text)
        if "command" in kw:
            self._command = kw.pop("command")
        if "variable" in kw:
            self._var = kw.pop("variable")
            self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        if "font" in kw:
            self._font = kw.pop("font")
            self._lbl.configure(font=self._font)
        if "bg" in kw:
            self._bg = kw.pop("bg")
            super().configure(bg=self._bg)
            self._c.configure(bg=self._bg)
            self._lbl.configure(bg=self._bg)
        st = kw.pop("state", None)
        if st is not None:
            self._disabled = str(st) == "disabled"
            cur = "" if self._disabled else "hand2"
            try:
                super().configure(cursor=cur)
                self._c.configure(cursor=cur)
                self._lbl.configure(cursor=cur)
            except tk.TclError:
                pass
        if kw:
            super().configure(**kw)
        self.after_idle(self._redraw)

    config = configure


class DarkRadiobutton(tk.Frame):
    """Botão de opção desenhado (ponto interior visível quando seleccionado)."""

    _SZ = 20

    def __init__(
        self,
        parent,
        text="",
        variable=None,
        value="",
        command=None,
        font=("Segoe UI", 9),
        **kw,
    ):
        bg = kw.pop("bg", None) or _tk_widget_bg(parent)
        super().__init__(parent, bg=bg, cursor="hand2", **kw)
        self._bg = bg
        self._var = variable if variable is not None else tk.StringVar()
        self._value = value
        self._command = command
        self._font = font
        self._disabled = False
        self._c = tk.Canvas(
            self,
            width=self._SZ,
            height=self._SZ,
            highlightthickness=0,
            bg=bg,
            cursor="hand2",
        )
        self._c.pack(side="left", padx=(0, 8))
        self._lbl = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=C["text2"],
            font=font,
            anchor="w",
            cursor="hand2",
        )
        self._lbl.pack(side="left", fill="x", expand=True)
        for w in (self, self._c, self._lbl):
            w.bind("<Button-1>", self._on_click)
        self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        self._redraw()

    def _on_click(self, _event=None):
        if self._disabled:
            return
        self._var.set(self._value)
        if self._command:
            self._command()

    def _redraw(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        selected = str(self._var.get()) == str(self._value)
        c = self._c
        c.delete("all")
        cx, cy = self._SZ // 2, self._SZ // 2
        r_out = 9
        r_in = 5
        if self._disabled:
            c.create_oval(cx - r_out, cy - r_out, cx + r_out, cy + r_out, outline=C["border"], width=2)
            self._lbl.configure(fg=C["text3"])
            return
        if selected:
            c.create_oval(
                cx - r_out,
                cy - r_out,
                cx + r_out,
                cy + r_out,
                outline=C["purple2"],
                fill=C["card"],
                width=2,
            )
            c.create_oval(
                cx - r_in,
                cy - r_in,
                cx + r_in,
                cy + r_in,
                outline=C["purple"],
                fill=C["purple"],
                width=1,
            )
            self._lbl.configure(fg=C["text"], font=self._font)
        else:
            c.create_oval(
                cx - r_out,
                cy - r_out,
                cx + r_out,
                cy + r_out,
                outline=C["border2"],
                fill=C["bg3"],
                width=2,
            )
            self._lbl.configure(fg=C["text2"], font=self._font)

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        if "text" in kw:
            self._lbl.configure(text=kw.pop("text"))
        if "command" in kw:
            self._command = kw.pop("command")
        if "variable" in kw:
            self._var = kw.pop("variable")
            self._var.trace_add("write", lambda *_a: self.after_idle(self._redraw))
        if "value" in kw:
            self._value = kw.pop("value")
        if "font" in kw:
            self._font = kw.pop("font")
            self._lbl.configure(font=self._font)
        if "bg" in kw:
            self._bg = kw.pop("bg")
            super().configure(bg=self._bg)
            self._c.configure(bg=self._bg)
            self._lbl.configure(bg=self._bg)
        st = kw.pop("state", None)
        if st is not None:
            self._disabled = str(st) == "disabled"
            cur = "" if self._disabled else "hand2"
            try:
                super().configure(cursor=cur)
                self._c.configure(cursor=cur)
                self._lbl.configure(cursor=cur)
            except tk.TclError:
                pass
        if kw:
            super().configure(**kw)
        self.after_idle(self._redraw)

    config = configure


class DarkEntry(tk.Frame):
    """Campo de texto com moldura arredondada.

    O ``Entry`` é filho deste ``Frame`` e fica *por cima* do ``Canvas`` (só decoração).
    Evita ``create_window`` no canvas, que no Windows costuma bloquear clique/teclado.
    """

    _radius = 12
    _FRAME_OPTS = frozenset(
        {
            "bg",
            "width",
            "height",
            "name",
            "cursor",
            "takefocus",
            "highlightthickness",
            "highlightbackground",
            "highlightcolor",
            "bd",
            "borderwidth",
            "relief",
            "padx",
            "pady",
        }
    )

    def __init__(self, parent, **kwargs):
        entry_kw = {}
        for k in ("show", "exportselection", "width", "font", "fg", "insertbackground", "state"):
            if k in kwargs:
                entry_kw[k] = kwargs.pop(k)
        frame_kw = {k: kwargs.pop(k) for k in list(kwargs.keys()) if k in DarkEntry._FRAME_OPTS}
        frame_kw.setdefault("bg", _tk_widget_bg(parent))
        super().__init__(parent, **frame_kw)

        self._focus_ring = False
        self._canvas = tk.Canvas(
            self,
            height=40,
            highlightthickness=0,
            bg=self.cget("bg"),
        )
        self._canvas.pack(fill="both", expand=True)
        self._entry = tk.Entry(
            self,
            bg=C["bg3"],
            fg=C["text"],
            insertbackground=C["purple2"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            takefocus=True,
            font=entry_kw.get("font", ("Segoe UI", 11)),
            **{k: v for k, v in entry_kw.items() if k != "font"},
        )

        def _focus_in(_e=None):
            self._set_focus_ring(True)

        def _focus_out(_e=None):
            self._set_focus_ring(False)

        self._entry.bind("<FocusIn>", _focus_in, add="+")
        self._entry.bind("<FocusOut>", _focus_out, add="+")
        self._de_cfg_job = None

        def _on_canvas_resize(_e):
            if self._de_cfg_job is not None:
                try:
                    self.after_cancel(self._de_cfg_job)
                except tk.TclError:
                    pass
            self._de_cfg_job = self.after(28, _layout_run)

        def _layout_run():
            self._de_cfg_job = None
            self._layout()

        self._canvas.bind("<Configure>", _on_canvas_resize)
        self._canvas.bind("<Button-1>", lambda e: self._entry.focus_set())
        self.bind("<Button-1>", lambda e: self._entry.focus_set())

    def _set_focus_ring(self, on):
        self._focus_ring = bool(on)
        self._layout()

    def _layout(self, event=None):
        if getattr(self, "_canvas", None) is None or getattr(self, "_entry", None) is None:
            return
        W = max(int(self._canvas.winfo_width()), 40)
        H = max(int(self._canvas.winfo_height()), 34)
        self._canvas.delete("edge", "face")
        r = self._radius
        edge = C["purple2"] if self._focus_ring else C["border"]
        ri = max(4, r - 2)
        _canvas_round_fill(self._canvas, 0, 0, W, H, r, edge, tag="edge", holder=self)
        _canvas_round_fill(self._canvas, 2, 2, W - 2, H - 2, ri, C["bg3"], tag="face", holder=self)
        inset_x = 10
        inset_y = max(5, (H - 22) // 2)
        ew = max(12, W - inset_x * 2)
        eh = max(18, H - inset_y * 2)
        try:
            self._entry.place(in_=self, x=inset_x, y=inset_y, width=ew, height=eh)
            self._entry.lift(self._canvas)
        except tk.TclError:
            pass

    def get(self):
        e = getattr(self, "_entry", None)
        return e.get() if e else ""

    def delete(self, first, last=None):
        e = getattr(self, "_entry", None)
        if e:
            return e.delete(first, last)

    def insert(self, index, string):
        e = getattr(self, "_entry", None)
        if e:
            return e.insert(index, string)

    def icursor(self, index):
        e = getattr(self, "_entry", None)
        if e:
            return e.icursor(index)

    def index(self, index):
        e = getattr(self, "_entry", None)
        if e:
            return e.index(index)

    def configure(self, cnf=None, **kw):
        if cnf and isinstance(cnf, dict):
            kw = dict(cnf, **kw)
        frame_kw = {}
        entry_kw = {}
        for k, v in list(kw.items()):
            if k in ("bg", "highlightbackground", "highlightthickness"):
                frame_kw[k] = v
            elif k in (
                "fg",
                "font",
                "show",
                "width",
                "state",
                "insertbackground",
                "exportselection",
            ):
                entry_kw[k] = v
        if frame_kw:
            super().configure(**frame_kw)
            try:
                if getattr(self, "_canvas", None):
                    self._canvas.configure(bg=self.cget("bg"))
            except tk.TclError:
                pass
        e = getattr(self, "_entry", None)
        if entry_kw and e is not None:
            e.configure(**entry_kw)
        if getattr(self, "_canvas", None) is not None:
            self.after_idle(self._layout)

    config = configure

    def bind(self, sequence=None, func=None, add=None):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.bind(sequence, func, add)
        return super().bind(sequence, func, add)

    def unbind(self, sequence):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.unbind(sequence)
        return super().unbind(sequence)

    def cget(self, key):
        e = getattr(self, "_entry", None)
        if e is not None and key in ("fg", "bg", "font", "show", "width", "state"):
            try:
                return e.cget(key)
            except tk.TclError:
                pass
        return super().cget(key)

    def focus_set(self):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.focus_set()
        return super().focus_set()

    def focus_force(self):
        e = getattr(self, "_entry", None)
        if e is not None:
            return e.focus_force()
        return super().focus_force()


class NavPillButton(tk.Canvas):
    """Botão da barra lateral com cantos arredondados."""

    _radius = 12

    def __init__(self, parent, text, command, **kwargs):
        self._text = text
        self._command = command
        self._active = False
        self._hover = False
        self._pressed = False
        kw = {k: v for k, v in kwargs.items() if k in ("cursor", "takefocus")}
        super().__init__(
            parent,
            height=40,
            highlightthickness=0,
            cursor=kw.get("cursor", "hand2"),
            takefocus=kw.get("takefocus", 0),
        )
        self.configure(bg=_tk_widget_bg(parent))
        self._np_cfg_job = None
        self.bind("<Configure>", self._on_np_configure_resize)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _on_np_configure_resize(self, _event=None):
        if self._np_cfg_job is not None:
            try:
                self.after_cancel(self._np_cfg_job)
            except tk.TclError:
                pass
        self._np_cfg_job = self.after(32, self._np_draw_after_resize)

    def _np_draw_after_resize(self):
        self._np_cfg_job = None
        self._draw()

    def set_active(self, active: bool):
        self._active = bool(active)
        self._draw()

    def _enter(self, _e=None):
        self._hover = True
        self._draw()

    def _leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _press(self, _e=None):
        self._pressed = True
        self._draw()

    def _release(self, event=None):
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self._command and event is not None:
            try:
                x, y = event.x, event.y
                if 0 <= x < int(self.winfo_width()) and 0 <= y < int(self.winfo_height()):
                    self._command()
            except tk.TclError:
                pass

    def _draw(self, event=None):
        w = max(int(self.winfo_width()), 20)
        h = max(int(self.winfo_height()), 36)
        self.delete("fill", "txt", "ring")
        if self._active:
            face = C["bg3"]
            fg = C["purple3"]
            edge = C["purple"]
        elif self._hover:
            face = C["bg3"]
            fg = C["text"]
            edge = C["border2"]
        else:
            face = C["bg2"]
            fg = C["text2"]
            edge = C["bg2"]
        rr = min(self._radius, h // 2 - 1)
        _canvas_round_fill(self, 2, 2, w - 2, h - 2, rr, edge, tag="ring", holder=self)
        ri = max(3, rr - 2)
        _canvas_round_fill(self, 3, 3, w - 3, h - 3, ri, face, tag="fill", holder=self)
        self.create_text(14, h // 2, text=self._text, anchor="w", fill=fg, font=("Segoe UI", 10), tags=("txt",))


class RoundedCard(tk.Canvas):
    """Painel com cantos arredondados; use ``.inner`` para o conteúdo."""

    def __init__(self, parent, *, radius=18, margin=12, fill_key="card", **kwargs):
        self._r = radius
        self._m = margin
        self._fill_key = fill_key if fill_key in C else "card"
        kw = {k: v for k, v in kwargs.items() if k in ("highlightthickness",)}
        super().__init__(parent, highlightthickness=kw.get("highlightthickness", 0), bg=_tk_widget_bg(parent))
        self.inner = tk.Frame(self, bg=C[self._fill_key])
        self._win_id = None
        self._rc_cfg_job = None
        self._rc_last_wh = None
        self.bind("<Configure>", self._on_rc_configure)

    def _on_rc_configure(self, _event=None):
        if self._rc_cfg_job is not None:
            try:
                self.after_cancel(self._rc_cfg_job)
            except tk.TclError:
                pass
        self._rc_cfg_job = self.after(24, self._refit_run)

    def _refit_run(self):
        self._rc_cfg_job = None
        self._refit()

    def _refit(self, event=None):
        W = max(int(self.winfo_width()), self._m * 2 + 40)
        H = max(int(self.winfo_height()), self._m * 2 + 40)
        if self._rc_last_wh == (W, H):
            return
        self._rc_last_wh = (W, H)
        self.delete("edge", "face")
        fill = C[self._fill_key]
        edge = C["border"]
        _canvas_round_fill(self, 0, 0, W, H, self._r, edge, tag="edge", holder=self)
        ri = max(4, self._r - 2)
        _canvas_round_fill(self, 2, 2, W - 2, H - 2, ri, fill, tag="face", holder=self)
        ix = self._m
        iy = self._m
        iw = max(20, W - 2 * self._m)
        ih = max(20, H - 2 * self._m)
        self.inner.configure(bg=fill)
        if self._win_id is None:
            self._win_id = self.create_window(ix, iy, window=self.inner, anchor="nw", width=iw, height=ih)
        else:
            self.coords(self._win_id, ix, iy)
            self.itemconfigure(self._win_id, width=iw, height=ih)


class ModernScrollbar(tk.Canvas):
    """
    Barra de scroll vertical ou horizontal com trilho e polegar arredondados
    (Pillow quando disponível; caso contrário vectorial).
    Compatível com ``canvas.yview`` / ``xview`` e ``set(frac_lo, frac_hi)``.
    """

    _pad = 5
    _min_thumb = 26

    def __init__(self, parent, command, orient="vertical", bar_width=12, **kwargs):
        self._command = command
        self._orient = str(orient or "vertical").lower()
        self._bw = max(10, int(bar_width))
        ibg = kwargs.pop("bg", _tk_widget_bg(parent))
        kwargs.setdefault("highlightthickness", 0)
        if self._orient == "vertical":
            super().__init__(parent, width=self._bw, bg=ibg, **kwargs)
        else:
            super().__init__(parent, height=self._bw, bg=ibg, **kwargs)
        self._ibg = ibg
        self._frac_lo = 0.0
        self._frac_hi = 1.0
        self._drag = False
        self._hover = False
        self._hover_thumb = False
        self._thumb_hit = None
        self._sb_cfg_job = None
        def _on_sb_configure(_e):
            if self._sb_cfg_job is not None:
                try:
                    self.after_cancel(self._sb_cfg_job)
                except tk.TclError:
                    pass
            self._sb_cfg_job = self.after(28, _sb_configure_draw)

        def _sb_configure_draw():
            self._sb_cfg_job = None
            self._draw()

        self.bind("<Configure>", _on_sb_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Motion>", self._on_motion_hover)
        self.after_idle(self._draw)
        try:
            cur = "sb_v_double_arrow" if self._orient == "vertical" else "sb_h_double_arrow"
            self.configure(cursor=cur)
        except tk.TclError:
            pass

    def _set_hover(self, on):
        self._hover = bool(on)
        if not on:
            self._hover_thumb = False
        if not self._drag:
            self._draw()

    def _on_motion_hover(self, e):
        if self._drag:
            return
        inside = self._hit_thumb(e.x, e.y)
        if inside != self._hover_thumb:
            self._hover_thumb = inside
            self._draw()

    def set(self, *args):
        """Callback ``yscrollcommand`` / ``xscrollcommand``."""
        try:
            if len(args) == 2:
                lo, hi = float(args[0]), float(args[1])
            elif len(args) == 1 and isinstance(args[0], (tuple, list)) and len(args[0]) >= 2:
                lo, hi = float(args[0][0]), float(args[0][1])
            else:
                return
        except (TypeError, ValueError, IndexError):
            return
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        if hi < lo:
            lo, hi = hi, lo
        self._frac_lo = lo
        self._frac_hi = hi
        self.after_idle(self._draw)

    def _trough_thumb_colors(self):
        trough = C.get("sb_trough", C.get("border", "#2a2a2a"))
        thumb = C.get("sb_thumb", C.get("border2", "#3a3a3a"))
        thumb_hot = C.get("sb_thumb_hover", C.get("border2", "#3a3a3a"))
        thumb_accent = C.get("sb_thumb_active", C.get("purple2", "#a78bfa"))
        return trough, thumb, thumb_hot, thumb_accent

    def _hit_thumb(self, x, y):
        h = self._thumb_hit
        if not h:
            return False
        x0, y0, x1, y1 = h
        return x0 <= x <= x1 and y0 <= y <= y1

    def _draw(self):
        self.delete("all")
        try:
            W = int(self.winfo_width())
            H = int(self.winfo_height())
        except tk.TclError:
            return
        if self._orient == "vertical":
            if W < 6 or H < 16:
                return
            self._draw_vertical(W, H)
        else:
            if H < 6 or W < 16:
                return
            self._draw_horizontal(W, H)

    def _draw_vertical(self, W, H):
        pad = self._pad
        track_x0, track_x1 = 2, W - 2
        track_y0, track_y1 = pad, H - pad
        track_w = max(4, track_x1 - track_x0)
        track_h = max(self._min_thumb * 2, track_y1 - track_y0)
        trough_c, thumb_c, thumb_hot, thumb_ac = self._trough_thumb_colors()
        r_tr = max(3, min(7, track_w // 2 - 1, track_h // 2 - 1))
        _canvas_round_fill_vector(
            self,
            float(track_x0),
            float(track_y0),
            float(track_x0 + track_w),
            float(track_y0 + track_h),
            r_tr,
            trough_c,
            tag="trough",
        )
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_h = max(self._min_thumb, int(delta * track_h + 0.5))
        thumb_h = min(thumb_h, track_h)
        if delta >= 1.0 - 1e-6:
            thumb_y = float(track_y0)
            thumb_h = int(track_h)
        else:
            span = max(1, track_h - thumb_h)
            thumb_y = float(track_y0) + (float(lo) / (1.0 - delta)) * float(span)
            thumb_y = max(float(track_y0), min(float(track_y0 + track_h - thumb_h), thumb_y))
        inset = max(1, min(3, track_w // 5))
        tx0 = float(track_x0 + inset)
        tx1 = float(track_x0 + track_w - inset)
        r_th = max(2, min(6, (tx1 - tx0) / 2.0 - 0.5))
        if self._drag:
            col = thumb_ac
        elif self._hover_thumb:
            col = thumb_hot
        else:
            col = thumb_c
        _canvas_round_fill_vector(self, tx0, thumb_y, tx1, thumb_y + float(thumb_h), r_th, col, tag="thumb")
        self._thumb_hit = (int(tx0), int(thumb_y), int(tx1), int(thumb_y + thumb_h))

    def _draw_horizontal(self, W, H):
        pad = self._pad
        track_y0, track_y1 = 2, H - 2
        track_x0, track_x1 = pad, W - pad
        track_h = max(4, track_y1 - track_y0)
        track_w = max(self._min_thumb * 2, track_x1 - track_x0)
        trough_c, thumb_c, thumb_hot, thumb_ac = self._trough_thumb_colors()
        r_tr = max(3, min(7, track_w // 2 - 1, track_h // 2 - 1))
        _canvas_round_fill_vector(
            self,
            float(track_x0),
            float(track_y0),
            float(track_x0 + track_w),
            float(track_y0 + track_h),
            r_tr,
            trough_c,
            tag="trough",
        )
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_w = max(self._min_thumb, int(delta * track_w + 0.5))
        thumb_w = min(thumb_w, track_w)
        if delta >= 1.0 - 1e-6:
            thumb_x = float(track_x0)
            thumb_w = int(track_w)
        else:
            span = max(1, track_w - thumb_w)
            thumb_x = float(track_x0) + (float(lo) / (1.0 - delta)) * float(span)
            thumb_x = max(float(track_x0), min(float(track_x0 + track_w - thumb_w), thumb_x))
        inset = max(1, min(3, track_h // 5))
        ty0 = float(track_y0 + inset)
        ty1 = float(track_y0 + track_h - inset)
        r_th = max(2, min(6, (ty1 - ty0) / 2.0 - 0.5))
        if self._drag:
            col = thumb_ac
        elif self._hover_thumb:
            col = thumb_hot
        else:
            col = thumb_c
        _canvas_round_fill_vector(self, thumb_x, ty0, thumb_x + float(thumb_w), ty1, r_th, col, tag="thumb")
        self._thumb_hit = (int(thumb_x), int(ty0), int(thumb_x + thumb_w), int(ty1))

    def _on_press(self, event):
        if self._orient == "vertical":
            self._press_vertical(event)
        else:
            self._press_horizontal(event)

    def _press_vertical(self, event):
        if not self._thumb_hit:
            self._draw()
        if not self._thumb_hit:
            return
        x0, y0, x1, y1 = self._thumb_hit
        if y0 <= event.y <= y1 and x0 <= event.x <= x1:
            self._drag = True
            self._draw()
        elif event.y < y0:
            self._command("scroll", -1, "pages")
        else:
            self._command("scroll", 1, "pages")

    def _press_horizontal(self, event):
        if not self._thumb_hit:
            self._draw()
        if not self._thumb_hit:
            return
        x0, y0, x1, y1 = self._thumb_hit
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self._drag = True
            self._draw()
        elif event.x < x0:
            self._command("scroll", -1, "pages")
        else:
            self._command("scroll", 1, "pages")

    def _on_motion(self, event):
        if not self._drag:
            return
        if self._orient == "vertical":
            self._motion_vertical(event)
        else:
            self._motion_horizontal(event)

    def _motion_vertical(self, event):
        pad = self._pad
        try:
            H = int(self.winfo_height())
        except tk.TclError:
            return
        track_y0, track_y1 = pad, H - pad
        track_h = max(self._min_thumb * 2, track_y1 - track_y0)
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_h = max(self._min_thumb, int(delta * track_h + 0.5))
        thumb_h = min(thumb_h, track_h)
        span = max(1, track_h - thumb_h)
        center = float(event.y)
        nlo = (center - float(track_y0) - float(thumb_h) * 0.5) / float(span) * (1.0 - delta)
        nlo = max(0.0, min(1.0 - delta, nlo))
        self._command("moveto", nlo)

    def _motion_horizontal(self, event):
        pad = self._pad
        try:
            W = int(self.winfo_width())
        except tk.TclError:
            return
        track_x0, track_x1 = pad, W - pad
        track_w = max(self._min_thumb * 2, track_x1 - track_x0)
        lo, hi = self._frac_lo, self._frac_hi
        delta = max(1e-9, float(hi) - float(lo))
        thumb_w = max(self._min_thumb, int(delta * track_w + 0.5))
        thumb_w = min(thumb_w, track_w)
        span = max(1, track_w - thumb_w)
        center = float(event.x)
        nlo = (center - float(track_x0) - float(thumb_w) * 0.5) / float(span) * (1.0 - delta)
        nlo = max(0.0, min(1.0 - delta, nlo))
        self._command("moveto", nlo)

    def _on_release(self, event):
        self._drag = False
        self._draw()


class ScrollableFrame(tk.Frame):
    """Scroll vertical; sincroniza largura do frame interno com o Canvas (evita texto espremido)."""

    def __init__(self, parent, inner_bg=None, **kwargs):
        ibg = inner_bg if inner_bg is not None else C["bg"]
        super().__init__(parent, bg=ibg, **kwargs)
        canvas = tk.Canvas(self, bg=ibg, highlightthickness=0)
        scrollbar = ModernScrollbar(self, canvas.yview, orient="vertical", bar_width=13, bg=ibg)
        self.inner = tk.Frame(canvas, bg=ibg)
        self._canvas = canvas
        inner_win = canvas.create_window((0, 0), window=self.inner, anchor="nw")

        _sr_job = [None]

        def _on_inner_configure(_event=None):
            if _sr_job[0] is not None:
                try:
                    self.after_cancel(_sr_job[0])
                except tk.TclError:
                    pass
            _sr_job[0] = self.after(24, _apply_scrollregion)

        def _apply_scrollregion():
            _sr_job[0] = None
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except tk.TclError:
                pass

        self._last_canvas_inner_w = None

        def _on_canvas_configure(event):
            # Sem isto, inner mantém largura ~1px e labels viram traços/pontos (Windows/Tk).
            try:
                w = int(event.width)
            except (TypeError, ValueError, tk.TclError):
                return
            if w < 2:
                return
            if self._last_canvas_inner_w == w:
                return
            self._last_canvas_inner_w = w
            try:
                canvas.itemconfigure(inner_win, width=w)
            except tk.TclError:
                pass

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _wheel_win(event):
            try:
                d = int(getattr(event, "delta", 0) or 0)
            except (TypeError, ValueError):
                d = 0
            if d:
                canvas.yview_scroll(int(-1 * (d / 120)), "units")
            return "break"

        def _wheel_linux_up(_event):
            canvas.yview_scroll(-1, "units")
            return "break"

        def _wheel_linux_down(_event):
            canvas.yview_scroll(1, "units")
            return "break"

        def _bind_wheel_recursive(widget):
            """Roda do rato passa nos filhos do inner, não no canvas — ligamos em toda a árvore."""
            try:
                widget.bind("<MouseWheel>", _wheel_win)
                widget.bind("<Button-4>", _wheel_linux_up)
                widget.bind("<Button-5>", _wheel_linux_down)
            except tk.TclError:
                return
            for ch in widget.winfo_children():
                _bind_wheel_recursive(ch)

        _rebind_job = [None]

        def _schedule_rebind_wheel(_event=None):
            if _rebind_job[0] is not None:
                try:
                    self.after_cancel(_rebind_job[0])
                except tk.TclError:
                    pass
            _rebind_job[0] = self.after(220, _run_rebind_wheel)

        def _run_rebind_wheel():
            _rebind_job[0] = None
            _bind_wheel_recursive(self.inner)

        def _on_inner_configure_full(event=None):
            _on_inner_configure(event)
            _schedule_rebind_wheel(event)

        self.inner.bind("<Configure>", _on_inner_configure_full)

        canvas.bind("<MouseWheel>", _wheel_win)
        canvas.bind("<Button-4>", _wheel_linux_up)
        canvas.bind("<Button-5>", _wheel_linux_down)
        scrollbar.bind("<MouseWheel>", _wheel_win)
        scrollbar.bind("<Button-4>", _wheel_linux_up)
        scrollbar.bind("<Button-5>", _wheel_linux_down)
        # Não forçar focus no canvas ao passar o rato: em Toplevel (janela do item) isto no Windows
        # pode empurrar a janela para segundo plano ou baralhar a ordem Z com a janela principal.

        def _sync_inner_width():
            try:
                w = canvas.winfo_width()
                if w > 1:
                    canvas.itemconfigure(inner_win, width=w)
            except tk.TclError:
                pass

        self.after_idle(_sync_inner_width)
        self.after_idle(_run_rebind_wheel)

    def yview_top(self):
        """Repor o scroll no topo (útil ao voltar a abrir Configurações)."""
        try:
            self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass

class ItemCard(tk.Frame):
    def __init__(self, parent, item, on_click, selected=False, thumb_loader=None, **kwargs):
        bg = C["card"] if not selected else "#1e0e40"
        super().__init__(parent, bg=bg, cursor="hand2", **kwargs)
        self.configure(pady=8, padx=10)

        # Borda colorida se selecionado
        border_color = C["purple"] if selected else C["border"]
        self.configure(highlightbackground=border_color, highlightthickness=1)

        thumb_slot = tk.Frame(self, bg=bg, width=44, height=44)
        thumb_slot.pack(side="left", padx=(0, 10))
        thumb_slot.pack_propagate(False)
        self._thumb_ref = None
        ic_url = _normalize_media_url(item.get("item_icon_url") or "")
        if ic_url and thumb_loader:
            ph = thumb_loader(ic_url)
            if ph:
                self._thumb_ref = ph
                tk.Label(thumb_slot, image=ph, bg=bg).place(relx=0.5, rely=0.5, anchor="center")
        if not self._thumb_ref:
            tk.Label(
                thumb_slot,
                text=item_emoji(item.get("name", "")),
                bg=bg,
                fg=C["text"],
                font=("Segoe UI", 16),
            ).place(relx=0.5, rely=0.5, anchor="center")

        info = tk.Frame(self, bg=bg)
        info.pack(side="left", fill="x", expand=True)

        raw_name = (item.get("item_card_title") or item.get("name") or "").strip()
        name_text = raw_name if raw_name else "Item Desconhecido"
        if item.get("is_costume"):
            name_text += "  [COSTUME]"
        tk.Label(info, text=name_text, bg=bg, fg=C["purple3"],
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        
        # Primeira linha: ID + Lojas Abertas
        info_row = tk.Frame(info, bg=bg)
        info_row.pack(fill="x")
        
        tk.Label(info_row, text=f"ID: {item.get('id', '?')}",
                 bg=bg, fg=C["text3"], font=("Segoe UI", 8), anchor="w").pack(side="left")
        
        # Mostra lojas abertas se tiver
        online_stores = item.get('online_stores', 0)
        if online_stores > 0:
            tk.Label(info_row, text=f"  •  🏪 {online_stores} loja(s) online",
                     bg=bg, fg=C["yellow"], font=("Segoe UI", 8, "bold")).pack(side="left")
        
        # Segunda linha: Preços mínimos por tipo de moeda
        min_prices = item.get('min_prices', {})
        if min_prices:
            prices_text_parts = []
            for sale_type in ["zeny", "rops", "hero_points", "rmt"]:
                if sale_type in min_prices:
                    price = min_prices[sale_type]
                    if sale_type == "zeny":
                        prices_text_parts.append(f"{fmt_price_stores(price)}Z")
                    elif sale_type == "rops":
                        prices_text_parts.append(f"{fmt_price_stores(price)}R$ (ROPS)")
                    elif sale_type == "hero_points":
                        prices_text_parts.append(f"{fmt_price_stores(price)} HP")
                    elif sale_type == "rmt":
                        prices_text_parts.append(f"{fmt_price_stores(price)}R$ (RMT)")
            
            if prices_text_parts:
                tk.Label(info, text="  •  ".join(prices_text_parts),
                         bg=bg, fg=C["green"], font=("Segoe UI", 8)).pack(fill="x")

        arrow = tk.Label(self, text="›", bg=bg, fg=C["text3"], font=("Segoe UI", 16))
        arrow.pack(side="right")

        # Bind clique em todos os filhos
        for w in [self, thumb_slot, info, arrow]:
            w.bind("<Button-1>", lambda e: on_click())
        for w in info.winfo_children():
            w.bind("<Button-1>", lambda e: on_click())
        for w in thumb_slot.winfo_children():
            w.bind("<Button-1>", lambda e: on_click())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        color = "#1d1038" if on else C["card"]
        self._set_bg(color)

    def _set_bg(self, color):
        self.configure(bg=color)
        for w in self.winfo_children():
            try:
                w.configure(bg=color)
                for c in w.winfo_children():
                    try: c.configure(bg=color)
                    except: pass
            except: pass


# ════════════════════════════════════════════════════════════════════════════
# ECRÃ DE ARRANQUE
# ════════════════════════════════════════════════════════════════════════════


class _StartupSplash(tk.Toplevel):
    """Janela modal com progresso enquanto a interface principal fica oculta."""

    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.title("Herosaga Monitor")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(master)
        fr = tk.Frame(self, bg=C["bg"], padx=36, pady=28)
        fr.pack(fill="both", expand=True)
        tk.Label(
            fr,
            text="⚔ HEROSAGA MONITOR",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            fr,
            text="A inicializar o sistema…",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 14))
        self._status = tk.Label(
            fr,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=380,
        )
        self._status.pack(anchor="w", fill="x", pady=(0, 10))
        self._prog = ttk.Progressbar(fr, mode="determinate", maximum=100, length=368)
        self._prog.pack(anchor="w")
        self.geometry("440x210")
        self.update_idletasks()
        w, h = 440, 210
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def set_progress(self, pct: float, msg: str) -> None:
        self._prog["value"] = max(0, min(100, float(pct)))
        self._status.configure(text=msg)
        self.update_idletasks()


# ════════════════════════════════════════════════════════════════════════════
# JANELA PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

class HeroSagaMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self._startup_complete = False
        self.title("Herosaga Monitor")
        self.geometry("1100x680")
        self.minsize(800, 550)
        self.configure(bg=C["bg"])

        # Tentar ícone
        try:
            self.iconbitmap("icon.ico")
        except Exception:
            pass

        self.current_items = []
        self.selected_item = None
        self.chart_canvas = None
        self._search_generation = 0
        self._item_detail_photo_ref = None
        self._alert_after_id = None
        self._monitored_home_photo_refs = []
        self._monitor_list_photo_refs = []
        self._alertas_list_photo_refs = []
        self._monitored_home_refresh_gen = 0
        self._alerts_display_refresh_gen = 0
        self._mh_drag = {"active": False}
        self._mh_inners = {}
        self._mh_col_shells = {}
        self._mh_cards_by_id = {}
        self._mh_drag_indicator = None
        self._mh_drag_indicator_category = None
        self._mh_icon_load_gen = 0
        self._mh_prices_refreshing = False
        self._item_icon_photo_ram = {}

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self._style()
        self.withdraw()

        splash = _StartupSplash(self)
        splash.update()
        splash.protocol("WM_DELETE_WINDOW", lambda sp=splash: self._cancel_startup_load(sp))

        try:
            splash.grab_set()
        except tk.TclError:
            pass

        try:
            splash.set_progress(5, "A carregar dados locais…")
            self.data = load_data()

            splash.set_progress(28, "A construir janelas e painéis…")
            self._build_ui()

            splash.set_progress(58, "A carregar definições e ficheiros de apoio…")
            self._startup_preload_auxiliary_data()

            splash.set_progress(72, "A carregar catálogo MVP…")
            self._mvp_startup_warm()

            splash.set_progress(84, "A preparar o monitor de alertas…")
            self._update_badge()
            self._schedule_alert_monitor_cycle()

            splash.set_progress(93, "A preparar gráficos e fontes…")
            self._startup_warmup()

            splash.set_progress(100, "Concluído.")
            splash.update_idletasks()
        except Exception:
            try:
                splash.grab_release()
            except tk.TclError:
                pass
            try:
                splash.destroy()
            except tk.TclError:
                pass
            try:
                self.deiconify()
            except tk.TclError:
                pass
            raise
        else:
            try:
                splash.grab_release()
            except tk.TclError:
                pass
            try:
                splash.destroy()
            except tk.TclError:
                pass
            self.deiconify()
            self.lift()
            try:
                self.focus_force()
            except tk.TclError:
                pass

        self._startup_complete = True

    def _cancel_startup_load(self, splash: tk.Toplevel) -> None:
        try:
            splash.grab_release()
        except tk.TclError:
            pass
        try:
            splash.destroy()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _startup_preload_auxiliary_data(self) -> None:
        for fn in (
            load_settings,
            load_mvp_storage,
            load_builds_file,
            load_prices_history,
        ):
            try:
                fn()
            except Exception:
                logger.debug("Falha no pré-load de arranque: %s", getattr(fn, "__name__", repr(fn)), exc_info=True)

    def _on_close_request(self):
        try:
            if hasattr(self, "_build_sim_persist_last_saved_id"):
                self._build_sim_persist_last_saved_id()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _startup_warmup(self):
        """Pré-aquece Tk/PIL para o primeiro arrasto e redesenho ficarem mais fluidos."""
        try:
            self.update_idletasks()
            self.tk.call("font", "metrics", "Segoe UI", "-ascent")
        except tk.TclError:
            pass
        if _HAS_PIL_ROUND:
            try:
                _pil_round_solid(10, 10, 3, C.get("card", "#2a2a2a"))
            except Exception:
                pass

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        # Scrollbars — trilho/polegar com cores dedicadas (evita thumb = trough no tema claro).
        sb_trough = C.get("sb_trough", C.get("border", C["bg3"]))
        sb_thumb = C.get("sb_thumb", C.get("bg3", "#1a1a1a"))
        sb_thumb_hover = C.get("sb_thumb_hover", C.get("border2", "#3a3a3a"))
        sb_thumb_pressed = C.get("sb_thumb_active", C.get("purple", "#8b5cf6"))
        style.configure(
            "TScrollbar",
            background=sb_thumb,
            troughcolor=sb_trough,
            bordercolor=sb_trough,
            darkcolor=sb_thumb,
            lightcolor=sb_thumb,
            arrowcolor=C.get("text3", "#737373"),
            borderwidth=0,
            relief="flat",
            gripcount=0,
            width=11,
        )
        try:
            style.configure("TScrollbar", arrowsize=11)
        except tk.TclError:
            pass
        style.map(
            "TScrollbar",
            background=[
                ("pressed", sb_thumb_pressed),
                ("active", sb_thumb_hover),
                ("!disabled", sb_thumb),
            ],
            arrowcolor=[
                ("pressed", C.get("purple3", C["text2"])),
                ("active", C.get("text2", "#b0b0b0")),
                ("!disabled", C.get("text3", "#737373")),
            ],
        )
        style.configure("Treeview",
                        background=C["card"], foreground=C["text2"],
                        fieldbackground=C["card"], rowheight=30,
                        font=("Segoe UI", 9))
        style.configure(
            "Treeview.Heading",
            background=C.get("column_hdr", C["bg3"]),
            foreground=C.get("column_hdr_fg", C["text2"]),
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padding=(4, 6),
        )
        # Sem map explícito, alguns builds Windows/ttk deixam o cabeçalho sem contraste ou altura ~0.
        style.map(
            "Treeview.Heading",
            background=[
                ("active", C.get("border2", C["bg3"])),
                ("pressed", C.get("border2", C["bg3"])),
                ("!disabled", C.get("column_hdr", C["bg3"])),
            ],
            foreground=[
                ("active", C.get("column_hdr_fg", C["text2"])),
                ("pressed", C.get("column_hdr_fg", C["text2"])),
                ("!disabled", C.get("column_hdr_fg", C["text2"])),
            ],
        )
        style.map("Treeview", background=[("selected", C["border2"])],
                  foreground=[("selected", C["purple3"])])

    def _build_ui(self):
        # ── Sidebar ─────────────────────────────────────────────────────────
        sidebar = tk.Frame(self, bg=C["bg2"], width=200)
        self.sidebar_frame = sidebar
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Logo
        logo_frame = tk.Frame(sidebar, bg=C["bg2"])
        logo_frame.pack(fill="x", padx=14, pady=(16, 12))
        tk.Label(logo_frame, text="⚔", bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 18)).pack(side="left")
        tk.Label(logo_frame, text=" HEROSAGA", bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")

        tk.Frame(sidebar, bg=C["border"], height=1).pack(fill="x", padx=10, pady=(0, 10))

        # Navegação
        self.nav_frames = {}
        self.current_page = tk.StringVar(value="busca")

        nav_items = [
            ("busca",   "🔍  Buscar Item",    self._show_busca),
            ("monitor", "🔔  Monitorados",    self._show_monitor),
            ("build",   "📐  Simulação de Build", self._show_build_sim),
            ("mvp",     "⏱  Timer MVP",     self._show_mvp_timer),
            ("alertas", "🔊  Alertas",        self._show_alertas),
            ("config",  "⚙  Configurações", self._show_config),
            ("hist",    "📋  Histórico",      self._show_hist),
        ]
        for key, label, cmd in nav_items:
            btn = NavPillButton(sidebar, text=label, command=lambda k=key, c=cmd: self._nav(k, c))
            btn.pack(fill="x", padx=8, pady=3)
            self.nav_frames[key] = btn

        # Badge contador (frame fixo + place para não sair do botão)
        self.badge_fr = tk.Frame(self.nav_frames["monitor"], bg=C["purple"], width=22, height=18)
        self.badge_fr.pack_propagate(False)
        self.badge_lbl = tk.Label(
            self.badge_fr,
            text="",
            bg=C["purple"],
            fg="white",
            font=("Segoe UI", 7, "bold"),
        )
        self.badge_lbl.pack(expand=True)

        # Footer sidebar
        tk.Frame(sidebar, bg=C["border"], height=1).pack(fill="x", padx=10, pady=8, side="bottom")
        tk.Label(sidebar, text="herosaga.com.br", bg=C["bg2"], fg=C["text3"],
                 font=("Segoe UI", 8)).pack(side="bottom", pady=(0, 8))
        self.status_dot = tk.Label(sidebar, text="● online", bg=C["bg2"], fg=C["green"],
                                   font=("Segoe UI", 8))
        self.status_dot.pack(side="bottom")
        
        # Link para abrir logs
        log_link = tk.Label(sidebar, text="📋 Logs", bg=C["bg2"], fg=C["purple2"],
                           font=("Segoe UI", 8, "underline"), cursor="hand2")
        log_link.pack(side="bottom", pady=(2, 0))
        log_link.bind("<Button-1>", lambda e: self._open_logs())

        # ── Área principal ───────────────────────────────────────────────────
        self.main = tk.Frame(self, bg=C["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        self._build_busca()
        self._build_monitor()
        self._build_alertas()
        self._build_config()
        self._build_build_sim()
        self._build_mvp_timer()
        self._build_hist()

        self._nav("busca", self._show_busca)

    def _reapply_theme(self, theme: str):
        """Aplica paleta e reconstrói barra lateral e área principal."""
        apply_palette(theme)
        self.configure(bg=C["bg"])
        self._style()
        try:
            self.sidebar_frame.destroy()
        except (tk.TclError, AttributeError):
            pass
        try:
            self.main.destroy()
        except (tk.TclError, AttributeError):
            pass
        self._build_ui()
        self._update_badge()

    def _nav(self, key, cmd):
        self.current_page.set(key)
        for k, btn in self.nav_frames.items():
            if hasattr(btn, "set_active"):
                btn.set_active(k == key)
            elif k == key:
                btn.configure(bg=C["bg3"], fg=C["purple3"])
            else:
                btn.configure(bg=C["bg2"], fg=C["text2"])
        cmd()

    def _open_logs(self):
        """Abre o arquivo de log do Windows"""
        try:
            os.startfile(LOG_FILE)
            logger.info("Log file opened by user")
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o arquivo de log:\n{e}")
            logger.error(f"Failed to open log file: {e}")

    def _clear_main(self):
        for w in self.main.winfo_children():
            w.pack_forget()

    def _list_search_query(self, prefix: str) -> str:
        try:
            var = getattr(self, f"_{prefix}_search_var")
            return str(var.get() or "").strip()
        except (tk.TclError, AttributeError):
            return ""

    def _list_search_show_busy(self, prefix: str) -> None:
        lbl = getattr(self, f"_{prefix}_search_hint", None)
        if lbl is None:
            return
        try:
            if self._list_search_query(prefix):
                lbl.configure(text="Filtrando…")
            else:
                lbl.configure(text="")
        except tk.TclError:
            pass

    def _list_search_update_hint(self, prefix: str, shown: int, total: int) -> None:
        lbl = getattr(self, f"_{prefix}_search_hint", None)
        if lbl is None:
            return
        q = self._list_search_query(prefix)
        try:
            if not q:
                lbl.configure(text="")
            elif shown == 0:
                lbl.configure(text="Nenhum resultado")
            elif shown < total:
                lbl.configure(text=f"{shown} de {total}")
            else:
                lbl.configure(text=f"{shown} resultado(s)" if shown != 1 else "1 resultado")
        except tk.TclError:
            pass

    def _list_search_scroll_to_top(self, scroll_frame) -> None:
        canvas = getattr(scroll_frame, "_canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _list_search_on_change(self, prefix: str) -> None:
        aid = getattr(self, f"_{prefix}_search_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
        self.after(0, lambda p=prefix: self._list_search_show_busy(p))
        setattr(
            self,
            f"_{prefix}_search_after_id",
            self.after(_LIST_SEARCH_DEBOUNCE_MS, lambda p=prefix: self._list_search_apply(p)),
        )

    def _list_search_apply(self, prefix: str) -> None:
        setattr(self, f"_{prefix}_search_after_id", None)
        renderers = {
            "mh": self._render_monitored_home,
            "monitor": self._render_monitor,
            "alertas": self._render_alertas,
        }
        cb = renderers.get(prefix)
        if cb is None:
            return
        if prefix == "mh" and self.current_page.get() != "busca":
            return
        if prefix == "monitor" and self.current_page.get() != "monitor":
            return
        if prefix == "alertas" and self.current_page.get() != "alertas":
            return
        try:
            cb()
        except tk.TclError:
            pass

    def _pack_list_search_bar(self, parent, prefix: str, label_text: str) -> None:
        """Campo de busca local com debounce (comportamento do Timer MVP)."""
        if not hasattr(self, f"_{prefix}_search_var"):
            setattr(self, f"_{prefix}_search_var", tk.StringVar(value=""))
            setattr(self, f"_{prefix}_search_after_id", None)
        var = getattr(self, f"_{prefix}_search_var")

        fr = tk.Frame(parent, bg=C["bg"])
        fr.pack(fill="x")
        tk.Label(
            fr,
            text=label_text,
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 10),
        ).pack(side="left")
        tk.Entry(
            fr,
            textvariable=var,
            width=42,
            font=("Segoe UI", 10),
            bg=C["bg3"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["purple"],
        ).pack(side="left", padx=(10, 6), ipady=4)
        hint = tk.Label(
            fr,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9, "italic"),
        )
        hint.pack(side="left", padx=(4, 0))
        setattr(self, f"_{prefix}_search_hint", hint)

        bound = getattr(self, f"_{prefix}_search_trace_bound", False)
        if not bound:
            var.trace_add("write", lambda *_a, p=prefix: self._list_search_on_change(p))
            setattr(self, f"_{prefix}_search_trace_bound", True)

    # ── PÁGINA: BUSCA ────────────────────────────────────────────────────────
    def _build_busca(self):
        self.busca_frame = tk.Frame(self.main, bg=C["bg"])

        # Header
        hdr = tk.Frame(self.busca_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 0))
        tk.Label(hdr, text="Monitoramento Herosaga", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")

        # Search bar
        search_frame = tk.Frame(self.busca_frame, bg=C["bg"])
        search_frame.pack(fill="x", padx=20, pady=12)

        entry_wrap = tk.Frame(search_frame, bg=C["bg"])
        entry_wrap.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.search_entry = DarkEntry(entry_wrap)
        self.search_entry.pack(fill="x", pady=2)
        self.search_entry.insert(0, "Ex: Mana Sombria, Espada, Poção...")
        self.search_entry.configure(fg=C["text3"])
        # add="+" para não substituir os handlers internos do DarkEntry (foco / redesenho).
        self.search_entry.bind("<FocusIn>", self._entry_focus_in, add="+")
        self.search_entry.bind("<FocusOut>", self._entry_focus_out, add="+")
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        DarkButton(search_frame, text="  Buscar  ", style="primary",
                   command=self._do_search).pack(side="left", padx=(8, 0))

        # ── Home: itens monitorados (atalhos) ───────────────────────────────
        self.monitored_home_outer = tk.Frame(self.busca_frame, bg=C["bg"])
        self.monitored_home_outer.pack(fill="both", expand=True, padx=0, pady=(4, 0))
        mh_hdr = tk.Frame(self.monitored_home_outer, bg=C["bg"])
        mh_hdr.pack(fill="x", padx=20, pady=(4, 2))
        tk.Label(
            mh_hdr,
            text="Itens monitorados",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", anchor="w")
        mh_search_row = tk.Frame(self.monitored_home_outer, bg=C["bg"])
        mh_search_row.pack(fill="x", padx=20, pady=(4, 0))
        self._pack_list_search_bar(mh_search_row, "mh", "Buscar item (nome ou ID):")
        mh_strip = tk.Frame(self.monitored_home_outer, bg=C["bg"])
        mh_strip.pack(fill="both", expand=True, padx=20, pady=(2, 16))
        self.mh_body = tk.Frame(mh_strip, bg=C["bg"])
        self.mh_body.pack(fill="both", expand=True)

        self._search_results_win = None
        self.items_label = None
        self.items_scroll = None

    def _entry_focus_in(self, e):
        if self.search_entry.get() == "Ex: Mana Sombria, Espada, Poção...":
            self.search_entry.delete(0, "end")
            self.search_entry.configure(fg=C["text"])

    def _entry_focus_out(self, e):
        if not self.search_entry.get():
            self.search_entry.insert(0, "Ex: Mana Sombria, Espada, Poção...")
            self.search_entry.configure(fg=C["text3"])

    def _show_busca(self):
        self._clear_main()
        self.busca_frame.pack(fill="both", expand=True)
        self._render_monitored_home()

    def _bind_click_open_item_detail(self, widget, item_id: int, item_name: str = ""):
        """Clique abre janela com lojas e histórico do item."""

        def go(_event=None, iid=item_id, nm=item_name):
            self._open_item_detail_window(item_id=iid, item_name_hint=nm or "")

        widget.bind("<Button-1>", go)
        widget.configure(cursor="hand2")
        for c in widget.winfo_children():
            self._bind_click_open_item_detail(c, item_id, item_name)

    def _clipboard_copy_ws_item_id(self, n: int):
        """Copia ``@ws <id>`` para a área de transferência (comando do jogo)."""
        try:
            self.clipboard_clear()
            self.clipboard_append(f"@ws {int(n)}")
            self.update_idletasks()
        except (tk.TclError, TypeError, ValueError):
            logger.warning("Clipboard: falha ao copiar @ws %s", n)

    def _pack_item_store_snapshot_row(
        self,
        parent,
        entry: dict,
        photo_refs: list,
        *,
        wraplength: int = 520,
        layout: str = "stack",
        id_subline=None,
        footer_labels=None,
        show_ws_copy=False,
        drag_handle_monitored=None,
        card_pack_fill_x=True,
        title_wraplength=None,
        icon_slot_px=None,
        compact_text_column=False,
        defer_icon_load=False,
        price_label_holder=None,
        static_incomplete=False,
    ):
        """
        Cartão com ícone, nome, ID, menores por moeda (mesmo formato da home).
        layout: 'stack' — linha única como na home; 'split' — coluna esquerda
          (clique para busca) + espaço à direita para botões (empacote após o return).
        Devolve (card, row, bind_target) para associar clique à busca por ID.
        drag_handle_monitored: {'iid': int, 'category': str} — alça «⠿» para arrastar entre categorias (só stack).
        card_pack_fill_x: na home usa True; no fantasma de arrasto use False para não esticar à largura da janela.
        title_wraplength: se definido, quebra o nome do item (útil no fantasma com largura fixa).
        icon_slot_px: largura/altura da caixa do ícone (omissão: 56).
        compact_text_column: no fantasma de arrasto use True — evita ``fill=y`` extra sob o texto.
        """
        name = entry.get("name") or entry.get("item_name") or "Item"
        eid = entry.get("id")
        if eid is None:
            eid = entry.get("item_id")
        eid_str = str(eid) if eid is not None else "?"

        card = tk.Frame(
            parent,
            bg=C["card"],
            highlightbackground=C["border"],
            highlightthickness=1,
        )
        if card_pack_fill_x:
            card.pack(fill="x", pady=4)
        else:
            card.pack(anchor="nw", pady=4)

        if layout == "split":
            row = tk.Frame(card, bg=C["card"])
            row.pack(fill="x", padx=10, pady=8)
            content = tk.Frame(row, bg=C["card"])
            content.pack(side="left", fill="both", expand=True)
            host = tk.Frame(content, bg=C["card"])
            host.pack(fill="x", anchor="w")
            bind_target = content
        else:
            if drag_handle_monitored:
                strip = tk.Frame(card, bg=C["card"])
                strip.pack(fill="x")
                dh = drag_handle_monitored
                iid_h = int(dh["iid"])
                cat_h = str(dh["category"])
                hlab = tk.Label(
                    strip,
                    text="⠿",
                    bg=C["card"],
                    fg=C["text3"],
                    cursor="hand2",
                    font=("Segoe UI", 12),
                )
                hlab.pack(side="left", padx=(6, 2), pady=8, anchor="n")
                hlab.bind(
                    "<ButtonPress-1>",
                    lambda e, ii=iid_h, cc=cat_h, nm=(name or "").strip(), snap=dict(entry): self._mh_drag_begin(
                        e, ii, cc, nm, snap
                    ),
                )
                row = tk.Frame(strip, bg=C["card"])
                row.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)
            else:
                row = tk.Frame(card, bg=C["card"])
                row.pack(fill="x", padx=10, pady=8)
            content = row
            host = row
            bind_target = row

        icon_sz = 56 if icon_slot_px is None else max(40, min(72, int(icon_slot_px)))
        icon_fr = tk.Frame(host, bg=C["card"], width=icon_sz, height=icon_sz)
        icon_fr.pack(side="left", padx=(0, 10))
        icon_fr.pack_propagate(False)
        url = _normalize_media_url(entry.get("item_icon_url") or "")
        icon_lbl = tk.Label(
            icon_fr,
            text=item_emoji(name),
            bg=C["card"],
            fg=C["text2"],
            font=("Segoe UI", 20),
        )
        icon_lbl.place(relx=0.5, rely=0.5, anchor="center")
        if defer_icon_load:
            card._mh_icon_fr = icon_fr
            card._mh_icon_lbl = icon_lbl
            try:
                card._mh_icon_item_id = int(eid) if eid is not None else None
            except (TypeError, ValueError):
                card._mh_icon_item_id = None
            card._mh_icon_url = url
            card._mh_icon_max = min(52, icon_sz - 4)
        elif url:
            try:
                iid_icon = int(eid) if eid is not None else None
            except (TypeError, ValueError):
                iid_icon = None
            ph = self._load_item_icon_photo(url, max_size=min(52, icon_sz - 4), item_id=iid_icon)
            if ph:
                photo_refs.append(ph)
                icon_lbl.configure(image=ph, text="")
                icon_lbl.image = ph
            else:
                icon_lbl.configure(text=item_emoji(name))
        else:
            icon_lbl.configure(text=item_emoji(name))

        txt = tk.Frame(host, bg=C["card"])
        if compact_text_column:
            txt.pack(side="left", fill="x", expand=True, anchor="n")
        else:
            txt.pack(side="left", fill="both", expand=True)
        name_kw = dict(
            text=name,
            bg=C["card"],
            fg=C["purple3"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        if title_wraplength is not None:
            try:
                name_kw["wraplength"] = max(80, int(title_wraplength))
            except (TypeError, ValueError):
                pass
        tk.Label(txt, **name_kw).pack(fill="x")
        sub = id_subline if id_subline is not None else f"ID: {eid_str}  ·  clique para abrir janela"
        if static_incomplete:
            sub = f"{sub}  ·  ⚠ dados incompletos"
        tk.Label(
            txt,
            text=sub,
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x")
        price_lbl = tk.Label(
            txt,
            text=_format_home_min_prices_for_monitored(entry),
            bg=C["card"],
            fg=C["green"],
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=wraplength,
            justify="left",
        )
        price_lbl.pack(fill="x", pady=(2, 0))
        card._mh_price_lbl = price_lbl
        if price_label_holder is not None:
            price_label_holder.append(price_lbl)

        for foot in footer_labels or ():
            pady = foot.get("pady")
            pack_kw = {"fill": "x", "anchor": "w"}
            if pady is not None:
                pack_kw["pady"] = pady
            tk.Label(
                txt,
                text=foot.get("text", ""),
                bg=C["card"],
                fg=foot.get("fg", C["text2"]),
                font=foot.get("font", ("Segoe UI", 8)),
                anchor="w",
                wraplength=foot.get("wraplength", wraplength),
                justify=foot.get("justify", "left"),
            ).pack(**pack_kw)

        if show_ws_copy and eid is not None:
            try:
                eid_int = int(eid)
            except (TypeError, ValueError):
                eid_int = None
            if eid_int is not None:
                wf = tk.Frame(card, bg=C["card"])
                wf.pack(fill="x", padx=10, pady=(0, 6))
                DarkButton(
                    wf,
                    text="📋  Copiar @ws",
                    style="ghost",
                    font=("Segoe UI", 8, "bold"),
                    padx=8,
                    pady=2,
                    command=lambda rid=eid_int: self._clipboard_copy_ws_item_id(rid),
                ).pack(anchor="w")

        if drag_handle_monitored:
            try:
                card._mh_item_id = int(drag_handle_monitored["iid"])
                card._mh_category = str(drag_handle_monitored["category"])
            except (TypeError, ValueError, KeyError):
                pass

        return card, row, bind_target

    def _monitor_categories_list(self):
        cats = self.data.get("monitor_categories")
        if not isinstance(cats, list) or not cats:
            return list(DEFAULT_MONITOR_CATEGORIES)
        return list(cats)

    def _monitor_home_layout_dims(self):
        """(largura_mínima_coluna_px, meta_categorias_visíveis) para a grade da home."""
        s = load_settings()
        try:
            wmin = int(s.get("monitor_home_col_min_width") or MH_HOME_CATEGORY_COL_MIN_WIDTH)
        except (TypeError, ValueError):
            wmin = MH_HOME_CATEGORY_COL_MIN_WIDTH
        wmin = max(160, min(600, wmin))
        try:
            vis = int(s.get("monitor_home_min_visible_cols") or MH_HOME_MIN_VISIBLE_CATEGORY_COLS)
        except (TypeError, ValueError):
            vis = MH_HOME_MIN_VISIBLE_CATEGORY_COLS
        vis = max(1, min(8, vis))
        return wmin, vis

    def _persist_monitored_data_async(self) -> None:
        """Grava ``herosaga_monitor_data.json`` em thread (não bloqueia UI)."""
        try:
            snapshot = json.loads(json.dumps(self.data, ensure_ascii=False))
        except Exception:
            snapshot = dict(self.data)

        def _run():
            try:
                save_data(snapshot)
            except Exception:
                logger.exception("Falha ao gravar dados monitorados em segundo plano")

        threading.Thread(target=_run, name="SaveMonitoredData", daemon=True).start()

    def _mh_clear_drop_indicator(self) -> None:
        ind = getattr(self, "_mh_drag_indicator", None)
        if ind is not None:
            try:
                ind.destroy()
            except tk.TclError:
                pass
        self._mh_drag_indicator = None
        self._mh_drag_indicator_category = None

    def _mh_drop_line_screen_geometry(self, inner, cards: list, insert_index: int):
        """Rectângulo em coordenadas de ecrã para a barra de inserção (Toplevel)."""
        try:
            inner.update_idletasks()
            ix = int(inner.winfo_rootx())
            iy = int(inner.winfo_rooty())
            iw = int(inner.winfo_width())
            ih = int(inner.winfo_height())
        except tk.TclError:
            return None
        if iw < 8 or ih < 8:
            return None
        pad_x = 10
        bar_h = 6
        x = ix + pad_x
        w = max(48, iw - 2 * pad_x)
        if not cards:
            y = iy + 8
        elif insert_index < len(cards):
            try:
                target = cards[insert_index]
                y = int(target.winfo_rooty()) - bar_h // 2 - 1
            except tk.TclError:
                y = iy + 8
        else:
            try:
                last = cards[-1]
                y = int(last.winfo_rooty()) + int(last.winfo_height()) + 2
            except tk.TclError:
                y = iy + ih - bar_h - 4
        return x, y, w, bar_h

    def _mh_is_drop_indicator_widget(self, widget) -> bool:
        return bool(getattr(widget, "_mh_drop_indicator", False))

    def _mh_category_card_widgets(self, inner) -> list:
        """Cartões monitorados no ``inner`` da categoria (ignora indicador e rótulos vazios)."""
        if inner is None:
            return []
        out = []
        try:
            for ch in inner.winfo_children():
                if self._mh_is_drop_indicator_widget(ch):
                    continue
                if getattr(ch, "_mh_item_id", None) is not None:
                    out.append(ch)
        except tk.TclError:
            pass
        return out

    def _mh_get_insert_index(self, inner, y_root: int, exclude_iid: Optional[int] = None) -> int:
        """Índice de inserção na categoria segundo a posição Y do rato (exclui o card em arrasto)."""
        idx = 0
        for card in self._mh_category_card_widgets(inner):
            try:
                ci = int(getattr(card, "_mh_item_id", None))
            except (TypeError, ValueError):
                continue
            if exclude_iid is not None and ci == int(exclude_iid):
                continue
            try:
                mid_y = card.winfo_rooty() + card.winfo_height() // 2
            except tk.TclError:
                continue
            if y_root < mid_y:
                return idx
            idx += 1
        return idx

    def _mh_find_card(self, iid: int):
        try:
            want = int(iid)
        except (TypeError, ValueError):
            return None
        by_id = getattr(self, "_mh_cards_by_id", None) or {}
        hit = by_id.get(want)
        if hit is not None:
            try:
                if hit.winfo_exists():
                    return hit
            except tk.TclError:
                pass
        for inner in (getattr(self, "_mh_inners", None) or {}).values():
            for ch in self._mh_category_card_widgets(inner):
                try:
                    if int(getattr(ch, "_mh_item_id", None)) == want:
                        return ch
                except (TypeError, ValueError):
                    continue
        return None

    def _mh_card_from_widget(self, widget):
        w = widget
        while w is not None:
            if getattr(w, "_mh_item_id", None) is not None:
                return w
            try:
                w = w.master
            except (tk.TclError, AttributeError):
                break
        return None

    def _mh_create_monitored_card_at_index(
        self,
        inner,
        entry: dict,
        category: str,
        insert_index: int,
        col_min_w: int,
    ):
        """Cria um único cartão na categoria (inserção por índice; outro master)."""
        self._mh_clear_category_empty_placeholder(inner)
        others = self._mh_category_card_widgets(inner)
        insert_index = min(max(0, int(insert_index)), len(others))
        try:
            iid = int(entry["id"])
        except (TypeError, ValueError, KeyError):
            return None, None
        card, _, bind_target = self._pack_item_store_snapshot_row(
            inner,
            entry,
            self._monitored_home_photo_refs,
            wraplength=max(160, col_min_w - 36),
            layout="stack",
            id_subline=f"ID: {entry.get('id', '?')}  ·  nova janela",
            show_ws_copy=True,
            drag_handle_monitored={"iid": iid, "category": category},
            defer_icon_load=True,
            static_incomplete=_monitored_static_incomplete(entry),
        )
        card._mh_category = str(category)
        try:
            card.pack_forget()
        except tk.TclError:
            pass
        pack_kw = dict(fill="x", pady=4)
        try:
            if insert_index < len(others):
                card.pack(before=others[insert_index], **pack_kw)
            elif others:
                card.pack(after=others[-1], **pack_kw)
            else:
                card.pack(**pack_kw)
        except tk.TclError:
            pass
        try:
            inner.update_idletasks()
        except tk.TclError:
            pass
        return card, bind_target

    def _mh_try_apply_cached_icon_for_card(self, item_id: int, card) -> None:
        if card is None:
            return
        try:
            max_sz = int(getattr(card, "_mh_icon_max", 52) or 52)
        except (TypeError, ValueError):
            max_sz = 52
        ph = self._item_icon_photo_ram.get((int(item_id), max_sz))
        if ph is None:
            url = getattr(card, "_mh_icon_url", None) or ""
            entry_url = ""
            for m in self.data.get("monitored") or []:
                try:
                    if int(m.get("id")) == int(item_id):
                        entry_url = _normalize_media_url(m.get("item_icon_url") or "")
                        break
                except (TypeError, ValueError):
                    continue
            ph = self._load_item_icon_photo(entry_url or url, max_size=max_sz, item_id=int(item_id))
        if ph is None:
            return
        self._monitored_home_photo_refs.append(ph)
        lbl = getattr(card, "_mh_icon_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(image=ph, text="")
                lbl.image = ph
            except tk.TclError:
                pass

    def _mh_repack_card(self, card, inner, insert_index: int) -> None:
        """Reposiciona um cartão existente na mesma categoria (mesmo master)."""
        others = [c for c in self._mh_category_card_widgets(inner) if c is not card]
        try:
            card.pack_forget()
        except tk.TclError:
            pass
        insert_index = min(max(0, int(insert_index)), len(others))
        pack_kw = dict(fill="x", pady=4)
        try:
            if insert_index < len(others):
                card.pack(before=others[insert_index], **pack_kw)
            elif others:
                card.pack(after=others[-1], **pack_kw)
            else:
                card.pack(**pack_kw)
        except tk.TclError:
            pass

    def _mh_clear_category_empty_placeholder(self, inner) -> None:
        for ch in list(inner.winfo_children()):
            if self._mh_is_drop_indicator_widget(ch):
                continue
            if getattr(ch, "_mh_item_id", None) is not None:
                continue
            try:
                ch.destroy()
            except tk.TclError:
                pass

    def _mh_ensure_empty_category_placeholder(self, inner, cat: str) -> None:
        if self._mh_category_card_widgets(inner):
            return
        tk.Label(
            inner,
            text="(sem itens nesta categoria)",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=12)

    def _monitored_splice_category_block(self, monitored: list, category: str, ordered_entries: list) -> list:
        """Substitui o bloco de uma categoria na lista ``monitored`` mantendo o resto."""
        cat = str(category)
        new_monitored = []
        emitted = False
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                new_monitored.append(m)
                continue
            if not emitted:
                new_monitored.extend(ordered_entries)
                emitted = True
        if not emitted:
            new_monitored.extend(ordered_entries)
        return new_monitored

    def _mh_widget_contains_screen(self, widget, x_root: int, y_root: int) -> bool:
        try:
            x1 = int(widget.winfo_rootx())
            y1 = int(widget.winfo_rooty())
            w = int(widget.winfo_width())
            h = int(widget.winfo_height())
        except tk.TclError:
            return False
        if w < 2 or h < 2:
            return False
        return x1 <= int(x_root) < x1 + w and y1 <= int(y_root) < y1 + h

    def _mh_update_drop_indicator(self, cat: str, y_root: int, moving_iid: int) -> None:
        """Barra de inserção flutuante (Toplevel) — visível acima do scroll e do fantasma."""
        inner = (getattr(self, "_mh_inners", None) or {}).get(cat)
        if inner is None:
            self._mh_clear_drop_indicator()
            return

        cards_all = self._mh_category_card_widgets(inner)
        try:
            mid_exclude = int(moving_iid)
        except (TypeError, ValueError):
            mid_exclude = -1
        cards = [
            c
            for c in cards_all
            if int(getattr(c, "_mh_item_id", -1) or -1) != mid_exclude
        ]
        insert_index = self._mh_get_insert_index(inner, int(y_root), exclude_iid=moving_iid)
        geom = self._mh_drop_line_screen_geometry(inner, cards, insert_index)
        if geom is None:
            self._mh_clear_drop_indicator()
            return
        x, y, w, h = geom

        st = getattr(self, "_mh_drag", None) or {}
        st["_drop_cat"] = cat
        st["_drop_insert_index"] = insert_index
        self._mh_drag = st

        ind = getattr(self, "_mh_drag_indicator", None)
        if ind is None:
            try:
                ind = tk.Toplevel(self)
                ind.withdraw()
                ind.overrideredirect(True)
                ind.configure(bg="#7b68ee", cursor="arrow")
                try:
                    ind.attributes("-topmost", True)
                except tk.TclError:
                    pass
                try:
                    ind.attributes("-alpha", 0.95)
                except tk.TclError:
                    pass
                ind._mh_drop_indicator = True
                self._mh_drag_indicator = ind
            except tk.TclError:
                return

        try:
            ind.deiconify()
            ind.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
            ind.lift()
            ind.update_idletasks()
        except tk.TclError:
            self._mh_clear_drop_indicator()
            return
        self._mh_drag_indicator_category = cat

    def _mh_restore_dragged_card_visible(self, st: dict) -> None:
        """Repor cartão na coluna após cancelar arrasto (estava com pack_forget)."""
        if not st.get("_src_card_unpacked"):
            return
        try:
            iid = int(st.get("iid"))
            src = str(st.get("src") or "")
        except (TypeError, ValueError):
            return
        inner = (getattr(self, "_mh_inners", None) or {}).get(src)
        card = self._mh_find_card(iid)
        if inner is None or card is None:
            return
        ids = []
        for m in self.data.get("monitored") or []:
            if str(m.get("category") or "Gerais") == src:
                try:
                    ids.append(int(m["id"]))
                except (TypeError, ValueError):
                    continue
        try:
            idx = ids.index(iid)
        except ValueError:
            idx = len(self._mh_category_card_widgets(inner))
        self._mh_repack_card(card, inner, idx)
        st["_src_card_unpacked"] = False

    def _mh_drag_unbind_all(self) -> None:
        for seq in ("<B1-Motion>", "<ButtonRelease-1>", "<Escape>"):
            try:
                self.unbind_all(seq)
            except tk.TclError:
                pass

    def _mh_drag_cleanup_ghost(self, st: dict) -> None:
        g = st.get("ghost")
        if g is not None:
            try:
                g.destroy()
            except tk.TclError:
                pass
        st["ghost"] = None
        gw = st.get("grab_widget")
        if gw is not None:
            try:
                gw.configure(cursor="hand2")
            except tk.TclError:
                pass
        try:
            self.configure(cursor="")
        except tk.TclError:
            pass

    def _mh_drag_cancel(self, _event=None) -> None:
        st = getattr(self, "_mh_drag", None) or {}
        if not st.get("active"):
            return
        st["active"] = False
        self._mh_drag = st
        self._mh_clear_drop_indicator()
        self._mh_restore_dragged_card_visible(st)
        self._mh_drag_unbind_all()
        self._mh_drag_cleanup_ghost(st)

    def _mh_drag_begin(self, event, iid: int, category: str, display_name: str = "", row_snapshot=None):
        card_src = self._mh_card_from_widget(event.widget)
        if card_src is not None:
            category = getattr(card_src, "_mh_category", None) or category
        prev = getattr(self, "_mh_drag", None) or {}
        old_g = prev.get("ghost")
        if old_g is not None:
            try:
                old_g.destroy()
            except tk.TclError:
                pass
        self._mh_clear_drop_indicator()
        src_card = card_src or self._mh_find_card(iid)
        src_card_unpacked = False
        if src_card is not None:
            try:
                src_card.pack_forget()
                src_card_unpacked = True
            except tk.TclError:
                pass
        try:
            event.widget.configure(cursor="hand1")
        except tk.TclError:
            pass

        ghost = tk.Toplevel(self)
        ghost.overrideredirect(True)
        try:
            ghost.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ghost.attributes("-alpha", 0.92)
        except tk.TclError:
            pass

        ghost.configure(bg=C["bg"])
        ghost_photo_refs = []
        if isinstance(row_snapshot, dict) and row_snapshot:
            entry = dict(row_snapshot)
        else:
            entry = {"id": iid, "name": (display_name or "").strip() or f"Item {iid}"}
        if entry.get("id") is None:
            entry["id"] = iid
        col_min_w, _ = self._monitor_home_layout_dims()
        wrap = max(160, col_min_w - 36)
        card, _, _ = self._pack_item_store_snapshot_row(
            ghost,
            entry,
            ghost_photo_refs,
            wraplength=wrap,
            layout="stack",
            id_subline=f"ID: {entry.get('id', iid)}  ·  nova janela",
            show_ws_copy=False,
            drag_handle_monitored=None,
            card_pack_fill_x=False,
            title_wraplength=wrap,
            icon_slot_px=50,
            compact_text_column=True,
        )

        ghost.update_idletasks()
        gw = min(max(int(card.winfo_reqwidth()) + 6, 100), 520)
        gh = int(card.winfo_reqheight()) + 6
        ox = -(gw // 2)
        oy = -min(24, max(8, gh // 3))

        self._mh_drag = {
            "active": True,
            "iid": iid,
            "src": category,
            "ghost": ghost,
            "ghost_photo_refs": ghost_photo_refs,
            "grab_widget": event.widget,
            "ox": ox,
            "oy": oy,
            "ghost_w": gw,
            "ghost_h": gh,
            "_last_x_root": event.x_root,
            "_last_y_root": event.y_root,
            "_hover_cat": None,
            "_last_motion_time": 0,
            "_drop_cat": None,
            "_drop_insert_index": None,
            "_src_card_unpacked": src_card_unpacked,
        }
        try:
            self.configure(cursor="hand1")
        except tk.TclError:
            pass
        try:
            ghost.geometry(f"{gw}x{gh}+{event.x_root + ox}+{event.y_root + oy}")
        except tk.TclError:
            pass

        try:
            self._mh_update_drop_indicator(category, event.x_root, event.y_root, int(iid))
        except (TypeError, ValueError):
            pass

        self.bind_all("<B1-Motion>", self._mh_drag_motion)
        self.bind_all("<ButtonRelease-1>", self._mh_drag_release)
        self.bind_all("<Escape>", self._mh_drag_cancel)

    def _mh_drag_motion(self, event):
        st = getattr(self, "_mh_drag", None) or {}
        if not st.get("active"):
            return
        st["_last_x_root"] = event.x_root
        st["_last_y_root"] = event.y_root
        self._mh_drag = st
        try:
            now = int(event.time)
        except (TypeError, ValueError, tk.TclError):
            now = 0
        last = int(st.get("_last_motion_time") or 0)
        if last and (now - last) < 16:
            return
        st["_last_motion_time"] = now
        self._mh_drag = st
        hc = self._mh_drop_category_at_screen(event.x_root, event.y_root)
        st["_hover_cat"] = hc
        self._mh_drag = st
        iid = st.get("iid")
        g = st.get("ghost")
        if g is not None:
            try:
                ox = int(st.get("ox", 0))
                oy = int(st.get("oy", 0))
                gw = st.get("ghost_w")
                gh = st.get("ghost_h")
                if gw and gh:
                    g.geometry(f"{int(gw)}x{int(gh)}+{event.x_root + ox}+{event.y_root + oy}")
                else:
                    g.geometry(f"+{event.x_root + ox}+{event.y_root + oy}")
            except tk.TclError:
                pass
        if hc and iid is not None:
            try:
                self._mh_update_drop_indicator(hc, event.x_root, event.y_root, int(iid))
            except (TypeError, ValueError):
                self._mh_clear_drop_indicator()
        else:
            self._mh_clear_drop_indicator()
        ind = getattr(self, "_mh_drag_indicator", None)
        if ind is not None:
            try:
                ind.lift()
            except tk.TclError:
                pass

    def _mh_drag_release(self, event):
        st = getattr(self, "_mh_drag", None) or {}
        if not st.get("active"):
            return
        st["active"] = False
        self._mh_drag = st
        drop_cat = st.get("_drop_cat")
        drop_index = st.get("_drop_insert_index")
        self._mh_clear_drop_indicator()
        self._mh_drag_unbind_all()
        self._mh_drag_cleanup_ghost(st)

        try:
            lx, ly = st.get("_last_x_root"), st.get("_last_y_root")
            if lx is not None and ly is not None:
                xr, yr = int(lx), int(ly)
            elif event is not None:
                xr, yr = event.x_root, event.y_root
            else:
                xr, yr = 0, 0

            tgt = self._mh_drop_category_at_screen(xr, yr)
            if tgt is None:
                tgt = st.get("_hover_cat")

            iid = st.get("iid")
            src = st.get("src")
            if iid is None or src is None:
                return
            iid = int(iid)
            src = str(src)

            if tgt == src:
                inner = (getattr(self, "_mh_inners", None) or {}).get(src)
                if inner is not None:
                    if drop_cat == src and drop_index is not None:
                        insert_index = int(drop_index)
                    else:
                        insert_index = self._mh_get_insert_index(inner, yr, exclude_iid=iid)
                    self._reorder_monitored_in_category_at_index(iid, src, insert_index)
                return

            if tgt and tgt != src:
                ins = int(drop_index) if drop_cat == tgt and drop_index is not None else None
                self._move_monitored_item_to_category(iid, tgt, y_root=yr, insert_index=ins)
        except Exception:
            logger.exception("Erro ao concluir drag na home monitorados")
            self._mh_clear_drop_indicator()

    def _mh_drop_category_at_screen(self, x_root, y_root):
        """Categoria sob o cursor — por geometria (o fantasma topmost bloqueia winfo_containing)."""
        xr, yr = int(x_root), int(y_root)
        shells = getattr(self, "_mh_col_shells", None) or {}
        for cat, shell in shells.items():
            try:
                if shell.winfo_exists() and self._mh_widget_contains_screen(shell, xr, yr):
                    return cat
            except tk.TclError:
                continue
        inners = getattr(self, "_mh_inners", None) or {}
        for cat, inner in inners.items():
            try:
                if inner.winfo_exists() and self._mh_widget_contains_screen(inner, xr, yr):
                    return cat
            except tk.TclError:
                continue
        return None

    def _move_monitored_item_to_category(
        self,
        iid: int,
        new_cat: str,
        y_root: Optional[int] = None,
        insert_index: Optional[int] = None,
    ):
        cats = self._monitor_categories_list()
        if new_cat not in cats:
            return
        monitored = list(self.data.get("monitored") or [])
        item = None
        old_cat = None
        for m in monitored:
            try:
                if int(m["id"]) == int(iid):
                    item = m
                    old_cat = str(m.get("category") or "Gerais")
                    break
            except (TypeError, ValueError):
                continue
        if item is None:
            return

        inner_tgt = (getattr(self, "_mh_inners", None) or {}).get(new_cat)
        if insert_index is not None:
            insert_index = int(insert_index)
        elif inner_tgt is not None and y_root is not None:
            insert_index = self._mh_get_insert_index(inner_tgt, int(y_root), exclude_iid=iid)
        else:
            insert_index = len(
                [m for m in monitored if str(m.get("category") or "Gerais") == new_cat and int(m["id"]) != int(iid)]
            )

        rest = [m for m in monitored if int(m["id"]) != int(iid)]
        item2 = dict(item)
        item2["category"] = new_cat

        ids = []
        for m in rest:
            if str(m.get("category") or "Gerais") == new_cat:
                try:
                    ids.append(int(m["id"]))
                except (TypeError, ValueError):
                    continue
        insert_index = min(max(0, int(insert_index)), len(ids))
        ids.insert(insert_index, int(iid))

        by_id = {}
        for m in monitored:
            try:
                pid = int(m["id"])
            except (TypeError, ValueError):
                continue
            by_id[pid] = item2 if pid == int(iid) else m
        new_cat_entries = [by_id[x] for x in ids if x in by_id]

        self.data["monitored"] = self._monitored_splice_category_block(rest, new_cat, new_cat_entries)

        if inner_tgt is None:
            self._persist_monitored_data_async()
            return

        old_card = self._mh_find_card(iid)
        if old_card is not None:
            try:
                old_card.destroy()
            except tk.TclError:
                pass
        self._mh_cards_by_id.pop(int(iid), None)

        if old_cat and old_cat != new_cat:
            src_inner = (getattr(self, "_mh_inners", None) or {}).get(old_cat)
            if src_inner is not None and not self._mh_category_card_widgets(src_inner):
                self._mh_ensure_empty_category_placeholder(src_inner, old_cat)

        col_min_w, _ = self._monitor_home_layout_dims()
        new_card, bind_target = self._mh_create_monitored_card_at_index(
            inner_tgt, item2, new_cat, insert_index, col_min_w
        )
        if new_card is None:
            logger.warning("Drag: falha ao recriar cartão %s em «%s»", iid, new_cat)
            self._persist_monitored_data_async()
            return

        self._mh_cards_by_id[int(iid)] = new_card
        self._bind_click_open_item_detail(bind_target, int(iid), str(item2.get("name", "") or ""))
        self._mh_try_apply_cached_icon_for_card(int(iid), new_card)
        self._persist_monitored_data_async()

    def _reorder_monitored_in_category_at_index(self, iid_move: int, category: str, insert_index: int):
        """Reordena um item na mesma categoria (dados + só o cartão movido na UI)."""
        monitored = list(self.data.get("monitored") or [])
        cat = str(category)
        ids = []
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                continue
            try:
                ids.append(int(m["id"]))
            except (TypeError, ValueError):
                continue
        if int(iid_move) not in ids:
            return
        ids_wo = [x for x in ids if x != int(iid_move)]
        insert_index = min(max(0, int(insert_index)), len(ids_wo))
        ids_wo.insert(insert_index, int(iid_move))

        by_id = {}
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                continue
            try:
                pid = int(m["id"])
            except (TypeError, ValueError):
                continue
            if pid not in by_id:
                by_id[pid] = m
        new_cat_entries = [by_id[x] for x in ids_wo if x in by_id]

        self.data["monitored"] = self._monitored_splice_category_block(monitored, cat, new_cat_entries)
        self._persist_monitored_data_async()

        card = self._mh_find_card(iid_move)
        inner = (getattr(self, "_mh_inners", None) or {}).get(cat)
        if card is not None and inner is not None:
            self._mh_repack_card(card, inner, insert_index)
            try:
                inner.update_idletasks()
            except tk.TclError:
                pass
        else:
            logger.warning("Drag: cartão %s não encontrado na UI (sem rebuild)", iid_move)

    def _reorder_monitored_in_category(self, iid_move: int, target_iid: int, category: str, insert_after: bool):
        """Compatibilidade: converte alvo relativo em índice e delega."""
        monitored = list(self.data.get("monitored") or [])
        cat = str(category)
        ids = []
        for m in monitored:
            if str(m.get("category") or "Gerais") != cat:
                continue
            try:
                ids.append(int(m["id"]))
            except (TypeError, ValueError):
                continue
        if int(iid_move) not in ids or int(target_iid) not in ids:
            return
        ids_wo = [x for x in ids if x != int(iid_move)]
        try:
            ti = ids_wo.index(int(target_iid))
        except ValueError:
            return
        ins = ti + (1 if insert_after else 0)
        self._reorder_monitored_in_category_at_index(iid_move, category, ins)

    def _prompt_add_monitor_category(self):
        cats = self._monitor_categories_list()
        d = tk.Toplevel(self)
        d.title("Nova categoria")
        d.configure(bg=C["bg"])
        d.transient(self)
        d.resizable(False, False)
        shell = RoundedCard(d, radius=18, margin=14, fill_key="card")
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        root = shell.inner
        tk.Label(
            root,
            text="Nome da categoria:",
            bg=C["card"],
            fg=C["text"],
            font=("Segoe UI", 10),
        ).pack(padx=18, pady=(16, 6), anchor="w")
        ent = DarkEntry(root, width=32)
        ent.pack(padx=18, fill="x")

        def add():
            name = ent.get().strip()
            if not name:
                messagebox.showwarning("Categoria", "Digite um nome.", parent=d)
                return
            if name in cats:
                messagebox.showwarning("Categoria", "Já existe uma categoria com esse nome.", parent=d)
                return
            self.data.setdefault("monitor_categories", []).append(name)
            save_data(self.data)
            d.destroy()
            self._render_monitored_home()

        bf = tk.Frame(root, bg=C["card"])
        bf.pack(fill="x", padx=18, pady=(8, 16))
        DarkButton(bf, text="Adicionar", style="success", command=add).pack(side="left", padx=(0, 8))
        DarkButton(bf, text="Cancelar", style="ghost", command=d.destroy).pack(side="left")

    def _prompt_remove_monitor_category(self):
        cats = [c for c in self._monitor_categories_list() if c != "Gerais"]
        if not cats:
            messagebox.showinfo(
                "Categorias",
                "Não há categorias removíveis. «Gerais» fica sempre disponível.",
            )
            return
        d = tk.Toplevel(self)
        d.title("Remover categoria")
        d.configure(bg=C["bg"])
        d.transient(self)
        d.resizable(False, False)
        shell = RoundedCard(d, radius=18, margin=14, fill_key="card")
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        root = shell.inner
        tk.Label(
            root,
            text="Seleccione a categoria a remover.\nOs itens passam para «Gerais».",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            justify="left",
        ).pack(padx=18, pady=(14, 8), anchor="w")
        lb = tk.Listbox(
            root,
            bg=C["bg3"],
            fg=C["text2"],
            selectbackground=C["border2"],
            height=min(10, len(cats)),
            font=("Segoe UI", 10),
        )
        lb.pack(padx=18, fill="x")
        for c in cats:
            lb.insert("end", c)
        lb.selection_set(0)

        def remove():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning("Categoria", "Seleccione uma categoria.", parent=d)
                return
            rm = lb.get(sel[0])
            if not messagebox.askyesno(
                "Confirmar",
                f"Remover a categoria «{rm}»?\nOs itens nela passam para «Gerais».",
                parent=d,
            ):
                return
            for m in self.data.get("monitored") or []:
                if str(m.get("category", "")) == rm:
                    m["category"] = "Gerais"
            self.data["monitor_categories"] = [c for c in self.data["monitor_categories"] if c != rm]
            if "Gerais" not in self.data["monitor_categories"]:
                self.data["monitor_categories"].insert(0, "Gerais")
            save_data(self.data)
            d.destroy()
            self._render_monitored_home()

        bf = tk.Frame(root, bg=C["card"])
        bf.pack(fill="x", padx=18, pady=(10, 16))
        DarkButton(bf, text="Remover", style="danger", command=remove).pack(side="left", padx=(0, 8))
        DarkButton(bf, text="Cancelar", style="ghost", command=d.destroy).pack(side="left")

    def _render_monitored_home(self):
        rid = getattr(self, "_mh_reflow_after_id", None)
        if rid is not None:
            try:
                self.after_cancel(rid)
            except tk.TclError:
                pass
        self._mh_reflow_after_id = None
        for w in self.mh_body.winfo_children():
            w.destroy()
        self._monitored_home_photo_refs = []
        self._mh_inners = {}
        self._mh_col_shells = {}
        self._mh_cards_by_id = {}

        monitored_all = self.data.get("monitored") or []
        mh_q = self._list_search_query("mh")
        monitored = monitored_all
        if mh_q:
            monitored = [m for m in monitored_all if item_matches_search(m, mh_q)]
        cats = self._monitor_categories_list()
        col_min_w, mh_vis_cols = self._monitor_home_layout_dims()

        tool = tk.Frame(self.mh_body, bg=C["bg"])
        tool.pack(fill="x", pady=(0, 8))
        prices_fr = tk.Frame(tool, bg=C["bg"])
        prices_fr.pack(side="left", anchor="w")
        btn_state = "disabled" if getattr(self, "_mh_prices_refreshing", False) else "normal"
        btn_text = "Atualizando…" if getattr(self, "_mh_prices_refreshing", False) else "🔄 Atualizar Preços"
        self._mh_prices_btn = DarkButton(
            prices_fr,
            text=btn_text,
            style="mh_refresh",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=6,
            command=self._mh_on_refresh_prices_click,
        )
        self._mh_prices_btn.pack(side="left")
        try:
            self._mh_prices_btn.configure(state=btn_state)
        except tk.TclError:
            pass
        self._mh_prices_status_lbl = tk.Label(
            prices_fr,
            text=_mh_last_prices_update_label(monitored),
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        )
        self._mh_prices_status_lbl.pack(side="left", padx=(10, 0))
        tk.Label(
            tool,
            text="Várias categorias ao mesmo tempo — arraste pelo «⠿» para mudar de coluna "
            "ou para cima/baixo na mesma coluna. Barra inferior se precisar de deslocar horizontalmente.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack(side="left", anchor="w", padx=(16, 0))
        DarkButton(
            tool,
            text="+ Categoria",
            style="ghost",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
            command=self._prompt_add_monitor_category,
        ).pack(side="right", padx=(4, 0))
        DarkButton(
            tool,
            text="− Categoria",
            style="ghost",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
            command=self._prompt_remove_monitor_category,
        ).pack(side="right")

        if not monitored:
            if monitored_all and mh_q:
                empty_msg = f"Nenhum item corresponde a «{mh_q}»."
            else:
                empty_msg = "Nenhum item monitorado. Use « + Monitorar » ao ver um item."
            tk.Label(
                self.mh_body,
                text=empty_msg,
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 9),
                justify="left",
            ).pack(anchor="w", pady=12)
            self._mh_inners = {}
            self._mh_col_shells = {}
            self._list_search_update_hint("mh", 0, len(monitored_all))
            return

        pan_wrap = tk.Frame(self.mh_body, bg=C["bg"])
        pan_wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(pan_wrap, bg=C["bg"], highlightthickness=0)
        hsb = ModernScrollbar(pan_wrap, canvas.xview, orient="horizontal", bar_width=13, bg=C["bg"])
        canvas.configure(xscrollcommand=hsb.set)
        canvas.pack(side="top", fill="both", expand=True)

        col_host = tk.Frame(canvas, bg=C["bg"])
        win_c = canvas.create_window((0, 0), anchor="nw", window=col_host)
        self._mh_reflow_after_id = None

        for cat in cats:
            col_rim = tk.Frame(col_host, bg=C["column_rim"])
            col_rim.pack(side="left", fill="y", expand=False, padx=(6, 6), pady=(4, 10))
            col_face = tk.Frame(col_rim, bg=C["column_face"])
            col_face.pack(fill="both", expand=True, padx=2, pady=2)
            col_shell = tk.Frame(
                col_face,
                bg=C["column_face"],
                width=col_min_w,
            )
            col_shell.pack(fill="both", expand=True)
            col_shell.pack_propagate(False)
            col_shell._mh_category = cat
            col_face._mh_category = cat
            col_rim._mh_category = cat
            col_rim._mh_col_shell = col_shell

            hdr_wrap = tk.Frame(col_shell, bg=C["column_hdr"])
            hdr_wrap.pack(fill="x", padx=(10, 10), pady=(10, 6))
            hdr = tk.Label(
                hdr_wrap,
                text=cat,
                bg=C["column_hdr"],
                fg=C["column_hdr_fg"],
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )
            hdr.pack(fill="x", padx=2, pady=4)
            hdr._mh_category = cat
            hdr_wrap._mh_category = cat

            sf = ScrollableFrame(col_shell)
            sf.pack(fill="both", expand=True)
            sf._mh_category = cat
            sf.inner._mh_category = cat
            inner = sf.inner
            self._mh_inners[cat] = inner
            self._mh_col_shells[cat] = col_shell

            items_here = [m for m in monitored if (m.get("category") or "Gerais") == cat]
            if not items_here:
                tk.Label(
                    inner,
                    text="(sem itens nesta categoria)",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 9),
                ).pack(anchor="w", pady=12)
            else:
                for m in items_here:
                    try:
                        iid = int(m["id"])
                    except (TypeError, ValueError):
                        continue
                    card, _, bind_target = self._pack_item_store_snapshot_row(
                        inner,
                        m,
                        self._monitored_home_photo_refs,
                        wraplength=max(160, col_min_w - 36),
                        layout="stack",
                        id_subline=f"ID: {m.get('id', '?')}  ·  nova janela",
                        show_ws_copy=True,
                        drag_handle_monitored={"iid": iid, "category": cat},
                        defer_icon_load=True,
                        static_incomplete=_monitored_static_incomplete(m),
                    )
                    self._mh_cards_by_id[iid] = card
                    self._bind_click_open_item_detail(
                        bind_target, iid, str(m.get("name", "") or "")
                    )

        def _reflow_mh_columns_sched(_event=None):
            if self._mh_reflow_after_id is not None:
                try:
                    self.after_cancel(self._mh_reflow_after_id)
                except tk.TclError:
                    pass
            self._mh_reflow_after_id = self.after(72, _reflow_mh_columns_do)

        def _reflow_mh_columns_do():
            self._mh_reflow_after_id = None
            col_min_w, mh_vis_cols = self._monitor_home_layout_dims()
            try:
                cw_raw = int(canvas.winfo_width())
                ch_raw = int(canvas.winfo_height())
            except tk.TclError:
                return
            if cw_raw < 32 or ch_raw < 64:
                return
            cw = cw_raw
            ch = ch_raw
            try:
                px0 = float(canvas.xview()[0])
            except tk.TclError:
                px0 = 0.0

            n = max(1, len(cats))
            # Largura «natural» da janela: divide pelo maior entre nº de categorias e a
            # meta — assim a largura mínima definida nas Configurações afecta o resultado
            # mesmo com poucas categorias (antes cw//meta sozinha ignorava col_min na
            # maior parte dos casos).
            eff = max(n, mh_vis_cols, 1)
            col_fit = max(1, cw) // eff
            col_w = max(col_min_w, col_fit)
            total_w = n * col_w
            for chf in col_host.winfo_children():
                try:
                    chf.configure(width=col_w)
                    cs = getattr(chf, "_mh_col_shell", None)
                    if cs is not None:
                        inner_w = max(col_min_w, col_w - 4)
                        cs.configure(width=inner_w)
                except tk.TclError:
                    pass
            col_host.update_idletasks()
            canvas.itemconfigure(win_c, width=total_w, height=ch)
            bbox = canvas.bbox(win_c)
            if bbox:
                canvas.configure(scrollregion=(0, 0, bbox[2], max(int(bbox[3]), ch)))
            need_scroll = total_w > (cw + 8)
            try:
                hsb_mapped = hsb.winfo_ismapped()
            except tk.TclError:
                hsb_mapped = False
            if need_scroll:
                if not hsb_mapped:
                    hsb.pack(side="bottom", fill="x")
                try:
                    canvas.xview_moveto(max(0.0, min(px0, 1.0)))
                except tk.TclError:
                    pass
            else:
                if hsb_mapped:
                    hsb.pack_forget()
                try:
                    canvas.xview_moveto(0)
                except tk.TclError:
                    pass

        canvas.bind("<Configure>", _reflow_mh_columns_sched)
        pan_wrap.bind("<Configure>", _reflow_mh_columns_sched)
        self.after_idle(_reflow_mh_columns_sched)
        self.after(250, _reflow_mh_columns_sched)

        def _mh_wheel_x(event):
            try:
                d = int(getattr(event, "delta", 0) or 0)
            except (TypeError, ValueError):
                d = 0
            if d and (getattr(event, "state", 0) & 0x0001):
                canvas.xview_scroll(int(-1 * (d / 120)), "units")
                return "break"
            return None

        canvas.bind("<MouseWheel>", _mh_wheel_x)
        hsb.bind("<MouseWheel>", _mh_wheel_x)

        if self.current_page.get() == "busca":
            self.after_idle(self._mh_start_icon_loader)
        self._list_search_update_hint("mh", len(monitored), len(monitored_all))

    def _mh_on_refresh_prices_click(self) -> None:
        if getattr(self, "_mh_prices_refreshing", False):
            return
        self._mh_prices_refreshing = True
        btn = getattr(self, "_mh_prices_btn", None)
        if btn is not None:
            try:
                btn.configure(state="disabled", text="Atualizando…")
            except tk.TclError:
                pass
        self._monitored_home_refresh_gen += 1
        gen = self._monitored_home_refresh_gen
        threading.Thread(
            target=lambda g=gen: self._refresh_monitored_home_prices_worker(g),
            name="MhRefreshPrices",
            daemon=True,
        ).start()

    def _mh_start_icon_loader(self) -> None:
        self._mh_icon_load_gen += 1
        gen = self._mh_icon_load_gen
        jobs = []
        for m in self.data.get("monitored") or []:
            try:
                iid = int(m["id"])
            except (TypeError, ValueError):
                continue
            url = _normalize_media_url(m.get("item_icon_url") or "")
            jobs.append((iid, url))
        if not jobs:
            return
        threading.Thread(
            target=lambda g=gen, j=jobs: self._mh_icon_loader_worker(g, j),
            name="MhIconLoader",
            daemon=True,
        ).start()

    def _mh_icon_loader_worker(self, gen: int, jobs: list) -> None:
        for iid, url in jobs:
            if gen != getattr(self, "_mh_icon_load_gen", 0):
                return
            raw = read_item_icon_png_bytes(iid, url, self._fetch_icon_url_bytes)
            if gen != getattr(self, "_mh_icon_load_gen", 0):
                return
            self.after(0, lambda mid=iid, data=raw, g=gen: self._mh_apply_card_icon(mid, data, g))

    def _mh_apply_card_icon(self, item_id: int, raw: Optional[bytes], gen: int) -> None:
        if gen != getattr(self, "_mh_icon_load_gen", 0):
            return
        if self.current_page.get() != "busca":
            return
        card = self._mh_find_card(item_id)
        if card is None:
            return
        try:
            max_sz = int(getattr(card, "_mh_icon_max", 52) or 52)
        except (TypeError, ValueError):
            max_sz = 52
        ph = self._photoimage_from_icon_bytes(raw, max_sz) if raw else None
        if ph is None:
            return
        self._monitored_home_photo_refs.append(ph)
        try:
            key = (int(item_id), int(max_sz))
            self._item_icon_photo_ram[key] = ph
        except (TypeError, ValueError):
            pass
        lbl = getattr(card, "_mh_icon_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(image=ph, text="")
                lbl.image = ph
            except tk.TclError:
                pass

    def _mh_update_card_prices_ui(self, item_id: int, gen: int) -> None:
        if gen != self._monitored_home_refresh_gen:
            return
        if self.current_page.get() != "busca":
            return
        card = self._mh_find_card(item_id)
        if card is None:
            return
        lbl = getattr(card, "_mh_price_lbl", None)
        if lbl is None:
            return
        for m in self.data.get("monitored") or []:
            try:
                if int(m["id"]) == int(item_id):
                    try:
                        lbl.configure(text=_format_home_min_prices_for_monitored(m))
                    except tk.TclError:
                        pass
                    break
            except (TypeError, ValueError):
                continue

    def _mh_finish_prices_refresh(self, gen: int) -> None:
        if gen != self._monitored_home_refresh_gen:
            return
        self._mh_prices_refreshing = False
        btn = getattr(self, "_mh_prices_btn", None)
        if btn is not None:
            try:
                btn.configure(state="normal", text="🔄 Atualizar Preços")
            except tk.TclError:
                pass
        lbl = getattr(self, "_mh_prices_status_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(text=_mh_last_prices_update_label(self.data.get("monitored") or []))
            except tk.TclError:
                pass

    def _refresh_monitored_home_prices_worker(self, gen: int):
        """Actualiza preços (só quando o utilizador pede); cada item actualiza o cartão na UI."""
        try:
            changed = False
            for m in list(self.data.get("monitored") or []):
                if gen != self._monitored_home_refresh_gen:
                    return
                iid = m.get("id")
                name = str(m.get("name") or "")
                if not iid:
                    continue
                try:
                    iid_int = int(iid)
                except (TypeError, ValueError):
                    continue
                try:
                    stores, meta = get_stores_from_item_page(
                        iid_int, name, force_refresh=True
                    )
                except Exception as e:
                    logger.warning("Home monitor refresh %s: %s", iid, e)
                    continue
                patch = {
                    "min_prices": _sale_min_prices_from_stores(stores),
                    "home_prices_updated_at": datetime.now().isoformat(),
                }
                if meta.get("item_icon_url") and not m.get("item_icon_url"):
                    patch["item_icon_url"] = _normalize_media_url(meta["item_icon_url"])
                m.update(patch)
                changed = True
                self.after(0, lambda mid=iid_int, g=gen: self._mh_update_card_prices_ui(mid, g))
                if patch.get("item_icon_url"):
                    url = patch["item_icon_url"]
                    self.after(
                        0,
                        lambda mid=iid_int, u=url, g=gen: self._mh_fetch_icon_after_price(mid, u, g),
                    )
            if changed and gen == self._monitored_home_refresh_gen:
                self._persist_monitored_data_async()
            self.after(0, lambda g=gen: self._after_monitored_prices_refresh(g))
        except Exception as e:
            logger.exception("Refresh monitorados home: %s", e)
            self.after(0, lambda g=gen: self._mh_finish_prices_refresh(g))

    def _mh_fetch_icon_after_price(self, item_id: int, url: str, gen: int) -> None:
        if gen != self._monitored_home_refresh_gen:
            return

        def _work():
            raw = read_item_icon_png_bytes(item_id, url, self._fetch_icon_url_bytes)
            self.after(0, lambda: self._mh_apply_card_icon(item_id, raw, getattr(self, "_mh_icon_load_gen", 0)))

        threading.Thread(target=_work, daemon=True).start()

    def _after_monitored_prices_refresh(self, gen: int):
        if gen != self._monitored_home_refresh_gen:
            return
        pg = self.current_page.get()
        if pg == "busca":
            self._mh_finish_prices_refresh(gen)
        elif pg == "monitor":
            self._render_monitor()

    def _refresh_alertas_display_prices_worker(self, gen: int):
        """Actualiza min_prices e ícone nos alertas (lista Alertas) e grava JSON."""
        try:
            alerts = load_alerts()
            if not alerts:
                return
            updates = {}
            for key, a in list(alerts.items()):
                if gen != self._alerts_display_refresh_gen:
                    return
                iid = a.get("item_id")
                if not iid:
                    continue
                try:
                    stores, meta = get_stores_from_item_page(int(iid), str(a.get("item_name") or ""))
                except Exception as e:
                    logger.debug("Alertas UI refresh %s: %s", iid, e)
                    continue
                upd = {
                    "min_prices": _sale_min_prices_from_stores(
                        stores, min_refinement=_alert_min_refinement(a)
                    ),
                    "home_prices_updated_at": datetime.now().isoformat(),
                }
                if meta.get("item_icon_url"):
                    upd["item_icon_url"] = _normalize_media_url(meta["item_icon_url"])
                updates[key] = upd
            if not updates or gen != self._alerts_display_refresh_gen:
                return
            with _ALERTS_IO_LOCK:
                cur = load_alerts()
                for k, u in updates.items():
                    if k in cur:
                        cur[k].update(u)
                save_alerts(cur)
            self.after(0, lambda g=gen: self._render_alertas_if_current(g))
        except Exception as e:
            logger.exception("Refresh alertas (UI): %s", e)

    def _render_alertas_if_current(self, gen: int):
        if gen != self._alerts_display_refresh_gen:
            return
        if self.current_page.get() != "alertas":
            return
        self._render_alertas()

    def _ensure_search_results_window(self):
        """Janela separada com a lista de resultados (a página Busca fica só com pesquisa + monitorados)."""
        win = getattr(self, "_search_results_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    return win
            except tk.TclError:
                pass

        win = tk.Toplevel(self)
        win.title("Resultados da busca — Herosaga Monitor")
        win.configure(bg=C["bg"])
        win.minsize(360, 320)
        win.geometry("540x580")

        shell = RoundedCard(win, radius=20, margin=12, fill_key="card")
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        body = tk.Frame(shell.inner, bg=C["card"])
        body.pack(fill="both", expand=True, padx=10, pady=10)
        self.items_label = tk.Label(body, text="", bg=C["card"], fg=C["text3"], font=("Segoe UI", 8))
        self.items_label.pack(anchor="w", pady=(0, 6))
        self.items_scroll = ScrollableFrame(body, inner_bg=C["card"])
        self.items_scroll.pack(fill="both", expand=True)
        self._search_results_win = win

        def _hide_results():
            try:
                win.withdraw()
            except tk.TclError:
                pass

        win.protocol("WM_DELETE_WINDOW", _hide_results)
        return win

    def _show_empty_items(self):
        if self.items_scroll is None:
            return
        for w in self.items_scroll.inner.winfo_children():
            w.destroy()

    def _do_search(self):
        query = self.search_entry.get().strip()
        if not query or query == "Ex: Mana Sombria, Espada, Poção...":
            messagebox.showwarning("Aviso", "Digite o nome de um item para buscar.")
            return

        # Só dígitos (ou @ws <id>) → abre logo a janela de lojas/histórico (sem lista intermédia).
        qid = query.strip()
        low = qid.lower()
        if low.startswith("@ws"):
            qid = qid[3:].strip()
        elif low.startswith("ws") and len(qid) > 2 and qid[2].isspace():
            qid = qid[2:].strip()
        if qid.isdigit():
            try:
                iid = int(qid)
            except (ValueError, OverflowError):
                iid = 0
            if iid > 0:
                self._search_generation += 1
                wr = getattr(self, "_search_results_win", None)
                if wr is not None:
                    try:
                        if wr.winfo_exists():
                            wr.withdraw()
                    except tk.TclError:
                        pass
                self.status_dot.configure(text="● online", fg=C["green"])
                self._open_item_detail_window(item_id=iid, item_name_hint=f"Item {iid}")
                return

        self._ensure_search_results_window()

        self._search_generation += 1
        gen = self._search_generation

        self.status_dot.configure(text="● buscando...", fg=C["yellow"])
        self.items_label.configure(text="Buscando itens e raspando lojas abertas...")
        for w in self.items_scroll.inner.winfo_children():
            w.destroy()
        tk.Label(self.items_scroll.inner, text="⏳ Aguarde...\nBuscando itens e extraindo dados de lojas...",
                 bg=C["bg"], fg=C["text3"], font=("Segoe UI", 10)).pack(pady=30)

        def run():
            search_error = None
            try:
                logger.info(f"🔍 Iniciando busca por: '{query}' (gen={gen})")
                results = api_search(query)
                if gen != self._search_generation:
                    logger.debug(f"Busca gen={gen} ignorada (atual={self._search_generation})")
                    return
                self.current_items = results
                self._save_search(query, len(results))
                logger.info(f"✓ Busca concluída: {len(results)} itens encontrados com informações de lojas")
                self.after(0, lambda r=results, g=gen: self._finish_search_render(r, g, None))
            except Exception as ex:
                search_error = str(ex)
                logger.error(f"Search error: {search_error}")
                import traceback
                logger.error(traceback.format_exc())
                self.after(0, lambda msg=search_error, g=gen: self._finish_search_render([], g, msg))

        threading.Thread(target=run, daemon=True).start()

    def _finish_search_render(self, results, gen, error_msg):
        """Aplica resultado da busca só se for a requisição mais recente."""
        if gen != self._search_generation:
            return
        if error_msg:
            self._search_error(error_msg)
            return
        self._render_items(results)

    def _search_error(self, msg):
        self.status_dot.configure(text="● erro", fg=C["red"])
        self.items_label.configure(text="Erro na busca")
        for w in self.items_scroll.inner.winfo_children():
            w.destroy()
        tk.Label(self.items_scroll.inner, text=f"⚠ Erro:\n{msg}",
                 bg=C["bg"], fg=C["red"], font=("Segoe UI", 9),
                 wraplength=420, justify="center").pack(pady=30)

    def _render_items(self, items):
        self.status_dot.configure(text="● online", fg=C["green"])
        for w in self.items_scroll.inner.winfo_children():
            w.destroy()

        if not items:
            self.items_label.configure(text="Nenhum item encontrado")
            tk.Label(self.items_scroll.inner,
                     text="🔍\n\nNenhum resultado.\nTente outro nome.",
                     bg=C["bg"], fg=C["text3"], font=("Segoe UI", 10),
                     justify="center").pack(pady=40)
            return

        self.items_label.configure(text=f"{len(items)} item(s) encontrado(s)")
        for i, item in enumerate(items):
            card = ItemCard(
                self.items_scroll.inner, item,
                on_click=lambda idx=i: self._select_item(idx),
                selected=(self.selected_item and self.selected_item.get("id") == item.get("id")),
                thumb_loader=lambda u, mx=44: self._load_item_icon_photo(u, max_size=mx),
            )
            card.pack(fill="x", pady=3)

    def _select_item(self, idx):
        item = self.current_items[idx]
        self.selected_item = item
        logger.info(f"Selected item: {item}")
        self._render_items(self.current_items)
        self._destroy_detail_chart_if_any()
        self._open_item_detail_window(item=item)

    def _detail_error(self, msg):
        error_text = f"⚠ Erro ao buscar detalhes:\n{msg}\n\n(Verifique o arquivo de log)"
        logger.error(f"Detail error displayed to user: {msg}")
        messagebox.showerror("Erro", error_text)

    def _destroy_detail_chart_if_any(self):
        if getattr(self, "chart_canvas", None) is not None:
            try:
                self.chart_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.chart_canvas = None

    def _item_id_monitored(self, item_id) -> bool:
        try:
            iid = int(item_id)
        except (TypeError, ValueError):
            return False
        for m in self.data.get("monitored") or []:
            try:
                if int(m.get("id")) == iid:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _pack_detail_window_header_actions(self, btn_frame, item: dict, all_sales: list):
        """Botões Monitorar/Remover e alerta no cabeçalho do detalhe (janela ou embebido)."""
        for w in btn_frame.winfo_children():
            w.destroy()
        it = dict(item)
        sl = all_sales if isinstance(all_sales, list) else []

        if self._item_id_monitored(it.get("id")):
            DarkButton(
                btn_frame,
                text="− Remover",
                style="danger",
                command=lambda iit=it, bf=btn_frame, s=sl: self._remove_monitor(
                    iit, detail_btn_frame=bf, detail_all_sales=s
                ),
            ).pack(side="left", padx=2)
        else:
            DarkButton(
                btn_frame,
                text="+ Monitorar",
                style="success",
                command=lambda iit=it, bf=btn_frame, s=sl: self._add_monitor(
                    iit, s, detail_btn_frame=bf
                ),
            ).pack(side="left", padx=2)

        DarkButton(
            btn_frame,
            text="🔔 Alerta",
            style="ghost",
            command=lambda iit=it: self._show_alert_dialog(iit),
        ).pack(side="left", padx=2)

    def _render_detail_into(self, root, item, data, *, chart_setter, preview_photo_holder=None):
        """Monta o painel de lojas + histórico dentro de *root* (janela principal ou Toplevel)."""
        all_sales = data.get("sales", [])

        sales_by_type = group_sales_by_type(all_sales)

        hdr = tk.Frame(root, bg=C["bg2"],
                       highlightbackground=C["border2"], highlightthickness=1)
        hdr.pack(fill="x", pady=(0, 8), padx=2)

        top = tk.Frame(hdr, bg=C["bg2"])
        top.pack(fill="x", padx=14, pady=10)

        hdr._hdr_thumb_refs = []
        icon_slot = tk.Frame(top, bg=C["bg2"], width=42, height=42)
        icon_slot.pack(side="left", padx=(0, 10))
        icon_slot.pack_propagate(False)
        nu = _normalize_media_url(item.get("item_icon_url") or "")
        hdr_icon = self._load_item_icon_photo(nu, max_size=40) if nu else None
        if hdr_icon:
            hdr._hdr_thumb_refs.append(hdr_icon)
            tk.Label(icon_slot, image=hdr_icon, bg=C["bg2"]).place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(
                icon_slot,
                text=item_emoji(item.get("name", "")),
                bg=C["bg2"],
                fg=C["text"],
                font=("Segoe UI", 20),
            ).place(relx=0.5, rely=0.5, anchor="center")

        info = tk.Frame(top, bg=C["bg2"])
        info.pack(side="left", fill="x", expand=True)

        name_row = tk.Frame(info, bg=C["bg2"])
        name_row.pack(fill="x")
        item_name = safe_get(item, "name", "Item Desconhecido")
        tk.Label(name_row, text=item_name,
                 bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")

        meta_parts = []
        if item.get("is_costume"):
            meta_parts.append("COSTUME")

        id_row = tk.Frame(info, bg=C["bg2"])
        id_row.pack(fill="x", anchor="w", pady=(2, 0))
        raw_id = item.get("id")
        id_text = str(raw_id) if raw_id not in (None, "") else "?"

        tk.Label(id_row, text="ID", bg=C["bg2"], fg=C["text3"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        id_ent = tk.Entry(
            id_row,
            width=14,
            font=("Consolas", 10),
            bg=C["bg2"],
            fg=C["text2"],
            insertbackground=C["purple3"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            selectbackground=C["border2"],
            selectforeground=C["text"],
        )
        id_ent.insert(0, id_text)
        id_ent.pack(side="left")
        try:
            id_ent.configure(state="readonly", readonlybackground=C["bg2"])
        except tk.TclError:
            try:
                id_ent.configure(state="readonly")
            except tk.TclError:
                pass

        def _copy_ws_id():
            try:
                n = int(raw_id)
            except (TypeError, ValueError):
                return
            self._clipboard_copy_ws_item_id(n)

        DarkButton(id_row, text="📋  Copiar @ws", style="ghost", command=_copy_ws_id).pack(side="left", padx=(8, 0))

        if meta_parts:
            tk.Label(
                id_row,
                text="  ·  " + "  ·  ".join(meta_parts),
                bg=C["bg2"],
                fg=C["text3"],
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(10, 0))

        btn_frame = tk.Frame(top, bg=C["bg2"])
        btn_frame.pack(side="right")
        self._pack_detail_window_header_actions(btn_frame, item, all_sales)

        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=2)

        left_panel = tk.Frame(body, bg=C["bg"])
        left_panel.pack(side="left", fill="both", expand=True)

        card_holder = tk.Frame(body, bg=C["bg"], width=258)
        card_holder.pack(side="right", fill="y", padx=(12, 4))
        card_holder.pack_propagate(False)
        self._build_item_preview_card(card_holder, item, photo_holder=preview_photo_holder)

        scroll = ScrollableFrame(left_panel)
        scroll.pack(fill="both", expand=True)
        inner = scroll.inner

        stores_holder = tk.Frame(inner, bg=C["bg"])
        stores_holder.pack(fill="x", pady=0)

        stores_list = item.get("stores_list", None)
        self._render_vending_stores(
            stores_holder, item.get("id"), item.get("name", "Item"), None, stores_list, item
        )

        if not all_sales:
            tk.Label(
                inner,
                text="📊  Sem histórico de vendas registrado para este item no site.",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 10),
                justify="center",
            ).pack(pady=(16, 8))
            return

        tabs_frame = tk.Frame(inner, bg=C["bg"])
        tabs_frame.pack(fill="x", padx=0, pady=(12, 0))

        active_tab = tk.StringVar(value="rops")
        tab_buttons = {}

        for sale_type in ["rops", "zeny", "rmt"]:
            sales = sales_by_type.get(sale_type, [])
            if not sales:
                continue

            count = len(sales)
            tab_text = f"{sale_type.upper()} ({count})"
            tab_color = C["rops"] if sale_type == "rops" else (C["zeny"] if sale_type == "zeny" else C["rmt"])

            def make_tab_click(st, cs):
                def click():
                    active_tab.set(st)
                    self._render_history_tabs(
                        inner, sales_by_type, st, item, tabs_frame, stores_holder, chart_setter=cs
                    )
                return click

            btn = tk.Button(tabs_frame, text=tab_text,
                            bg=C["bg3"], fg=tab_color,
                            relief="flat", font=("Segoe UI", 9, "bold"),
                            cursor="hand2", command=make_tab_click(sale_type, chart_setter),
                            padx=12, pady=6)
            btn.pack(side="left", padx=4, pady=4)
            tab_buttons[sale_type] = btn

        first_type = next((t for t in ["rops", "zeny", "rmt"] if sales_by_type.get(t)), "rops")
        active_tab.set(first_type)
        self._render_history_tabs(
            inner, sales_by_type, first_type, item, tabs_frame, stores_holder, chart_setter=chart_setter
        )

    def _render_history_tabs(self, parent, sales_by_type, sale_type, item, tabs_frame, stores_holder, chart_setter=None):
        """Renderiza o conteúdo da aba selecionada com histórico de preços e vendas."""
        # Remove só o bloco de histórico — preserva lojas abertas e botões de moeda
        keep = {tabs_frame, stores_holder}
        for w in list(parent.winfo_children()):
            if w not in keep:
                w.destroy()
        
        sales = sales_by_type.get(sale_type, [])
        if not sales:
            tk.Label(parent, text=f"Sem dados para {sale_type.upper()}",
                     bg=C["bg"], fg=C["text3"], font=("Segoe UI", 9)).pack(pady=20)
            return
        
        # ── SEÇÃO 1: ESTATÍSTICAS ────────────────────────────────────────────
        stats = calculate_stats(sales)
        
        stat_colors = {
            "Último": C["yellow"],
            "Mínimo": C["green"],
            "Máximo": C["red"],
            "Média": C["purple3"],
            "Vendas": C["text2"],
        }
        
        stats_data = [
            ("Último",  fmt_price(stats["último"]),    stat_colors["Último"]),
            ("Mínimo",  fmt_price(stats["mínimo"]),    stat_colors["Mínimo"]),
            ("Máximo",  fmt_price(stats["máximo"]),    stat_colors["Máximo"]),
            ("Média",   fmt_price(stats["média"]),     stat_colors["Média"]),
            ("Vendas",  str(stats["quantidade"]),      stat_colors["Vendas"]),
        ]
        
        stats_row = tk.Frame(parent, bg=C["bg"])
        stats_row.pack(fill="x", pady=(4, 8))
        for label, val, color in stats_data:
            card = tk.Frame(stats_row, bg=C["bg3"],
                            highlightbackground=C["border"], highlightthickness=1)
            card.pack(side="left", padx=3, pady=2, fill="x", expand=True)
            tk.Label(card, text=label, bg=C["bg3"], fg=C["text3"],
                     font=("Segoe UI", 7, "bold")).pack(pady=(6, 0))
            tk.Label(card, text=val, bg=C["bg3"], fg=color,
                     font=("Segoe UI", 11, "bold")).pack(pady=(2, 6))

        # ── SEÇÃO 2: GRÁFICO ─────────────────────────────────────────────────
        chart_wrap = tk.Frame(parent, bg=C["bg3"],
                              highlightbackground=C["border"], highlightthickness=1)
        chart_wrap.pack(fill="x", pady=(0, 8))
        tk.Label(chart_wrap, text=f"HISTÓRICO DE PREÇO - {sale_type.upper()}",
                 bg=C["bg3"], fg=C["text3"],
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=10, pady=(8, 0))

        reversed_sales = list(reversed(sales))
        dates  = [s.get("sale_date", "")[:10] for s in reversed_sales]
        values = [s.get("price", 0) for s in reversed_sales]

        fig = Figure(figsize=(5, 2), dpi=90, facecolor=C["bg3"])
        ax  = fig.add_subplot(111, facecolor=C["bg3"])
        ax.plot(dates, values, color=C["purple2"], linewidth=2, marker="o",
                markersize=4, markerfacecolor=C["purple3"])
        ax.fill_between(range(len(values)), values,
                        alpha=0.15, color=C["purple"])
        ax.set_xticks(range(0, len(dates), max(1, len(dates)//5)))
        ax.set_xticklabels([dates[i] if i < len(dates) else "" 
                            for i in range(0, len(dates), max(1, len(dates)//5))],
                           rotation=40, ha="right", color=C["text3"], fontsize=7)
        ax.tick_params(axis="y", colors=C["text3"], labelsize=7)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda x, _: f"{int(x):,}".replace(",", ".")))
        for spine in ax.spines.values():
            spine.set_edgecolor(C["border2"])
        ax.grid(axis="y", color=C["border"], linewidth=0.5)
        fig.tight_layout(pad=1.5)

        canvas = FigureCanvasTkAgg(fig, master=chart_wrap)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="x", padx=6, pady=(4, 8))
        if chart_setter is not None:
            chart_setter(canvas)
        else:
            self.chart_canvas = canvas

        # ── SEÇÃO 3: HISTÓRICO DE VENDAS ─────────────────────────────────────
        tk.Label(parent, text=f"📜 HISTÓRICO DE VENDAS - {sale_type.upper()}",
                 bg=C["bg"], fg=C["text3"],
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", pady=(12, 8), padx=4)

        cols = ("Data", "Vendedor", "Comprador", "Preço", "Qtd")
        tree = ttk.Treeview(parent, columns=cols, show="headings",
                            height=min(len(sales), 8))
        widths = [90, 140, 140, 90, 40]
        for col, w in zip(cols, widths):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="center" if col in ("Preço","Qtd","Data") else "w")

        # Ordena vendas por data (mais recentes primeiro)
        sorted_sales = sorted(sales, key=lambda x: x.get("sale_date", ""), reverse=True)
        
        for i, s in enumerate(sorted_sales):
            # Calcula diferença em relação à venda anterior (que é mais antiga)
            prev = sorted_sales[i + 1] if i + 1 < len(sorted_sales) else None
            diff = (s.get("price", 0) - prev.get("price", 0)) if prev else 0
            arrow = " ▲" if diff > 0 else (" ▼" if diff < 0 else "")
            price_str = fmt_price(s.get("price", 0)) + arrow
            tree.insert("", "end", values=(
                s.get("sale_date", "N/A")[:16] if s.get("sale_date") else "N/A",
                safe_get(s, "seller_name", "Anônimo"),
                safe_get(s, "buyer_name", "Anônimo"),
                price_str,
                safe_get(s, "quantity", "1"),
            ))

        tree.pack(fill="x", pady=(0, 12))
        tree.tag_configure("oddrow", background=C["bg3"])
    
    def _render_vending_stores(self, parent, item_id, item_name, sale_type, stores_list=None, item=None):
        """Lista lojas abertas no estilo do site (LOJA, refinamento, cartas, valor, qtd, venda por)."""
        for w in parent.winfo_children():
            w.destroy()

        if stores_list is None:
            stores, _ = get_stores_from_item_page(item_id, item_name)
        else:
            stores = list(stores_list) if stores_list else []
            # Lista vazia da busca (ex.: item fora dos 10 primeiros) não deve bloquear nova raspagem.
            if not stores:
                stores, _ = get_stores_from_item_page(item_id, item_name)

        if sale_type is not None:
            sale_type_lower = sale_type.lower()
            if sale_type_lower == "rops":
                stores = [s for s in stores if s.get("sale_type", "").lower() in ["rops", "rp", "r$"]]
            elif sale_type_lower == "zeny":
                stores = [s for s in stores if s.get("sale_type", "").lower() in ["zeny", "z", "z$"]]
            elif sale_type_lower == "hero_points":
                stores = [s for s in stores if "hero" in s.get("sale_type", "").lower()]
            elif sale_type_lower == "rmt":
                stores = [s for s in stores if s.get("sale_type", "").lower() in ["rmt", "rm", "rm$", "m"]]

        stores.sort(key=lambda x: x.get("price", float("inf")))

        # ── Caixa com borda (similar ao site) ───────────────────────────────
        box = tk.Frame(
            parent,
            bg=C["bg2"],
            highlightbackground="#b8860b",
            highlightthickness=2,
        )
        box.pack(fill="x", pady=(4, 10), padx=0)

        head = tk.Frame(box, bg=C["bg2"])
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(
            head,
            text="LOJAS ABERTAS",
            bg=C["bg2"],
            fg=C["yellow"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            head,
            text="Lojas online com este item à venda (menor → maior preço).",
            bg=C["bg2"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(box, bg=C["bg2"])
        body.pack(fill="x", padx=8, pady=(4, 12))

        if not stores:
            tk.Label(
                body,
                text="Nenhuma loja online vendendo este item no momento.",
                bg=C["bg2"],
                fg=C["text3"],
                font=("Segoe UI", 9),
            ).pack(pady=8)
            return

        hdr_bg = C.get("column_hdr", C["border2"])
        hdr_fg = C.get("column_hdr_fg", C["purple3"])
        hdr_h = 32
        header_frame = tk.Frame(body, bg=hdr_bg, height=hdr_h)
        header_frame.pack(fill="x", pady=(0, 4))
        header_frame.pack_propagate(False)

        cols_info = [
            ("Nome da loja", 200, "w"),
            ("Refino", 72, "center"),
            ("Slots", 56, "center"),
            ("Preço", 180, "center"),
            ("Qtd", 56, "center"),
            ("Venda por", 82, "center"),
        ]
        for col_name, width, anchor in cols_info:
            expand = col_name == "Nome da loja"
            # pack_propagate(False) sem height fixa deixa altura ~0 — texto do cabeçalho desaparece (Windows/Tk).
            col_frame = tk.Frame(header_frame, bg=hdr_bg, width=width, height=hdr_h)
            col_frame.pack(side="left", fill="x", expand=expand, padx=1)
            col_frame.pack_propagate(False)
            tk.Label(
                col_frame,
                text=col_name,
                bg=hdr_bg,
                fg=hdr_fg,
                font=("Segoe UI", 8, "bold"),
                anchor=anchor,
            ).pack(fill="both", expand=True, pady=4)

        stores_frame = tk.Frame(body, bg=C["bg2"])
        stores_frame.pack(fill="x")

        for i, store in enumerate(stores):
            char_name = store.get("char_name") or store.get("seller_name") or store.get("owner") or "—"
            refinement = store.get("refinement") or store.get("refine") or store.get("enhancement") or 0
            cards = store.get("cards") or store.get("slots") or 0
            price = store.get("price") or store.get("sell_price") or store.get("valor") or 0
            quantity = store.get("amount") or store.get("quantity") or 1
            store_sale_type = store.get("sale_type") or "zeny"

            price_str, price_color = _format_store_price_display(price, store_sale_type)
            badge_txt, badge_bg = _store_badge_label(store_sale_type)

            row_bg = C["bg3"] if i % 2 == 0 else C["bg2"]

            # Altura livre: linhas com nome longo precisam de mais que ~34px (senão texto virava traços).
            row_frame = tk.Frame(stores_frame, bg=row_bg, height=70)
            row_frame.pack(fill="x", pady=1)
            row_frame.pack_propagate(False)

            loja_frame = tk.Frame(row_frame, bg=row_bg, height=70)
            loja_frame.pack(side="left", fill="both", expand=True, padx=6, pady=0)
            loja_frame.pack_propagate(False)
            tk.Label(
                loja_frame,
                text=char_name,
                bg=row_bg,
                fg=C["text"],
                font=("Segoe UI", 9),
                anchor="w",
                justify="left",
                wraplength=180,
            ).pack(fill="both", expand=True, padx=0, pady=0)

            ref_frame = tk.Frame(row_frame, bg=row_bg, width=72, height=70)
            ref_frame.pack(side="left", padx=2, pady=0)
            ref_frame.pack_propagate(False)
            tk.Label(ref_frame, text=str(refinement), bg=row_bg, fg=C["text2"], font=("Segoe UI", 9), anchor="center").pack(fill="both", expand=True)

            cards_frame = tk.Frame(row_frame, bg=row_bg, width=56, height=70)
            cards_frame.pack(side="left", padx=2, pady=0)
            cards_frame.pack_propagate(False)
            tk.Label(cards_frame, text=str(cards), bg=row_bg, fg=C["text2"], font=("Segoe UI", 9), anchor="center").pack(fill="both", expand=True)

            price_frame = tk.Frame(row_frame, bg=row_bg, width=180, height=70)
            price_frame.pack(side="left", padx=2, pady=0)
            price_frame.pack_propagate(False)
            tk.Label(
                price_frame,
                text=price_str,
                bg=row_bg,
                fg=price_color,
                font=("Segoe UI", 9, "bold"),
                anchor="center",
                wraplength=0,
            ).pack(fill="both", expand=True)

            qty_frame = tk.Frame(row_frame, bg=row_bg, width=56, height=70)
            qty_frame.pack(side="left", padx=2, pady=0)
            qty_frame.pack_propagate(False)
            tk.Label(qty_frame, text=str(quantity), bg=row_bg, fg=C["text2"], font=("Segoe UI", 9), anchor="center").pack(fill="both", expand=True)

            badge_fr = tk.Frame(row_frame, bg=row_bg, width=82, height=70)
            badge_fr.pack(side="left", padx=(4, 8), pady=0)
            badge_fr.pack_propagate(False)
            tk.Label(
                badge_fr,
                text=badge_txt,
                bg=badge_bg,
                fg="#ffffff",
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=2,
            ).pack(fill="both", expand=True)

    def _fetch_icon_url_bytes(self, url: str) -> Optional[bytes]:
        url = _normalize_media_url(url or "")
        if not url:
            return None
        try:
            r = scraper.get(url, timeout=18)
            r.raise_for_status()
            return r.content
        except Exception as e:
            logger.debug("Fetch ícone %s: %s", url, e)
            return None

    def _photoimage_from_icon_bytes(self, raw: bytes, max_size: int):
        if not raw:
            return None
        try:
            from io import BytesIO
            from PIL import Image, ImageTk

            im = Image.open(BytesIO(raw))
            if im.mode == "P":
                im = im.convert("RGBA")
            elif im.mode in ("RGBA", "LA"):
                im = im.convert("RGBA")
            else:
                im = im.convert("RGBA")
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            im.thumbnail((max_size, max_size), resample)
            im = _pil_knockout_near_white_rgba(im, thresh=246)
            try:
                return ImageTk.PhotoImage(im, master=self)
            except tk.TclError:
                hx = (C.get("card") or "#151515").strip().lstrip("#")
                if len(hx) >= 6:
                    bg_rgb = (
                        int(hx[0:2], 16),
                        int(hx[2:4], 16),
                        int(hx[4:6], 16),
                    )
                else:
                    bg_rgb = (21, 21, 21)
                flat = Image.new("RGB", im.size, bg_rgb)
                flat.paste(im, mask=im.split()[3])
                return ImageTk.PhotoImage(flat, master=self)
        except ImportError:
            logger.warning("Pillow não instalado — sem ícone do item. pip install Pillow")
            return None
        except Exception as e:
            logger.debug("Ícone bytes→PhotoImage: %s", e)
            return None

    def _load_item_icon_photo(self, url: str, max_size: int = 144, item_id: Optional[int] = None):
        """Ícone: cache disco (se item_id) → rede; RAM na sessão."""
        url = _normalize_media_url(url or "")
        ram_key = None
        if item_id is not None:
            try:
                ram_key = (int(item_id), int(max_size))
                hit = self._item_icon_photo_ram.get(ram_key)
                if hit is not None:
                    return hit
            except (TypeError, ValueError):
                ram_key = None
        raw = None
        if item_id is not None:
            try:
                raw = read_item_icon_png_bytes(int(item_id), url, self._fetch_icon_url_bytes)
            except (TypeError, ValueError):
                raw = None
        elif url:
            raw = self._fetch_icon_url_bytes(url)
        if not raw:
            return None
        ph = self._photoimage_from_icon_bytes(raw, max_size)
        if ph is not None and ram_key is not None:
            self._item_icon_photo_ram[ram_key] = ph
        return ph

    def _build_item_preview_card(self, parent, item, photo_holder=None):
        """Painel claro à direita (nome, ícone, descrição, peso), como no site.
        photo_holder: se for uma list, a PhotoImage é guardada em photo_holder[0]
        (janela extra); senão usa self._item_detail_photo_ref."""
        U = ITEM_CARD_UI
        wrap = tk.Frame(
            parent,
            bg=U["bg"],
            highlightbackground=U["border"],
            highlightthickness=2,
        )
        wrap.pack(fill="y", anchor="n")

        inner = tk.Frame(wrap, bg=U["bg"])
        inner.pack(fill="x", padx=12, pady=14)

        title = item.get("item_card_title") or item.get("name") or "Item"
        tk.Label(
            inner,
            text=title,
            bg=U["bg"],
            fg=U["title"],
            font=("Segoe UI", 11, "bold"),
            wraplength=232,
            justify="center",
        ).pack(fill="x", pady=(0, 10))

        icon_url = _normalize_media_url(item.get("item_icon_url") or "")
        img_holder = tk.Frame(inner, bg=U["bg"], highlightbackground="#e8dfd0", highlightthickness=1)
        img_holder.pack(fill="x", pady=(0, 10))

        photo = self._load_item_icon_photo(icon_url) if icon_url else None
        if photo:
            if photo_holder is not None:
                photo_holder.clear()
                photo_holder.append(photo)
            else:
                self._item_detail_photo_ref = photo
            img_lbl = tk.Label(img_holder, image=photo, bg=U["bg"])
            img_lbl._tk_photo_ref = photo
            img_holder._tk_photo_ref = photo
            img_lbl.pack(padx=10, pady=12)
        else:
            tk.Label(
                img_holder,
                text="Sem imagem",
                bg=U["bg"],
                fg=U["muted"],
                font=("Segoe UI", 9),
                pady=28,
            ).pack(fill="x")

        desc = (item.get("item_description") or "").strip()
        
        # Debug: log quando descrição está vazia mas deveria ter
        if not desc and item.get("name"):
            logger.debug(f"⚠️ Item '{item.get('name')}' (ID {item.get('id')}) sem descrição extraída")
        
        desc_fr = tk.Frame(inner, bg=U["desc_bg"], highlightbackground="#ddd", highlightthickness=1)
        desc_fr.pack(fill="x", pady=(0, 10))
        if desc:
            # Usar Text widget para melhor formatação de múltiplas linhas
            desc_text = tk.Text(
                desc_fr,
                bg=U["desc_bg"],
                fg=U["desc_fg"],
                font=("Segoe UI", 9),
                height=25,
                width=28,
                wrap="word",
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=10,
            )
            desc_text.pack(fill="both", expand=True)
            desc_text.insert(tk.END, desc)
            desc_text.config(state="disabled")  # Somente leitura
        else:
            tk.Label(
                desc_fr,
                text="Sem descrição disponível.",
                bg=U["desc_bg"],
                fg=U["muted"],
                font=("Segoe UI", 8),
                wraplength=228,
            ).pack(fill="x", padx=10, pady=10)

        weight = (item.get("item_weight") or "").strip()
        badge = tk.Frame(inner, bg=U["weight_bg"], highlightbackground=U["border"], highlightthickness=1)
        badge.pack(anchor="w")
        tk.Label(
            badge,
            text=f"Peso: {weight}" if weight else "Peso: —",
            bg=U["weight_bg"],
            fg=U["weight_fg"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        ).pack()

        tk.Label(
            inner,
            text=f"ID {item.get('id', '?')}",
            bg=U["bg"],
            fg=U["muted"],
            font=("Segoe UI", 8),
        ).pack(pady=(10, 0))

    def _show_alert_dialog(self, item):
        """Diálogo modal para configurar alertas (Evita travar cliques no Windows)."""
        dialog = tk.Toplevel(self)
        dialog.title(f"Alerta de Preço — {item.get('name', 'Item')}")
        dialog.configure(bg=C["bg"])
        dialog.resizable(False, False)
        dialog.transient(self)
        # Altura suficiente para radiobuttons + botões sempre visíveis
        dialog.geometry("480x680")

        shell = RoundedCard(dialog, radius=22, margin=10, fill_key="card")
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        root = shell.inner

        def dismiss():
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=C["bg2"])
        hdr.pack(fill="x", padx=0, pady=0)
        tk.Label(hdr, text="📢 Configurar Alerta", bg=C["bg2"], fg=C["purple3"],
                 font=("Segoe UI", 12, "bold")).pack(padx=20, pady=12)

        # Conteúdo sem expand=True para não empurrar botões para fora da área clicável
        content = tk.Frame(root, bg=C["card"])
        content.pack(fill="x", padx=20, pady=16)

        tk.Label(content, text="Alertar quando o preço:", bg=C["card"], fg=C["text"],
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

        alert_type = tk.StringVar(value="below")
        DarkRadiobutton(
            content,
            text="Cair abaixo de:",
            variable=alert_type,
            value="below",
            bg=C["card"],
        ).pack(anchor="w", fill="x")
        DarkRadiobutton(
            content,
            text="Subir acima de:",
            variable=alert_type,
            value="above",
            bg=C["card"],
        ).pack(anchor="w", fill="x")

        entry_frame = tk.Frame(content, bg=C["card"])
        entry_frame.pack(fill="x", pady=(12, 8))
        tk.Label(entry_frame, text="Valor:", bg=C["card"], fg=C["text"]).pack(side="left", padx=(0, 10))
        price_entry = DarkEntry(entry_frame, width=18)
        price_entry.pack(side="left")

        tk.Label(content, text="Moeda:", bg=C["card"], fg=C["text"]).pack(anchor="w", pady=(8, 4))

        sale_type = tk.StringVar(value="zeny")
        currency_opts = [
            ("zeny", "ZENY"),
            ("rmt", "RMT"),
            ("hero_points", "HERO POINTS"),
        ]
        for val, label in currency_opts:
            DarkRadiobutton(
                content,
                text=label,
                variable=sale_type,
                value=val,
                bg=C["card"],
            ).pack(anchor="w", fill="x")

        tk.Label(
            content,
            text="E-mail para notificação (opcional — se vazio, usa o padrão em Configurações):",
            bg=C["card"],
            fg=C["text"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(12, 4))
        email_entry = DarkEntry(content, width=42)
        email_entry.pack(anchor="w", fill="x")
        try:
            email_entry.insert(0, (load_settings().get("notify_email") or "").strip())
        except Exception:
            pass

        tk.Label(
            content,
            text="Refino (opcional):",
            bg=C["card"],
            fg=C["text"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(14, 2))
        tk.Label(
            content,
            text="Deixe vazio para qualquer refino. Ex.: 10 — só contam ofertas com refino +10 ou superior.",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")
        ref_frame = tk.Frame(content, bg=C["card"])
        ref_frame.pack(fill="x", pady=(4, 0))
        tk.Label(ref_frame, text="+", bg=C["card"], fg=C["text"]).pack(side="left")
        refinement_entry = DarkEntry(ref_frame, width=6)
        refinement_entry.pack(side="left", padx=(2, 0))

        btn_frame = tk.Frame(root, bg=C["card"])
        btn_frame.pack(fill="x", padx=20, pady=(16, 20))

        def save_alert():
            raw_p = price_entry.get().strip()
            try:
                price_value = float(parse_price_cell(raw_p))
            except (ValueError, TypeError):
                messagebox.showerror(
                    "Erro",
                    "Digite um valor válido (ex.: 500000, 350.000, 12,99 ou 225,000).",
                    parent=dialog,
                )
                return
            if price_value <= 0:
                messagebox.showerror("Erro", "O valor deve ser maior que zero.", parent=dialog)
                return

            ref_raw = refinement_entry.get().strip()
            refinement_val = None
            if ref_raw != "":
                try:
                    refinement_val = int(ref_raw)
                except ValueError:
                    messagebox.showerror(
                        "Erro", "Refino inválido: use um número inteiro (ex.: 0, 7, 10) ou deixe vazio.",
                        parent=dialog,
                    )
                    return
                if refinement_val < 0 or refinement_val > 20:
                    messagebox.showerror("Erro", "Refino deve estar entre 0 e 20.", parent=dialog)
                    return

            sl = item.get("stores_list")
            if isinstance(sl, list) and sl:
                mp = _sale_min_prices_from_stores(sl, min_refinement=refinement_val)
            elif refinement_val is not None:
                mp = {}
            else:
                mp = dict(item["min_prices"]) if item.get("min_prices") else {}

            alerts = load_alerts()
            key = f"{item['id']}_{sale_type.get()}"
            alerts[key] = {
                "item_id": item["id"],
                "item_name": item.get("name"),
                "price": price_value,
                "type": alert_type.get(),
                "sale_type": sale_type.get(),
                "notify_email": email_entry.get().strip(),
                "condition_met": False,
                "created_at": datetime.now().isoformat(),
                **({"item_icon_url": item["item_icon_url"]} if item.get("item_icon_url") else {}),
                **({"min_prices": mp} if mp else {}),
            }
            if refinement_val is not None:
                alerts[key]["refinement"] = refinement_val
            else:
                alerts[key].pop("refinement", None)
            # Ofertas que já cumprem o critério no momento do save ficam «vistas» — só notifica ofertas novas depois.
            try:
                st_chk, _ = get_stores_from_item_page(int(item["id"]), str(item.get("name") or ""))
            except Exception:
                st_chk = list(item.get("stores_list") or [])
            fx = filter_stores_by_currency(st_chk, alerts[key]["sale_type"])
            fx = filter_stores_by_refinement(fx, alerts[key])
            alerts[key]["notified_listing_keys"] = [
                listing_fingerprint(s) for s in qualifying_stores_for_alert(alerts[key], fx)
            ]
            save_alerts(alerts)
            dismiss()
            messagebox.showinfo(
                "Sucesso",
                f"Alerta salvo para {item.get('name')} ({sale_type.get().replace('_', ' ').upper()}). "
                "O programa verifica as lojas online periodicamente; será notificado por cada nova oferta "
                "que cumprir o critério (e-mail e aviso na app, se o SMTP e o destino estiverem configurados).",
                parent=self,
            )

        DarkButton(btn_frame, text="✓ Salvar", style="success", command=save_alert).pack(side="left", padx=4)
        DarkButton(btn_frame, text="✕ Cancelar", style="danger", command=dismiss).pack(side="left", padx=4)

        dialog.protocol("WM_DELETE_WINDOW", dismiss)
        price_entry.focus_set()

        try:
            x = self.winfo_rootx() + 80
            y = self.winfo_rooty() + 40
            dialog.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

        dialog.update_idletasks()
        dialog.lift(self)
        dialog.focus_force()
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

    # ── MONITORADOS ──────────────────────────────────────────────────────────
    def _add_monitor(self, item, sales=None, detail_btn_frame=None):
        try:
            iid = int(item["id"])
        except (TypeError, ValueError):
            return
        if any(int(m["id"]) == iid for m in self.data["monitored"]):
            messagebox.showinfo("Info", "Este item já está sendo monitorado.")
            return
        last_price = sales[0]["price"] if sales else 0
        self.data["monitored"].append({
            "id": iid,
            "name": item.get("name", "Item"),
            "is_costume": item.get("is_costume", False),
            "last_price": last_price,
            "added_at": datetime.now().isoformat(),
            "category": "Gerais",
            **({"item_icon_url": item["item_icon_url"]} if item.get("item_icon_url") else {}),
            **({"min_prices": dict(item["min_prices"])} if item.get("min_prices") else {}),
        })
        save_data(self.data)
        self._update_badge()
        pg = getattr(self, "current_page", None) and self.current_page.get()
        if pg == "busca":
            self._render_monitored_home()
        elif pg == "monitor":
            self._render_monitor()
        if pg == "monitor":
            self._monitored_home_refresh_gen += 1
            g = self._monitored_home_refresh_gen
            threading.Thread(
                target=lambda gen=g: self._refresh_monitored_home_prices_worker(gen),
                daemon=True,
            ).start()
        if detail_btn_frame is not None:
            try:
                if detail_btn_frame.winfo_exists():
                    self._pack_detail_window_header_actions(
                        detail_btn_frame, dict(item), sales if isinstance(sales, list) else []
                    )
            except tk.TclError:
                pass
        else:
            try:
                idx = next(i for i, it in enumerate(self.current_items) if int(it.get("id", -1)) == iid)
            except (StopIteration, TypeError, ValueError):
                idx = None
            if idx is not None and getattr(self, "items_scroll", None) is not None:
                self._render_items(self.current_items)

    def _remove_monitor(self, item, detail_btn_frame=None, detail_all_sales=None):
        try:
            iid = int(item["id"])
        except (TypeError, ValueError):
            return
        self.data["monitored"] = [m for m in self.data["monitored"] if int(m["id"]) != iid]
        save_data(self.data)
        self._update_badge()
        if getattr(self, "current_page", None) and self.current_page.get() == "busca":
            self._render_monitored_home()
        elif getattr(self, "current_page", None) and self.current_page.get() == "monitor":
            self._render_monitor()
        if detail_btn_frame is not None:
            try:
                if detail_btn_frame.winfo_exists():
                    sl = detail_all_sales if isinstance(detail_all_sales, list) else []
                    self._pack_detail_window_header_actions(detail_btn_frame, dict(item), sl)
            except tk.TclError:
                pass
        else:
            try:
                idx = next(i for i, it in enumerate(self.current_items) if int(it.get("id", -1)) == iid)
            except (StopIteration, TypeError, ValueError):
                idx = None
            if idx is not None and getattr(self, "items_scroll", None) is not None:
                self._render_items(self.current_items)

    def _build_monitor(self):
        self.monitor_frame = tk.Frame(self.main, bg=C["bg"])

        hdr = tk.Frame(self.monitor_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 4))
        tk.Label(hdr, text="Itens Monitorados", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            hdr,
            text="Imagem, nome, ID e menores preços por moeda nas lojas online; actualização ao abrir esta página.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w")

        mon_search_row = tk.Frame(self.monitor_frame, bg=C["bg"])
        mon_search_row.pack(fill="x", padx=20, pady=(8, 0))
        self._pack_list_search_bar(mon_search_row, "monitor", "Buscar item (nome ou ID):")

        self.monitor_list_frame = ScrollableFrame(self.monitor_frame)
        self.monitor_list_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def _show_monitor(self):
        self._clear_main()
        self.monitor_frame.pack(fill="both", expand=True)
        self._render_monitor()
        self._monitored_home_refresh_gen += 1
        gen = self._monitored_home_refresh_gen
        threading.Thread(
            target=lambda g=gen: self._refresh_monitored_home_prices_worker(g),
            daemon=True,
        ).start()

    def _render_monitor(self):
        for w in self.monitor_list_frame.inner.winfo_children():
            w.destroy()
        self._monitor_list_photo_refs = []

        monitored_all = self.data.get("monitored") or []
        mon_q = self._list_search_query("monitor")
        monitored = monitored_all
        if mon_q:
            monitored = [m for m in monitored_all if item_matches_search(m, mon_q)]

        if not monitored:
            if monitored_all and mon_q:
                empty_msg = f"🔍\n\nNenhum item corresponde a «{mon_q}»."
            else:
                empty_msg = (
                    "🔔\n\nNenhum item monitorado.\n\nBusque um item e clique em '+ Monitorar'."
                )
            tk.Label(
                self.monitor_list_frame.inner,
                text=empty_msg,
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=60)
            self._list_search_update_hint("monitor", 0, len(monitored_all))
            return

        for m in monitored:
            added = m.get("added_at", "")[:10]
            _, row, bind_target = self._pack_item_store_snapshot_row(
                self.monitor_list_frame.inner,
                m,
                self._monitor_list_photo_refs,
                wraplength=520,
                layout="split",
                id_subline=f"ID: {m['id']}  ·  Adicionado: {added}",
            )
            btns = tk.Frame(row, bg=C["card"])
            btns.pack(side="right")
            DarkButton(
                btns,
                text="Ver preços",
                style="ghost",
                command=lambda iid=m["id"], nm=str(m.get("name", "") or ""): self._open_search_by_item_id(iid, nm),
            ).pack(side="left", padx=3)
            DarkButton(
                btns,
                text="Remover",
                style="danger",
                command=lambda mid=m["id"]: self._remove_by_id(mid),
            ).pack(side="left")
            self._bind_click_open_item_detail(bind_target, int(m["id"]), str(m.get("name", "") or ""))

        self._list_search_scroll_to_top(self.monitor_list_frame)
        self._list_search_update_hint("monitor", len(monitored), len(monitored_all))

    def _remove_by_id(self, item_id):
        try:
            rid = int(item_id)
        except (TypeError, ValueError):
            return
        self.data["monitored"] = [m for m in self.data["monitored"] if int(m["id"]) != rid]
        save_data(self.data)
        self._update_badge()
        self._render_monitor()
        if getattr(self, "current_page", None) and self.current_page.get() == "busca":
            self._render_monitored_home()

    def _open_item_detail_window(self, *, item=None, item_id=None, item_name_hint=""):
        """Abre lojas + histórico do item numa nova janela (sempre)."""
        if item is not None:
            iid = int(item["id"])
            iw = dict(item)
            title_name = str(iw.get("name") or item_name_hint or f"Item {iid}")
        elif item_id is not None:
            iid = int(item_id)
            title_name = str(item_name_hint or f"Item {iid}")
            iw = {"id": iid, "name": title_name}
        else:
            return

        win = tk.Toplevel(self)
        win.title(f"{title_name} — lojas e histórico")
        win.geometry("1000x760")
        win.configure(bg=C["bg"])
        win.minsize(720, 520)

        shell = RoundedCard(win, radius=20, margin=8, fill_key="card")
        shell.pack(fill="both", expand=True, padx=10, pady=10)
        container = shell.inner

        def clear_popup_chart():
            c = getattr(win, "_hs_chart_canvas", None)
            if c is not None:
                try:
                    c.get_tk_widget().destroy()
                except Exception:
                    pass
                win._hs_chart_canvas = None

        def set_popup_chart(c):
            clear_popup_chart()
            win._hs_chart_canvas = c

        tk.Label(
            container,
            text="⏳ A carregar lojas online e histórico de vendas…",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 11),
        ).pack(expand=True, pady=48)

        preview_ph = []

        def _safe_relift_item_win():
            try:
                if win.winfo_exists():
                    win.lift(self)
            except tk.TclError:
                pass

        def finish(iwork, data):
            if not win.winfo_exists():
                return
            clear_popup_chart()
            for w in container.winfo_children():
                w.destroy()
            self._render_detail_into(
                container,
                iwork,
                data,
                chart_setter=set_popup_chart,
                preview_photo_holder=preview_ph,
            )
            disp = (
                str(iwork.get("name") or iwork.get("item_card_title") or "").strip()
                or f"Item {iwork.get('id', '?')}"
            )
            try:
                win.title(f"{disp} — lojas e histórico")
            except tk.TclError:
                pass
            try:
                win.lift(self)
                win.after(150, _safe_relift_item_win)
            except tk.TclError:
                pass

        def fail(msg):
            if not win.winfo_exists():
                return
            clear_popup_chart()
            for w in container.winfo_children():
                w.destroy()
            tk.Label(
                container,
                text=f"⚠ Erro ao carregar:\n{msg}",
                bg=C["bg"],
                fg=C["red"],
                font=("Segoe UI", 10),
                wraplength=480,
                justify="center",
            ).pack(expand=True, pady=40)

        def run():
            try:
                data = api_item_history(iid)
                iwork = dict(iw)
                if SCRAPER_AVAILABLE:
                    d = get_herosaga_item_stores(iid)
                    if d and "error" not in d:
                        for _k in _ITEM_CARD_KEYS:
                            v = d.get(_k)
                            if v:
                                iwork[_k] = _normalize_media_url(v) if _k == "item_icon_url" else v
                        if d.get("stores") is not None:
                            st = d["stores"]
                            iwork["stores_list"] = list(st) if isinstance(st, (list, tuple)) else []
                _sync_iwork_name_from_sources(iwork, data if isinstance(data, dict) else None)
                iwork_snap = dict(iwork)
                data_snap = dict(data) if isinstance(data, dict) else data
                self.after(0, lambda iw=iwork_snap, dt=data_snap: finish(iw, dt))
            except Exception as ex:
                logger.error("Janela item %s: %s", iid, ex)
                self.after(0, lambda m=str(ex): fail(m))

        def on_close():
            clear_popup_chart()
            try:
                win.destroy()
            except tk.TclError:
                pass

        win.protocol("WM_DELETE_WINDOW", on_close)
        threading.Thread(target=run, daemon=True).start()

    def _open_search_by_item_id(self, item_id: int, item_name: str = ""):
        """Compat: abre detalhe (lojas + histórico) numa nova janela."""
        self._open_item_detail_window(item_id=item_id, item_name_hint=item_name or "")

    def _quick_search(self, query: str):
        """Repete uma busca do histórico (texto livre: nome ou ID)."""
        self._nav("busca", self._show_busca)
        self.update_idletasks()
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, query)
        self.search_entry.configure(fg=C["text"])
        self._do_search()

    def _update_badge(self):
        count = len(self.data["monitored"])
        if count > 0:
            text = str(count)
            if count >= 100:
                self.badge_lbl.configure(text=text, font=("Segoe UI", 6, "bold"))
                badge_w = 28
            elif count >= 10:
                self.badge_lbl.configure(text=text, font=("Segoe UI", 7, "bold"))
                badge_w = 24
            else:
                self.badge_lbl.configure(text=text, font=("Segoe UI", 7, "bold"))
                badge_w = 20
            self.badge_fr.configure(width=max(20, badge_w), height=20)
            self.badge_fr.place(relx=1.0, rely=0.5, anchor="e", x=-6)
        else:
            self.badge_fr.place_forget()

    # ── ALERTAS ──────────────────────────────────────────────────────────────
    def _build_alertas(self):
        self.alertas_frame = tk.Frame(self.main, bg=C["bg"])

        hdr = tk.Frame(self.alertas_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 4))
        tk.Label(hdr, text="Alertas de Preço", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            hdr,
            text="Cada alerta mostra o item e os menores preços por moeda (só listagens com refino igual ou superior ao do alerta, se definido); actualização ao abrir esta página.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w")

        alert_search_row = tk.Frame(self.alertas_frame, bg=C["bg"])
        alert_search_row.pack(fill="x", padx=20, pady=(8, 0))
        self._pack_list_search_bar(alert_search_row, "alertas", "Buscar item (nome ou ID):")

        self.alertas_list_frame = ScrollableFrame(self.alertas_frame)
        self.alertas_list_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def _show_alertas(self):
        self._clear_main()
        self.alertas_frame.pack(fill="both", expand=True)
        self._render_alertas()
        self._alerts_display_refresh_gen += 1
        gen = self._alerts_display_refresh_gen
        threading.Thread(
            target=lambda g=gen: self._refresh_alertas_display_prices_worker(g),
            daemon=True,
        ).start()

    def _render_alertas(self):
        for w in self.alertas_list_frame.inner.winfo_children():
            w.destroy()
        self._alertas_list_photo_refs = []

        alerts_all = load_alerts()
        alert_q = self._list_search_query("alertas")
        alert_items = list(alerts_all.items())
        if alert_q:
            alert_items = [(k, a) for k, a in alert_items if item_matches_search(a, alert_q)]

        if not alert_items:
            if alerts_all and alert_q:
                empty_msg = f"🔍\n\nNenhum alerta corresponde a «{alert_q}»."
            else:
                empty_msg = (
                    "🔊\n\nNenhum alerta configurado.\n\n"
                    "Clique em 'Alerta' ao visualizar um item para criar um."
                )
            tk.Label(
                self.alertas_list_frame.inner,
                text=empty_msg,
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=60)
            self._list_search_update_hint("alertas", 0, len(alerts_all))
            return

        for key, alert_info in alert_items:
            sale_type = (alert_info.get("sale_type", "") or "").upper().replace("_", " ")
            alert_type = "cair abaixo" if alert_info.get("type") == "below" else "subir acima"
            price = fmt_price_stores(alert_info.get("price", 0))
            notify = (alert_info.get("notify_email") or "").strip()
            bell_color = C["green"] if alert_info.get("type") == "below" else C["red"]

            footer_labels = [
                {
                    "text": f"🔔 {sale_type}  ·  ➞ {alert_type} de {price}",
                    "fg": bell_color,
                    "font": ("Segoe UI", 8, "bold"),
                    "pady": (8, 0),
                },
            ]
            ref_f = alert_info.get("refinement")
            if ref_f is not None and str(ref_f).strip() != "":
                try:
                    footer_labels.append(
                        {
                            "text": f"⚔ Refino +{int(ref_f)} ou superior",
                            "fg": C["yellow"],
                            "font": ("Segoe UI", 8),
                            "pady": (2, 0),
                        }
                    )
                except (TypeError, ValueError):
                    pass
            if notify:
                footer_labels.append(
                    {
                        "text": f"✉ {notify}",
                        "fg": C["text3"],
                        "font": ("Segoe UI", 8),
                        "pady": (2, 0),
                    }
                )

            iid = int(alert_info["item_id"])
            _, row, bind_target = self._pack_item_store_snapshot_row(
                self.alertas_list_frame.inner,
                alert_info,
                self._alertas_list_photo_refs,
                wraplength=480,
                layout="split",
                id_subline=f"ID: {iid}  ·  clique para abrir janela",
                footer_labels=footer_labels,
            )
            btn_frame = tk.Frame(row, bg=C["card"])
            btn_frame.pack(side="right", padx=0)
            DarkButton(
                btn_frame,
                text="Ver preços",
                style="ghost",
                command=lambda x=iid, nm=str(alert_info.get("item_name", "") or ""): self._open_search_by_item_id(
                    x, nm
                ),
            ).pack(side="left", padx=2)
            DarkButton(btn_frame, text="✕ Remover", style="danger",
                       command=lambda k=key: self._remove_alert(k)).pack(side="left", padx=2)
            self._bind_click_open_item_detail(
                bind_target, iid, str(alert_info.get("item_name", "") or "")
            )

        self._list_search_scroll_to_top(self.alertas_list_frame)
        self._list_search_update_hint("alertas", len(alert_items), len(alerts_all))

    def _remove_alert(self, alert_key):
        """Remove um alerta."""
        alerts = load_alerts()
        if alert_key in alerts:
            del alerts[alert_key]
            save_alerts(alerts)
            messagebox.showinfo("Sucesso", "Alerta removido!")
            self._render_alertas()

    def _schedule_alert_monitor_cycle(self):
        """Reagenda verificação periódica de alertas (consulta lojas online)."""
        settings = load_settings()
        sec = max(60, int(settings.get("alert_interval_seconds", 300)))
        ms = sec * 1000
        if self._alert_after_id is not None:
            try:
                self.after_cancel(self._alert_after_id)
            except tk.TclError:
                pass
        self._alert_after_id = self.after(ms, self._alert_monitor_tick)

    def _alert_monitor_tick(self):
        """Executa uma rodada de verificação em thread (evita travar a UI)."""

        def worker():
            try:
                alerts = load_alerts()
                settings = load_settings()
                if alerts:
                    snap = dict(alerts)
                    events, updates = run_alert_pass(snap, settings, get_stores_from_item_page)
                    with _ALERTS_IO_LOCK:
                        cur = load_alerts()
                        for key, u in updates.items():
                            if key in cur:
                                cur[key]["condition_met"] = u["condition_met"]
                                if "notified_listing_keys" in u:
                                    cur[key]["notified_listing_keys"] = u["notified_listing_keys"]
                        save_alerts(cur)
                    if events:
                        st_copy = dict(settings)
                        ev_copy = list(events)
                        self.after(
                            0,
                            lambda ev=ev_copy, st=st_copy: self._dispatch_alert_events(ev, st),
                        )
                try:
                    build_ev = run_build_total_alerts(get_stores_from_item_page)
                except Exception as e:
                    logger.debug("Alertas build total: %s", e)
                    build_ev = []
                if build_ev:
                    st_copy = dict(settings)
                    bev = list(build_ev)
                    self.after(
                        0,
                        lambda ev=bev, st=st_copy: self._dispatch_build_alert_events(ev, st),
                    )
            except Exception as e:
                logger.exception("Monitor de alertas: %s", e)
            finally:
                self.after(0, self._schedule_alert_monitor_cycle)

        threading.Thread(target=worker, daemon=True).start()

    def _dispatch_alert_events(self, events, settings):
        """E-mail + pop-up e som (Windows) para cada alerta disparado."""
        for ev in events:
            alert = ev["alert"]
            store = ev["store"]
            shop = (store.get("char_name") or store.get("seller_name") or "Loja")[:48]
            body = build_email_body(alert, store, ev.get("extra"))
            subject = f"[Herosaga] Alerta: {alert.get('item_name', 'Item')} — {shop}"
            to_addr = (alert.get("notify_email") or "").strip() or (
                settings.get("notify_email") or ""
            ).strip()
            smtp_ok = bool((settings.get("smtp_host") or "").strip()) and bool(to_addr)
            if smtp_ok:
                ok, err = send_alert_email(settings, to_addr, subject, body)
                if not ok:
                    logger.warning("E-mail de alerta: %s", err)
                    body = f"{body}\n\n(Erro ao enviar e-mail: {err})"
            else:
                body = (
                    f"{body}\n\n"
                    "(Configure o e-mail e o SMTP em Configurações, ou informe o e-mail no alerta.)"
                )
            try:
                if sys.platform == "win32":
                    import winsound

                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
            messagebox.showinfo("Alerta de preço", body, parent=self)

    def _dispatch_build_alert_events(self, events, settings):
        """Notifica quando o custo total (HP equiv. ou Zeny em builds antigas) cai abaixo do limiar."""
        for ev in events:
            body = build_email_body_build_total(ev)
            kind = ev.get("alert_kind") or "zeny"
            if kind == "hp_equiv":
                subject = f"[Herosaga] Build «{ev.get('build_name', 'Build')}» — custo total HP (equiv.)"
            else:
                subject = f"[Herosaga] Build «{ev.get('build_name', 'Build')}» — custo total Zeny"
            to_addr = (ev.get("notify_email") or "").strip() or (settings.get("notify_email") or "").strip()
            smtp_ok = bool((settings.get("smtp_host") or "").strip()) and bool(to_addr)
            if smtp_ok:
                ok, err = send_alert_email(settings, to_addr, subject, body)
                if not ok:
                    logger.warning("E-mail alerta build: %s", err)
                    body = f"{body}\n\n(Erro ao enviar e-mail: {err})"
            else:
                body = (
                    f"{body}\n\n"
                    "(Configure o e-mail e o SMTP em Configurações para receber alertas por e-mail.)"
                )
            try:
                if sys.platform == "win32":
                    import winsound

                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
            messagebox.showinfo("Alerta de build (custo total)", body, parent=self)

    # ── CONFIGURAÇÕES ─────────────────────────────────────────────────────────
    def _build_config(self):
        self.config_frame = tk.Frame(self.main, bg=C["bg"])
        hdr = tk.Frame(self.config_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 6))
        tk.Label(
            hdr,
            text="Configurações",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="E-mail, SMTP, tema da interface e início com o Windows",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        scroll = ScrollableFrame(self.config_frame)
        self._config_scroll = scroll
        scroll.pack(fill="both", expand=True, padx=20, pady=8)
        inner = scroll.inner

        self._cfg_fields = {}

        def add_row(parent, label, key, password=False, width=44):
            fr = tk.Frame(parent, bg=C["bg"])
            fr.pack(fill="x", pady=4)
            tk.Label(
                fr,
                text=label,
                bg=C["bg"],
                fg=C["text"],
                width=26,
                anchor="w",
                font=("Segoe UI", 9),
            ).pack(side="left", padx=(0, 8))
            e = DarkEntry(fr, width=width)
            if password:
                e.configure(show="*")
            e.pack(side="left", fill="x", expand=True)
            self._cfg_fields[key] = e

        s = load_settings()

        mail_hdr = tk.Frame(inner, bg=C["bg"])
        mail_hdr.pack(fill="x", pady=(0, 8))
        tk.Label(
            mail_hdr,
            text="Notificações por e-mail (SMTP)",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            mail_hdr,
            text="Estes dados enviam os alertas de preço. Use a roda do rato para ver o resto da página.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        add_row(inner, "E-mail destino (padrão)", "notify_email")
        self._cfg_fields["notify_email"].insert(0, s.get("notify_email") or "")
        add_row(inner, "SMTP servidor", "smtp_host")
        self._cfg_fields["smtp_host"].insert(0, s.get("smtp_host") or "")
        add_row(inner, "SMTP porta", "smtp_port")
        self._cfg_fields["smtp_port"].insert(0, str(s.get("smtp_port") or 587))
        add_row(inner, "SMTP utilizador", "smtp_user")
        self._cfg_fields["smtp_user"].insert(0, s.get("smtp_user") or "")
        add_row(inner, "SMTP palavra-passe", "smtp_password", password=True)
        self._cfg_fields["smtp_password"].insert(0, s.get("smtp_password") or "")

        tls_fr = tk.Frame(inner, bg=C["bg"])
        tls_fr.pack(fill="x", pady=6)
        self._cfg_tls = tk.BooleanVar(value=bool(s.get("smtp_use_tls", True)))
        DarkCheckbutton(
            tls_fr,
            text="Usar TLS (STARTTLS, porta 587 — recomendado Gmail/Outlook)",
            variable=self._cfg_tls,
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x")

        tk.Label(
            inner,
            text="A palavra-passe SMTP fica guardada neste computador (ficheiro em %USERPROFILE%).",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(10, 14))

        dp_fr = tk.Frame(inner, bg=C["bg"])
        dp_fr.pack(fill="x", pady=(0, 14))
        tk.Label(
            dp_fr,
            text="Divine Pride (API opcional)",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            dp_fr,
            text="Documentação: https://www.divine-pride.net/api — pedir chave no perfil do fórum. "
            "Alternativa: DIVINE_PRIDE_API_KEY. Pedidos Monster/Item usam Accept-Language inglês; "
            "o servidor (p.ex. iRO) define o shard em ?server=.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        add_row(dp_fr, "Chave API Divine Pride", "divine_pride_api_key", password=True, width=40)
        self._cfg_fields["divine_pride_api_key"].insert(0, s.get("divine_pride_api_key") or "")
        add_row(dp_fr, "Servidor DP (iRO, bRO…)", "divine_pride_server", width=12)
        self._cfg_fields["divine_pride_server"].insert(0, s.get("divine_pride_server") or "iRO")

        theme_fr = tk.Frame(inner, bg=C["bg"])
        theme_fr.pack(fill="x", pady=(0, 14))
        tk.Label(
            theme_fr,
            text="Tema da interface",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        self._cfg_theme = tk.StringVar(value=s.get("ui_theme", "dark"))
        DarkRadiobutton(
            theme_fr,
            text="Escuro (preto e cinza)",
            variable=self._cfg_theme,
            value="dark",
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x", pady=1)
        DarkRadiobutton(
            theme_fr,
            text="Claro",
            variable=self._cfg_theme,
            value="light",
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x", pady=1)

        mh_home_fr = tk.Frame(inner, bg=C["bg"])
        mh_home_fr.pack(fill="x", pady=(0, 14))
        tk.Label(
            mh_home_fr,
            text="Colunas dos monitorados (página Buscar)",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            mh_home_fr,
            text="Largura mínima: largura mínima de cada coluna (px). "
            "Meta visível: usada com o nº de categorias — a janela divide-se pelo maior dos dois, "
            "e aplica-se o maior entre esse valor e a largura mínima (160–600 px; meta 1–8). "
            "Guarde e volte a «Buscar Item» para ver; ao guardar, a grelha actualiza-se em segundo plano.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 8),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        add_row(mh_home_fr, "Largura mín. (px)", "monitor_home_col_min_width", width=8)
        self._cfg_fields["monitor_home_col_min_width"].insert(
            0, str(s.get("monitor_home_col_min_width") or 260)
        )
        add_row(mh_home_fr, "Meta cols. visíveis", "monitor_home_min_visible_cols", width=8)
        self._cfg_fields["monitor_home_min_visible_cols"].insert(
            0, str(s.get("monitor_home_min_visible_cols") or 3)
        )

        iv_fr = tk.Frame(inner, bg=C["bg"])
        iv_fr.pack(fill="x", pady=4)
        tk.Label(
            iv_fr,
            text="Intervalo verificação alertas (s)",
            bg=C["bg"],
            fg=C["text"],
            width=26,
            anchor="w",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 8))
        self._cfg_fields["alert_interval_seconds"] = DarkEntry(iv_fr, width=12)
        self._cfg_fields["alert_interval_seconds"].insert(0, str(s.get("alert_interval_seconds") or 300))

        as_fr = tk.Frame(inner, bg=C["bg"])
        as_fr.pack(fill="x", pady=8)
        self._cfg_autostart = tk.BooleanVar(value=bool(s.get("start_with_windows", False)))
        DarkCheckbutton(
            as_fr,
            text="Iniciar o Herosaga Monitor com o Windows",
            variable=self._cfg_autostart,
            bg=C["bg"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", fill="x")

        btn_fr = tk.Frame(self.config_frame, bg=C["bg"])
        btn_fr.pack(fill="x", padx=20, pady=(8, 20))

        def _save_config():
            try:
                port = int(self._cfg_fields["smtp_port"].get().strip() or "587")
            except ValueError:
                messagebox.showerror("Erro", "Porta SMTP inválida.", parent=self)
                return
            try:
                interval = int(self._cfg_fields["alert_interval_seconds"].get().strip() or "300")
            except ValueError:
                messagebox.showerror("Erro", "Intervalo inválido.", parent=self)
                return
            interval = max(60, interval)
            try:
                mhw = int(self._cfg_fields["monitor_home_col_min_width"].get().strip() or "260")
            except ValueError:
                messagebox.showerror(
                    "Erro",
                    "Largura mínima das colunas inválida (use um número).",
                    parent=self,
                )
                return
            mhw = max(160, min(600, mhw))
            try:
                mhv = int(self._cfg_fields["monitor_home_min_visible_cols"].get().strip() or "3")
            except ValueError:
                messagebox.showerror(
                    "Erro",
                    "Meta de colunas visíveis inválida (use um número inteiro).",
                    parent=self,
                )
                return
            mhv = max(1, min(8, mhv))
            data = load_settings()
            prev_theme = data.get("ui_theme", "dark")
            data["notify_email"] = self._cfg_fields["notify_email"].get().strip()
            data["smtp_host"] = self._cfg_fields["smtp_host"].get().strip()
            data["smtp_port"] = port
            data["smtp_user"] = self._cfg_fields["smtp_user"].get().strip()
            data["smtp_password"] = self._cfg_fields["smtp_password"].get()
            data["smtp_use_tls"] = self._cfg_tls.get()
            data["alert_interval_seconds"] = interval
            data["start_with_windows"] = self._cfg_autostart.get()
            data["ui_theme"] = self._cfg_theme.get()
            data["monitor_home_col_min_width"] = mhw
            data["monitor_home_min_visible_cols"] = mhv
            data["divine_pride_api_key"] = self._cfg_fields["divine_pride_api_key"].get().strip()
            data["divine_pride_server"] = self._cfg_fields["divine_pride_server"].get().strip()
            save_settings(data)
            try:
                if self.busca_frame.winfo_exists():
                    self._render_monitored_home()
            except (tk.TclError, AttributeError):
                pass
            if data.get("ui_theme") != prev_theme:
                self._reapply_theme(data.get("ui_theme", "dark"))
            ok, msg = set_windows_autostart(data["start_with_windows"])
            extra = f"\n{msg}" if msg else ""
            if not ok and data["start_with_windows"]:
                messagebox.showwarning("Início automático", f"Não foi possível activar:{extra}", parent=self)
            else:
                messagebox.showinfo("Configurações", f"Guardado.{extra}", parent=self)
            self._schedule_alert_monitor_cycle()

        def _test_email():
            st = load_settings()
            to_addr = self._cfg_fields["notify_email"].get().strip()
            if not to_addr:
                messagebox.showerror("Erro", "Indique o e-mail destino.", parent=self)
                return
            ok, err = send_alert_email(
                {
                    **st,
                    "smtp_host": self._cfg_fields["smtp_host"].get().strip(),
                    "smtp_port": int(self._cfg_fields["smtp_port"].get().strip() or "587"),
                    "smtp_user": self._cfg_fields["smtp_user"].get().strip(),
                    "smtp_password": self._cfg_fields["smtp_password"].get(),
                    "smtp_use_tls": self._cfg_tls.get(),
                },
                to_addr,
                "[Herosaga] Teste de e-mail",
                "Se recebeu esta mensagem, o SMTP está configurado correctamente.",
            )
            if ok:
                messagebox.showinfo("Teste", "E-mail de teste enviado.", parent=self)
            else:
                messagebox.showerror("Teste", f"Falhou:\n{err}", parent=self)

        def _test_divine_pride():
            key = self._cfg_fields["divine_pride_api_key"].get().strip()
            srv = self._cfg_fields["divine_pride_server"].get().strip() or None
            if not key:
                messagebox.showerror(
                    "Divine Pride",
                    "Indique a chave API ou use DIVINE_PRIDE_API_KEY.",
                    parent=self,
                )
                return
            try:
                from divine_pride_api import fetch_item

                d = fetch_item(5017, api_key=key, server=srv)
                nm = d.get("name") or "?"
                messagebox.showinfo(
                    "Divine Pride",
                    f"Ligação OK. Item de teste 5017: {nm}",
                    parent=self,
                )
            except Exception as e:
                messagebox.showerror("Divine Pride", str(e), parent=self)

        DarkButton(btn_fr, text="Guardar", style="success", command=_save_config).pack(
            side="left", padx=4
        )
        DarkButton(btn_fr, text="Enviar e-mail de teste", style="primary", command=_test_email).pack(
            side="left", padx=4
        )
        DarkButton(btn_fr, text="Testar Divine Pride", style="ghost", command=_test_divine_pride).pack(
            side="left", padx=4
        )

    def _show_config(self):
        self._clear_main()
        s = load_settings()
        for key, entry in self._cfg_fields.items():
            entry.delete(0, "end")
            if key == "smtp_port":
                entry.insert(0, str(s.get(key) or 587))
            elif key == "alert_interval_seconds":
                entry.insert(0, str(s.get(key) or 300))
            elif key == "monitor_home_col_min_width":
                entry.insert(0, str(s.get(key) or 260))
            elif key == "monitor_home_min_visible_cols":
                entry.insert(0, str(s.get(key) or 3))
            else:
                entry.insert(0, str(s.get(key) or ""))
        self._cfg_tls.set(bool(s.get("smtp_use_tls", True)))
        self._cfg_autostart.set(bool(s.get("start_with_windows", False)))
        self._cfg_theme.set(s.get("ui_theme", "dark"))
        self.config_frame.pack(fill="both", expand=True)

        def _cfg_scroll_top():
            sc = getattr(self, "_config_scroll", None)
            if sc is not None:
                try:
                    sc.inner.update_idletasks()
                except tk.TclError:
                    pass
                sc.yview_top()

        self.after_idle(_cfg_scroll_top)

    # ── SIMULAÇÃO DE BUILD ───────────────────────────────────────────────────
    def _build_build_sim(self):
        self.build_sim_frame = tk.Frame(self.main, bg=C["bg"])
        self._build_sim_refresh_gen = 0
        self._build_state = {"equip": default_layer_state(), "visual": default_layer_state()}
        self._build_ui_slot_widgets = {"equip": {}, "visual": {}}
        self._build_price_cache = {}
        self._build_sim_photo_refs = []
        self._build_sim_last_saved_id = None
        self._build_sim_selected_saved_id = None

        scroll = ScrollableFrame(self.build_sim_frame, inner_bg=C["bg"])
        scroll.pack(fill="both", expand=True, padx=10, pady=8)
        root = scroll.inner

        hdr = tk.Frame(root, bg=C["bg"])
        hdr.pack(fill="x", pady=(4, 8))
        hdr_top = tk.Frame(hdr, bg=C["bg"])
        hdr_top.pack(fill="x")
        tk.Label(
            hdr_top,
            text="Simulação de Build",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left", anchor="w")
        hdr_pick = tk.Frame(hdr, bg=C["bg"])
        hdr_pick.pack(fill="x", pady=(8, 0))
        tk.Label(
            hdr_pick,
            text="Build guardada:",
            bg=C["bg"],
            fg=C["text"],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 8))
        self._build_sim_combo_ignore = False
        self._build_sim_saved_list = []
        self._build_sim_saved_combo = ttk.Combobox(
            hdr_pick,
            state="readonly",
            width=56,
            font=("Segoe UI", 9),
        )
        self._build_sim_saved_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._build_sim_saved_combo.bind("<<ComboboxSelected>>", self._build_sim_on_saved_combo_pick)
        DarkButton(
            hdr_pick,
            text="Principal",
            style="ghost",
            font=("Segoe UI", 8),
            padx=8,
            pady=2,
            command=self._build_sim_mark_selected_as_primary,
        ).pack(side="left")

        totals = tk.Frame(root, bg=C["card"], highlightbackground=C["border"], highlightthickness=1)
        totals.pack(fill="x", pady=6)
        tk.Label(
            totals,
            text="Totais estimados",
            bg=C["card"],
            fg=C["purple3"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))

        row_hp = tk.Frame(totals, bg=C["card"])
        row_hp.pack(fill="x", padx=12, pady=4)
        tk.Label(row_hp, text="1 RMT =", bg=C["card"], fg=C["text"]).pack(side="left")
        self._build_hp_entry = DarkEntry(row_hp, width=8)
        self._build_hp_entry.pack(side="left", padx=6)
        self._build_hp_entry.insert(0, "30")
        tk.Label(
            row_hp,
            text="Hero Points",
            bg=C["card"],
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack(side="left")

        row_t = tk.Frame(totals, bg=C["card"])
        row_t.pack(fill="x", padx=12, pady=(4, 8))
        self._build_lbl_total_rmt = tk.Label(
            row_t, text="RMT: —", bg=C["card"], fg=C["rmt"], font=("Segoe UI", 10, "bold")
        )
        self._build_lbl_total_rmt.pack(side="left", padx=(0, 14))
        self._build_lbl_total_hp = tk.Label(
            row_t,
            text="HP (equiv.): —",
            bg=C["card"],
            fg=C["hero_points"],
            font=("Segoe UI", 10, "bold"),
        )
        self._build_lbl_total_hp.pack(side="left", padx=(0, 14))

        btn_row = tk.Frame(totals, bg=C["card"])
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        DarkButton(
            btn_row,
            text="Atualizar preços",
            style="primary",
            command=self._build_sim_refresh_prices,
        ).pack(side="left", padx=4)
        DarkButton(btn_row, text="Salvar Build", style="success", command=self._build_sim_save_dialog).pack(
            side="left", padx=4
        )

        boards = tk.Frame(root, bg=C["bg"])
        boards.pack(fill="both", expand=True, pady=8)

        equip_wrap = tk.Frame(boards, bg=C["bg"], highlightthickness=0)
        equip_wrap.pack(side="left", fill="both", expand=True, padx=(4, 36), pady=6)
        self._build_sim_layer_panel(equip_wrap, "equip", "Equipamento (principal)")

        gap_mid = tk.Frame(boards, bg=C["bg"], width=32)
        gap_mid.pack(side="left", fill="y", padx=20, pady=6)
        gap_mid.pack_propagate(False)

        visual_wrap = tk.Frame(boards, bg=C["bg"], highlightthickness=0)
        visual_wrap.pack(side="left", fill="both", expand=True, padx=(36, 4), pady=6)
        self._build_sim_layer_panel(visual_wrap, "visual", "Visual (cosmético)")

        self._build_sim_refresh_saved_combo_list()
        self.after(120, self._build_sim_restore_from_settings)

    def _build_sim_persist_last_saved_id(self):
        """Grava em settings o id da build guardada seleccionada (vazio = nova simulação)."""
        try:
            if not getattr(self, "_build_sim_saved_combo", None):
                return
            sid = getattr(self, "_build_sim_selected_saved_id", None) or ""
            cfg = load_settings()
            cfg["last_build_sim_saved_id"] = str(sid) if sid else ""
            save_settings(cfg)
        except Exception:
            pass

    def _build_sim_mark_selected_as_primary(self):
        """Define a build actualmente seleccionada na lista como principal (aberta ao iniciar)."""
        idx = self._build_sim_saved_combo.current()
        if idx <= 0:
            messagebox.showinfo(
                "Build principal",
                "Seleccione uma build guardada na lista (não «Nova simulação»).",
                parent=self,
            )
            return
        b = self._build_sim_saved_list[idx - 1]
        bid = str(b.get("id") or "")
        if not bid:
            return
        cfg = load_settings()
        cfg["primary_build_sim_saved_id"] = bid
        save_settings(cfg)
        messagebox.showinfo(
            "Build principal",
            "Esta build será carregada ao abrir a simulação (se ainda existir na lista).",
            parent=self,
        )

    def _build_sim_restore_from_settings(self):
        """Ao iniciar, reabre a build principal (se definida), senão a última seleccionada."""
        try:
            if not getattr(self, "_build_sim_saved_combo", None):
                return
            cfg = load_settings()
            primary = (cfg.get("primary_build_sim_saved_id") or "").strip()
            last = (cfg.get("last_build_sim_saved_id") or "").strip()
            sid_order = []
            if primary:
                sid_order.append(primary)
            if last and last not in sid_order:
                sid_order.append(last)
            found = None
            sid = ""
            for cand in sid_order:
                for s in self._build_sim_saved_list:
                    if isinstance(s, dict) and str(s.get("id")) == cand:
                        found = s
                        sid = cand
                        break
                if found:
                    break
            if not found:
                cfg2 = load_settings()
                changed = False
                if primary and not any(
                    isinstance(s, dict) and str(s.get("id")) == primary for s in self._build_sim_saved_list
                ):
                    cfg2["primary_build_sim_saved_id"] = ""
                    changed = True
                if last and not any(
                    isinstance(s, dict) and str(s.get("id")) == last for s in self._build_sim_saved_list
                ):
                    cfg2["last_build_sim_saved_id"] = ""
                    changed = True
                if changed:
                    save_settings(cfg2)
                return
            self._build_sim_combo_ignore = True
            try:
                for i, s in enumerate(self._build_sim_saved_list):
                    if str(s.get("id")) == sid:
                        self._build_sim_saved_combo.current(i + 1)
                        break
            finally:
                self._build_sim_combo_ignore = False
            self._build_sim_selected_saved_id = found.get("id")
            self._build_sim_apply_saved_build_dict(found)
            for layer in ("equip", "visual"):
                for sk in self._all_build_slot_keys():
                    self._build_sim_sync_row_from_state(layer, sk)
                    self._build_sim_update_slot_icon(layer, sk)
            self._build_sim_set_left_hand_state("equip", "weapon_left")
            self._build_sim_clear_slot_price_labels()
            self.after(120, self._build_sim_refresh_prices)
            self.after(140, self._build_sim_fetch_missing_icons)
        except Exception:
            pass

    def _build_sim_refresh_saved_combo_list(self, select_id=None):
        """Preenche o combobox com builds guardadas; ``select_id`` selecciona uma pelo ``id``."""
        data = load_builds_file()
        self._build_sim_saved_list = [x for x in (data.get("saved") or []) if isinstance(x, dict)]
        vals = ["(Nova simulação — não guardada)"] + [
            f"{s.get('name', 'Build')}  [{str(s.get('id', ''))[:8]}]" for s in self._build_sim_saved_list
        ]
        combo = self._build_sim_saved_combo
        combo["values"] = vals
        self._build_sim_combo_ignore = True
        try:
            if select_id:
                sid = str(select_id)
                for i, s in enumerate(self._build_sim_saved_list):
                    if str(s.get("id")) == sid:
                        combo.current(i + 1)
                        self._build_sim_selected_saved_id = s.get("id")
                        break
                else:
                    combo.current(0)
                    self._build_sim_selected_saved_id = None
            else:
                sid = getattr(self, "_build_sim_selected_saved_id", None)
                if sid:
                    found = False
                    for i, s in enumerate(self._build_sim_saved_list):
                        if str(s.get("id")) == str(sid):
                            combo.current(i + 1)
                            found = True
                            break
                    if not found:
                        combo.current(0)
                        self._build_sim_selected_saved_id = None
                else:
                    combo.current(0)
        finally:
            self._build_sim_combo_ignore = False

    def _build_sim_on_saved_combo_pick(self, _event=None):
        if getattr(self, "_build_sim_combo_ignore", False):
            return
        idx = self._build_sim_saved_combo.current()
        if idx < 0:
            return
        if idx == 0:
            self._build_sim_selected_saved_id = None
            self._build_state = {"equip": default_layer_state(), "visual": default_layer_state()}
            try:
                self._build_hp_entry.delete(0, "end")
                self._build_hp_entry.insert(0, "30")
            except tk.TclError:
                pass
        else:
            b = self._build_sim_saved_list[idx - 1]
            self._build_sim_selected_saved_id = b.get("id")
            self._build_sim_apply_saved_build_dict(b)
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                self._build_sim_sync_row_from_state(layer, sk)
                self._build_sim_update_slot_icon(layer, sk)
        self._build_sim_set_left_hand_state("equip", "weapon_left")
        self._build_sim_clear_slot_price_labels()
        if idx > 0:
            self.after(80, self._build_sim_refresh_prices)
            self.after(90, self._build_sim_fetch_missing_icons)
        self._build_sim_persist_last_saved_id()

    def _build_sim_apply_saved_build_dict(self, b: dict):
        try:
            hpr = int(b.get("hp_per_rmt") or 30)
        except (TypeError, ValueError):
            hpr = 30
        try:
            self._build_hp_entry.delete(0, "end")
            self._build_hp_entry.insert(0, str(hpr))
        except tk.TclError:
            pass
        eq = b.get("equip") if isinstance(b.get("equip"), dict) else {}
        vis = b.get("visual") if isinstance(b.get("visual"), dict) else {}
        for layer_key, src in (("equip", eq), ("visual", vis)):
            for sk in self._all_build_slot_keys():
                cell = default_slot_state()
                raw = src.get(sk)
                if not isinstance(raw, dict):
                    for alt in _BUILD_SIM_SLOT_LEGACY_SRC_KEYS.get(sk, ()):
                        raw = src.get(alt)
                        if isinstance(raw, dict):
                            break
                    else:
                        raw = None
                if isinstance(raw, dict):
                    for key in cell:
                        if key not in raw:
                            continue
                        val = raw[key]
                        if key == "item_id" and val is not None:
                            try:
                                val = int(val)
                            except (TypeError, ValueError):
                                pass
                        cell[key] = val
                self._build_state[layer_key][sk] = cell

    def _build_sim_clear_slot_price_labels(self):
        self._build_price_cache = {}
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                w = self._build_ui_slot_widgets[layer][sk]
                w["lrmt"].configure(text="RMT: —", fg=C["rmt"])
                w["lhp"].configure(text="HP: —", fg=C["hero_points"])
        self._build_sim_recalc_totals()

    def _show_build_sim(self):
        self._clear_main()
        self.build_sim_frame.pack(fill="both", expand=True)
        try:
            self._build_sim_refresh_saved_combo_list()
        except (tk.TclError, AttributeError):
            pass

    def _all_build_slot_keys(self):
        return list(BUILD_SLOT_LEFT) + list(BUILD_SLOT_RIGHT)

    def _build_sim_layer_panel(self, parent, layer: str, title: str):
        tk.Label(parent, text=title, bg=C["bg"], fg=C["purple3"], font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=6, pady=(4, 2)
        )
        row = tk.Frame(parent, bg=C["bg"], highlightthickness=0)
        row.pack(fill="both", expand=True, padx=2, pady=(0, 4))
        lf = tk.Frame(row, bg=C["bg"], highlightthickness=0)
        lf.pack(side="left", fill="both", expand=True, padx=(0, 10))
        rf = tk.Frame(row, bg=C["bg"], highlightthickness=0)
        rf.pack(side="left", fill="both", expand=True, padx=(10, 0))

        for sk in BUILD_SLOT_LEFT:
            self._build_sim_slot_row(lf, layer, sk)
        for sk in BUILD_SLOT_RIGHT:
            self._build_sim_slot_row(rf, layer, sk)

    def _build_sim_slot_row(self, parent, layer: str, slot_key: str):
        sb = C["build_slot_bg"]
        rim = C["build_slot_rim"]
        ebg = C["build_slot_entry_bg"]

        outer = tk.Frame(parent, bg=C["bg"], highlightthickness=0)
        outer.pack(fill="x", pady=5, padx=1)

        cv = tk.Canvas(outer, height=92, bg=C["bg"], highlightthickness=0, borderwidth=0)
        cv.pack(fill="x", expand=True)
        inner = tk.Frame(cv, bg=sb)
        win_id = cv.create_window(2, 2, window=inner, anchor="nw")
        _slot_after = [None]

        def redraw(_e=None):
            if _slot_after[0] is not None:
                try:
                    outer.after_cancel(_slot_after[0])
                except tk.TclError:
                    pass

            def run():
                _slot_after[0] = None
                try:
                    cv.update_idletasks()
                    w = max(int(cv.winfo_width()), 80)
                    inner.update_idletasks()
                    ih = max(int(inner.winfo_reqheight()), 32)
                    ht = ih + 8
                    if w == getattr(cv, "_bslot_rw", -1) and ht == getattr(cv, "_bslot_rh", -1):
                        return
                    cv._bslot_rw, cv._bslot_rh = w, ht
                    cv.configure(height=ht)
                    cv.delete("slotbg")
                    ro, ri = 18, 14
                    _canvas_round_fill(cv, 0, 0, w, ht, ro, rim, tag="slotbg", holder=cv)
                    _canvas_round_fill(cv, 4, 4, w - 8, ht - 8, ri, sb, tag="slotbg", holder=cv)
                    cv.itemconfigure(win_id, width=max(1, w - 8), height=max(1, ht - 8))
                    cv.coords(win_id, 4, 4)
                except tk.TclError:
                    pass

            _slot_after[0] = outer.after(28, run)

        inner.bind("<Configure>", redraw)
        cv.bind("<Configure>", redraw)

        top = tk.Frame(inner, bg=sb)
        top.pack(fill="x", padx=8, pady=(6, 0))

        icon_slot = tk.Frame(top, bg=sb, width=36, height=28)
        icon_slot.pack(side="left", padx=(0, 6))
        icon_slot.pack_propagate(False)
        icon_lbl = tk.Label(icon_slot, text="·", bg=sb, fg=C["text3"], font=("Segoe UI", 8))
        icon_lbl.place(relx=0.5, rely=0.5, anchor="center")

        col = tk.Frame(top, bg=sb)
        col.pack(side="left", fill="both", expand=True)

        tk.Label(
            col,
            text=SLOT_LABELS_PT.get(slot_key, slot_key),
            bg=sb,
            fg=C["text2"],
            font=("Segoe UI", 7, "bold"),
            anchor="w",
        ).pack(anchor="w")

        r1 = tk.Frame(col, bg=sb)
        r1.pack(fill="x", pady=0)
        ent = tk.Entry(
            r1,
            bg=ebg,
            fg=C["text"],
            insertbackground=C["purple2"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=C["build_slot_rim"],
            highlightcolor=C["purple2"],
            font=("Segoe UI", 9),
            width=25,
        )
        ent.pack(side="left", fill="none", expand=False, padx=(0, 8), ipady=1)
        tk.Label(r1, text="Ref.", bg=sb, fg=C["text3"], font=("Segoe UI", 7)).pack(side="left", padx=(0, 1))
        tk.Label(r1, text="+", bg=sb, fg=C["text3"], font=("Segoe UI", 7)).pack(side="left", padx=(0, 1))
        ref_sb = tk.Spinbox(
            r1,
            from_=0,
            to=20,
            width=3,
            bg=ebg,
            fg=C["text"],
            buttonbackground=C["bg3"],
            highlightthickness=0,
            font=("Segoe UI", 8),
        )
        ref_sb.pack(side="left", padx=(0, 6))
        tk.Frame(r1, bg=sb).pack(side="left", fill="x", expand=True)
        DarkButton(
            r1,
            text="Buscar",
            style="success",
            font=("Segoe UI", 8),
            padx=8,
            pady=1,
            command=lambda ly=layer, sk=slot_key: self._build_sim_apply_slot(ly, sk),
        ).pack(side="right")

        name_row = tk.Frame(col, bg=sb)
        name_row.pack(fill="x", pady=(4, 0))
        lname = tk.Label(
            name_row,
            text="—",
            bg=sb,
            fg=C["text3"],
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        lname.pack(fill="x", anchor="w")

        prices = tk.Frame(col, bg=sb)
        prices.pack(fill="x", pady=(2, 6))
        fz = ("Segoe UI", 7)
        lrmt = tk.Label(prices, text="RMT: —", bg=sb, fg=C["rmt"], font=fz, anchor="w")
        lrmt.pack(side="left", padx=(0, 6))
        lhp = tk.Label(prices, text="HP: —", bg=sb, fg=C["hero_points"], font=fz, anchor="w")
        lhp.pack(side="left", padx=(0, 6))

        self._build_ui_slot_widgets[layer][slot_key] = {
            "frame": outer,
            "entry": ent,
            "refine_sb": ref_sb,
            "icon_lbl": icon_lbl,
            "lname": lname,
            "lrmt": lrmt,
            "lhp": lhp,
        }
        self._build_sim_sync_row_from_state(layer, slot_key)
        try:
            outer.after_idle(redraw)
        except tk.TclError:
            pass

    def _build_sim_sync_row_from_state(self, layer: str, slot_key: str):
        w = self._build_ui_slot_widgets[layer][slot_key]
        cell = self._build_state[layer][slot_key]
        w["entry"].delete(0, "end")
        iid = cell.get("item_id")
        try:
            if iid is not None and int(iid) > 0:
                w["entry"].insert(0, str(int(iid)))
        except (TypeError, ValueError, tk.TclError):
            pass
        try:
            w["refine_sb"].delete(0, "end")
            w["refine_sb"].insert(0, str(int(cell.get("refine") or 0)))
        except tk.TclError:
            pass
        iid = cell.get("item_id")
        try:
            if iid is not None and int(iid) > 0:
                nm = (cell.get("item_name") or "").strip()
                disp = nm if nm else f"Item {int(iid)}"
                w["lname"].configure(text=disp, fg=C["text2"])
            else:
                w["lname"].configure(text="—", fg=C["text3"])
        except (TypeError, ValueError, tk.TclError, KeyError):
            try:
                w["lname"].configure(text="—", fg=C["text3"])
            except tk.TclError:
                pass
        self._build_sim_set_left_hand_state(layer, slot_key)

    def _build_sim_set_left_hand_state(self, layer: str, slot_key: str):
        if layer != "equip" or slot_key != "weapon_left":
            return
        w = self._build_ui_slot_widgets["equip"]["weapon_left"]
        block = bool(self._build_state["equip"]["weapon_right"].get("is_2h"))
        st = "disabled" if block else "normal"
        try:
            w["entry"].configure(state=st)
            w["refine_sb"].configure(state=st)
        except tk.TclError:
            pass

    def _build_sim_sync_ui_to_state(self):
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                cell = self._build_state[layer][sk]
                if not cell.get("item_id"):
                    continue
                w = self._build_ui_slot_widgets[layer][sk]
                try:
                    cell["refine"] = max(0, min(20, int(w["refine_sb"].get())))
                except (ValueError, TypeError, tk.TclError):
                    cell["refine"] = 0
                cell["cards"] = 0

    def _build_sim_merge_entries_into_state(self):
        """Lê ID e refino das caixas para o estado antes de actualizar preços (sem premir «Buscar»)."""
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                w = self._build_ui_slot_widgets[layer][sk]
                cell = self._build_state[layer][sk]
                try:
                    ref = max(0, min(20, int(w["refine_sb"].get())))
                except (ValueError, TypeError, tk.TclError):
                    try:
                        ref = max(0, min(20, int(cell.get("refine") or 0)))
                    except (TypeError, ValueError):
                        ref = 0
                raw = w["entry"].get().strip()
                pid = None
                if raw:
                    q = raw.strip()
                    low = q.lower()
                    if low.startswith("@ws"):
                        q = q[3:].strip()
                    elif low.startswith("ws") and len(q) > 2 and q[2].isspace():
                        q = q[2:].strip()
                    digits = re.sub(r"\D", "", q)
                    if digits:
                        try:
                            pid = int(digits)
                        except ValueError:
                            pid = None
                try:
                    old_id = int(cell.get("item_id") or 0)
                except (TypeError, ValueError):
                    old_id = 0
                if pid is None:
                    if old_id > 0:
                        cell["refine"] = ref
                    continue
                if old_id != pid:
                    cell["item_name"] = ""
                cell["item_id"] = pid
                cell["refine"] = ref

    def _build_sim_apply_slot(self, layer: str, slot_key: str):
        if layer == "equip" and slot_key == "weapon_left" and self._build_state["equip"]["weapon_right"].get("is_2h"):
            messagebox.showinfo("Arma a duas mãos", "A arma na mão direita ocupa as duas mãos.")
            return
        w = self._build_ui_slot_widgets[layer][slot_key]
        query = w["entry"].get().strip()
        if not query:
            self._build_state[layer][slot_key] = default_slot_state()
            self._build_sim_sync_row_from_state(layer, slot_key)
            self._build_sim_update_slot_icon(layer, slot_key)
            if layer == "equip" and slot_key == "weapon_right":
                self._build_sim_clear_left_if_not_2h()
            return
        try:
            ref_ui = max(0, min(20, int(w["refine_sb"].get())))
        except (ValueError, TypeError, tk.TclError):
            ref_ui = 0

        def work():
            err = None
            try:
                q = query.strip()
                low = q.lower()
                if low.startswith("@ws"):
                    q = q[3:].strip()
                elif low.startswith("ws") and len(q) > 2 and q[2].isspace():
                    q = q[2:].strip()
                digits = re.sub(r"\D", "", q)
                if not digits:
                    raise ValueError("Use só o ID numérico do item (dígitos).")
                iid = int(digits)
                name = f"Item {iid}"
                rows = api_search_item_names(str(iid))
                for r in rows or []:
                    try:
                        if int(r.get("id", 0)) == iid and r.get("name"):
                            name = str(r.get("name")).strip()
                            break
                    except (TypeError, ValueError):
                        continue
                stores, meta = get_stores_from_item_page(iid, "", force_refresh=True)
                ref = ref_ui
                is2 = item_meta_is_two_handed(meta)
                icon_u = meta.get("item_icon_url") if isinstance(meta, dict) else None
            except Exception as e:
                err = str(e)
                iid = name = ref = is2 = icon_u = None
                stores = meta = None

            def done():
                if err:
                    messagebox.showerror("Build", err, parent=self)
                    return
                cell = default_slot_state()
                cell.update(
                    {
                        "item_id": iid,
                        "item_name": name,
                        "refine": ref,
                        "cards": 0,
                        "is_2h": bool(is2),
                        "item_icon_url": _normalize_media_url(icon_u) if icon_u else "",
                    }
                )
                self._build_state[layer][slot_key] = cell
                self._build_sim_sync_row_from_state(layer, slot_key)
                self._build_sim_update_slot_icon(layer, slot_key)
                if layer == "equip" and slot_key == "weapon_right" and cell.get("is_2h"):
                    self._build_state["equip"]["weapon_left"] = default_slot_state()
                    self._build_sim_sync_row_from_state("equip", "weapon_left")
                    self._build_sim_update_slot_icon("equip", "weapon_left")
                elif layer == "equip" and slot_key == "weapon_right":
                    self._build_sim_clear_left_if_not_2h()
                self._build_sim_set_left_hand_state("equip", "weapon_left")
                to_refresh = [(layer, slot_key)]
                if layer == "equip" and slot_key == "weapon_right" and cell.get("is_2h"):
                    to_refresh.append(("equip", "weapon_left"))
                self.after(60, lambda tr=tuple(to_refresh): self._build_sim_refresh_prices_slots(tr))

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_fetch_missing_icons(self):
        """Para slots com ``item_id`` mas sem URL de ícone (ex.: build guardada), obtém o ícone pela página do item."""
        tasks = []
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                cell = self._build_state[layer][sk]
                try:
                    iid = int(cell.get("item_id") or 0)
                except (TypeError, ValueError):
                    continue
                if iid <= 0:
                    continue
                if _normalize_media_url(cell.get("item_icon_url") or ""):
                    continue
                tasks.append((layer, sk, iid))

        if not tasks:
            return

        def work():
            updates = []
            for layer, sk, iid in tasks:
                try:
                    _stores, meta = get_stores_from_item_page(iid, "")
                    if not isinstance(meta, dict):
                        continue
                    icon_u = meta.get("item_icon_url")
                    url = _normalize_media_url(icon_u) if icon_u else ""
                    if url:
                        updates.append((layer, sk, url))
                except Exception:
                    pass

            def apply_icons():
                for layer, sk, url in updates:
                    try:
                        cell = self._build_state.get(layer, {}).get(sk)
                        if not isinstance(cell, dict):
                            continue
                        cell["item_icon_url"] = url
                        self._build_sim_update_slot_icon(layer, sk)
                    except (tk.TclError, KeyError):
                        pass

            self.after(0, apply_icons)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_clear_left_if_not_2h(self):
        if not self._build_state["equip"]["weapon_right"].get("is_2h"):
            self._build_sim_set_left_hand_state("equip", "weapon_left")

    def _build_sim_update_slot_icon(self, layer: str, slot_key: str):
        w = self._build_ui_slot_widgets[layer][slot_key]
        cell = self._build_state[layer][slot_key]
        lbl = w["icon_lbl"]
        url = _normalize_media_url(cell.get("item_icon_url") or "")
        if url:
            ph = self._load_item_icon_photo(url, max_size=26)
            if ph:
                self._build_sim_photo_refs.append(ph)
                lbl.configure(image=ph, text="")
                return
        lbl.configure(image="", text="·")

    def _build_sim_compute_slot_price_cache(self, layer: str, sk: str, *, force_refresh: bool):
        """Calcula entrada de preço para um slot (RMT/HP conforme refino no estado)."""
        cell = self._build_state[layer][sk]
        try:
            iid_int = int(cell.get("item_id") or 0)
        except (TypeError, ValueError):
            return {"empty": True}
        if iid_int <= 0:
            return {"empty": True}
        try:
            stores, _ = get_stores_from_item_page(iid_int, "", force_refresh=force_refresh)
            want_ref = int(cell.get("refine") or 0)
            want_ref = max(0, min(20, want_ref))
            matched = filter_stores_slot(stores, want_ref, 0)
            mp = min_prices_from_stores(matched, only_qty_one=True)
            if not mp and want_ref == 0:
                # +0: se não houver linha exacta, ainda pode haver inconsistência no site — usa o menor global.
                mp = min_prices_from_stores(stores or [], only_qty_one=True)
            elif not mp:
                # Refino > 0: não misturar outras refinagens (evita mostrar preço de +0 quando pediu +10).
                mp = {}
            return {"empty": False, "mins": mp}
        except Exception as e:
            return {"empty": False, "err": str(e)}

    def _build_sim_apply_price_entry_to_slot_widgets(self, layer: str, sk: str, ent: dict):
        w = self._build_ui_slot_widgets[layer][sk]
        if ent.get("empty"):
            w["lrmt"].configure(text="RMT: —", fg=C["rmt"])
            w["lhp"].configure(text="HP: —", fg=C["hero_points"])
            return
        if ent.get("err"):
            w["lrmt"].configure(text=f"Erro: {ent['err'][:24]}", fg=C["rmt"])
            w["lhp"].configure(text="", fg=C["hero_points"])
            return
        mp = ent.get("mins") or {}
        rr = mp.get("rmt")
        hh = mp.get("hero_points")
        w["lrmt"].configure(
            text=f"RMT: {fmt_price_stores(rr) if rr is not None else '—'}",
            fg=C["rmt"],
        )
        w["lhp"].configure(
            text=f"HP: {fmt_price_stores(hh) if hh is not None else '—'}",
            fg=C["hero_points"],
        )

    def _build_sim_refresh_prices_slots(self, slots):
        """Actualiza preços só para os slots indicados (lista de (layer, slot_key))."""
        if not slots:
            return
        self._build_sim_refresh_gen += 1
        gen = self._build_sim_refresh_gen
        targets = list(slots)

        def work():
            updates = {}
            for layer, sk in targets:
                updates[(layer, sk)] = self._build_sim_compute_slot_price_cache(
                    layer, sk, force_refresh=True
                )
            if gen != self._build_sim_refresh_gen:
                return

            def apply_ui():
                if gen != self._build_sim_refresh_gen:
                    return
                for (layer, sk), ent in updates.items():
                    self._build_price_cache[(layer, sk)] = ent
                    self._build_sim_apply_price_entry_to_slot_widgets(layer, sk, ent)
                self._build_sim_recalc_totals()

            self.after(0, apply_ui)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_refresh_prices(self):
        self._build_sim_merge_entries_into_state()
        self._build_sim_sync_ui_to_state()
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                self._build_sim_sync_row_from_state(layer, sk)
        self._build_sim_clear_slot_price_labels()
        self._build_sim_refresh_gen += 1
        gen = self._build_sim_refresh_gen

        def work():
            cache = {}
            for layer in ("equip", "visual"):
                for sk in self._all_build_slot_keys():
                    cache[(layer, sk)] = self._build_sim_compute_slot_price_cache(
                        layer, sk, force_refresh=True
                    )

            if gen != self._build_sim_refresh_gen:
                return

            def apply_ui():
                if gen != self._build_sim_refresh_gen:
                    return
                self._build_price_cache = cache
                for layer in ("equip", "visual"):
                    for sk in self._all_build_slot_keys():
                        self._build_sim_apply_price_entry_to_slot_widgets(
                            layer, sk, cache.get((layer, sk), {})
                        )
                self._build_sim_recalc_totals()

            self.after(0, apply_ui)

        threading.Thread(target=work, daemon=True).start()

    def _build_sim_recalc_totals(self):
        rmt = hp = 0.0
        for layer in ("equip", "visual"):
            for sk in self._all_build_slot_keys():
                t = self._build_price_cache.get((layer, sk), {})
                if not t or t.get("empty") or t.get("err"):
                    continue
                mp = t.get("mins") or {}
                if "rmt" in mp:
                    rmt += float(mp["rmt"])
                if "hero_points" in mp:
                    hp += float(mp["hero_points"])
        try:
            ratio = float(self._build_hp_entry.get().strip() or "30")
        except (ValueError, TypeError, tk.TclError, AttributeError):
            ratio = 30.0
        hp_equiv = hp + rmt * max(0.0, ratio)
        self._build_lbl_total_rmt.configure(text=f"RMT: {fmt_price_stores(rmt) if rmt else '0'}")
        self._build_lbl_total_hp.configure(text=f"HP (equiv.): {fmt_price_stores(hp_equiv) if hp_equiv else '0'}")

    def _build_sim_save_dialog(self):
        self._build_sim_sync_ui_to_state()
        d = tk.Toplevel(self)
        d.title("Guardar build")
        d.configure(bg=C["bg"])
        d.transient(self)
        d.geometry("440x248")

        shell = tk.Frame(d, bg=C["bg"])
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        overwrite_id = getattr(self, "_build_sim_selected_saved_id", None)
        if overwrite_id:
            tk.Label(
                shell,
                text="Substitui a build seleccionada na lista (mesmo id). Sem build seleccionada, cria uma nova.",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 8),
                wraplength=400,
                justify="left",
            ).pack(anchor="w", pady=(0, 6))
        tk.Label(shell, text="Nome da build", bg=C["bg"], fg=C["text"]).pack(anchor="w")
        nm = DarkEntry(shell, width=40)
        nm.pack(fill="x", pady=(4, 12))
        found_name = None
        if overwrite_id:
            for s in (load_builds_file().get("saved") or []):
                if isinstance(s, dict) and str(s.get("id")) == str(overwrite_id):
                    found_name = str(s.get("name") or "Build")
                    break
        nm.insert(0, found_name or "Minha build")

        cfg0 = load_settings()
        cur_primary = (cfg0.get("primary_build_sim_saved_id") or "").strip()
        if overwrite_id:
            default_primary_cb = str(overwrite_id) == cur_primary
        else:
            default_primary_cb = not cur_primary
        var_make_primary = tk.BooleanVar(value=default_primary_cb)
        DarkCheckbutton(
            shell,
            text="Definir como build principal (aberta ao iniciar, se existir)",
            variable=var_make_primary,
            bg=C["bg"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", fill="x", pady=(0, 8))

        def ok(oid=overwrite_id):
            name = nm.get().strip() or "Build"
            data = load_builds_file()
            saved = data.setdefault("saved", [])
            try:
                hpr = int(self._build_hp_entry.get().strip() or "30")
            except (ValueError, TypeError, tk.TclError, AttributeError):
                hpr = 30
            entry = None
            if oid:
                for i, s in enumerate(saved):
                    if not isinstance(s, dict):
                        continue
                    if str(s.get("id")) != str(oid):
                        continue
                    old = dict(s)
                    entry = {
                        "id": old.get("id"),
                        "name": name,
                        "saved_at": datetime.now().isoformat(),
                        "hp_per_rmt": hpr,
                        "equip": {k: dict(v) for k, v in self._build_state["equip"].items()},
                        "visual": {k: dict(v) for k, v in self._build_state["visual"].items()},
                        "alert_when_total_zeny_below": old.get("alert_when_total_zeny_below"),
                        "alert_when_total_hp_equiv_below": old.get("alert_when_total_hp_equiv_below"),
                        "notify_email": old.get("notify_email") or "",
                        "alert_total_armed": old.get("alert_total_armed", True),
                    }
                    saved[i] = entry
                    break
            if entry is None:
                entry = {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "saved_at": datetime.now().isoformat(),
                    "hp_per_rmt": hpr,
                    "equip": {k: dict(v) for k, v in self._build_state["equip"].items()},
                    "visual": {k: dict(v) for k, v in self._build_state["visual"].items()},
                    "alert_when_total_zeny_below": None,
                    "alert_when_total_hp_equiv_below": None,
                    "notify_email": "",
                    "alert_total_armed": True,
                }
                saved.append(entry)
            save_builds_file(data)
            cfg = load_settings()
            if var_make_primary.get():
                cfg["primary_build_sim_saved_id"] = str(entry.get("id") or "")
            save_settings(cfg)
            self._build_sim_last_saved_id = entry["id"]
            self._build_sim_selected_saved_id = entry.get("id")
            self._build_sim_refresh_saved_combo_list(select_id=entry["id"])
            self._build_sim_persist_last_saved_id()
            d.destroy()
            messagebox.showinfo("Guardado", f"Build «{name}» guardada.", parent=self)

        bf = tk.Frame(shell, bg=C["bg"])
        bf.pack(fill="x", pady=(12, 0))
        DarkButton(bf, text="Guardar", style="success", command=ok).pack(side="left", padx=4)
        DarkButton(bf, text="Cancelar", style="danger", command=d.destroy).pack(side="left", padx=4)

    # ── TIMER MVP ─────────────────────────────────────────────────────────────
    def _build_mvp_timer(self):
        self.mvp_timer_frame = tk.Frame(self.main, bg=C["bg"])
        self._mvp_timer_tick_job = None
        self._mvp_photo_refs = []
        self._mvp_card_labels = {}
        self._mvp_catalog_items = []
        self._mvp_catalog_fetching = False
        self._mvp_spawn_enriching = False
        self._mvp_search_after_id = None
        topbar = tk.Frame(self.mvp_timer_frame, bg=C["bg"])
        topbar.pack(fill="x", padx=12, pady=(12, 4))
        topbar.columnconfigure(1, weight=1)

        tk.Label(
            topbar,
            text="⚔ MVP Timer",
            bg=C["bg"],
            fg=C["purple3"],
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w")

        center = tk.Frame(topbar, bg=C["bg"])
        center.grid(row=0, column=1)
        self._mvp_filter_mode = tk.StringVar(value="todos")
        self._mvp_filter_btns = {}
        filt_specs = [
            ("Todos os MVPs", "todos"),
            ("Timers Ativos", "ativos"),
            ("Respawn pendente", "pendente"),
            ("MVPs disponíveis", "disponiveis"),
        ]
        for i, (label, val) in enumerate(filt_specs):

            def make_cmd(v=val):
                return lambda: self._mvp_set_filter(v)

            b = tk.Button(
                center,
                text=label,
                command=make_cmd(),
                relief="flat",
                cursor="hand2",
                font=("Segoe UI", 9, "bold"),
                padx=12,
                pady=6,
            )
            b.grid(row=0, column=i, padx=4)
            self._mvp_filter_btns[val] = b

        add_fr = tk.Frame(topbar, bg=C["bg"])
        add_fr.grid(row=0, column=2, sticky="e")
        self._mvp_catalog_hdr_status = tk.Label(add_fr, text="", bg=C["bg"], fg=C["text3"], font=("Segoe UI", 8))
        self._mvp_catalog_hdr_status.pack(side="right", padx=(8, 0))
        DarkButton(add_fr, text="Resetar todos os timers", style="ghost", command=self._mvp_reset_all_timers, padx=6).pack(
            side="left", padx=2
        )
        self._mvp_sync_filter_styles()

        tk.Label(
            self.mvp_timer_frame,
            text="Todos os MVPs do catálogo (Divine Pride) — grelha com sprites em data/mvp_sprites quando disponíveis. «Registrar» define morte e coords; o timer só corre após «Salvar».",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(2, 6))

        search_fr = tk.Frame(self.mvp_timer_frame, bg=C["bg"])
        search_fr.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(
            search_fr,
            text="Buscar MVP (nome ou ID):",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 10),
        ).pack(side="left")
        self._mvp_search_var = tk.StringVar(value="")
        self._mvp_search_var.trace_add("write", lambda *_a: self._mvp_on_search_change())
        tk.Entry(
            search_fr,
            textvariable=self._mvp_search_var,
            width=42,
            font=("Segoe UI", 10),
            bg=C["bg3"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["purple"],
        ).pack(side="left", padx=(10, 6), ipady=4)
        # Texto «Filtrando…» imediato na busca/filtros (ocultado ao terminar o render da grelha).
        self._mvp_search_filter_hint = tk.Label(
            search_fr,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9, "italic"),
        )
        self._mvp_search_filter_hint.pack(side="left", padx=(4, 0))

        self._mvp_grid_progress_label = tk.Label(
            self.mvp_timer_frame,
            text="",
            bg=C["bg"],
            fg=C["text2"],
            font=("Segoe UI", 9),
        )

        self._mvp_scroll_outer = tk.Frame(self.mvp_timer_frame, bg=C["bg"])
        self._mvp_scroll_outer.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        scroll = ScrollableFrame(self._mvp_scroll_outer, inner_bg=C["bg"])
        scroll.pack(fill="both", expand=True)
        self._mvp_cards_scroll = scroll
        self.mvp_cards_host = scroll.inner

        self.mvp_catalog_host = None
        self._mvp_catalog_win = None
        self._MVP_GRID_COLS = 5
        self._mvp_cards_generation = 0
        self._mvp_grid_render_gen_done = None
        self._mvp_chunk_after_id = None
        self._mvp_grid_refresh_after_id = None
        self._mvp_last_render_sig = None
        # Contador lógico dos dados de timers (gravar/invalidar), mais estável que mtime em disco na assinatura de skip.
        self._mvp_timer_storage_rev = 0
        self._mvp_storage_tick_cache = None
        self._mvp_storage_tick_mtime = None
        self._mvp_filter_cache_key = None
        self._mvp_filter_cache_items = None
        self._mvp_catalog_cache_mtime = None
        self._mvp_sprite_bytes_lru = OrderedDict()
        self._mvp_image_loader = MvpImageLoader()
        self._mvp_sprite_poll_after = None
        self._mvp_card_refresh_job = None
    def _mvp_file_mtime(self, path: str):
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    def _mvp_render_signature(self):
        try:
            sq = str(self._mvp_search_var.get() or "").strip()
        except (tk.TclError, AttributeError):
            sq = ""
        try:
            mode = self._mvp_filter_mode.get()
        except tk.TclError:
            mode = "todos"
        try:
            st_m = os.path.getmtime(MVP_DATA_FILE) if os.path.isfile(MVP_DATA_FILE) else None
        except OSError:
            st_m = None
        return (
            self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE),
            getattr(self, "_mvp_timer_storage_rev", 0),
            st_m,
            mode,
            sq,
            len(self._mvp_catalog_items or []),
            bool(self._mvp_catalog_fetching),
        )

    def _mvp_should_skip_grid_redraw(self) -> bool:
        if self._mvp_catalog_fetching:
            return False
        if not (self._mvp_catalog_items or []):
            return False
        if getattr(self, "_mvp_grid_render_gen_done", None) != getattr(self, "_mvp_cards_generation", -1):
            return False
        sig = self._mvp_render_signature()
        if sig != getattr(self, "_mvp_last_render_sig", None):
            return False
        host = self.mvp_cards_host
        try:
            if not host.winfo_children():
                return False
        except tk.TclError:
            return False
        return True

    def _mvp_cancel_chunked_render(self):
        aid = getattr(self, "_mvp_chunk_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_chunk_after_id = None

    def _mvp_cancel_deferred_grid_refresh(self):
        aid = getattr(self, "_mvp_grid_refresh_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_grid_refresh_after_id = None

    def _mvp_queue_mvp_grid_refresh(self, delay_ms: int = 320):
        """Um único redesenho após enriquecimento API — evita múltiplos «flashes» seguidos."""

        def run():
            self._mvp_grid_refresh_after_id = None
            if self.current_page.get() != "mvp":
                return
            self._mvp_render_mvp_cards()

        self._mvp_cancel_deferred_grid_refresh()
        self._mvp_grid_refresh_after_id = self.after(delay_ms, run)

    def _mvp_storage_for_tick(self):
        """Evita reler JSON em disco a cada segundo se o ficheiro não mudou."""
        try:
            mtime = os.path.getmtime(MVP_DATA_FILE) if os.path.isfile(MVP_DATA_FILE) else None
        except OSError:
            mtime = None
        if mtime == self._mvp_storage_tick_mtime and self._mvp_storage_tick_cache is not None:
            return self._mvp_storage_tick_cache
        self._mvp_storage_tick_cache = load_mvp_storage()
        self._mvp_storage_tick_mtime = mtime
        return self._mvp_storage_tick_cache

    def _mvp_timers_data(self):
        """Snapshot dos timers MVP (mesmo cache que o tick — invalida após gravar)."""
        return self._mvp_storage_for_tick()

    def _mvp_invalidate_filter_cache(self) -> None:
        """Invalida o cache da lista filtrada (busca + modo); chamado quando timers ou catálogo mudam."""
        self._mvp_filter_cache_key = None
        self._mvp_filter_cache_items = None

    def _mvp_invalidate_timer_storage_cache(self):
        self._mvp_storage_tick_cache = None
        self._mvp_storage_tick_mtime = None
        try:
            self._mvp_timer_storage_rev = int(getattr(self, "_mvp_timer_storage_rev", 0)) + 1
        except (TypeError, ValueError):
            self._mvp_timer_storage_rev = 1
        self._mvp_invalidate_filter_cache()

    def _mvp_filter_cache_key_tuple(self) -> tuple:
        """Chave do cache de filtro: UI + revisão de storage + meta do catálogo em disco."""
        try:
            sq = str(self._mvp_search_var.get() or "").strip()
        except (tk.TclError, AttributeError):
            sq = ""
        try:
            mode = self._mvp_filter_mode.get()
        except tk.TclError:
            mode = "todos"
        rev = getattr(self, "_mvp_timer_storage_rev", 0)
        try:
            st_m = os.path.getmtime(MVP_DATA_FILE) if os.path.isfile(MVP_DATA_FILE) else None
        except OSError:
            st_m = None
        cat_m = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        n = len(self._mvp_catalog_items or [])
        fetching = bool(getattr(self, "_mvp_catalog_fetching", False))
        return (sq, mode, rev, st_m, cat_m, n, fetching)

    def _mvp_cancel_card_refresh_chunk(self):
        jid = getattr(self, "_mvp_card_refresh_job", None)
        if jid is not None:
            try:
                self.after_cancel(jid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_card_refresh_job = None

    def _mvp_display_name_for_mid(self, mid: int, fallback: str = "") -> str:
        for it in self._mvp_catalog_items or []:
            try:
                if int(it.get("id") or 0) == int(mid):
                    n = str(it.get("name") or "").strip()
                    if n:
                        return n
            except (TypeError, ValueError):
                continue
        return (fallback or "").strip() or "MVP"

    def _mvp_startup_warm(self):
        """Carrega o catálogo MVP em memória a partir do cache (sem sprites em rede)."""
        try:
            cached = load_mvp_catalog_cache()
            if cached:
                self._mvp_catalog_items = list(cached)
            self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        except Exception as ex:
            logger.debug("MVP warm-up catálogo: %s", ex)
        try:
            self._mvp_storage_for_tick()
        except Exception as ex:
            logger.debug("MVP warm-up timers: %s", ex)

    def _mvp_show_filter_busy(self) -> None:
        """Feedback imediato antes do debounce / render (Tk pinta o botão primeiro)."""
        lbl = getattr(self, "_mvp_search_filter_hint", None)
        if lbl is not None:
            try:
                lbl.configure(text="Filtrando…")
            except tk.TclError:
                pass

    def _mvp_clear_filter_busy(self) -> None:
        lbl = getattr(self, "_mvp_search_filter_hint", None)
        if lbl is not None:
            try:
                lbl.configure(text="")
            except tk.TclError:
                pass

    def _mvp_scroll_grid_to_top(self) -> None:
        """Grelha MVP: scroll ao topo (filtros, reset, fim do render)."""
        sf = getattr(self, "_mvp_cards_scroll", None)
        if sf is None:
            return
        canvas = getattr(sf, "_canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _mvp_set_filter(self, value: str):
        self._mvp_filter_mode.set(value)
        self._mvp_sync_filter_styles()
        self._mvp_scroll_grid_to_top()
        self.after(0, self._mvp_show_filter_busy)
        # Deixa o estilo dos botões atualizar antes do trabalho pesado da grelha.
        self.after(0, lambda: self._mvp_render_mvp_cards())

    def _mvp_sync_filter_styles(self):
        cur = self._mvp_filter_mode.get()
        for val, b in getattr(self, "_mvp_filter_btns", {}).items():
            try:
                if val == cur:
                    b.configure(
                        bg=C["purple"],
                        fg="#ffffff",
                        activebackground=C["accent"],
                        activeforeground="#ffffff",
                    )
                else:
                    b.configure(
                        bg=C["bg3"],
                        fg=C["text"],
                        activebackground=C["border"],
                        activeforeground=C["text"],
                    )
            except tk.TclError:
                pass

    def _mvp_on_search_change(self):
        """Debounce do filtro: menos renders durante a digitação (300 ms)."""
        aid = getattr(self, "_mvp_search_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
        self.after(0, self._mvp_show_filter_busy)
        self._mvp_search_after_id = self.after(300, self._mvp_apply_search_filter)

    def _mvp_apply_search_filter(self):
        self._mvp_search_after_id = None
        try:
            self._mvp_render_mvp_cards()
        except tk.TclError:
            pass

    def _mvp_catalog_base_count(self) -> int:
        """MVPs no catálogo em disco (exclui nomes de instância)."""
        n = 0
        for it in self._mvp_catalog_items or []:
            if not isinstance(it, dict):
                continue
            if mvp_catalog_entry_skipped(it):
                continue
            try:
                if int(it.get("id") or 0):
                    n += 1
            except (TypeError, ValueError):
                pass
        return n

    def _mvp_filtered_catalog_items(self, data=None) -> list:
        use_cache = data is None
        cache_key = None
        if use_cache:
            cache_key = self._mvp_filter_cache_key_tuple()
            if cache_key == getattr(self, "_mvp_filter_cache_key", None) and getattr(
                self, "_mvp_filter_cache_items", None
            ) is not None:
                return list(self._mvp_filter_cache_items)

        cat = list(self._mvp_catalog_items or [])
        if data is None:
            data = self._mvp_timers_data()
        by_mid: dict = {}
        for e in data.get("entries") or []:
            mid = int(e.get("monster_id") or 0)
            if mid and mid not in by_mid:
                by_mid[mid] = e
        cat_base = []
        for it in cat:
            if not isinstance(it, dict):
                continue
            try:
                mid = int(it.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if not mid:
                continue
            if mvp_catalog_entry_skipped(it):
                continue
            cat_base.append(it)
        cat = cat_base

        try:
            q = str(self._mvp_search_var.get() or "") if getattr(self, "_mvp_search_var", None) else ""
        except (tk.TclError, AttributeError):
            q = ""
        if q.strip():
            cat = [it for it in cat if mvp_catalog_matches_search(it, q)]

        mode = self._mvp_filter_mode.get()
        if mode == "todos":
            result = cat
        else:
            out = []
            for it in cat:
                mid = int(it["id"])
                ent = by_mid.get(mid)
                if mode == "ativos" and ent:
                    su = seconds_until_spawn(ent)
                    if su is not None:
                        out.append(it)
                elif mode == "pendente" and ent:
                    su = seconds_until_spawn(ent)
                    if su is not None and su > 0:
                        out.append(it)
                elif mode == "disponiveis":
                    if ent:
                        su = seconds_until_spawn(ent)
                        if su is not None and su < 0:
                            out.append(it)
            result = out

        if use_cache and cache_key is not None:
            self._mvp_filter_cache_key = cache_key
            self._mvp_filter_cache_items = result
        return result

    def _mvp_filtered_ordered_ids(self, data=None) -> list:
        return [int(x["id"]) for x in self._mvp_filtered_catalog_items(data)]

    def _mvp_clock_label_fg(self, ent, su) -> str:
        """Verde: ainda falta para o respawn; vermelho: tempo esgotado (contagem negativa). Neutro: sem dados."""
        if su is None:
            return C["text3"]
        if su > 0:
            return C["green"]
        return C["red"]

    def _mvp_sprite_lru_get(self, mid: int) -> Optional[bytes]:
        """LRU só na main thread: devolve bytes PNG em cache ou None."""
        od = self._mvp_sprite_bytes_lru
        mid = int(mid)
        if mid not in od:
            return None
        od.move_to_end(mid)
        return od[mid]

    def _mvp_sprite_lru_set(self, mid: int, blob: bytes) -> None:
        """Grava miniatura no LRU (máx. 150 entradas)."""
        od = self._mvp_sprite_bytes_lru
        mid = int(mid)
        if mid in od:
            del od[mid]
        od[mid] = blob
        od.move_to_end(mid)
        while len(od) > 150:
            od.popitem(last=False)

    def _mvp_cancel_sprite_poll(self) -> None:
        aid = getattr(self, "_mvp_sprite_poll_after", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except (tk.TclError, ValueError):
                pass
            self._mvp_sprite_poll_after = None

    def _mvp_schedule_sprite_poll(self) -> None:
        """Garante um loop de polling de resultados do worker (main thread)."""
        if getattr(self, "_mvp_sprite_poll_after", None) is not None:
            return
        self._mvp_sprite_poll_after = self.after(0, self._mvp_poll_sprite_loop)

    def _mvp_poll_sprite_loop(self) -> None:
        self._mvp_sprite_poll_after = None
        if self.current_page.get() != "mvp":
            return
        drained = 0
        while True:
            r = self._mvp_image_loader.try_get_result()
            if r is None:
                break
            drained += 1
            self._mvp_apply_sprite_from_worker(*r)
        if drained > 0 or self._mvp_image_loader.has_backlog():
            self._mvp_sprite_poll_after = self.after(16, self._mvp_poll_sprite_loop)

    def _mvp_apply_sprite_from_worker(self, gen: int, mid: int, blob: Optional[bytes]) -> None:
        """Aplica PNG recebido do worker; ignora gerações antigas da grelha."""
        if gen != self._mvp_cards_generation:
            return
        if blob:
            self._mvp_sprite_lru_set(mid, blob)
        w = self._mvp_card_labels.get(str(int(mid)))
        if not w:
            return
        host = w.get("sprite_host")
        if not host:
            return
        card_bg = C["card"]
        try:
            for ch in host.winfo_children():
                ch.destroy()
        except tk.TclError:
            return
        if blob:
            try:
                from io import BytesIO

                from PIL import Image, ImageTk

                im = Image.open(BytesIO(blob)).convert("RGBA")
                ph = ImageTk.PhotoImage(im, master=self)
                self._mvp_photo_refs.append(ph)
                tk.Label(host, image=ph, bg=card_bg, bd=0, highlightthickness=0).place(
                    relx=0.5, rely=0.5, anchor="center"
                )
            except Exception:
                tk.Label(host, text="—", fg=C["text3"], bg=card_bg, font=("Segoe UI", 11)).place(
                    relx=0.5, rely=0.5, anchor="center"
                )
        else:
            tk.Label(host, text="—", fg=C["text3"], bg=card_bg, font=("Segoe UI", 11)).place(
                relx=0.5, rely=0.5, anchor="center"
            )

    def _mvp_fill_card_inner(self, inner, cit: dict, ent, mid: int) -> None:
        """Conteúdo visual de um card (sprite, textos, timer, botão)."""
        card_bg = C["card"]
        card_bd = C["border"]
        title_fg = C["purple3"]
        st_fg = C["purple2"]
        box_bg = C["bg3"]
        mid = int(mid)
        name = str(cit.get("name") or "—")

        cv_sz = 76
        sprite_host = tk.Frame(
            inner,
            width=cv_sz,
            height=cv_sz,
            bg=card_bg,
            highlightbackground=card_bd,
            highlightthickness=1,
        )
        sprite_host.pack_propagate(False)
        sprite_host.pack(pady=(0, 4))
        gen = int(getattr(self, "_mvp_cards_generation", 0))
        ph = None
        cached_blob = self._mvp_sprite_lru_get(mid)
        if cached_blob:
            try:
                from io import BytesIO

                from PIL import Image, ImageTk

                im = Image.open(BytesIO(cached_blob)).convert("RGBA")
                ph = ImageTk.PhotoImage(im, master=self)
                self._mvp_photo_refs.append(ph)
            except Exception:
                ph = None
        if ph is not None:
            tk.Label(sprite_host, image=ph, bg=card_bg, bd=0, highlightthickness=0).place(
                relx=0.5, rely=0.5, anchor="center"
            )
        else:
            tk.Label(
                sprite_host,
                text="…",
                fg=C["text3"],
                bg=card_bg,
                font=("Segoe UI", 16),
            ).place(relx=0.5, rely=0.5, anchor="center")
            self._mvp_image_loader.enqueue(gen, mid, name)
            self._mvp_schedule_sprite_poll()

        name_fr = tk.Frame(inner, bg=card_bg)
        name_fr.pack(fill=tk.X)
        name_w = tk.Text(
            name_fr,
            wrap=tk.WORD,
            width=24,
            height=1,
            font=("Segoe UI", 10, "bold"),
            bg=card_bg,
            fg=title_fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            cursor="ibeam",
            insertofftime=0,
            insertontime=0,
            takefocus=1,
            undo=False,
        )
        name_w.tag_configure("center", justify="center")
        name_w.insert("1.0", name)
        name_w.tag_add("center", "1.0", "end")
        lc = int(str(name_w.index("end-1c")).split(".")[0])
        name_w.configure(height=max(1, lc))

        def _mvp_copyable_text_key(e):
            if e.keysym in (
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Next",
                "Prior",
                "Tab",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
                "Alt_L",
                "Alt_R",
            ):
                return
            if (e.state & 4) and e.keysym.lower() in ("c", "a", "insert"):
                return
            return "break"

        name_w.bind("<Key>", _mvp_copyable_text_key)
        name_w.bind("<<Paste>>", lambda _e: "break")
        name_w.bind("<<Cut>>", lambda _e: "break")
        name_w.pack(anchor=tk.CENTER)

        id_fr = tk.Frame(inner, bg=card_bg)
        id_fr.pack(fill=tk.X)
        id_row = tk.Entry(
            id_fr,
            font=("Segoe UI", 8),
            fg=C["text3"],
            bg=card_bg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            justify="center",
            insertbackground=card_bg,
            insertofftime=0,
            insertontime=0,
            cursor="ibeam",
            takefocus=1,
        )
        try:
            id_row.configure(readonlybackground=card_bg)
        except tk.TclError:
            pass
        id_row.insert(0, f"ID {mid}")
        id_row.configure(state="readonly")
        id_row.pack(anchor=tk.CENTER)

        if ent:
            dm = str(ent.get("death_map") or "").strip()
            maps_txt = dm if dm else "—"
        else:
            maps_txt = "—"
        tk.Label(
            inner,
            text=maps_txt,
            bg=card_bg,
            fg=C["text2"],
            font=("Segoe UI", 8),
            wraplength=178,
            justify="center",
        ).pack(pady=(6, 2))

        if ent and ent.get("death_x") is not None and ent.get("death_y") is not None:
            loc = f"{ent['death_x']}, {ent['death_y']}"
        else:
            loc = "—"
        tk.Label(
            inner,
            text=f"Coords  {loc}",
            bg=card_bg,
            fg=C["text3"],
            font=("Segoe UI", 8),
        ).pack()

        box = tk.Frame(inner, bg=box_bg, highlightbackground=card_bd, highlightthickness=1)
        box.pack(fill="x", pady=(10, 0), ipady=6, ipadx=4)

        st_txt = mvp_dashboard_status_text(ent)
        lbl_st = tk.Label(
            box,
            text=st_txt,
            bg=box_bg,
            fg=st_fg,
            font=("Segoe UI", 9, "bold"),
        )
        lbl_st.pack()

        su = seconds_until_spawn(ent) if ent else None
        clk_fg = self._mvp_clock_label_fg(ent, su)
        lbl_ck = tk.Label(
            box,
            text=format_countdown_clock(su),
            bg=box_bg,
            fg=clk_fg,
            font=("Consolas", 15, "bold"),
        )
        lbl_ck.pack()

        self._mvp_card_labels[str(mid)] = {
            "lbl_clock": lbl_ck,
            "lbl_status": lbl_st,
            "entry": ent,
            "inner": inner,
            "sprite_host": sprite_host,
        }

        def reg_btn():
            return tk.Button(
                inner,
                relief="flat",
                bg=C["purple"],
                fg="#ffffff",
                activebackground=C["accent"],
                activeforeground="#ffffff",
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                padx=4,
                pady=8,
            )

        if ent:
            b = reg_btn()
            b.configure(text="⏱  Editar timer", command=lambda eid=ent["entry_id"]: self._mvp_open_edit_dialog(eid))
        else:
            b = reg_btn()
            b.configure(text="⏱  Registrar", command=lambda m=mid: self._mvp_add_monster_by_catalog_id(m))
        b.pack(fill="x", pady=(12, 0))

    def _mvp_refresh_card_for_monster(self, mid: int) -> None:
        mid = int(mid)
        w = self._mvp_card_labels.get(str(mid))
        inner = w.get("inner") if w else None
        try:
            if inner is None or not inner.winfo_exists():
                self._mvp_render_mvp_cards()
                return
        except tk.TclError:
            self._mvp_render_mvp_cards()
            return
        cit = next((x for x in (self._mvp_catalog_items or []) if int(x.get("id") or 0) == mid), None)
        if cit is None:
            self._mvp_render_mvp_cards()
            return
        data = self._mvp_timers_data()
        by_mid = {}
        for e in data.get("entries") or []:
            m = int(e.get("monster_id") or 0)
            if m and m not in by_mid:
                by_mid[m] = e
        ent = by_mid.get(mid)
        for ch in inner.winfo_children():
            ch.destroy()
        self._mvp_fill_card_inner(inner, cit, ent, mid)

    def _mvp_storage_change_refresh(self, affected_mid: int, before_ids: list) -> None:
        """Actualiza só o card se a lista filtrada (ordem e tamanho) não mudou; senão redesenha a grelha."""
        am = int(affected_mid)
        after_ids = self._mvp_filtered_ordered_ids()
        if before_ids == after_ids and str(am) in self._mvp_card_labels:
            self._mvp_refresh_card_for_monster(am)
        else:
            self._mvp_render_mvp_cards()

    def _mvp_set_catalog_status(self, text: str):
        lbl = getattr(self, "_mvp_catalog_hdr_status", None)
        if lbl is not None:
            try:
                lbl.configure(text=text)
            except tk.TclError:
                pass

    def _mvp_refresh_catalog_header_counts(self):
        """Canto superior direito: quantos MVPs estão visíveis com filtro + busca."""
        if self._mvp_catalog_fetching:
            return
        shown = len(self._mvp_filtered_catalog_items())
        total = self._mvp_catalog_base_count()
        self._mvp_set_catalog_status(f"Mostrando {shown} de {total} MVPs")

    def _show_mvp_timer(self):
        self._clear_main()
        self.mvp_timer_frame.pack(fill="both", expand=True)
        self.after_idle(self._mvp_show_mvp_timer_finish)

    def _mvp_show_mvp_timer_finish(self):
        if self.current_page.get() != "mvp":
            return
        self._mvp_ensure_catalog()
        self._mvp_schedule_tick()

    def _mvp_ensure_catalog(self):
        cm = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        if cm != getattr(self, "_mvp_catalog_cache_mtime", None) or not (self._mvp_catalog_items or []):
            cached = load_mvp_catalog_cache()
            self._mvp_catalog_items = list(cached) if cached else []
            self._mvp_catalog_cache_mtime = cm
            # Catálogo novo: lista filtrada em cache já não corresponde à memória.
            self._mvp_invalidate_filter_cache()
        if self._mvp_catalog_items:
            if self._mvp_should_skip_grid_redraw():
                self._mvp_refresh_catalog_header_counts()
            else:
                self._mvp_render_mvp_cards()
            names_en = mvp_catalog_names_are_english_marked()
            need_sync = not names_en
            if need_sync and not (load_settings().get("divine_pride_api_key") or "").strip():
                self._mvp_set_catalog_status(
                    "Catálogo carregado. Configure a chave Divine Pride (Configurações) para obter nomes dos MVPs em inglês via API."
                )
            self._mvp_start_spawn_enrich(sync_all_names=need_sync)
            return
        self._mvp_render_mvp_cards()
        self._mvp_start_catalog_fetch(force=False)

    def _mvp_refresh_catalog(self):
        self._mvp_start_catalog_fetch(force=True)

    def _mvp_start_catalog_fetch(self, *, force: bool):
        if self._mvp_catalog_fetching:
            return
        self._mvp_set_catalog_status("A sincronizar lista MVP (Divine Pride)…")
        self._mvp_catalog_fetching = True
        self._mvp_render_mvp_cards()

        def work():
            err = None
            items = None
            try:
                cfg = load_settings()
                srv = (cfg.get("divine_pride_server") or "").strip() or None
                sess = requests.Session()
                sess.headers.update(DIVINE_PRIDE_LIST_HEADERS)
                items = fetch_mvp_catalog_from_divine_pride(sess, list_server=srv)
                old_by = {int(x["id"]): x for x in (self._mvp_catalog_items or [])}
                for it in items:
                    mid = int(it["id"])
                    if mid in old_by and old_by[mid].get("spawn_maps"):
                        it["spawn_maps"] = list(old_by[mid]["spawn_maps"])
                save_mvp_catalog_cache(items, name_display_locale="pending")
            except Exception as ex:
                err = str(ex)
            self.after(0, lambda e=err, it=items: self._mvp_catalog_fetch_done(e, it))

        threading.Thread(target=work, daemon=True).start()

    def _mvp_catalog_fetch_done(self, err, items):
        self._mvp_catalog_fetching = False
        if err or not items:
            msg = err or "Lista vazia"
            logger.warning("Catálogo MVP: %s", msg)
            self._mvp_set_catalog_status(f"Erro: {msg[:80]}")
            self._mvp_render_mvp_cards(update_hdr_counts=False)
            return
        self._mvp_catalog_items = list(items)
        self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
        self._mvp_invalidate_filter_cache()
        self._mvp_render_mvp_cards()
        self._mvp_start_spawn_enrich(sync_all_names=True)

    def _mvp_start_spawn_enrich(self, *, sync_all_names: bool = False):
        """Enriquece via API (nomes em inglês, Accept-Language na API). *sync_all_names*: todos os MVPs."""
        if getattr(self, "_mvp_spawn_enriching", False):
            return
        if not self._mvp_catalog_items:
            return
        cfg = load_settings()
        key = (cfg.get("divine_pride_api_key") or "").strip()
        dp_srv = (cfg.get("divine_pride_server") or "").strip() or None
        if not key:
            return

        def _has_sm(it: dict) -> bool:
            sm = it.get("spawn_maps") if isinstance(it.get("spawn_maps"), list) else []
            return any(str(x).strip() for x in sm)

        if not sync_all_names:
            if not any(not _has_sm(it) for it in self._mvp_catalog_items):
                return
        self._mvp_spawn_enriching = True

        def work():
            api_hits = 0
            catalog_changed = False
            st_changed = False
            try:
                for it in list(self._mvp_catalog_items or []):
                    if not isinstance(it, dict):
                        continue
                    if mvp_catalog_entry_skipped(it):
                        continue
                    try:
                        mid = int(it.get("id") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not mid:
                        continue
                    has_maps = _has_sm(it)
                    if not sync_all_names and has_maps:
                        continue
                    try:
                        mobj = fetch_monster(mid, api_key=key, server=dp_srv)
                        api_hits += 1
                        nn = monster_api_display_name(mobj)
                        if nn:
                            old_n = str(it.get("name") or "").strip()
                            if old_n != nn:
                                it["name"] = nn
                                catalog_changed = True
                        if not has_maps:
                            it["spawn_maps"] = spawn_maps_from_monster(mobj)
                            catalog_changed = True
                    except Exception as ex:
                        logger.debug("enrich MVP %s: %s", mid, ex)
                    time.sleep(0.12)
                try:
                    st_data = load_mvp_storage()
                    by_mid_e = {
                        int(e.get("monster_id") or 0): e
                        for e in st_data.get("entries") or []
                        if int(e.get("monster_id") or 0)
                    }
                    for cit in self._mvp_catalog_items or []:
                        if not isinstance(cit, dict):
                            continue
                        try:
                            mid_k = int(cit.get("id") or 0)
                        except (TypeError, ValueError):
                            continue
                        if not mid_k or mid_k not in by_mid_e:
                            continue
                        cn = str(cit.get("name") or "").strip()
                        if cn and by_mid_e[mid_k].get("name") != cn:
                            by_mid_e[mid_k]["name"] = cn
                            st_changed = True
                    if st_changed:
                        save_mvp_storage(st_data)
                        self._mvp_invalidate_timer_storage_cache()
                except Exception as ex:
                    logger.debug("sync timer entry names from catalog: %s", ex)
                try:
                    if catalog_changed or st_changed or sync_all_names:
                        loc = None
                        if sync_all_names:
                            loc = "en" if api_hits > 0 else "pending"
                        save_mvp_catalog_cache(self._mvp_catalog_items, name_display_locale=loc)
                except Exception as ex:
                    logger.warning("save_mvp_catalog_cache after enrich: %s", ex)
            finally:
                self._mvp_spawn_enriching = False
                # Só agenda redesenho se dados visíveis mudaram — evita grelha completa ao reabrir a aba sem alterações.
                if catalog_changed or st_changed:
                    if catalog_changed:
                        self._mvp_invalidate_filter_cache()
                    self.after(0, lambda: self._mvp_queue_mvp_grid_refresh())

        threading.Thread(target=work, daemon=True).start()

    def _mvp_add_monster_by_catalog_id(self, mid: int):
        cfg = load_settings()
        dp_srv = (cfg.get("divine_pride_server") or "").strip() or None
        if not (cfg.get("divine_pride_api_key") or "").strip():
            messagebox.showerror(
                "MVP",
                "Configure a chave Divine Pride em Configurações (ou variável DIVINE_PRIDE_API_KEY).",
                parent=self,
            )
            return
        data = self._mvp_timers_data()
        if any(int(e.get("monster_id") or 0) == int(mid) for e in data.get("entries") or []):
            messagebox.showinfo("MVP", "Este MVP já está na lista de timers.", parent=self)
            return

        def work():
            err = None
            mobj = None
            try:
                mobj = fetch_monster(
                    mid,
                    api_key=cfg.get("divine_pride_api_key"),
                    server=dp_srv,
                )
            except Exception as ex:
                err = str(ex)
            self.after(0, lambda: self._mvp_add_monster_done(err, mobj))

        threading.Thread(target=work, daemon=True).start()

    def _mvp_schedule_tick(self):
        if self._mvp_timer_tick_job is not None:
            try:
                self.after_cancel(self._mvp_timer_tick_job)
            except tk.TclError:
                pass
            self._mvp_timer_tick_job = None
        self._mvp_timer_tick()

    def _mvp_timer_tick(self):
        self._mvp_timer_tick_job = None
        try:
            if self.current_page.get() != "mvp":
                return
            self._mvp_update_countdown_labels()
            self._mvp_check_spawn_alerts()
        except Exception:
            logger.exception("mvp_timer_tick")
        self._mvp_timer_tick_job = self.after(1000, self._mvp_timer_tick)

    def _mvp_update_countdown_labels(self):
        data = self._mvp_storage_for_tick()
        by_mid = {}
        for e in data.get("entries") or []:
            mid = int(e.get("monster_id") or 0)
            if mid and mid not in by_mid:
                by_mid[mid] = e
        for mid_str, w in list(self._mvp_card_labels.items()):
            try:
                mid = int(mid_str)
            except (TypeError, ValueError):
                continue
            ent = by_mid.get(mid)
            try:
                if "lbl_clock" in w:
                    su = seconds_until_spawn(ent) if ent else None
                    w["lbl_clock"].configure(
                        text=format_countdown_clock(su), fg=self._mvp_clock_label_fg(ent, su)
                    )
                if "lbl_status" in w:
                    w["lbl_status"].configure(text=mvp_dashboard_status_text(ent))
            except tk.TclError:
                pass

    def _mvp_check_spawn_alerts(self):
        data = self._mvp_timers_data()
        changed = False
        for e in data.get("entries") or []:
            if e.get("alert_fired"):
                continue
            su = seconds_until_spawn(e)
            if su is None:
                continue
            if su > 0:
                continue
            e["alert_fired"] = True
            changed = True
            name = e.get("name") or "MVP"
            # Som antes do pop-up modal — showinfo bloqueia até OK.
            try:
                snd = str(load_settings().get("mvp_alert_sound_path") or "").strip()
                play_mvp_spawn_alert_sound(snd or None)
            except Exception:
                logger.debug("mvp spawn alert sound", exc_info=True)
            try:
                messagebox.showinfo(
                    "MVP — respawn",
                    f"«{name}»: o tempo de contagem terminou.\nVerifique in-game; abra «Editar» no card e registe a morte após matar o MVP.",
                    parent=self,
                )
            except tk.TclError:
                pass
        if changed:
            save_mvp_storage(data)
            self._mvp_invalidate_timer_storage_cache()

    def _mvp_add_monster_done(self, err, mobj):
        if err:
            messagebox.showerror("MVP", f"Erro ao carregar monstro:\n{err}", parent=self)
            return
        summ = summarize_monster_for_timer(mobj)
        data = self._mvp_timers_data()
        if any(int(e.get("monster_id") or 0) == int(summ["monster_id"]) for e in data.get("entries") or []):
            messagebox.showinfo("MVP", "Este MVP já está na lista de timers.", parent=self)
            return
        if not summ["is_mvp"]:
            if not messagebox.askyesno(
                "MVP",
                "Na Divine Pride este monstro não está marcado como MVP. Adicionar à mesma?",
                parent=self,
            ):
                return
        before_ids = self._mvp_filtered_ordered_ids(data)
        maps = summ["spawn_maps"]
        dm = maps[0] if maps else ""
        entry = new_timer_entry(
            summ["monster_id"],
            summ["name"],
            maps,
            summ["respawn_seconds"],
            death_map=dm,
            death_at_iso="",
        )
        data.setdefault("entries", []).append(entry)
        eid_new = entry["entry_id"]
        save_mvp_storage(data)
        self._mvp_invalidate_timer_storage_cache()
        for it in self._mvp_catalog_items or []:
            if int(it.get("id") or 0) == int(summ["monster_id"]):
                if summ.get("spawn_maps"):
                    it["spawn_maps"] = list(summ["spawn_maps"])
                break
        if self._mvp_catalog_items:
            try:
                save_mvp_catalog_cache(self._mvp_catalog_items)
                self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
            except Exception:
                pass
        self._mvp_storage_change_refresh(int(summ["monster_id"]), before_ids)
        self.after(100, lambda eid=eid_new: self._mvp_open_edit_dialog(eid))

    def _mvp_refresh_visible_cards_batched(self, mids: list, idx: int = 0, batch: int = 14) -> None:
        """Reconstrói cartões visíveis em fatias — UI não bloqueia em resets grandes."""
        self._mvp_card_refresh_job = None
        if self.current_page.get() != "mvp":
            return
        n = len(mids)
        end = min(idx + max(1, int(batch)), n)
        for i in range(idx, end):
            try:
                self._mvp_refresh_card_for_monster(int(mids[i]))
            except Exception:
                logger.debug("mvp_refresh_visible_cards_batched", exc_info=True)
        if end < n:
            self._mvp_card_refresh_job = self.after(
                1, lambda: self._mvp_refresh_visible_cards_batched(mids, end, batch)
            )
        else:
            self._mvp_refresh_catalog_header_counts()

    def _mvp_refresh_all_visible_cards_batched(self, batch: int = 14) -> None:
        self._mvp_cancel_card_refresh_chunk()
        mids = []
        for mid_str in list(self._mvp_card_labels.keys()):
            try:
                mids.append(int(mid_str))
            except (TypeError, ValueError):
                continue
        if not mids:
            self._mvp_refresh_catalog_header_counts()
            return
        self._mvp_refresh_visible_cards_batched(mids, 0, batch)

    def _mvp_reset_all_timers(self):
        data = self._mvp_timers_data()
        entries = data.get("entries") or []
        if not entries:
            messagebox.showinfo("MVP", "Não há MVPs registados.", parent=self)
            return
        if not messagebox.askyesno(
            "MVP",
            "Resetar todos os timers?\n\n"
            "Isto remove a hora de morte e as coordenadas de cada MVP registado. "
            "A contagem só volta a correr depois de abrir «Editar timer», definir a morte e «Salvar».",
            parent=self,
        ):
            return
        for e in entries:
            e["death_at"] = ""
            e["death_x"] = None
            e["death_y"] = None
            e["alert_fired"] = False
        save_mvp_storage(data)
        self._mvp_invalidate_timer_storage_cache()
        self._mvp_scroll_grid_to_top()
        self._mvp_refresh_all_visible_cards_batched()

    def _mvp_open_edit_dialog(self, entry_id):
        st = self._mvp_timers_data()
        ent = None
        for e in st.get("entries") or []:
            if e.get("entry_id") == entry_id:
                ent = e
                break
        if not ent:
            return

        mid_edit = int(ent.get("monster_id") or 0)

        top = tk.Toplevel(self)
        title_name = self._mvp_display_name_for_mid(mid_edit, str(ent.get("name") or "MVP"))
        top.title(f"Editar MVP — {title_name}")
        top.configure(bg=C["bg"])
        top.transient(self)

        def persist(patch: dict) -> None:
            d = load_mvp_storage()
            for x in d.get("entries") or []:
                if x.get("entry_id") == entry_id:
                    x.update(patch)
                    break
            save_mvp_storage(d)
            self._mvp_invalidate_timer_storage_cache()

        def load_ent():
            d = load_mvp_storage()
            for x in d.get("entries") or []:
                if x.get("entry_id") == entry_id:
                    return x
            return None

        fr = tk.Frame(top, bg=C["bg"])
        fr.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(
            fr,
            text="Escolha o mapa e clique nas áreas coloridas do minimapa. "
            "1 pixel = 1 célula; origem (0,0) no canto inferior esquerdo, Y sobe.",
            bg=C["bg"],
            fg=C["text3"],
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        maps = list(ent.get("spawn_maps") or [])
        if not maps:
            try:
                mid_ent = int(ent.get("monster_id") or 0)
            except (TypeError, ValueError):
                mid_ent = 0
            if mid_ent:
                for it in self._mvp_catalog_items or []:
                    try:
                        if int(it.get("id") or 0) == mid_ent:
                            maps = [
                                str(x).strip()
                                for x in (it.get("spawn_maps") or [])
                                if str(x).strip()
                            ]
                            break
                    except (TypeError, ValueError):
                        continue
        row_map = tk.Frame(fr, bg=C["bg"])
        row_map.pack(fill="x", pady=4)
        tk.Label(row_map, text="Mapa da morte:", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).pack(side="left")
        map_cb = ttk.Combobox(row_map, values=maps or [""], width=28, font=("Segoe UI", 9), state="readonly")
        cur_dm = (ent.get("death_map") or "").strip() or (maps[0] if maps else "")
        if cur_dm in maps or not maps:
            map_cb.set(cur_dm or "")
        elif maps:
            map_cb.set(maps[0])
        map_cb.pack(side="left", padx=8)

        row_d = tk.Frame(fr, bg=C["bg"])
        row_d.pack(fill="x", pady=4)
        tk.Label(row_d, text="Morte (AAAA-MM-DD HH:MM):", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).pack(
            side="left"
        )
        raw_death = str(ent.get("death_at") or "").strip()
        if raw_death:
            death_s = raw_death[:16].replace("T", " ")
        else:
            death_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        de = DarkEntry(row_d, width=20)
        de.pack(side="left", padx=6)
        de.insert(0, death_s)

        row_r = tk.Frame(fr, bg=C["bg"])
        row_r.pack(fill="x", pady=4)
        tk.Label(row_r, text="Respawn (min):", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).pack(side="left")
        rm = max(1, int(ent.get("respawn_seconds") or 3600) // 60)
        sp = tk.Spinbox(
            row_r,
            from_=1,
            to=10080,
            width=8,
            bg=C.get("bg3", "#2a2a2a"),
            fg=C["text"],
            insertbackground=C["purple2"],
            font=("Segoe UI", 9),
        )
        sp.delete(0, "end")
        sp.insert(0, str(rm))
        sp.pack(side="left", padx=6)

        row_xy = tk.Frame(fr, bg=C["bg"])
        row_xy.pack(fill="x", pady=4)
        tk.Label(row_xy, text="Coords (jogo):", bg=C["bg"], fg=C["text"], font=("Segoe UI", 9)).pack(side="left")
        ex_x = DarkEntry(row_xy, width=8)
        ex_x.pack(side="left", padx=(6, 2))
        ex_x.insert(0, str(ent["death_x"]) if ent.get("death_x") is not None else "")
        ex_y = DarkEntry(row_xy, width=8)
        ex_y.pack(side="left", padx=2)
        ex_y.insert(0, str(ent["death_y"]) if ent.get("death_y") is not None else "")

        map_host = tk.Frame(fr, bg=C["bg"])
        map_host.pack(fill="x", pady=8)

        lbl_xy_status = tk.Label(fr, text="", bg=C["bg"], fg=C["hero_points"], font=("Segoe UI", 9))
        lbl_xy_status.pack(anchor="w")

        cv_ref = [None]
        map_photo_ref: list = []
        map_native_wh = [0, 0]
        map_display_wh = [0, 0]
        map_display_off = [0, 0]
        map_click_mask = [b""]

        def flush_dialog() -> None:
            raw_death = de.get().strip()
            dt = parse_user_datetime(raw_death) if raw_death else None
            if dt:
                persist({"death_at": dt.strftime("%Y-%m-%d %H:%M:%S"), "alert_fired": False})
            elif not raw_death:
                persist({"death_at": "", "alert_fired": False})
            try:
                mn = int(sp.get())
                persist({"respawn_seconds": max(60, mn * 60)})
            except (ValueError, tk.TclError):
                pass
            dm = map_cb.get().strip()
            persist({"death_map": dm})
            xs, ys = ex_x.get().strip(), ex_y.get().strip()
            patch: dict = {}
            if not xs:
                patch["death_x"] = None
            elif xs.isdigit() or (xs.startswith("-") and xs[1:].isdigit()):
                patch["death_x"] = int(xs)
            if not ys:
                patch["death_y"] = None
            elif ys.isdigit() or (ys.startswith("-") and ys[1:].isdigit()):
                patch["death_y"] = int(ys)
            if patch:
                persist(patch)

        def redraw_minimap() -> None:
            for w in map_host.winfo_children():
                w.destroy()
            cv_ref[0] = None
            map_native_wh[:] = [0, 0]
            map_display_wh[:] = [0, 0]
            map_display_off[:] = [0, 0]
            map_click_mask[:] = [b""]
            lbl_xy_status.configure(text="")
            dm = map_cb.get().strip()
            if not dm:
                tk.Label(
                    map_host,
                    text="Seleccione o mapa da morte para activar a área de clique (coordenadas).",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 9),
                    wraplength=480,
                ).pack(pady=12)
                return
            try:
                from io import BytesIO

                from PIL import Image, ImageTk

                map_blob, _map_url = resolve_map_image(dm)
                if not map_blob:
                    tk.Label(
                        map_host,
                        text=f"Sem imagem local para «{dm}». Importe com tools/import_mvp_map_folder.py",
                        bg=C["bg"],
                        fg=C["text3"],
                        font=("Segoe UI", 9),
                        wraplength=480,
                    ).pack(pady=12)
                    return

                im = Image.open(BytesIO(map_blob)).convert("RGBA")
                nw, nh = im.size
                if nw <= 0 or nh <= 0:
                    return
                mw, mh, mask_bytes = build_mvp_map_click_mask_from_image(im)
                box_w, box_h = _MVP_MAP_DISPLAY_BOX_W, _MVP_MAP_DISPLAY_BOX_H
                dw, dh, off_x, off_y = mvp_map_display_layout(nw, nh, box_w, box_h)
                map_native_wh[:] = [nw, nh]
                map_display_wh[:] = [dw, dh]
                map_display_off[:] = [off_x, off_y]
                map_click_mask[:] = [mask_bytes]
                map_photo_ref.clear()

                if dw != nw or dh != nh:
                    im_show = im.resize((dw, dh), Image.Resampling.NEAREST)
                else:
                    im_show = im

                shell = tk.Frame(map_host, bg=C["bg"])
                shell.pack(anchor="center")

                cv = tk.Canvas(
                    shell,
                    width=box_w,
                    height=box_h,
                    bg="#0a0a12",
                    highlightthickness=1,
                    highlightbackground=C["border"],
                    cursor="arrow",
                )
                cv.pack()
                cv_ref[0] = cv

                ph = ImageTk.PhotoImage(im_show, master=top)
                map_photo_ref.append(ph)
                cv.create_image(off_x, off_y, anchor="nw", image=ph, tags="map_bg")

                tk.Label(
                    map_host,
                    text=(
                        f"Mapa {dm}: {nw}×{nh} células (1:1) — vista {box_w}×{box_h} px, "
                        "centrada. Origem inferior esquerda."
                    ),
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 8),
                ).pack(anchor="center", pady=(4, 0))

                def _canvas_xy(ev) -> Tuple[float, float]:
                    return float(ev.x), float(ev.y)

                def _local_on_map(cx: float, cy: float) -> Optional[Tuple[float, float]]:
                    lx, ly = cx - off_x, cy - off_y
                    if lx < 0 or ly < 0 or lx >= dw or ly >= dh:
                        return None
                    return lx, ly

                def draw_mob_at_game(gx: int, gy: int) -> None:
                    canvas = cv_ref[0]
                    if not canvas:
                        return
                    canvas.delete("mvp_icon")
                    px, py = game_to_pixel_coords(
                        gx, gy, nw, nh, display_w=dw, display_h=dh
                    )
                    px += off_x
                    py += off_y
                    r = 8
                    canvas.create_line(
                        px - r, py, px + r, py, fill=C["purple2"], width=2, tags="mvp_icon"
                    )
                    canvas.create_line(
                        px, py - r, px, py + r, fill=C["purple2"], width=2, tags="mvp_icon"
                    )

                def on_motion(ev):
                    cx, cy = _canvas_xy(ev)
                    local = _local_on_map(cx, cy)
                    if local is None:
                        cv.configure(cursor="arrow")
                        lbl_xy_status.configure(text="")
                        return
                    lx, ly = local
                    gx, gy = pixel_to_game_coords(
                        lx, ly, nw, nh, display_w=dw, display_h=dh
                    )
                    if is_mvp_map_coord_clickable(gx, gy, mw, mh, mask_bytes):
                        cv.configure(cursor="crosshair")
                        lbl_xy_status.configure(
                            text=f"X={gx}  Y={gy}  ({nw}×{nh}) — clique para marcar"
                        )
                    else:
                        cv.configure(cursor="no")
                        lbl_xy_status.configure(
                            text="Fora do mapa jogável — clique nas áreas coloridas"
                        )

                def on_click(ev):
                    cx, cy = _canvas_xy(ev)
                    local = _local_on_map(cx, cy)
                    if local is None:
                        return
                    lx, ly = local
                    gx, gy = pixel_to_game_coords(
                        lx, ly, nw, nh, display_w=dw, display_h=dh
                    )
                    if not is_mvp_map_coord_clickable(gx, gy, mw, mh, mask_bytes):
                        lbl_xy_status.configure(
                            text="Clique ignorado: só conta em pixels do mapa (não no fundo preto)."
                        )
                        return
                    ex_x.delete(0, "end")
                    ex_x.insert(0, str(gx))
                    ex_y.delete(0, "end")
                    ex_y.insert(0, str(gy))
                    draw_mob_at_game(gx, gy)
                    persist({"death_map": dm, "death_x": gx, "death_y": gy})
                    lbl_xy_status.configure(text=f"Posição: X={gx}  Y={gy}  (mapa {dm})")

                cv.bind("<Motion>", on_motion)
                cv.bind("<Leave>", lambda _e: cv.configure(cursor="arrow"))
                cv.bind("<Button-1>", on_click)

                xe = load_ent()
                if xe and (xe.get("death_map") or "").strip() == dm:
                    xn, yn = xe.get("death_x"), xe.get("death_y")
                    if xn is not None and yn is not None:
                        try:
                            draw_mob_at_game(int(xn), int(yn))
                            lbl_xy_status.configure(text=f"Marcador — X={xn} Y={yn}")
                        except (TypeError, ValueError):
                            pass
            except Exception as ex:
                tk.Label(map_host, text=str(ex), bg=C["bg"], fg=C["hero_exp"]).pack()

        def on_map_change(_e=None):
            dm_sel = map_cb.get().strip()
            persist({"death_map": dm_sel})
            redraw_minimap()

        map_cb.bind("<<ComboboxSelected>>", on_map_change)
        top.after(60, redraw_minimap)

        def close_dialog():
            before_ids = self._mvp_filtered_ordered_ids()
            flush_dialog()
            top.destroy()
            self._mvp_storage_change_refresh(mid_edit, before_ids)

        def dismiss_without_save():
            """Fechar pela X: não gravar o formulário (timer e dados só com «Salvar»)."""
            before_ids = self._mvp_filtered_ordered_ids()
            try:
                top.destroy()
            except tk.TclError:
                pass
            self._mvp_storage_change_refresh(mid_edit, before_ids)

        top.protocol("WM_DELETE_WINDOW", dismiss_without_save)

        bf = tk.Frame(fr, bg=C["bg"])
        bf.pack(fill="x", pady=(14, 0))
        DarkButton(bf, text="Salvar", style="success", command=close_dialog, padx=8).pack(side="left", padx=4)

    def _mvp_grid_place_card(self, host, idx: int, cit: dict, ent, cols: int, card_bg: str, card_bd: str) -> None:
        mid = int(cit["id"])
        r, col = divmod(idx, cols)
        card = tk.Frame(
            host,
            bg=card_bg,
            highlightbackground=card_bd,
            highlightthickness=1,
        )
        card.grid(row=r, column=col, padx=6, pady=6, sticky="nsew")
        inner = tk.Frame(card, bg=card_bg)
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        self._mvp_fill_card_inner(inner, cit, ent, mid)

    def _mvp_render_mvp_cards(self, *, update_hdr_counts: bool = True):
        self._mvp_cancel_card_refresh_chunk()
        self._mvp_cancel_sprite_poll()
        self._mvp_cancel_deferred_grid_refresh()
        self._mvp_cancel_chunked_render()
        self._mvp_cards_generation += 1
        gen = self._mvp_cards_generation
        self._mvp_card_labels.clear()
        self._mvp_photo_refs = []
        host = self.mvp_cards_host

        def _finish_render():
            self._mvp_grid_render_gen_done = gen
            self._mvp_last_render_sig = self._mvp_render_signature()
            self._mvp_catalog_cache_mtime = self._mvp_file_mtime(MVP_CATALOG_PORTABLE_FILE)
            try:
                self._mvp_grid_progress_label.pack_forget()
            except tk.TclError:
                pass
            self._mvp_clear_filter_busy()
            self._mvp_scroll_grid_to_top()

        for w in host.winfo_children():
            w.destroy()

        if self._mvp_catalog_fetching and not self._mvp_catalog_items:
            tk.Label(
                host,
                text="A sincronizar todos os MVPs com divine-pride.net…",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 12),
                justify="center",
            ).pack(pady=80)
            _finish_render()
            return

        data = self._mvp_timers_data()
        items = self._mvp_filtered_catalog_items()
        if not self._mvp_catalog_items:
            tk.Label(
                host,
                text="Sem catálogo MVP em cache.\nEsperado o ficheiro em data/ (carregado ao iniciar).",
                bg=C["bg"],
                fg=C["text3"],
                font=("Segoe UI", 11),
                justify="center",
            ).pack(pady=60)
            if update_hdr_counts:
                self._mvp_refresh_catalog_header_counts()
            _finish_render()
            return

        if not items:
            mode = self._mvp_filter_mode.get()
            try:
                sq = str(self._mvp_search_var.get() or "").strip()
            except (tk.TclError, AttributeError):
                sq = ""
            if sq:
                tk.Label(
                    host,
                    text=f"Nenhum MVP corresponde à busca «{sq[:50]}{'…' if len(sq) > 50 else ''}».\n"
                    "Tente outras palavras, parte do ID ou verifique acentos.",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 11),
                    justify="center",
                ).pack(pady=60)
            elif mode == "todos":
                tk.Label(
                    host,
                    text="Nenhum MVP no catálogo.\nActualize a lista (internet) ou verifique data/mvp_catalog_cache.json.",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 11),
                    justify="center",
                ).pack(pady=60)
            else:
                tk.Label(
                    host,
                    text="Nenhum MVP corresponde a este filtro.\nEscolha «Todos os MVPs» ou ajuste a busca.",
                    bg=C["bg"],
                    fg=C["text3"],
                    font=("Segoe UI", 11),
                    justify="center",
                ).pack(pady=60)
            if update_hdr_counts:
                self._mvp_refresh_catalog_header_counts()
            _finish_render()
            return

        by_mid = {}
        for e in data.get("entries") or []:
            mid = int(e.get("monster_id") or 0)
            if mid and mid not in by_mid:
                by_mid[mid] = e

        cols = max(1, int(getattr(self, "_MVP_GRID_COLS", 5)))
        for c in range(cols):
            host.columnconfigure(c, weight=1, uniform="mvp_tile")
        rows = (len(items) + cols - 1) // cols
        for rr in range(rows):
            host.rowconfigure(rr, weight=1)

        card_bd = C["border"]
        card_bg = C["card"]

        n = len(items)
        chunk_sz = 20
        self._mvp_grid_progress_label.configure(text=f"Carregando… 0/{n}")
        self._mvp_grid_progress_label.pack(fill="x", padx=16, pady=(0, 4))
        self._mvp_schedule_sprite_poll()

        state = {"i": 0}

        def pump():
            if gen != self._mvp_cards_generation:
                return
            if self.current_page.get() != "mvp":
                return
            end = min(state["i"] + chunk_sz, n)
            for idx in range(state["i"], end):
                cit = items[idx]
                mid = int(cit["id"])
                ent = by_mid.get(mid)
                self._mvp_grid_place_card(host, idx, cit, ent, cols, card_bg, card_bd)
            try:
                self._mvp_grid_progress_label.configure(text=f"Carregando… {end}/{n}")
            except tk.TclError:
                pass
            state["i"] = end
            if end < n:
                self._mvp_chunk_after_id = self.after(10, pump)
            else:
                self._mvp_chunk_after_id = None
                if update_hdr_counts:
                    self._mvp_refresh_catalog_header_counts()
                _finish_render()

        self._mvp_chunk_after_id = self.after(0, pump)

    # ── HISTÓRICO ─────────────────────────────────────────────────────────────
    def _build_hist(self):
        """Constrói o frame do histórico de buscas."""
        self.hist_frame = tk.Frame(self.main, bg=C["bg"])

        hdr = tk.Frame(self.hist_frame, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(20, 4))
        tk.Label(hdr, text="Histórico de Buscas", bg=C["bg"], fg=C["purple3"],
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Clique para rebuscar",
                 bg=C["bg"], fg=C["text3"], font=("Segoe UI", 9)).pack(anchor="w")

        self.hist_list_frame = ScrollableFrame(self.hist_frame)
        self.hist_list_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def _show_hist(self):
        """Mostra o histórico de buscas."""
        self._clear_main()
        self.hist_frame.pack(fill="both", expand=True)
        self._render_hist()

    def _render_hist(self):
        """Renderiza o histórico de buscas."""
        for w in self.hist_list_frame.inner.winfo_children():
            w.destroy()

        if not self.data["searches"]:
            tk.Label(self.hist_list_frame.inner,
                     text="📋\n\nNenhuma busca realizada ainda.",
                     bg=C["bg"], fg=C["text3"], font=("Segoe UI", 11),
                     justify="center").pack(pady=60)
            return

        for s in self.data["searches"]:
            card = tk.Frame(self.hist_list_frame.inner, bg=C["card"],
                            highlightbackground=C["border"], highlightthickness=1,
                            cursor="hand2")
            card.pack(fill="x", pady=3)
            card.bind("<Button-1>", lambda e, q=s["q"]: self._quick_search(q))

            row = tk.Frame(card, bg=C["card"])
            row.pack(fill="x", padx=14, pady=8)
            row.bind("<Button-1>", lambda e, q=s["q"]: self._quick_search(q))

            tk.Label(row, text="🔍", bg=C["card"], fg=C["text"],
                     font=("Segoe UI", 14)).pack(side="left", padx=(0, 10))

            info = tk.Frame(row, bg=C["card"])
            info.pack(side="left", fill="x", expand=True)
            info.bind("<Button-1>", lambda e, q=s["q"]: self._quick_search(q))

            tk.Label(info, text=s["q"], bg=C["card"], fg=C["purple3"],
                     font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
            ts = s.get("ts", "")[:19].replace("T", " ")
            tk.Label(info, text=ts, bg=C["card"], fg=C["text3"],
                     font=("Segoe UI", 8), anchor="w").pack(fill="x")

            count_frame = tk.Frame(row, bg=C["card"])
            count_frame.pack(side="right")
            tk.Label(count_frame, text=str(s.get("count", 0)),
                     bg=C["card"], fg=C["purple3"],
                     font=("Segoe UI", 13, "bold")).pack()
            tk.Label(count_frame, text="resultado(s)",
                     bg=C["card"], fg=C["text3"], font=("Segoe UI", 7)).pack()

    def _save_search(self, q, count):
        """Salva uma busca no histórico."""
        self.data["searches"].insert(0, {
            "q": q, "count": count,
            "ts": datetime.now().isoformat()
        })
        self.data["searches"] = self.data["searches"][:30]
        save_data(self.data)

# ════════════════════════════════════════════════════════════════════════════
# APLICAÇÃO PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        logger.info("🚀 Iniciando Herosaga Monitor...")
        app = HeroSagaMonitor()
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("⏹️ Aplicação encerrada pelo usuário")
    except Exception as e:
        logger.error(f"❌ Erro fatal: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        messagebox.showerror("Erro Fatal", f"Erro: {str(e)}")
