"""
GUIA PRÁTICO DE INTEGRAÇÃO — stores_scraper.py no app.py

Como integrar o novo módulo de scraping BeautifulSoup no app.py existente.
"""

# ════════════════════════════════════════════════════════════════════════════
# PASSO 1: Adicionar Imports no app.py
# ════════════════════════════════════════════════════════════════════════════

# Adicione estas linhas no início do app.py (após os imports existentes):

from stores_scraper import (
    search_item_all_stores,
    get_herosaga_item_stores,
    HerosagaScraper,
    scraper_registry
)


# ════════════════════════════════════════════════════════════════════════════
# PASSO 2: Substituir Funções Existentes
# ════════════════════════════════════════════════════════════════════════════

# ── OPÇÃO A: Substituir api_vending_search ──────────────────────────────────
# ANTIGO (em app.py):
"""
def api_vending_search(name: str):
    url = f"{BASE_URL}/?module=vending&action=search&item_search={requests.utils.quote(name)}"
    try:
        logger.info(f"🔍 Vending Search for: {name}")
        response = scraper.get(url, timeout=15)
        results = response.json().get("results", [])
        # ...
        return results
    except Exception as e:
        logger.error(f"❌ Vending Search Error: {str(e)}")
        return []
"""

# NOVO (com BeautifulSoup):
def api_vending_search_v2(name: str):
    """
    Versão melhorada que usa o módulo stores_scraper.
    Mais robusto e prepara para múltiplas lojas.
    """
    try:
        logger.info(f"🔍 Buscando '{name}' em lojas online...")
        
        # Busca em todas as lojas configuradas
        all_results = search_item_all_stores(name)
        
        # Pega resultados do Herosaga (principal)
        herosaga_items = all_results.get("herosaga", [])
        
        logger.info(f"✓ {len(herosaga_items)} lojas encontradas")
        
        # Converte para formato compatível com seu app
        standardized = []
        for item in herosaga_items:
            standardized.append({
                "id": item.get("id"),  # Se houver ID
                "name": name,
                "char_name": item.get("char_name", "Shop"),
                "price": item.get("price", 0),
                "amount": item.get("quantity", 1),
                "refinement": item.get("refinement", 0),
                "cards": item.get("cards", 0),
                "sale_type": item.get("sale_type", "zeny"),
                "source": "herosaga"
            })
        
        return standardized
        
    except Exception as e:
        logger.error(f"❌ Erro na busca de lojas: {str(e)}")
        return []


# ── OPÇÃO B: Melhorar get_stores_from_item_page ─────────────────────────────
# ANTIGO (em app.py):
"""
def get_stores_from_item_page(item_id: int, item_name: str = ""):
    # Código complicado de parse HTML...
    stores = []
    try:
        url = f"{BASE_URL}/?module=item&action=view&id={item_id}"
        # ...parsing com BeautifulSoup
        return stores
"""

# NOVO (usando stores_scraper):
def get_stores_from_item_page_v2(item_id: int, item_name: str = ""):
    """
    Versão melhorada usando o módulo robusto.
    Melhor logging, tratamento de erros e estrutura.
    """
    try:
        logger.info(f"🏪 Carregando lojas para item {item_id}...")
        
        # Usa o scraper do Herosaga diretamente
        details = get_herosaga_item_stores(item_id)
        
        if "error" in details:
            logger.error(f"❌ {details['error']}")
            return []
        
        stores = details.get("stores", [])
        logger.info(f"✓ {len(stores)} lojas encontradas")
        
        return stores
        
    except Exception as e:
        logger.error(f"❌ Erro ao obter lojas: {str(e)}")
        return []


# ════════════════════════════════════════════════════════════════════════════
# PASSO 3: Adicionar Novas Funcionalidades
# ════════════════════════════════════════════════════════════════════════════

