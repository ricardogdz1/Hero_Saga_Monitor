#!/usr/bin/env python3
"""
Script para forçar recarga de descrição de um item e comparar antes/depois.
"""

import sys
import os
import json
import io

# Fix encoding para Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

from stores_scraper import get_herosaga_item_stores

# Item ID para testar
test_id = 6755  # Mude se quiser testar outro

data_file = os.path.expanduser("~/herosaga_monitor_data.json")

print(f"\n{'='*80}")
print(f"Testando recarga de descrição para item ID: {test_id}")
print(f"{'='*80}\n")

# 1. Carrega dados em cache se existirem
cache_data = {}
cached_desc = "N/A"

if os.path.exists(data_file):
    with open(data_file, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    
    items = cache_data.get("items", {})
    item_key = str(test_id)
    
    if item_key in items:
        cached_desc = items[item_key].get("item_description", "").strip() or "(vazio)"
        print(f"DESCRIÇÃO EM CACHE:")
        print(f"  {cached_desc[:100]}...")
    else:
        print(f"Item {test_id} não encontrado em cache")

# 2. Recarrega do site
print(f"\nRECAREGANDO DO SITE...")
try:
    details = get_herosaga_item_stores(test_id)
    
    if details and "error" not in details:
        new_desc = details.get("item_description", "").strip() or "(vazio)"
        print(f"DESCRIÇÃO DO SITE:")
        print(f"  {new_desc[:100]}...")
        
        print(f"\nCOMPARAÇÃO:")
        print(f"  Cache  : {'✓ Tem descrição' if cached_desc != '(vazio)' and cached_desc != 'N/A' else '✗ SEM descrição'}")
        print(f"  Site   : {'✓ Tem descrição' if new_desc != '(vazio)' else '✗ SEM descrição'}")
        
        if cached_desc != new_desc:
            print(f"\n⚠️ DIVERGÊNCIA DETECTADA!")
            print(f"  Cache (antes): {cached_desc[:50]}")
            print(f"  Site (agora) : {new_desc[:50]}")
        else:
            print(f"\n✓ Descrições são iguais")
    else:
        print(f"Erro ao carregar do site: {details}")
        
except Exception as e:
    print(f"Erro: {str(e)}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*80}\n")
