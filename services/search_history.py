"""Histórico de pesquisas do utilizador."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def append_search(data: Dict[str, Any], query: str, count: int, *, max_entries: int = 30) -> None:
    if "searches" not in data or not isinstance(data["searches"], list):
        data["searches"] = []
    data["searches"].insert(
        0,
        {"q": query, "count": count, "ts": datetime.now().isoformat()},
    )
    data["searches"] = data["searches"][:max_entries]
