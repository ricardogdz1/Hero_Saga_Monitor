#!/usr/bin/env python3
"""
Script de debug para diagnosticar por que descrições estão faltando.
Teste com um item específico para ver o HTML e verificar a extração.
"""

import sys
import os
import logging
import io

# Fix encoding para Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from stores_scraper import HerosagaScraper
from bs4 import BeautifulSoup
import cloudscraper

# Testa com um item ID
test_item_id = 6755  # Ou mude para outro ID

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

url = f"https://herosaga.com.br/?module=item&action=view&id={test_item_id}"
print(f"\n{'='*80}")
print(f"Testando extração de descrição para item ID: {test_item_id}")
print(f"URL: {url}")
print(f"{'='*80}\n")

try:
    response = scraper.get(url, headers=HEADERS, timeout=15)
    
    if response.status_code != 200:
        print(f"❌ Erro: Status {response.status_code}")
        sys.exit(1)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Salva HTML completo para inspeção
    html_file = os.path.expanduser("~/herosaga_debug_html.html")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(response.text)
    print(f"✓ HTML salvo em: {html_file}\n")
    
    # Tenta encontrar descrição
    print("=" * 80)
    print("BUSCANDO DESCRIÇÃO:")
    print("=" * 80)
    
    # Teste 1: Seletor principal
    desc_box = soup.select_one(".item-description-text")
    if desc_box:
        print(f"✓ Encontrado: .item-description-text")
        print(f"  HTML: {str(desc_box)[:200]}...")
        print(f"  Texto: {desc_box.get_text()[:100]}...")
    else:
        print(f"❌ NÃO encontrado: .item-description-text")
    
    # Teste 2: Seletores alternativos
    alt_selectors = [
        ".description-text",
        ".item-description",
        "[class*='description']",
        "div.description",
    ]
    
    for selector in alt_selectors:
        result = soup.select_one(selector)
        if result:
            print(f"✓ Encontrado por: {selector}")
            print(f"  Classe: {result.get('class')}")
            print(f"  Texto: {result.get_text()[:100]}...")
    
    # Teste 3: Procura por divs com "description" na classe
    print(f"\n{'='*80}")
    print("DIVS COM 'DESCRIPTION' NA CLASSE:")
    print(f"{'='*80}")
    for i, div in enumerate(soup.find_all("div")):
        cls = div.get("class", [])
        if isinstance(cls, list):
            cls_str = " ".join(cls)
        else:
            cls_str = str(cls)
        
        if "description" in cls_str.lower():
            print(f"\n{i}. Class: {cls_str}")
            text = div.get_text(strip=True)[:100]
            print(f"   Texto: {text}")
    
    # Teste 4: Usa o scraper para extrair
    print(f"\n{'='*80}")
    print("RESULTADO DO SCRAPER:")
    print(f"{'='*80}")
    
    scraper_obj = HerosagaScraper()
    card = scraper_obj._parse_item_card(soup)
    
    print(f"\nCard extraído:")
    print(f"  Título: {card.get('item_card_title')}")
    print(f"  Descrição ({len(card.get('item_description', ''))} chars): {card.get('item_description', '')[:150]}")
    print(f"  Peso: {card.get('item_weight')}")
    print(f"  Ícone: {card.get('item_icon_url')}")
    
except Exception as e:
    print(f"❌ Erro: {str(e)}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*80}\n")
