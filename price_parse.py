"""
Parse de preços em texto vindo do site (PT-BR, US/EN com vírgula de milhar, etc.).
Evita confundir milhar com decimal (ex.: 350.000 zeny; 225,000 Hero Points).
"""

import re


def parse_price_cell(price_text: str) -> float:
    if not price_text or not str(price_text).strip():
        return 0.0
    s = re.sub(r"[^\d.,]", "", str(price_text).strip())
    if not s:
        return 0.0

    last_comma = s.rfind(",")
    last_dot = s.rfind(".")

    # Ponto e vírgula: o separador mais à direita é o decimal
    if "," in s and "." in s:
        if last_dot > last_comma:
            # US/EN: 1,234,567.89
            try:
                return float(s.replace(",", ""))
            except ValueError:
                return 0.0
        # BR: 1.234.567,89 ou 1234,56
        left, right = s.rsplit(",", 1)
        if not re.fullmatch(r"\d+", right):
            return 0.0
        left_digits = left.replace(".", "")
        if not re.fullmatch(r"\d*", left_digits):
            return 0.0
        try:
            return float((left_digits or "0") + "." + right)
        except ValueError:
            return 0.0

    # Só vírgulas
    if "," in s and "." not in s:
        # Milhar estilo US: 225,000 ou 1,234,567 (blocos ,###)
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
            try:
                return float(s.replace(",", ""))
            except ValueError:
                return 0.0
        # Decimal BR: 12,5 ou 12,99
        left, right = s.rsplit(",", 1)
        if not re.fullmatch(r"\d+", right) or not re.fullmatch(r"\d+", left):
            return 0.0
        try:
            return float(left + "." + right)
        except ValueError:
            return 0.0

    # Só pontos (ou sem separadores)
    parts = s.split(".")
    if len(parts) == 1:
        try:
            return float(parts[0])
        except ValueError:
            return 0.0

    last = parts[-1]
    if not all(p.isdigit() for p in parts):
        try:
            return float(s)
        except ValueError:
            return 0.0

    if len(last) <= 2:
        try:
            return float(s)
        except ValueError:
            return 0.0

    if len(last) == 3 and 1 <= len(parts[0]) <= 3:
        if len(parts) == 2 or all(len(p) == 3 for p in parts[1:-1]):
            try:
                return float("".join(parts))
            except ValueError:
                return 0.0

    try:
        return float(s)
    except ValueError:
        return 0.0


def coerce_price(value) -> float:
    """Converte preço de API (número ou string formatada) para float."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return parse_price_cell(str(value))
