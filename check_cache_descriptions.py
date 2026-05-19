#!/usr/bin/env python3
"""
Script para verificar quais itens no cache JSON estão sem descrição.
"""

import sys
import os
import json
import io

# Fix encoding para Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

data_file = os.path.expanduser("~/herosaga_monitor_data.json")

print(f"\nVerificando cache em: {data_file}\n")

if not os.path.exists(data_file):
    print("Arquivo de cache não encontrado!")
    sys.exit(1)

try:
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    items = data.get("items", {})
    
    print(f"Total de itens no cache: {len(items)}\n")
    print("ITENS SEM DESCRIÇÃO:")
    print("=" * 80)
    
    without_desc = []
    for item_id, item in items.items():
        desc = item.get("item_description", "").strip()
        if not desc:
            without_desc.append({
                "id": item_id,
                "name": item.get("name"),
                "has_icon": bool(item.get("item_icon_url")),
            })
    
    if without_desc:
        print(f"Encontrados {len(without_desc)} itens sem descrição:\n")
        for item in without_desc[:20]:  # Mostra os primeiros 20
            print(f"  ID {item['id']}: {item['name']}")
            print(f"    Tem ícone: {'Sim' if item['has_icon'] else 'Não'}")
    else:
        print("TODOS os itens têm descrição!")
    
    # Estatísticas
    print(f"\n{'=' * 80}")
    print("ESTATÍSTICAS:")
    print(f"{'=' * 80}")
    print(f"Itens COM descrição: {len(items) - len(without_desc)}")
    print(f"Itens SEM descrição: {len(without_desc)}")
    if len(items) > 0:
        print(f"Taxa: {((len(items) - len(without_desc)) / len(items) * 100):.1f}% com descrição")
    else:
        print("(Nenhum item no cache ainda)")
    
    
except Exception as e:
    print(f"Erro ao ler cache: {str(e)}")
    import traceback
    traceback.print_exc()