def get_store_statistcs(item_name: str) -> dict:
    """
    Nova função: Calcula estatísticas de preço em todas as lojas.
    """
    try:
        results = search_item_all_stores(item_name)
        stats = {}
        
        for store_name, items in results.items():
            if items:
                prices = [item.get("price", 0) for item in items if item.get("price", 0) > 0]
                
                if prices:
                    stats[store_name] = {
                        "num_sellers": len(items),
                        "min_price": min(prices),
                        "max_price": max(prices),
                        "avg_price": sum(prices) / len(prices),
                        "median_price": sorted(prices)[len(prices)//2]
                    }
        
        return stats
    except Exception as e:
        logger.error(f"Erro ao calcular estatísticas: {str(e)}")
        return {}


def search_best_deal(item_name: str, max_price: float = None) -> list:
    """
    Nova função: Encontra as melhores ofertas de um item.
    
    Args:
        item_name: Nome do item a buscar
        max_price: Filtro opcional - apenas preços até este valor
    
    Returns:
        Lista de melhores ofertas, ordenada por preço
    """
    try:
        results = search_item_all_stores(item_name)
        all_deals = []
        
        for store_name, items in results.items():
            for item in items:
                if max_price and item.get("price", 0) > max_price:
                    continue
                
                all_deals.append({
                    "store": store_name,
                    "seller": item.get("char_name", "Shop"),
                    "price": item.get("price", 0),
                    "quantity": item.get("quantity", 1),
                    "specs": {
                        "refinement": item.get("refinement", 0),
                        "cards": item.get("cards", 0)
                    },
                    "sale_type": item.get("sale_type", "zeny")
                })
        
        # Ordena por preço
        all_deals.sort(key=lambda x: x["price"])
        
        logger.info(f"✓ Encontradas {len(all_deals)} ofertas para '{item_name}'")
        return all_deals
        
    except Exception as e:
        logger.error(f"Erro ao buscar melhores ofertas: {str(e)}")
        return []


# ════════════════════════════════════════════════════════════════════════════
# PASSO 4: Adicionar ao Seu Event Loop/Thread
# ════════════════════════════════════════════════════════════════════════════

# Se você tem uma thread de monitoramento automático, adicione:

def monitor_item_prices(item_name: str, interval_seconds: int = 300):
    """
    Nova função: Monitora preço de um item continuamente.
    
    Args:
        item_name: Item a monitorar
        interval_seconds: Intervalo entre verificações (padrão: 5 min)
    """
    import time
    from collections import defaultdict
    
    price_history = defaultdict(list)
    
    while True:
        try:
            logger.info(f"📊 Monitorando '{item_name}'...")
            
            deals = search_best_deal(item_name)
            
            if deals:
                best_deal = deals[0]
                timestamp = datetime.now().isoformat()
                
                price_history[item_name].append({
                    "timestamp": timestamp,
                    "price": best_deal["price"],
                    "seller": best_deal["seller"],
                    "quantity": best_deal["quantity"]
                })
                
                # Notifica se preço mudou
                if len(price_history[item_name]) > 1:
                    previous = price_history[item_name][-2]["price"]
                    current = best_deal["price"]
                    
                    if current < previous:
                        logger.warning(f"💭 Preço DROPPED! {previous} → {current}")
                    elif current > previous:
                        logger.warning(f"📈 Preço SUBIU! {previous} → {current}")
            
            # Aguarda intervalo
            time.sleep(interval_seconds)
            
        except Exception as e:
            logger.error(f"Erro no monitoring: {str(e)}")
            time.sleep(interval_seconds)


# ════════════════════════════════════════════════════════════════════════════
# PASSO 5: Atualizar a UI do Tkinter
# ════════════════════════════════════════════════════════════════════════════

# Se você tem um widget de busca, atualize assim:

# ANTIGO:
"""
def on_search_click():
    item_name = search_entry.get()
    results = api_vending_search(item_name)  # Antiga função
    display_results(results)
"""

# NOVO:
def on_search_click_v2():
    """Versão com novo módulo de scraping."""
    item_name = search_entry.get()
    
    # Busca com novo módulo
    results = api_vending_search_v2(item_name)
    
    # Exibe resultados
    display_results(results)
    
    # EXTRA: Exibe estatísticas
    stats = get_store_statistcs(item_name)
    display_statistics(stats)


# ════════════════════════════════════════════════════════════════════════════
# PASSO 6: Tratamento de Erros e Logging
# ════════════════════════════════════════════════════════════════════════════

# Adicione isto à sua configuração de logging:

def setup_enhanced_logging():
    """Configura logging para o novo módulo."""
    
    # Logging para stores_scraper
    scraper_logger = logging.getLogger("StoreScraper")
    scraper_logger.setLevel(logging.DEBUG)
    
    # Handler para arquivo separado (opcional)
    scraper_handler = logging.FileHandler(
        os.path.join(os.path.expanduser("~"), "herosaga_scraper.log"),
        encoding="utf-8"
    )
    scraper_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    scraper_logger.addHandler(scraper_handler)


# ════════════════════════════════════════════════════════════════════════════
# EXEMPLO COMPLETO: Mini-app de Teste
# ════════════════════════════════════════════════════════════════════════════

def test_integration():
    """Teste rápido de integração."""
    
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "="*80)
    print("TESTE DE INTEGRAÇÃO - Scraper BeautifulSoup")
    print("="*80 + "\n")
    
    # Teste 1: Busca simples
    print("1️⃣ Busca Simples:")
    print("-" * 80)
    results = api_vending_search_v2("Espada")
    print(f"  ✓ Encontradas {len(results)} lojas")
    if results:
        print(f"  Mais barata: {results[0]['char_name']} - {results[0]['price']} ZENY\n")
    
    # Teste 2: Estatísticas
    print("2️⃣ Estatísticas:")
    print("-" * 80)
    stats = get_store_statistcs("Espada")
    for store, data in stats.items():
        print(f"  {store}: Min={data['min_price']:.0f} "
              f"Max={data['max_price']:.0f} Avg={data['avg_price']:.0f}")
    print()
    
    # Teste 3: Melhores ofertas
    print("3️⃣ Melhores Ofertas:")
    print("-" * 80)
    deals = search_best_deal("Espada")
    for i, deal in enumerate(deals[:3], 1):
        print(f"  {i}. {deal['seller']:20} - {deal['price']:10.0f} {deal['sale_type']}")
    
    print("\n" + "="*80)
    print("✓ Teste concluído!")
    print("="*80 + "\n")


if __name__ == "__main__":
    test_integration()
