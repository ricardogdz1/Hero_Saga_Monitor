from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import urljoin

import requests


def normalize_media_url(url, *, base_url: str) -> str:
    """Garante URL absoluta para ícones/imagens do site (evita falha no download)."""
    if not url:
        return ""
    u = str(url).strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(base_url + "/", u[1:])
    return u


def api_search_item_names(query: str, *, base_url: str, scraper, logger=None):
    """Busca metadados de itens no vending search (sem raspar lojas)."""
    url = f"{base_url}/?module=vending&action=search&item_search={requests.utils.quote(query)}"
    try:
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{base_url}/",
        }
        response = scraper.get(url, headers=headers, timeout=15)
        if not response.text.strip():
            return []
        return response.json().get("results", []) or []
    except Exception as e:
        if logger:
            logger.debug("api_search_item_names %r: %s", query, e)
        return []


def sync_iwork_name_from_sources(
    iwork: dict,
    history_data,
    *,
    api_search_item_names_fn: Callable[[str], list],
    logger=None,
) -> None:
    """Preenche iwork['name'] via card, histórico ou busca por ID."""
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
        for it in api_search_item_names_fn(str(iid_int)):
            if int(it.get("id", 0)) == iid_int and it.get("name"):
                iwork["name"] = str(it["name"]).strip()
                return
    except Exception as e:
        if logger:
            logger.debug("Resolver nome por ID %s: %s", iid_int, e)


def item_card_meta_from_details(details: dict, *, item_card_keys) -> dict:
    if not details:
        return {}
    return {k: details[k] for k in item_card_keys if details.get(k)}


def api_item_history(
    item_id: int,
    *,
    base_url: str,
    scraper,
    clean_json_response_fn: Callable[[str, bytes], str],
    load_prices_history_fn: Callable[[], dict],
    save_prices_history_fn: Callable[[dict], None],
    get_item_history_fn: Callable[[int], dict],
    logger=None,
):
    """
    Busca histórico de vendas/preços do item usando o endpoint correto.
    Tenta múltiplos tipos de venda: rops, zeny, rmt.
    """
    if logger:
        logger.info(f"Fetching history for item ID: {item_id}")

    all_sales = []
    sale_types = ["rops", "zeny", "rmt"]

    for sale_type in sale_types:
        try:
            url = f"{base_url}/?module=item&action=saleshistory&item_id={item_id}&sale_type={sale_type}"
            if logger:
                logger.info(f"Tentando {sale_type}: {url}")

            response = scraper.get(url, timeout=10)
            if logger:
                logger.debug(f"Status {sale_type}: {response.status_code}")

            if response.status_code == 200 and response.text.strip():
                try:
                    clean_text = clean_json_response_fn(response.text, response.content)
                    data = json.loads(clean_text)

                    if data.get("success") and data.get("sales"):
                        sales = data.get("sales", [])
                        if logger:
                            logger.info(f"✓ {sale_type}: {len(sales)} vendas encontradas")
                        all_sales.extend(sales)
                        if logger and sales:
                            logger.debug(f"Primeira venda de {sale_type}: {json.dumps(sales[0], ensure_ascii=False)}")
                except Exception as e:
                    if logger:
                        logger.debug(f"Parse error para {sale_type}: {str(e)}")
        except Exception as e:
            if logger:
                logger.debug(f"Erro ao buscar {sale_type}: {str(e)}")

    if all_sales:
        if logger:
            logger.info(f"✓ Total de vendas encontradas: {len(all_sales)}")
        all_sales.sort(key=lambda x: x.get("sale_date", ""), reverse=True)

        history = load_prices_history_fn()
        history[str(item_id)] = []

        for sale in all_sales[:30]:
            history[str(item_id)].append(
                {
                    "timestamp": sale.get("sale_date", datetime.now().isoformat()),
                    "price": sale.get("price", 0),
                    "seller_name": sale.get("seller_name", "Shop"),
                    "buyer_name": sale.get("buyer_name", "Comprador"),
                    "quantity": sale.get("quantity", 1),
                    "sale_type": sale.get("sale_type", ""),
                }
            )

        save_prices_history_fn(history)
        if logger:
            logger.info(f"✓ Histórico armazenado com {len(history[str(item_id)])} vendas")

        return {"success": True, "sales": all_sales, "item_id": item_id, "total_sales": len(all_sales)}

    if logger:
        logger.warning(f"Nenhuma venda encontrada para item {item_id}")
    return get_item_history_fn(item_id)


