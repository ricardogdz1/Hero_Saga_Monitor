from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def item_emoji(name: str) -> str:
    if not name:
        return "📦"
    n = name.lower()
    if any(x in n for x in ["espada", "sword", "sabre"]):
        return "⚔"
    if "mana" in n:
        return "💜"
    if any(x in n for x in ["poção", "pocao", "elixir"]):
        return "🧪"
    if "escudo" in n:
        return "🛡"
    if "arco" in n:
        return "🏹"
    if any(x in n for x in ["cajado", "staff", "varinha"]):
        return "🪄"
    if any(x in n for x in ["elmo", "capacete", "helm"]):
        return "🪖"
    # "carta" antes de "ring": nomes de mobs como Poring/Angeling contêm "ring"
    if "carta" in n:
        return "🃏"
    if any(x in n for x in ["anel", "ring"]):
        return "💍"
    if any(x in n for x in ["bota", "sapato", "boot"]):
        return "👢"
    return "🗡"


def fmt_price(p) -> str:
    try:
        return f"{int(p):,}".replace(",", ".")
    except Exception:
        return str(p)


def fmt_price_stores(p) -> str:
    """
    Preço para lojas online: mantém todas as casas decimais (não trunca como int).
    Inteiros: separador de milhar em ponto (igual fmt_price). Com decimais: ponto
    como separador decimal, sem agrupar milhares (evita ambiguidade com vários pontos).
    """
    if p is None:
        return "0"
    try:
        raw = str(p).strip().replace(",", ".")
        d = Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        try:
            d = Decimal(str(float(p)))
        except (InvalidOperation, ValueError, TypeError):
            return str(p)
    if d == d.to_integral_value():
        return fmt_price(int(d))
    s = format(d, "f")
    if "." in s:
        a, b = s.split(".", 1)
        b = b.rstrip("0")
        if not b:
            try:
                return fmt_price(int(a))
            except (ValueError, TypeError):
                return a
        return f"{a}.{b}"
    return s


def safe_get(d: dict, key: str, default: str = "N/A") -> str:
    value = d.get(key, default)
    if value is None:
        return default
    return str(value)


def clean_shop_name(name: str) -> str:
    """
    Limpa nome da loja removendo caracteres especiais, controle e espaços extras.
    Mantém apenas letras, números, espaços e caracteres latinos.
    """
    if not name:
        return "Shop"
    cleaned = re.sub(r"[^\w\s\-\.\(\)]", "", name, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or len(cleaned) < 2:
        return "Shop"
    return cleaned

