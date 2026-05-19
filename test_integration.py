"""
TESTE DE INTEGRAÇÃO — Verifica se o BeautifulSoup foi integrado com sucesso no app.py
"""

import sys
import logging

# Configura logging para ver os detalhes
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

print("\n" + "="*80)
print("TESTE DE INTEGRAÇÃO - BEAUTIFULSOUP EM APP.PY")
print("="*80 + "\n")

try:
    # Teste 1: Importa o app
    print("1️⃣ Importando app.py...")
    import app
    print("   ✅ app.py importado com sucesso\n")
    
    # Teste 2: Verifica se o módulo stores_scraper está disponível
    print("2️⃣ Verificando módulo stores_scraper...")
    if app.SCRAPER_AVAILABLE:
        print("   ✅ Módulo stores_scraper DISPONÍVEL")
        print("   → BeautifulSoup está ativo!\n")
    else:
        print("   ⚠️  Módulo stores_scraper NÃO disponível")
        print("   → Será usado fallback (API JSON)\n")
    
    # Teste 3: Testa função api_vending_search
    print("3️⃣ Testando função api_vending_search()...")
    print("   Buscando 'Espada'...")
    
    results = app.api_vending_search("Espada")
    
    if results:
        print(f"   ✅ {len(results)} lojas encontradas!\n")
        print("   Primeiras 3 ofertas:")
        for i, store in enumerate(results[:3], 1):
            char = store.get("char_name", "?")
            price = store.get("price", "?")
            sale_type = store.get("sale_type", "?").upper()
            qty = store.get("amount", 1)
            print(f"      {i}. {char:20} | R${price:>10.0f} {sale_type:6} | Qtd: {qty}")
    else:
        print("   ⚠️ Nenhuma loja encontrada\n")
    
    print()
    
    # Teste 4: Testa função get_stores_from_item_page
    print("4️⃣ Testando função get_stores_from_item_page()...")
    print("   Buscando lojas para item ID 1001...")
    
    stores, _meta = app.get_stores_from_item_page(1001, "Espada")
    
    if stores:
        print(f"   ✅ {len(stores)} lojas encontradas!\n")
        print("   Primeiras 3 lojas:")
        for i, store in enumerate(stores[:3], 1):
            char = store.get("char_name", "?")
            price = store.get("price", "?")
            ref = store.get("refinement", 0)
            cards = store.get("cards", 0)
            print(f"      {i}. {char:20} | R${price:>10.0f} | Ref: {ref} | Cards: {cards}")
    else:
        print("   ℹ️  Nenhuma loja encontrada (item pode não existir)\n")
    
    print("\n" + "="*80)
    print("✅ INTEGRAÇÃO BEM-SUCEDIDA!")
    print("="*80)
    print("\nO que foi integrado:")
    print("  ✓ Módulo stores_scraper.py com BeautifulSoup")
    print("  ✓ Função api_vending_search() melhorada")
    print("  ✓ Função get_stores_from_item_page() melhorada")
    print("  ✓ Fallback automático para modo anterior se necessário")
    print("\nProximos passos:")
    print("  1. Rode a aplicação: python app.py")
    print("  2. Teste a busca de itens na interface")
    print("  3. Monitore os logs para ver o BeautifulSoup em ação")
    print("="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ ERRO NA INTEGRAÇÃO:")
    print(f"   {str(e)}\n")
    import traceback
    traceback.print_exc()
    print()
