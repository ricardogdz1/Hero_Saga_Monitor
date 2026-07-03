"""
Cliente para a API JSON do Divine Pride (Database API).

Documentação: https://www.divine-pride.net/api

Antes de usar, registe-se no fórum e obtenha uma chave no perfil.
Nunca commite chaves no repositório: use Configurações da app ou a variável
de ambiente DIVINE_PRIDE_API_KEY.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.divine-pride.net"

# API / listagem HTML Monster: inglês (Accept-Language, cf. documentação Divine Pride).
DEFAULT_MONSTER_ACCEPT_LANGUAGE = "en-US,en;q=0.9"

__all__ = [
    "BASE_URL",
    "resolve_api_key",
    "fetch_achievement",
    "fetch_buff",
    "fetch_experience",
    "fetch_item",
    "fetch_map",
    "fetch_monster",
    "fetch_npc_identity",
    "fetch_quest",
    "fetch_skill",
    "fetch_title",
    "database_get",
    "search_items_by_name",
    "search_items_html",
    "parse_item_rows_from_search_html",
    "DEFAULT_MONSTER_ACCEPT_LANGUAGE",
    "DEFAULT_ITEM_SEARCH_LANG",
]

ITEM_SEARCH_URL = f"{BASE_URL}/database/item"
DEFAULT_ITEM_SEARCH_LANG = "pt-BR,pt;q=0.9,en;q=0.8"


def resolve_api_key(explicit: Optional[str] = None) -> str:
    """Ordem: argumento > variável de ambiente DIVINE_PRIDE_API_KEY."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return (os.environ.get("DIVINE_PRIDE_API_KEY") or "").strip()


def _require_key(api_key: Optional[str]) -> str:
    key = resolve_api_key(api_key)
    if not key:
        raise ValueError(
            "Chave Divine Pride em falta. Defina em Configurações ou DIVINE_PRIDE_API_KEY."
        )
    return key


