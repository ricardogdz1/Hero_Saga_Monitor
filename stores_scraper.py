"""
Store Data Scraper — Módulo para extrair dados de lojas online
Usa BeautifulSoup para fazer parsing de HTML de múltiplas plataformas
"""

import logging
import json
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from datetime import datetime
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup
import requests

from price_parse import parse_price_cell, coerce_price

logger = logging.getLogger(__name__)

# Instancia scraper global
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# Headers para simular navegador real
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class StoreScraper(ABC):
    """Classe base abstrata para scrapers de lojas."""
    
    def __init__(self, store_name: str):
        self.store_name = store_name
        self.logger = logging.getLogger(f"StoreScraper.{store_name}")
    
    @abstractmethod
    def search_item(self, item_name: str) -> List[Dict]:
        """Busca um item na loja e retorna lista de ofertas."""
        pass
    
    @abstractmethod
    def get_item_details(self, item_id: str) -> Dict:
        """Obtém detalhes completos de um item."""
        pass
    
    def _fetch_url(self, url: str, timeout: int = 15, *, force_refresh: bool = False) -> Optional[str]:
        """Faz requisição segura e retorna HTML."""
        try:
            self.logger.debug(f"Buscando: {url}")
            hdr = dict(HEADERS)
            if force_refresh:
                hdr["Cache-Control"] = "no-cache"
                hdr["Pragma"] = "no-cache"
            response = scraper.get(url, headers=hdr, timeout=timeout)
            
            if response.status_code == 200:
                self.logger.debug(f"✓ Status 200 - {len(response.text)} bytes")
                return response.text
            else:
                self.logger.warning(f"❌ Status {response.status_code}")
                return None
        except Exception as e:
            self.logger.error(f"❌ Erro ao buscar URL: {str(e)}")
            return None
    
    def _parse_html(self, html: str) -> Optional[BeautifulSoup]:
        """Parse seguro de HTML."""
        try:
            return BeautifulSoup(html, 'html.parser')
        except Exception as e:
            self.logger.error(f"❌ Erro ao fazer parse HTML: {str(e)}")
            return None
    
    def _extract_price(self, price_text: str) -> float:
        """Extrai valor numérico de texto de preço (milhar com ponto, decimal com vírgula)."""
        try:
            return parse_price_cell(price_text or "")
        except Exception as e:
            self.logger.debug(f"Erro ao extrair preço de '{price_text}': {e}")
            return 0.0


