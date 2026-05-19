#!/usr/bin/env python3
"""
Script de teste completo do scraping de lojas com busca
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from app import api_search
import json

print("\n" + "="*80)
print("TESTE COMPLETO: Busca com Scraping de Lojas")
print("="*80 + "\n")

# Buscar por "armadura" para ter itens com refinamento
search_term = "armadura"

print("[*] Buscando por: '%s'\n" % search_term)

try:
    results = api_search(search_term)
    
    if results:
        print("[OK] %d itens encontrados!\n" % len(results))
        
        # Mostrar primeiros 5 resultados
        for i, item in enumerate(results[:5], 1):
            print("\n" + "-"*80)
            print("%d. %s" % (i, item.get('name', 'Item Desconhecido')))
            print("   ID: %s" % item.get('id', '?'))
            
            online_stores = item.get('online_stores', 0)
            if online_stores > 0:
                print("   [LOJAS] %d loja(s) online" % online_stores)
                
                # Precos minimos por moeda
                min_prices = item.get('min_prices', {})
                if min_prices:
                    print("\n   [PRECOS]:")
                    for sale_type, price in min_prices.items():
                        if sale_type == "zeny":
                            print("      - ZENY: %s" % format(price, ',').replace(',', '.'))
                        elif sale_type == "rops":
                            print("      - ROPS: R$ %s" % format(price, ',').replace(',', '.'))
                        elif sale_type == "rmt":
                            print("      - RMT: R$ %s" % format(price, ',').replace(',', '.'))
                
                # Mostrar algumas lojas
                stores = item.get('stores_list', [])
                if stores:
                    print("\n   [LOJAS LISTA]:")
                    for j, store in enumerate(stores[:3], 1):
                        print("      %d. %s" % (j, store.get('char_name', 'Shop')))
                        ref = store.get('refinement', 0)
                        cards = store.get('cards', 0)
                        price = store.get('price', 0)
                        qty = store.get('amount', 1)
                        sale_type = store.get('sale_type', 'zeny')
                        
                        info = ""
                        if ref > 0 or cards > 0:
                            info += "Refino: +%d | Cartas: %d" % (ref, cards)
                        if info:
                            print("         %s | Preco: %s %s" % (info, price, sale_type.upper()))
                        else:
                            print("         Preco: %s %s" % (price, sale_type.upper()))
                        print("         Quantidade: %d" % qty)
            else:
                print("   [ERRO] Nenhuma loja online")
            
    else:
        print("[ERRO] Nenhum item encontrado!")
        
except Exception as e:
    print("[ERRO] %s" % str(e))
    import traceback
    traceback.print_exc()

print("\n" + "="*80 + "\n")
