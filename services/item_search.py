"""
Caso de uso: buscar itens por nome no Hero Saga.
"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from adapters.herosaga_client import HerosagaClient


class ItemSearchService:
    def __init__(self, client: "HerosagaClient"):
        self._client = client

    def search_by_name(self, query: str) -> List[dict]:
        q = (query or "").strip()
        if not q:
            return []
        return self._client.search_items_by_name(q)

    @staticmethod
    def parse_direct_item_id(query: str) -> Optional[int]:
        """
        Se a pesquisa for só ID (ou ``@ws <id>`` / ``ws <id>``), devolve o ID.
        Caso contrário ``None`` (fluxo de lista de resultados).
        """
        qid = (query or "").strip()
        low = qid.lower()
        if low.startswith("@ws"):
            qid = qid[3:].strip()
        elif low.startswith("ws") and len(qid) > 2 and qid[2].isspace():
            qid = qid[2:].strip()
        if not qid.isdigit():
            return None
        try:
            iid = int(qid)
        except (ValueError, OverflowError):
            return None
        return iid if iid > 0 else None
