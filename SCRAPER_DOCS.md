# BeautifulSoup Store Scraper — Documentação

## 📋 O que é?

Material novo para **web scraping robusto** de lojas online usando **BeautifulSoup4** e **cloudscraper**.

- ✅ **Modular**: Fácil adicionar novas lojas
- ✅ **Reutilizável**: Classes base abstratas e padrões
- ✅ **Anti-bot**: Usa cloudscraper para contornar proteções
- ✅ **Logging detalhado**: Para debug e monitoring
- ✅ **Type hints**: Melhor suporte IDE

## 📦 Arquivos Criados

### `stores_scraper.py`
Módulo principal com:
- `StoreScraper` - Classe base abstrata
- `HerosagaScraper` - Scraper do Herosaga  
- `MercadoLivreGameScraper` - Scraper do Mercado Livre (beta)
- `StoreScraperRegistry` - Registro central

### `scraping_examples.py`
6 exemplos completos:
1. Busca simples
2. Detalhes de item
3. Usar scraper direto
4. Estatísticas de preço
5. Adicionar nova loja
6. Integração com app.py

## 🚀 Quick Start

### Uso Básico

```python
from stores_scraper import search_item_all_stores

# Busca um item em todas as lojas configuradas
results = search_item_all_stores("Espada")

# results = {
#     "herosaga": [
#         {
#             "store": "Herosaga",
#             "item_name": "Espada",
#             "char_name": "Vendedor1",
#             "price": 1500.0,
#             "quantity": 5,
#             "refinement": 5,
#             "cards": 2,
#             "sale_type": "zeny",
#             "timestamp": "2024-04-27T10:30:00"
#         },
#         ...
#     ]
# }

# Exibe os 3 mais baratos
for item in results["herosaga"][:3]:
    print(f"{item['char_name']}: {item['price']} {item['sale_type']}")
```

### Obter Detalhes de Um Item

```python
from stores_scraper import get_herosaga_item_stores

details = get_herosaga_item_stores(item_id=1001)

# details = {
#     "item_id": "1001",
#     "stores": [
#         {
#             "char_name": "Shop1",
#             "price": 2000,
#             "refinement": 5,
#             "cards": 3,
#             "quantity": 10,
#             "sale_type": "zeny"
#         },
#         ...
#     ],
#     "total_stores": 15,
#     "fetched_at": "2024-04-27T10:30:00"
# }

print(f"Item tem {details['total_stores']} lojas vendendo")
```

## 🛠️ Adicionar Uma Nova Loja

### Passo 1: Criar Classe

```python
from stores_scraper import StoreScraper
from typing import List, Dict

class MinhaLojaComScraper(StoreScraper):
    """Scraper customizado para minha loja."""
    
    BASE_URL = "https://example.com"
    
    def __init__(self):
        super().__init__("Minha Loja")
    
    def search_item(self, item_name: str) -> List[Dict]:
        """Busca item na loja e retorna ofertas."""
        try:
            # 1. Monta URL de busca
            url = f"{self.BASE_URL}/search?q={item_name}"
            
            # 2. Faz requisição segura
            html = self._fetch_url(url)
            if not html:
                return []
            
            # 3. Parse do HTML
            soup = self._parse_html(html)
            if not soup:
                return []
            
            # 4. Extrai dados
            results = []
            for item_elem in soup.find_all('div', class_='product-item'):
                try:
                    name = item_elem.find('h3').get_text(strip=True)
                    price_text = item_elem.find('span', class_='price').get_text(strip=True)
                    price = self._extract_price(price_text)
                    
                    results.append({
                        "store": self.store_name,
                        "item_name": item_name,
                        "title": name,
                        "price": price,
                        "currency": "BRL",
                        "timestamp": datetime.now().isoformat()
                    })
                except:
                    continue
            
            return results
            
        except Exception as e:
            self.logger.error(f"Erro na busca: {str(e)}")
            return []
    
    def get_item_details(self, item_id: str) -> Dict:
        """Obtém detalhes completos de um item."""
        # Implementar conforme necessário
        return {"error": "Não implementado"}
```

### Passo 2: Registrar

```python
from stores_scraper import scraper_registry

scraper = MinhaLojaComScraper()
scraper_registry.add_scraper("minha_loja", scraper)

# Agora funciona:
results = search_item_all_stores("Espada")
# results incluirá dados de "minha_loja"
```

## 📊 Estrutura de Dados Padronizada

Todos os scrapers retornam dados neste formato:

```python
{
    "store": str,          # Nome da loja
    "item_name": str,      # Nome do item buscado
    "char_name": str,      # Nome do vendedor (Herosaga)
    "price": float,        # Preço em número
    "quantity": int,       # Quantidade disponível
    "refinement": int,     # Nível de refinamento (Herosaga)
    "cards": int,          # Cartas encaixadas (Herosaga)
    "sale_type": str,      # Tipo de moeda: "zeny", "rops", "rmt"
    "timestamp": str,      # ISO timestamp da coleta
}
```

## 🔧 Métodos Herdados (Classe Base)

Quando você herda de `StoreScraper`, tem acesso a:

