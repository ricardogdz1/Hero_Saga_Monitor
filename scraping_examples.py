"""
Exemplo de integração do stores_scraper.py com app.py

Este arquivo mostra como usar o módulo de scraping BeautifulSoup
para melhorar a coleta de dados do Herosaga Monitor.
"""

from stores_scraper import (
    search_item_all_stores,
    get_herosaga_item_stores,
    HerosagaScraper,
    scraper_registry
)
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ── EXEMPLO 1: Busca simples de um item ──────────────────────────────────────
def exemplo_busca_simples():
    """Busca um item no Herosaga e exibe o resultado."""
    print("\n" + "="*80)
    print("EXEMPLO 1: Busca Simples")
    print("="*80)
    
    results = search_item_all_stores("Espada")
    
    # Exibe resultados formatados
    for store_name, items in results.items():
        if items:
            print(f"\n📦 {store_name.upper()}: {len(items)} lojas encontradas")
            print("-" * 80)
            
            # Exibe os 5 mais baratos
            for i, item in enumerate(items[:5], 1):
                price = item.get("price", 0)
                char = item.get("char_name", "Shop")
                qty = item.get("quantity", 1)
                sale_type = item.get("sale_type", "zeny").upper()
                
                print(f"{i}. {char:20} | Preço: {price:10.0f} {sale_type} | Qtd: {qty}")


# ── EXEMPLO 2: Obter detalhes de um item específico ───────────────────────────
def exemplo_detalhes_item():
    """Obtém detalhes completos de um item pelo ID."""
    print("\n" + "="*80)
    print("EXEMPLO 2: Detalhes Completos de Um Item")
    print("="*80)
    
    item_id = 1001  # ID exemplo - mude conforme necessário
    
    details = get_herosaga_item_stores(item_id)
    
    if "error" not in details:
        stores = details.get("stores", [])
        print(f"\n🏪 {len(stores)} lojas encontradas para item {item_id}")
        
        # Organiza por tipo de venda
        by_type = {}
        for store in stores:
            sale_type = store.get("sale_type", "unknown")
            if sale_type not in by_type:
                by_type[sale_type] = []
            by_type[sale_type].append(store)
        
        # Exibe agrupado por tipo
        for sale_type, type_stores in by_type.items():
            print(f"\n💰 {sale_type.upper()}:")
            print("-" * 80)
            for store in sorted(type_stores, key=lambda x: x.get("price", float('inf')))[:3]:
                char = store.get("char_name", "Shop")
                price = store.get("price", 0)
                refin = store.get("refinement", 0)
                cards = store.get("cards", 0)
                qty = store.get("quantity", 1)
                print(f"  {char:20} | Preço: {price:8.0f} | R:{refin} C:{cards} | Qtd:{qty}")
    else:
        print(f"\n❌ Erro: {details['error']}")


# ── EXEMPLO 3: Usar scraper customizado ──────────────────────────────────────
def exemplo_scraper_direto():
    """Usa o scraper do Herosaga diretamente."""
    print("\n" + "="*80)
    print("EXEMPLO 3: Usando Scraper Direto")
    print("="*80)
    
    scraper = HerosagaScraper()
    
    # Busca por nome
    print("\n🔍 Buscando 'Poção de Vida'...")
    items = scraper.search_item("Poção de Vida")
    
    print(f"✓ Encontradas {len(items)} ofertas\n")
    
    # Exibe em JSON formatado
    print(json.dumps(items[:3], ensure_ascii=False, indent=2))