def api_vending_search(
    name: str,
    *,
    base_url: str,
    scraper,
    scraper_available: bool,
    search_item_all_stores_fn: Optional[Callable[[str], dict]],
    coerce_price_fn: Callable[[object], float],
    logger=None,
):
    """
    Busca lojas abertas com o item à venda e retorna ordenado por preço.
    Usa stores_scraper quando disponível, com fallback para API JSON.
    """
    if scraper_available and callable(search_item_all_stores_fn):
        try:
            if logger:
                logger.info(f"🔍 Buscando '{name}' com stores_scraper (BeautifulSoup)...")
            all_results = search_item_all_stores_fn(name)
            herosaga_items = all_results.get("herosaga", [])

            if herosaga_items:
                if logger:
                    logger.info(f"✓ {len(herosaga_items)} lojas encontradas com BeautifulSoup")
                results = []
                for item in herosaga_items:
                    results.append(
                        {
                            "char_name": item.get("char_name", "Shop"),
                            "price": item.get("price", 0),
                            "amount": item.get("quantity", 1),
                            "refinement": item.get("refinement", 0),
                            "cards": item.get("cards", 0),
                            "sale_type": item.get("sale_type", "zeny"),
                        }
                    )
                return results
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ Erro com stores_scraper, usando fallback: {str(e)}")

    url = f"{base_url}/?module=vending&action=search&item_search={requests.utils.quote(name)}"
    try:
        if logger:
            logger.info(f"🔍 Buscando '{name}' com API JSON (fallback)...")
        response = scraper.get(url, timeout=15)
        if logger:
            logger.debug(f"Status: {response.status_code}")
        results = response.json().get("results", [])

        if results:
            if logger:
                logger.info(f"✓ {len(results)} lojas encontradas com API JSON")
                logger.info("Estrutura do primeiro resultado:")
                logger.info(f"{json.dumps(results[0], ensure_ascii=False, indent=2)}")

            def get_price(store):
                price = store.get("price") or store.get("sell_price") or store.get("valor") or float("inf")
                if price == float("inf"):
                    return float("inf")
                try:
                    return coerce_price_fn(price)
                except Exception:
                    return float("inf")

            results.sort(key=get_price)
            if logger:
                logger.info("✓ Ordenadas por preço (menor → maior)")
                for i, store in enumerate(results[:3]):
                    price = get_price(store)
                    logger.debug(f"  #{i+1}: {store.get('char_name', 'Shop')} - Preço: {price}")
        else:
            if logger:
                logger.warning(f"❌ Nenhuma loja encontrada para: {name}")

        return results
    except Exception as e:
        if logger:
            logger.error(f"❌ Erro na busca: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
        return []


def collect_price(
    item_id: int,
    item_data: dict,
    *,
    load_prices_history_fn: Callable[[], dict],
    save_prices_history_fn: Callable[[dict], None],
    logger=None,
):
    """Coleta e armazena preço real do item do vending search."""
    if logger:
        logger.debug(f"Item data received: {json.dumps(item_data, ensure_ascii=False, indent=2)}")

    price = item_data.get("price")
    if logger:
        logger.info(f"Tentando campo 'price': {price}")

    if not price or price == 0:
        price = item_data.get("sell_price") or item_data.get("venda_price") or item_data.get("valor") or item_data.get("preco")
        if logger:
            logger.info(f"Tentando campos alternativos: {price}")

    if not price or price == 0:
        if logger:
            logger.warning(f"Nenhum preço válido encontrado para item {item_id}. Campos disponíveis: {list(item_data.keys())}")
        return

    history = load_prices_history_fn()
    item_id_str = str(item_id)
    if item_id_str not in history:
        history[item_id_str] = []

    sale_entry = {
        "timestamp": datetime.now().isoformat(),
        "price": price,
        "seller_name": item_data.get("char_name") or item_data.get("seller") or "Shop",
        "quantity": item_data.get("amount") or item_data.get("quantity") or 1,
    }

    now = datetime.now().strftime("%Y-%m-%d %H:%M:")
    if not any(s["timestamp"].startswith(now) for s in history[item_id_str]):
        history[item_id_str].append(sale_entry)
        history[item_id_str] = history[item_id_str][-30:]
        save_prices_history_fn(history)
        if logger:
            logger.debug(f"✓ Preço coletado para item {item_id}: {price} ZENY")


def get_item_history(item_id: int, *, load_prices_history_fn: Callable[[], dict], safe_get_fn: Callable[[dict, str, str], str]) -> dict:
    """Retorna histórico de preços coletados para um item."""
    history = load_prices_history_fn()
    item_id_str = str(item_id)

    if item_id_str not in history or not history[item_id_str]:
        return {
            "sales": [],
            "sale_type": "ZENY",
            "item_id": item_id,
            "message": "Nenhum preço coletado ainda. Continue buscando!",
        }

    sales = sorted(history[item_id_str], key=lambda x: x.get("timestamp", ""), reverse=True)
    formatted_sales = []
    for sale in sales:
        formatted_sales.append(
            {
                "sale_date": sale.get("timestamp", ""),
                "seller_name": sale.get("seller_name", "Shop"),
                "buyer_name": safe_get_fn(sale, "buyer_name", "—"),
                "price": sale.get("price", 0),
                "quantity": sale.get("quantity", 1),
            }
        )

    return {"sales": formatted_sales, "sale_type": "ZENY", "item_id": item_id, "total_sales": len(formatted_sales)}


def get_stores_from_item_page(
    item_id: int,
    item_name: str = "",
    *,
    force_refresh: bool = False,
    scraper_available: bool,
    get_herosaga_item_stores_fn,
    item_card_meta_from_details_fn: Callable[[dict], dict],
    parse_item_card_from_soup_fn,
    clean_shop_name_fn: Callable[[str], str],
    parse_price_cell_fn: Callable[[str], float],
    base_url: str,
    headers: dict,
    scraper,
    BeautifulSoup_cls,
    logger=None,
):
    """
    Extrai lojas da página do item e metadados do card (ícone, descrição, peso).
    Retorna (lista_de_lojas, dict_metadados_card).
    """
    extra_meta_from_bs: dict = {}
    if logger:
        logger.info(f"🏪 Carregando lojas para item {item_id} ({item_name})...")

    if scraper_available and callable(get_herosaga_item_stores_fn):
        try:
            if logger:
                logger.info(f"📦 Usando stores_scraper (BeautifulSoup) para item {item_id}...")
            details = get_herosaga_item_stores_fn(item_id, force_refresh=force_refresh)
            if details and "error" not in details:
                stores = details.get("stores") or []
                meta = item_card_meta_from_details_fn(details)
                if logger:
                    logger.info(f"✓ {len(stores)} lojas (scraper); card meta: {bool(meta)}")
                if stores:
                    if logger:
                        logger.debug(f"Lojas: {json.dumps(stores[:2], ensure_ascii=False)}")
                    return stores, meta
                if meta:
                    extra_meta_from_bs.update(meta)
            else:
                if logger:
                    logger.warning(f"⚠️ Resposta inválida do stores_scraper: {details}")
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ Erro com stores_scraper: {str(e)}")
                import traceback

                logger.debug(traceback.format_exc())

    if logger:
        logger.info("🔄 Usando fallback (parse HTML manual)...")

    stores = []
    card_meta = {}

    def _merge_card_meta(cm: dict) -> dict:
        out = dict(cm)
        for k, v in extra_meta_from_bs.items():
            if v and not out.get(k):
                out[k] = v
        return out

    try:
        url = f"{base_url}/?module=item&action=view&id={item_id}"
        if force_refresh:
            url += f"&_={int(datetime.now().timestamp() * 1000)}"
        get_kw = {"timeout": 15}
        if force_refresh:
            get_kw["headers"] = {**headers, "Cache-Control": "no-cache", "Pragma": "no-cache"}
        if logger:
            logger.debug(f"URL: {url}")
        response = scraper.get(url, **get_kw)
        if logger:
            logger.debug(f"Status: {response.status_code}")
        if response.status_code != 200:
            if logger:
                logger.warning(f"❌ Página retornou status {response.status_code}")
            return [], _merge_card_meta({})

        html_debug_file = os.path.join(os.path.expanduser("~"), "herosaga_item_page.html")
        with open(html_debug_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        if logger:
            logger.debug(f"✓ HTML salvo em: {html_debug_file}")

        soup = BeautifulSoup_cls(response.text, "html.parser")
        if scraper_available and callable(parse_item_card_from_soup_fn):
            try:
                card_meta = parse_item_card_from_soup_fn(soup, item_id=str(item_id))
            except Exception as e:
                if logger:
                    logger.debug(f"Card meta fallback: {e}")

        tables = soup.find_all("table")
        if logger:
            logger.info(f"🔍 Encontradas {len(tables)} tabelas na página")

        stores_table = None
        for table in tables:
            headers_local = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            headers_text = " ".join(headers_local)
            if any(
                keyword in headers_text
                for keyword in ["loja", "shop", "refinamento", "refine", "valor", "price", "qtd", "quantity", "vending", "venda"]
            ):
                stores_table = table
                if logger:
                    logger.info(f"✓ Encontrada tabela de lojas com headers: {headers_local}")
                break

        if not stores_table:
            if logger:
                logger.warning("⚠️ Nenhuma tabela com headers reconhecidos encontrada")
                logger.info("🔄 Tentando encontrar por número de colunas...")
            for table_idx, table in enumerate(tables):
                rows = table.find_all("tr")
                if rows:
                    first_row = rows[0]
                    cols = first_row.find_all(["td", "th"])
                    if logger:
                        logger.debug(f"Tabela {table_idx}: {len(rows)} linhas, {len(cols)} colunas")
                    if len(cols) >= 4:
                        stores_table = table
                        if logger:
                            logger.info(f"✓ Selecionada tabela {table_idx} com {len(cols)} colunas")
                        break

        if not stores_table:
            if logger:
                logger.error("❌ Nenhuma tabela adequada encontrada")
            return [], _merge_card_meta(card_meta)

        rows = stores_table.find_all("tr")[1:]
        if logger:
            logger.info(f"✓ Encontradas {len(rows)} linhas na tabela")

        try:
            from stores_scraper import parse_herosaga_item_stores_table as _parse_hs_stores

            stores = _parse_hs_stores(stores_table)
            for st in stores:
                st["char_name"] = clean_shop_name_fn(st.get("char_name") or "")
        except Exception as _pe:
            if logger:
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
                            price = parse_price_cell_fn(price_text)
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
                    shop_name = clean_shop_name_fn(shop_name)
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
                    if logger:
                        logger.debug(
                            f"✓ Loja {row_idx+1}: {shop_name} - R:{refinement} C:{cards} P:{price} ({sale_type}) Q:{quantity}"
                        )
                except Exception as e:
                    if logger:
                        logger.debug(f"Erro ao processar linha {row_idx}: {str(e)}")
                    continue

        stores.sort(key=lambda x: x.get("price", float("inf")))
        if logger:
            logger.info(f"✓ Extraídas {len(stores)} lojas com sucesso")
        return stores, _merge_card_meta(card_meta)
    except Exception as e:
        if logger:
            logger.error(f"❌ Erro ao fazer parse do HTML: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
        return [], _merge_card_meta({})


def api_search(
    name: str,
    *,
    base_url: str,
    scraper,
    get_stores_from_item_page_fn: Callable[[int, str], tuple],
    normalize_media_url_fn: Callable[[str], str],
    logger=None,
):
    """Busca items por nome no vending search."""
    url = f"{base_url}/?module=vending&action=search&item_search={requests.utils.quote(name)}"
    try:
        headers = {"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest", "Referer": f"{base_url}/"}
        response = scraper.get(url, headers=headers, timeout=15)
        if not response.text.strip():
            if logger:
                logger.warning(f"Empty response for search '{name}'")
            return []
        try:
            results = response.json().get("results", [])
            if logger:
                logger.info(f"Search '{name}' returned {len(results)} results")
                if results:
                    logger.debug(f"Primeiro resultado: id={results[0].get('id')}, name={results[0].get('name')}")
            if results:
                if logger:
                    logger.info(f"🏪 Raspando informações de lojas abertas para {len(results)} itens...")
                for item in results[:10]:
                    try:
                        item_id = item.get("id")
                        if item_id:
                            stores, card_meta = get_stores_from_item_page_fn(item_id, item.get("name", ""))
                            if logger:
                                logger.debug(f"Card meta para {item.get('name')} ({item_id}): {card_meta}")
                            for _k, _v in card_meta.items():
                                if _v is not None and _v != "":
                                    item[_k] = normalize_media_url_fn(_v) if _k == "item_icon_url" else _v
                            if stores:
                                prices_by_type = {}
                                for store in stores:
                                    sale_type = store.get("sale_type", "zeny")
                                    price = store.get("price", 0)
                                    if sale_type not in prices_by_type or price < prices_by_type[sale_type]:
                                        prices_by_type[sale_type] = price
                                item["online_stores"] = len(stores)
                                item["min_prices"] = prices_by_type
                                item["stores_list"] = stores
                                if logger:
                                    logger.debug(
                                        f"✓ Item {item.get('name')}: {len(stores)} lojas, preços: {prices_by_type}"
                                    )
                            else:
                                item["online_stores"] = 0
                                item["min_prices"] = {}
                                item["stores_list"] = []
                    except Exception as e:
                        if logger:
                            import traceback

                            logger.debug(
                                f"⚠️ Erro ao buscar lojas para item {item.get('id')} ({item.get('name')}): {str(e)}"
                            )
                            logger.debug(f"   Stacktrace: {traceback.format_exc()}")
                        item["online_stores"] = 0
                        item["min_prices"] = {}
                        item["stores_list"] = []
            return results
        except ValueError as e:
            if logger:
                logger.error(f"JSON decode error for '{name}': {str(e)}")
            return []
    except Exception as e:
        if logger:
            logger.error(f"Search error for '{name}': {str(e)}")
        return []
