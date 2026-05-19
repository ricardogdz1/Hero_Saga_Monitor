#!/usr/bin/env python3
"""
Script de teste para raspar lojas do item ID 6755
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from app import get_stores_from_item_page

# Teste item 6755
item_id = 6755
item_name = "Espada Lendária"  # Você pode verificar o nome real depois

print(f"\n{'='*80}")
print(f"Testando scraping de lojas para item ID: {item_id}")
print(f"{'='*80}\n")

try:
    stores, card_meta = get_stores_from_item_page(item_id, item_name)
    print(f"Card meta: {card_meta}\n")

    if stores:
        print(f"✓ {len(stores)} lojas encontradas!\n")
        print("LOJAS DISPONÍVEIS:")
        print("-" * 80)
        
        for i, store in enumerate(stores[:20], 1):
            print(f"\n{i}. {store.get('char_name', 'Shop')}")
            print(f"   • Refinamento: {store.get('refinement', 0)}")
            print(f"   • Cartas: {store.get('cards', 0)}")
            print(f"   • Preço: {store.get('price', 0)} ({store.get('sale_type', 'zeny')})")
            print(f"   • Quantidade: {store.get('amount', 1)}")
    else:
        print("❌ Nenhuma loja encontrada!")
        
except Exception as e:
    print(f"❌ Erro: {str(e)}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*80}\n")