# ── EXEMPLO 4: Estatísticas de preço ─────────────────────────────────────────
def exemplo_estatisticas():
    """Calcula estatísticas de preço de um item."""
    print("\n" + "="*80)
    print("EXEMPLO 4: Estatísticas de Preço")
    print("="*80)
    
    results = search_item_all_stores("Espada")
    
    for store_name, items in results.items():
        if items:
            prices = [item.get("price", 0) for item in items if item.get("price", 0) > 0]
            
            if prices:
                prices_sorted = sorted(prices)
                
                print(f"\n📊 {store_name.upper()}:")
                print(f"   Total de ofertas: {len(items)}")
                print(f"   Menor preço: {min(prices):.0f}")
                print(f"   Maior preço: {max(prices):.0f}")
                print(f"   Preço médio: {sum(prices)/len(prices):.0f}")
                print(f"   Mediana: {prices_sorted[len(prices)//2]:.0f}")


# ── EXEMPLO 5: Extensão com nova loja ────────────────────────────────────────
def exemplo_adicionar_nova_loja():
    """Demonstra como adicionar um novo scraper de loja."""
    print("\n" + "="*80)
    print("EXEMPLO 5: Como Adicionar Uma Nova Loja")
    print("="*80)
    
    print("""
    Para adicionar uma nova loja, siga estes passos:
    
    1. Crie uma classe que herada de StoreScraper:
    
       from stores_scraper import StoreScraper
       
       class MinhaLojaComScraper(StoreScraper):
           def __init__(self):
               super().__init__("Nome da Minha Loja")
           
           def search_item(self, item_name: str) -> List[Dict]:
               # Implementar lógica de busca
               pass
           
           def get_item_details(self, item_id: str) -> Dict:
               # Implementar lógica de detalhes
               pass
    
    2. Registre no registry:
    
       from stores_scraper import scraper_registry, MinhaLojaComScraper
       
       minha_loja = MinhaLojaComScraper()
       scraper_registry.add_scraper("minhalojakey", minha_loja)
    
    3. Use normalmente:
    
       results = search_item_all_stores("Item")
       # Agora inclui resultados de "minhalojakey"
    """)


# ── EXEMPLO 6: Integração com app.py ─────────────────────────────────────────
def exemplo_integracao_app_py():
    """Mostra código para integrar no app.py."""
    print("\n" + "="*80)
    print("EXEMPLO 6: Integração com app.py")
    print("="*80)
    
    print("""
    No seu app.py, você pode usar o novo módulo assim:
    
    # No início do arquivo, adicione:
    from stores_scraper import search_item_all_stores, get_herosaga_item_stores
    
    # Na função que faz busca, substitua por:
    def search_stores(item_name: str):
        # Antiga (apenas API JSON):
        # results = api_search(item_name)
        
        # Nova (usa BeautifulSoup + API):
        all_results = search_item_all_stores(item_name)
        
        # Processa resultados
        stores = all_results.get("herosaga", [])
        for store in stores:
            print(f"Loja: {store['char_name']} - Preço: {store['price']}")
    
    # Para obter detalhes de um item:
    def get_item_details(item_id: int):
        details = get_herosaga_item_stores(item_id)
        stores = details.get("stores", [])
        
        # Agora você tem acesso a:
        # - char_name (nome do personagem/loja)
        # - price (preço)
        # - refinement (nível de refinamento)
        # - cards (cartas encaixadas)
        # - quantity (quantidade disponível)
        # - sale_type (tipo de moeda: zeny, rops, rmt)
    """)


# ── EXECUTAR EXEMPLOS ────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "HEROSAGA MONITOR - EXEMPLOS DE SCRAPING" + " "*19 + "║")
    print("║" + " "*25 + "com BeautifulSoup e cloudscraper" + " "*21 + "║")
    print("╚" + "="*78 + "╝")
    
    try:
        # Descomente os exemplos que quer rodar:
        
        exemplo_busca_simples()
        
        # exemplo_detalhes_item()
        
        # exemplo_scraper_direto()
        
        # exemplo_estatisticas()
        
        exemplo_adicionar_nova_loja()
        
        exemplo_integracao_app_py()
        
        print("\n" + "="*80)
        print("✓ Exemplos concluídos!")
        print("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"Erro ao executar exemplos: {str(e)}", exc_info=True)