def _database_request(
    resource_path: str,
    *,
    api_key: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    accept_language: Optional[str] = None,
    timeout: float = 30.0,
) -> Any:
    """
    GET https://www.divine-pride.net/api/database/{resource_path}?apiKey=...

    *resource_path* sem barra inicial (ex. ``Item/5017``, ``Map/prt_fild08``).
    """
    key = _require_key(api_key)
    url = f"{BASE_URL}/api/database/{resource_path.lstrip('/')}"
    params: Dict[str, str] = {"apiKey": key}
    if extra_params:
        for k, v in extra_params.items():
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            params[str(k)] = str(v).strip()
    headers: Dict[str, str] = {}
    if accept_language and str(accept_language).strip():
        headers["Accept-Language"] = str(accept_language).strip()
    try:
        r = requests.get(
            url,
            params=params,
            headers=headers or None,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.warning("Divine Pride GET %s: %s", resource_path, e)
        raise


def fetch_achievement(
    achievement_id: int,
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """GET /api/database/Achievement/:id"""
    data = _database_request(
        f"Achievement/{int(achievement_id)}",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Achievement: esperado object JSON")
    return data


def fetch_buff(
    buff_id: int,
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """GET /api/database/Buff/:id"""
    data = _database_request(
        f"Buff/{int(buff_id)}",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Buff: esperado object JSON")
    return data


def fetch_experience(
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """GET /api/database/Experience (tabelas de EXP, etc.)"""
    data = _database_request(
        "Experience",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Experience: esperado object JSON")
    return data


def fetch_item(
    item_id: int,
    *,
    api_key: Optional[str] = None,
    server: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """
    GET /api/database/Item/:id?apiKey=...&server=...

    *server* opcional: aRO, bRO, iRO, etc. (ver documentação).
    *accept_language*: ``None`` envia ``DEFAULT_MONSTER_ACCEPT_LANGUAGE`` (inglês).
    """
    if accept_language is None:
        lang: Optional[str] = DEFAULT_MONSTER_ACCEPT_LANGUAGE
    else:
        lang = str(accept_language).strip() or None
    extra: Dict[str, Any] = {}
    if server and str(server).strip():
        extra["server"] = str(server).strip()
    data = _database_request(
        f"Item/{int(item_id)}",
        api_key=api_key,
        extra_params=extra or None,
        accept_language=lang,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Item: esperado object JSON")
    return data


def fetch_map(
    map_id: str,
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 45.0,
) -> Dict[str, Any]:
    """
    GET /api/database/Map/:id — *map_id* é o identificador de mapa (ex. ``prt_fild08``).
    """
    mid = str(map_id).strip()
    if not mid:
        raise ValueError("map_id vazio")
    safe = quote(mid, safe="._-")
    data = _database_request(
        f"Map/{safe}",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Map: esperado object JSON")
    return data


def fetch_monster(
    monster_id: int,
    *,
    api_key: Optional[str] = None,
    server: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    GET /api/database/Monster/:id

    *accept_language*: ``None`` envia ``DEFAULT_MONSTER_ACCEPT_LANGUAGE`` (inglês).
    String vazia omite o cabeçalho (comportamento do servidor).
    *server*: parâmetro ``server`` na query se definido e não vazio (ex. ``bRO``).
    """
    if accept_language is None:
        lang: Optional[str] = DEFAULT_MONSTER_ACCEPT_LANGUAGE
    else:
        lang = str(accept_language).strip() or None

    if server is None:
        srv: Optional[str] = None
    else:
        srv = str(server).strip() or None
    extra: Optional[Dict[str, Any]] = {"server": srv} if srv else None

    data = _database_request(
        f"Monster/{int(monster_id)}",
        api_key=api_key,
        extra_params=extra,
        accept_language=lang,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Monster: esperado object JSON")
    return data


def fetch_npc_identity(
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    GET /api/database/NpcIdentity — mapa nome interno de NPC/monstro → id.
    A resposta é um único object JSON com muitas chaves (ex. ``PORING``: 1002).
    """
    data = _database_request(
        "NpcIdentity",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta NpcIdentity: esperado object JSON")
    return data


def fetch_quest(
    quest_id: int,
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """GET /api/database/Quest/:id"""
    data = _database_request(
        f"Quest/{int(quest_id)}",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Quest: esperado object JSON")
    return data


def fetch_skill(
    skill_id: int,
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """GET /api/database/Skill/:id"""
    data = _database_request(
        f"Skill/{int(skill_id)}",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Skill: esperado object JSON")
    return data


def fetch_title(
    title_id: int,
    *,
    api_key: Optional[str] = None,
    accept_language: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """GET /api/database/Title/:id"""
    data = _database_request(
        f"Title/{int(title_id)}",
        api_key=api_key,
        accept_language=accept_language,
        timeout=timeout,
    )
    if not isinstance(data, dict):
        raise ValueError("Resposta Title: esperado object JSON")
    return data


def parse_item_rows_from_search_html(html: str) -> List[Dict[str, Any]]:
    """Extrai (id, nome?) das linhas da tabela de pesquisa de itens no site DP."""
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table")
    if not table:
        return []
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for tr in table.find_all("tr")[1:]:
        a = tr.find("a", href=re.compile(r"/database/item/\d+"))
        if not a:
            continue
        mm = re.search(r"/database/item/(\d+)", str(a.get("href") or ""))
        if not mm:
            continue
        try:
            iid = int(mm.group(1))
        except (TypeError, ValueError):
            continue
        if iid in seen or iid <= 0:
            continue
        seen.add(iid)
        tds = tr.find_all("td")
        name = (tds[0].get_text(" ", strip=True) if tds else "") or (a.get_text(" ", strip=True) or "")
        if name.startswith("[PH]"):
            name = ""
        out.append({"id": iid, "name": name})
    return out


def _dp_item_servers(server: Optional[str]) -> tuple[str, ...]:
    """Hero Saga BR → tenta bRO antes do servidor configurado."""
    out: list[str] = []
    for s in ("bRO", str(server or "").strip(), "iRO"):
        if s and s not in out:
            out.append(s)
    return tuple(out)


def _fetch_item_display_name(
    item_id: int,
    *,
    api_key: str,
    servers: tuple[str, ...],
    accept_language: Optional[str],
    timeout: float,
) -> str:
    for srv in servers:
        try:
            data = fetch_item(
                int(item_id),
                api_key=api_key,
                server=srv,
                accept_language=accept_language,
                timeout=timeout,
            )
        except Exception as ex:  # noqa: BLE001
            logger.debug("Divine Pride item id=%s server=%s: %s", item_id, srv, ex)
            continue
        name = _name_from_item_api(data, item_id)
        if name:
            return name
    return ""


def search_items_html(
    query: str,
    *,
    server: Optional[str] = "bRO",
    limit: int = 40,
    accept_language: Optional[str] = None,
    timeout: float = 25.0,
) -> List[Dict[str, Any]]:
    """
    Pesquisa itens por nome no site Divine Pride (HTML).

    O formulário de itens usa o campo ``Name``; ``find=Search`` submete a pesquisa.
    """
    q = str(query or "").strip()
    if not q:
        return []
    params: Dict[str, str] = {"Name": q, "find": "Search"}
    srv = str(server or "").strip()
    if srv:
        params["server"] = srv
    lang = str(accept_language or DEFAULT_ITEM_SEARCH_LANG).strip() or DEFAULT_ITEM_SEARCH_LANG
    try:
        r = requests.get(
            ITEM_SEARCH_URL,
            params=params,
            headers={"Accept-Language": lang},
            timeout=timeout,
        )
        r.raise_for_status()
    except requests.RequestException as ex:
        logger.warning("Divine Pride item search Name=%r: %s", q, ex)
        return []
    rows = parse_item_rows_from_search_html(r.text)
    cap = max(1, int(limit or 40))
    return rows[:cap]


def _name_from_item_api(data: dict, item_id: int) -> str:
    for key in ("name", "Name", "unidentifiedDisplayName", "identifiedDisplayName"):
        v = data.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s and not s.startswith("[PH]"):
            return s
    return ""


def search_items_by_name(
    query: str,
    *,
    api_key: Optional[str] = None,
    server: Optional[str] = "bRO",
    accept_language: Optional[str] = "pt-BR,pt;q=0.9",
    html_limit: int = 46,
    timeout: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Busca itens por nome: pesquisa HTML no site + nomes via API ``Item/:id``.

    A API oficial não expõe pesquisa por nome; os IDs vêm da tabela HTML e cada
    candidato é validado/enriquecido com ``fetch_item``. Devolve todos os
    candidatos nomeados (até *html_limit*) para o caller escolher o melhor match.
    """
    key = resolve_api_key(api_key)
    if not key:
        return []

    html_rows = search_items_html(
        query,
        server="bRO",
        limit=html_limit,
        accept_language=accept_language or DEFAULT_ITEM_SEARCH_LANG,
        timeout=timeout,
    )
    if not html_rows:
        return []

    servers = _dp_item_servers(server)
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for row in html_rows:
        try:
            iid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if iid in seen or iid <= 0:
            continue
        seen.add(iid)

        name = str(row.get("name") or "").strip()
        if not name:
            name = _fetch_item_display_name(
                iid,
                api_key=key,
                servers=servers,
                accept_language=accept_language,
                timeout=timeout,
            )
        if not name:
            continue
        out.append({"id": iid, "name": name})
    return out


def database_get(
    resource_path: str,
    *,
    api_key: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    accept_language: Optional[str] = None,
    timeout: float = 30.0,
) -> Any:
    """
    Chamada genérica ``GET /api/database/{resource_path}`` para endpoints futuros
    ou parâmetros não expostos nas funções acima.

    Ex.: ``database_get("Item/5017", extra_params={"server": "iRO"})``
    """
    return _database_request(
        resource_path,
        api_key=api_key,
        extra_params=extra_params,
        accept_language=accept_language,
        timeout=timeout,
    )