```python
class MeuScraper(StoreScraper):
    
    def _fetch_url(self, url: str, timeout: int = 15) -> Optional[str]:
        """Faz requisição GET com headers de navegador real."""
        # Automático! Retorna HTML ou None
        pass
    
    def _parse_html(self, html: str) -> Optional[BeautifulSoup]:
        """Faz parse seguro de HTML."""
        # Automático! Retorna BeautifulSoup ou None
        pass
    
    def _extract_price(self, price_text: str) -> float:
        """Extrai número de texto de preço."""
        # Ex: "R$ 1.500,00" -> 1500.0
        pass
```

## 🐛 Debug e Logging

Os scrapers usam logging automático. Configure assim:

```python
import logging

# Verbose logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Agora vê tudo que está acontecendo
results = search_item_all_stores("Espada")
```

Outputs:
```
2024-04-27 10:30:00 - StoreScraper.Herosaga - INFO - 🔍 Buscando 'Espada' no Herosaga...
2024-04-27 10:30:01 - StoreScraper.Herosaga - DEBUG - Buscando: https://herosaga.com.br/?module=vending&action=search&item_search=Espada
2024-04-27 10:30:02 - StoreScraper.Herosaga - DEBUG - ✓ Status 200 - 5234 bytes
2024-04-27 10:30:02 - StoreScraper.Herosaga - INFO - ✓ Encontradas 42 lojas
...
```

## 📈 Casos de Uso

### 1. Monitorar Preço de Item Específico

```python
from datetime import datetime, timedelta
import time

item_name = "Espada Lendária"
price_history = []

for i in range(24):  # Coleta 24 vezes
    results = search_item_all_stores(item_name)
    herosaga_items = results.get("herosaga", [])
    
    if herosaga_items:
        min_price = min(item["price"] for item in herosaga_items)
        price_history.append({
            "timestamp": datetime.now().isoformat(),
            "min_price": min_price,
            "num_sellers": len(herosaga_items)
        })
    
    print(f"[{datetime.now().strftime('%H:%M')}] Preço mínimo: {min_price}")
    
    time.sleep(3600)  # Aguarda 1 hora

print(f"\n📊 Histórico de 24 horas:")
for entry in price_history:
    print(f"  {entry['timestamp']} - {entry['min_price']} ZENY ({entry['num_sellers']} lojas)")
```

### 2. Comparar Preços Entre Lojas

```python
results = search_item_all_stores("Espada")

print("💰 Comparação de Preços:\n")

for store_name, items in results.items():
    if items:
        prices = [item["price"] for item in items]
        print(f"{store_name.upper()}:")
        print(f"  Min:  {min(prices):,.0f}")
        print(f"  Max:  {max(prices):,.0f}")
        print(f"  Avg:  {sum(prices)/len(prices):,.0f}")
        print()
```

### 3. Alertar Preço Baixo

```python
def alertar_se_preco_baixo(item_name: str, max_price: float):
    results = search_item_all_stores(item_name)
    
    for store_name, items in results.items():
        for item in items:
            if item["price"] <= max_price:
                print(f"🚨 ALERTA! {item['char_name']} tem "
                      f"{item['item_name']} por apenas {item['price']} ZENY!")

# Uso:
alertar_se_preco_baixo("Espada", max_price=1000)
```

## ⚙️ Configuração Avançada

### Headers Customizados

```python
# Em stores_scraper.py, modifique HEADERS:

HEADERS = {
    "User-Agent": "Seu User Agent customizado",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    # ... mais headers
}
```

### Timeout e Retry

```python
from stores_scraper import HerosagaScraper
import time

scraper = HerosagaScraper()

# Com retry automático
max_attempts = 3
for attempt in range(max_attempts):
    try:
        results = scraper.search_item("Espada")
        if results:
            break
    except Exception as e:
        print(f"Tentativa {attempt + 1} falhou: {e}")
        time.sleep(2 ** attempt)  # Backoff exponencial
```

## 🎯 Troubleshooting

| Problema | Solução |
|----------|---------|
| 403 Forbidden | Headers insuficientes. Cloudscraper contorna isso. |
| Parse falha | Estrutura HTML mudou. Capture o HTML (debug) e ajuste seletores. |
| Timeout | Aumente timeout: `_fetch_url(url, timeout=30)` |
| Muitas requisições | Adicione delay entre requisições. |

## 📝 Integrar com app.py Existente

Substitua as funções antigas:

```python
# Antigo:
def api_search(name: str):
    ...

def api_vending_search(name: str):
    ...

# Novo:
from stores_scraper import search_item_all_stores

def search_stores_new(name: str):
    results = search_item_all_stores(name)
    return results.get("herosaga", [])
```

## 📚 Referências

- **BeautifulSoup**: https://www.crummy.com/software/BeautifulSoup/
- **Cloudscraper**: https://github.com/VeNoMouS/cloudscraper
- **Requests**: https://requests.readthedocs.io/

## ✅ Checklist para Nova Loja

- [ ] Criar classe herdando `StoreScraper`
- [ ] Implementar `search_item()`
- [ ] Implementar `get_item_details()`
- [ ] Testar com alguns itens
- [ ] Registrar em `scraper_registry`
- [ ] Adicionar testes em `scraping_examples.py`
- [ ] Documentar campos de resposta

---

**Desenvolvido com ❤️ para Herosaga Monitor**
