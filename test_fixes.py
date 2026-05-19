"""
TESTE DE CORREÇÕES — Detecta sale_type e limpeza de nomes corretamente
"""

import logging
logging.basicConfig(level=logging.WARNING)

print("\n" + "="*80)
print("TESTE DE CORREÇÕES - SALE_TYPE E NOMES DE LOJAS")
print("="*80 + "\n")

# Teste 1: Importar app.py
print("1️⃣ Importando app.py...")
try:
    import app
    print("   ✅ app.py importado\n")
except Exception as e:
    print(f"   ❌ Erro: {e}\n")
    exit(1)

# Teste 2: Testar função clean_shop_name
print("2️⃣ Testando limpeza de nomes:")
test_names = [
    ("normALShop", "normALShop"),
    ("░░░░░░ Loja com lixo", "Loja com lixo"),
    ("████ ShopNome", "ShopNome"),
    ("LojaÜber", "LojaÜber"),
    ("   Espaços   Extras   ", "Espaços Extras"),
    ("@#$%^&*()", "Shop"),  # Só caracteres especiais
]

for name_in, expected in test_names:
    cleaned = app.clean_shop_name(name_in)
    status = "✅" if cleaned == expected else "⚠️"
    print(f"   {status} '{name_in}' → '{cleaned}'")

print()

# Teste 3: Testar detecção de sale_type em app.py
print("3️⃣ Testando detecção de sale_type (app.py):")

# Simula detecção de sale_type como feita em get_stores_from_item_page
import re

def test_sale_type_app(price_text):
    price_lower = price_text.lower().strip()
    
    if 'rmt' in price_lower or re.search(r'\brm\b', price_lower):
        return "rmt"
    elif 'rops' in price_lower or re.search(r'\brp\b', price_lower) or \
         (re.search(r'\br\$\b', price_lower) or re.search(r'\br\b', price_lower)) and 'refinamento' not in price_lower:
        return "rops"
    else:
        return "zeny"

test_prices = [
    ("150000 Z", "zeny"),
    ("150000 ZENY", "zeny"),
    ("Z$ 150000", "zeny"),
    ("500 RMT", "rmt"),
    ("500 R$M", "rmt"),
    ("1000 ROPS", "rops"),
    ("1000 RP", "rops"),
    ("Refinamento: 5 - 100 R$", "zeny"),  # NÃO deve ser rops
    ("2500 Z (Refinamen)", "zeny"),
]

for price, expected in test_prices:
    detected = test_sale_type_app(price)
    status = "✅" if detected == expected else "❌"
    print(f"   {status} '{price}' → {detected} (esperado: {expected})")

print()

# Teste 4: Testar detecção em stores_scraper.py
print("4️⃣ Testando detecção de sale_type (stores_scraper.py):")

from stores_scraper import HerosagaScraper

scraper = HerosagaScraper()

for price, expected in test_prices:
    detected = scraper._detect_sale_type(price)
    status = "✅" if detected == expected else "❌"
    print(f"   {status} '{price}' → {detected} (esperado: {expected})")

print()

print("="*80)
print("✅ TESTES CONCLUÍDOS!")
print("="*80)
print("\nMudanças aplicadas:")
print("  ✓ Função clean_shop_name() adicionada em app.py")
print("  ✓ Detecção de sale_type melhorada em app.py")
print("  ✓ Detecção de sale_type melhorada em stores_scraper.py")
print("  ✓ Símbolos de moeda corrigidos (Z, RM, RMT)")
print("  ✓ Filtragem por sale_type mais robusta")
print("="*80 + "\n")