class HerosagaScraper(StoreScraper):
    """Scraper específico para Hero Saga (herosaga.com.br)."""
    
    BASE_URL = "https://herosaga.com.br"
    
    def __init__(self):
        super().__init__("Herosaga")
    
    def search_item(self, item_name: str) -> List[Dict]:
        """Busca item e retorna lojas que vendem."""
        try:
            url = f"{self.BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(item_name)}"
            
            self.logger.info(f"🔍 Buscando '{item_name}' no Herosaga...")
            response = scraper.get(url, timeout=15)
            
            if response.status_code != 200:
                return []
            
            results = response.json().get("results", [])
            self.logger.info(f"✓ Encontradas {len(results)} lojas")
            
            # Padroniza resposta
            standardized = []
            for store in results:
                standardized.append({
                    "store": self.store_name,
                    "item_name": item_name,
                    "char_name": store.get("char_name", "Shop"),
                    "price": coerce_price(store.get("price", 0)),
                    "quantity": int(store.get("amount", 1)),
                    "refinement": int(store.get("refinement", 0)),
                    "cards": int(store.get("cards", 0)),
                    "sale_type": store.get("sale_type", "zeny"),
                    "timestamp": datetime.now().isoformat()
                })
            
            return standardized
            
        except Exception as e:
            self.logger.error(f"❌ Erro na busca: {str(e)}")
            return []
    
    def get_item_details(self, item_id: str, *, force_refresh: bool = False) -> Dict:
        """Obtém detalhes do item de sua página de detalhes."""
        try:
            url = f"{self.BASE_URL}/?module=item&action=view&id={item_id}"
            if force_refresh:
                url += f"&_={int(datetime.now().timestamp() * 1000)}"
            html = self._fetch_url(url, force_refresh=force_refresh)
            
            if not html:
                return {"error": "Não foi possível carregar a página"}
            
            soup = self._parse_html(html)
            if not soup:
                return {"error": "Erro no parse HTML"}
            
            stores = self._parse_stores_table(soup)
            card = self._parse_item_card(soup)

            return {
                "item_id": item_id,
                "stores": stores,
                "total_stores": len(stores),
                "fetched_at": datetime.now().isoformat(),
                **card,
            }
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao obter detalhes: {str(e)}")
            return {"error": str(e)}
    
    def _parse_item_card(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extrai nome exibido, URL do ícone, descrição e peso (painel direito do site).
        """
        out: Dict[str, Any] = {
            "item_icon_url": None,
            "item_description": "",
            "item_weight": "",
            "item_card_title": None,
        }
        try:
            img = soup.find("img", class_="item-title-icon")
            if img and img.get("src"):
                src = (img.get("src") or "").strip()
                if src:
                    out["item_icon_url"] = urljoin(f"{self.BASE_URL}/", src)

            h = soup.find("h4", class_="item-description-name")
            if h:
                out["item_card_title"] = h.get_text(strip=True)

            # Tenta múltiplos seletores para encontrar a descrição
            desc_box = soup.select_one(".item-description-text")
            
            if not desc_box:
                # Tenta seletores alternativos
                desc_box = soup.select_one(".description-text")
            
            if not desc_box:
                # Tenta div com class que contém "description"
                for div in soup.find_all("div"):
                    cls = div.get("class", [])
                    if isinstance(cls, list):
                        cls_str = " ".join(cls)
                    else:
                        cls_str = str(cls)
                    
                    if "description" in cls_str.lower() and "text" in cls_str.lower():
                        desc_box = div
                        break
            
            if desc_box:
                # Extrai texto preservando quebras de linha (de <br> e <p>)
                desc_lines = []
                for elem in desc_box.children:
                    if isinstance(elem, str):
                        text = elem.strip()
                        if text:
                            desc_lines.append(text)
                    elif hasattr(elem, "name"):
                        if elem.name == "br":
                            desc_lines.append("\n")
                        elif elem.name in ("p", "div"):
                            text = elem.get_text(strip=True)
                            if text:
                                desc_lines.append(text)
                                # Adiciona quebra apenas se não for o último elemento
                                if elem != list(desc_box.children)[-1]:
                                    desc_lines.append("\n")
                
                result_desc = "".join(desc_lines).strip()
                if result_desc:
                    out["item_description"] = result_desc
                    self.logger.debug(f"✓ Descrição extraída: {len(result_desc)} caracteres")
                else:
                    self.logger.debug("⚠️ Descrição vazia após processamento")
            else:
                self.logger.debug("⚠️ Elemento .item-description-text não encontrado")

            for strong in soup.find_all("strong"):
                t = strong.get_text(strip=True)
                if t.lower().startswith("peso"):
                    nxt = strong.find_next_sibling()
                    if nxt and nxt.name == "span":
                        out["item_weight"] = nxt.get_text(strip=True)
                    break
        except Exception as e:
            self.logger.debug(f"Card do item: {e}")
        return out

    def _parse_stores_table(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse da tabela de lojas na página de detalhes.
        Retorna lista de dicts com dados padronizados.
        """
        stores = []
        
        try:
            tables = soup.find_all('table')
            self.logger.debug(f"Encontradas {len(tables)} tabelas")
            
            # Encontra tabela de lojas
            stores_table = None
            for table in tables:
                headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
                headers_text = ' '.join(headers)
                
                # Verifica se é a tabela correta
                if any(kw in headers_text for kw in ['loja', 'shop', 'refinamento', 'preço', 'price']):
                    stores_table = table
                    self.logger.debug(f"✓ Tabela de lojas encontrada com headers: {headers}")
                    break
            
            if not stores_table:
                self.logger.warning("⚠️ Tabela de lojas não encontrada")
                return stores
            
            stores = parse_herosaga_item_stores_table(stores_table)
            stores.sort(key=lambda x: x.get("price", float("inf")))
            self.logger.info(f"✓ {len(stores)} lojas extraídas e ordenadas por preço")
            return stores
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao fazer parse da tabela: {str(e)}")
            return stores
    
    @staticmethod
    def _extract_number(text: str) -> int:
        """Extrai primeiro número encontrado em texto."""
        import re
        match = re.search(r'\d+', text)
        return int(match.group()) if match else 0
    
    @staticmethod
    def _detect_sale_type(price_text: str) -> str:
        """
        Detecta tipo de moeda do texto do preço com mais precisão.
        Verifica RMT → ROPS → ZENY (padrão)
        """
        import re
        text = (price_text or "").lower().strip()
        
        # Se contém "refinamento", provavelmente é informação de item, não preço
        if 'refinamento' in text or 'refin' in text:
            return "zeny"  # Padrão para dados de item
        
        # Hero Points (preço costuma vir como 225,000c sem citar moeda na célula)
        if "hero point" in text or "heropoint" in text or "hero points" in text:
            return "hero_points"
        
        # 1. Verifica RMT PRIMEIRO (mais específico)
        # Aceita: rmt, rm, r$m, r m, etc
        if 'rmt' in text or re.search(r'(rm(\$| |$)|r[\$\s]?m|rmt)', text):
            return "rmt"
        
        # 2. Depois ROPS
        if 'rops' in text or re.search(r'(rp(\$| |$)|r\$(?!\s*m)|^\s*r\$)', text):
            return "rops"
        
        # 3. Tudo mais = ZENY (padrão)
        return "zeny"


def _stores_table_header_indices(headers: List[str]) -> Dict[str, int]:
    """Mapeia cabeçalhos da tabela de lojas do Herosaga para índices de coluna."""
    h = [(x or "").strip().lower() for x in headers]
    out: Dict[str, int] = {}
    pairs = [
        ("loja", ("loja", "vendedor", "personagem", "char", "shop")),
        ("ref", ("refinamento", "refino", "refine", "enhancement")),
        ("cards", ("cartas", "cards", "slot")),
        ("valor", ("valor", "preço", "preco", "price")),
        ("qtd", ("qtd", "quant", "quantity")),
        ("venda", ("venda", "moeda", "tipo")),
    ]
    for i, cell in enumerate(h):
        for key, variants in pairs:
            if key in out:
                continue
            if any(v in cell for v in variants):
                out[key] = i
                break
    return out


def parse_herosaga_item_stores_table(stores_table) -> List[Dict]:
    """
    Extrai linhas da tabela «Lojas Abertas» da página do item.
    Usa cabeçalhos (Loja, Refinamento, Cartas, Valor, …) para não trocar colunas
    quando o HTML tiver coluna extra (checkbox) ou ordem ligeiramente diferente.
    """
    log = logging.getLogger(__name__)
    stores: List[Dict] = []
    hdr_tr = stores_table.find("tr")
    headers_raw = [th.get_text(strip=True) for th in hdr_tr.find_all("th")] if hdr_tr else []
    idx = _stores_table_header_indices(headers_raw)
    nh = len(headers_raw)
    use_map = idx.get("valor") is not None and idx.get("ref") is not None

    def gv(texts: List[str], key: str, default_i: int) -> str:
        if use_map:
            j = idx.get(key)
            if j is not None and j < len(texts):
                return texts[j] or ""
        if default_i < len(texts):
            return texts[default_i] or ""
        return ""

    rows = stores_table.find_all("tr")[1:]
    for row_idx, row in enumerate(rows):
        try:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            texts = [c.get_text(strip=True) for c in cols]
            if use_map and nh > 0 and len(texts) == nh + 1:
                first = texts[0] or ""
                if len(first) <= 2 and not re.search(r"[a-zA-Z\u00c0-\u024f]", first):
                    texts = texts[1:]
            if use_map and len(texts) < 3:
                continue

            shop_name = gv(texts, "loja", 0).strip() or "—"
            ref_raw = gv(texts, "ref", 1)
            cards_raw = gv(texts, "cards", 2)
            price_text = gv(texts, "valor", 3)
            q_raw = gv(texts, "qtd", 4)
            venda_raw = gv(texts, "venda", 5)

            refinement = HerosagaScraper._extract_number(ref_raw)
            refinement = max(0, min(20, refinement))
            if "sim" in (cards_raw or "").lower():
                cards = 1
            else:
                cards = HerosagaScraper._extract_number(cards_raw)
            quantity = HerosagaScraper._extract_number(q_raw) if q_raw else 1
            quantity = max(1, quantity)

            sale_type = HerosagaScraper._detect_sale_type(f"{price_text} {venda_raw}".strip())
            try:
                price = float(parse_price_cell(price_text or ""))
            except Exception:
                price = 0.0
            if price <= 0:
                continue

            store = {
                "char_name": shop_name,
                "refinement": refinement,
                "cards": cards,
                "price": price,
                "quantity": quantity,
                "amount": quantity,
                "sale_type": sale_type,
            }
            stores.append(store)
            log.debug(
                "Loja linha %s: %s R:%s P:%s (%s) q:%s",
                row_idx + 1,
                shop_name[:32],
                refinement,
                price,
                sale_type,
                quantity,
            )
        except Exception as e:
            log.debug("parse row %s: %s", row_idx, e)
            continue

    stores.sort(key=lambda x: x.get("price", float("inf")))
    return stores


class MercadoLivreGameScraper(StoreScraper):
    """Scraper para Mercado Livre (seção de games/itens online)."""
    
    def __init__(self):
        super().__init__("Mercado Livre Games")
    
    def search_item(self, item_name: str) -> List[Dict]:
        """Busca item no Mercado Livre."""
        try:
            # Nota: ML requer mais cuidado com anti-bot
            search_url = f"https://lista.mercadolivre.com.br/{item_name.replace(' ', '-')}"
            
            self.logger.info(f"🔍 Buscando '{item_name}' no Mercado Livre...")
            html = self._fetch_url(search_url, timeout=20)
            
            if not html:
                return []
            
            soup = self._parse_html(html)
            if not soup:
                return []
            
            results = self._parse_mercado_livre_items(soup, item_name)
            self.logger.info(f"✓ Encontrados {len(results)} itens")
            
            return results
            
        except Exception as e:
            self.logger.error(f"❌ Erro na busca: {str(e)}")
            return []
    
    def _parse_mercado_livre_items(self, soup: BeautifulSoup, item_name: str) -> List[Dict]:
        """Parse dos itens do Mercado Livre."""
        items = []
        
        try:
            # Procura por containers de produtos
            product_divs = soup.find_all('div', {'data-component': 'item'})
            self.logger.debug(f"Encontrados {len(product_divs)} produtos")
            
            for product in product_divs[:10]:  # Limita a 10 primeiros
                try:
                    # Extrai dados do produto
                    title_elem = product.find('h2')
                    price_elem = product.find('span', {'class': 'price-tag'})
                    seller_elem = product.find('p', {'class': 'seller-info'})
                    
                    if not title_elem or not price_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    price = self._extract_price(price_elem.get_text(strip=True))
                    seller = seller_elem.get_text(strip=True) if seller_elem else "Mercado Livre"
                    
                    items.append({
                        "store": self.store_name,
                        "item_name": item_name,
                        "title": title,
                        "price": price,
                        "seller": seller,
                        "currency": "BRL",
                        "timestamp": datetime.now().isoformat()
                    })
                    
                except Exception as e:
                    self.logger.debug(f"Erro ao extrair produto: {e}")
                    continue
            
            return items
            
        except Exception as e:
            self.logger.error(f"❌ Erro no parse: {str(e)}")
            return []
    
    def get_item_details(self, item_id: str) -> Dict:
        """Obtém detalhes de um item específico do ML."""
        # Implementar se necessário
        return {"error": "Não implementado"}


# ── Registry de Scrapers ─────────────────────────────────────────────────────
class StoreScraperRegistry:
    """Registro central de todos os scrapers disponíveis."""
    
    def __init__(self):
        self.scrapers = {
            "herosaga": HerosagaScraper(),
            # "mercadolivre": MercadoLivreGameScraper(),  # Comentado - precisa de ajustes
        }
        self.logger = logging.getLogger("StoreScraperRegistry")
    
    def search_all_stores(self, item_name: str) -> Dict[str, List[Dict]]:
        """Busca item em todas as lojas registradas."""
        results = {}
        
        self.logger.info(f"🛍️ Buscando '{item_name}' em {len(self.scrapers)} lojas...")
        
        for store_key, scraper in self.scrapers.items():
            try:
                self.logger.info(f"  → {scraper.store_name}...")
                items = scraper.search_item(item_name)
                results[store_key] = items
                self.logger.debug(f"  ✓ {len(items)} itens encontrados")
            except Exception as e:
                self.logger.error(f"  ❌ Erro: {str(e)}")
                results[store_key] = []
        
        return results
    
    def get_scraper(self, store_name: str) -> Optional[StoreScraper]:
        """Obtém scraper específico por nome."""
        return self.scrapers.get(store_name.lower())
    
    def add_scraper(self, key: str, scraper: StoreScraper):
        """Adiciona novo scraper ao registro."""
        self.scrapers[key.lower()] = scraper
        self.logger.info(f"✓ Scraper '{scraper.store_name}' registrado")


# Instância global
scraper_registry = StoreScraperRegistry()


# ── Funções de Conveniência ──────────────────────────────────────────────────
def search_item_all_stores(item_name: str) -> Dict[str, List[Dict]]:
    """Busca um item em todas as lojas configuradas."""
    return scraper_registry.search_all_stores(item_name)


def get_herosaga_item_stores(item_id: int, *, force_refresh: bool = False) -> Dict:
    """Obtém lojas que vendem um item específico no Herosaga."""
    scraper = HerosagaScraper()
    return scraper.get_item_details(str(item_id), force_refresh=force_refresh)


def parse_item_card_from_soup(soup: BeautifulSoup) -> Dict[str, Any]:
    """Conveniência: metadados do card a partir de HTML já carregado."""
    return HerosagaScraper()._parse_item_card(soup)


if __name__ == "__main__":
    # Exemplo de uso
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Testa busca no Herosaga
    print("\n=== Teste: Buscando no Herosaga ===")
    results = search_item_all_stores("espada")
    print(json.dumps(results, ensure_ascii=False, indent=2))
