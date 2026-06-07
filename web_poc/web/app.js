"use strict";

const CURRENCY = {
  zeny: { label: "Z", fmt: (v) => full(v) },
  rmt: { label: "RMT", fmt: (v) => money(v) },
  hero_points: { label: "HP", fmt: (v) => full(v) },
};
const ORDER = ["zeny", "rmt", "hero_points"];

let STATE = { categories: [], total: 0 };
let CURRENT = "home";
let HOME_FILTER = "";
let DRAG = null;
let UI_THEME = "dark";

// ── Tema e sidebar ─────────────────────────────────────────
function applyTheme(theme) {
  UI_THEME = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", UI_THEME);
}

function initSidebar() {
  const shell = document.getElementById("app-shell");
  const btn = document.getElementById("nav-toggle");
  if (!shell || !btn) return;
  const collapsed = localStorage.getItem("hs_sidebar_collapsed") === "1";
  shell.classList.toggle("nav-collapsed", collapsed);
  btn.title = collapsed ? "Expandir menu" : "Recolher menu";
  btn.setAttribute("aria-label", btn.title);
  btn.addEventListener("click", () => {
    const now = !shell.classList.contains("nav-collapsed");
    shell.classList.toggle("nav-collapsed", now);
    localStorage.setItem("hs_sidebar_collapsed", now ? "1" : "0");
    btn.title = now ? "Expandir menu" : "Recolher menu";
    btn.setAttribute("aria-label", btn.title);
  });
}

// ── Utilitários ────────────────────────────────────────────
function full(v) {
  return (Number(v) || 0).toLocaleString("pt-BR", { maximumFractionDigits: 20 });
}
function coin(v) {
  if (v == null || v === "") return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  return n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function money(v) {
  return (Number(v) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function priceChips(prices) {
  const keys = ORDER.filter((k) => prices && prices[k] != null);
  if (keys.length === 0) return '<span class="chip empty">sem preço</span>';
  return keys.map((k) => `<span class="chip ${k}">${CURRENCY[k].fmt(prices[k])} ${CURRENCY[k].label}</span>`).join("");
}
const head = () => document.getElementById("page-head");
const view = () => document.getElementById("view");

// ── Router ─────────────────────────────────────────────────
const ROUTES = {
  home: renderHome,
  build: renderBuild,
  mvp: renderMvp,
  loot: renderLoot,
  alerts: renderAlerts,
  config: renderConfig,
};

function go(route) {
  if (!ROUTES[route]) route = "home";
  CURRENT = route;
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === route));
  ROUTES[route]();
}

function rerenderCurrent() {
  if (ROUTES[CURRENT]) ROUTES[CURRENT]();
}

// ── Home ───────────────────────────────────────────────────
function renderHome() {
  head().innerHTML = `
    <div class="ph-title">
      <h2>Início</h2>
      <p>${STATE.categories.length} categorias · ${STATE.total} itens monitorados</p>
    </div>
    <div class="home-toolbar">
      <div class="home-toolbar-left">
        <div class="home-catalog-wrap" id="home-catalog-wrap">
          <div class="home-catalog-field search-accent">
            <svg viewBox="0 0 24 24" class="search-ic" aria-hidden="true"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
            <input id="home-catalog-input" type="text" placeholder="Digite o nome ou ID do item..." autocomplete="off" title="Buscar um novo item para monitorar" />
            <button type="button" id="home-catalog-btn" class="btn-catalog-go" title="Buscar no catálogo">
              <svg viewBox="0 0 24 24" class="search-ic" aria-hidden="true"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
              <span class="btn-catalog-label">Buscar novo item</span>
            </button>
          </div>
          <div id="home-catalog-msg" class="home-catalog-msg hidden" role="status"></div>
        </div>
      </div>
      <div class="home-toolbar-right">
        <div class="search">
          <svg viewBox="0 0 24 24" class="search-ic" aria-hidden="true"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          <input id="home-search" type="text" placeholder="Filtrar monitorados…" autocomplete="off" value="${escapeHtml(HOME_FILTER)}" title="Filtrar itens já monitorados" />
        </div>
        <button id="refresh" class="btn-refresh" title="Atualizar preços de todos os itens">
          <svg viewBox="0 0 24 24" class="refresh-ic"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v5h-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>Atualizar preços</span>
        </button>
        <div class="count-pill"><span id="count">${STATE.total}</span> itens</div>
      </div>
    </div>`;

  const board = el("div", "board");
  board.id = "board";
  STATE.categories.forEach((cat, i) => board.appendChild(columnNode(cat, i)));
  board.appendChild(addCategoryColumn());
  view().innerHTML = "";
  view().appendChild(board);

  document.getElementById("home-search").addEventListener("input", (e) => {
    HOME_FILTER = e.target.value;
    applyFilter(HOME_FILTER);
  });
  bindHomeCatalogSearch();
  document.getElementById("refresh").addEventListener("click", refreshPrices);
  if (HOME_FILTER) applyFilter(HOME_FILTER);
}

function applyFilter(q) {
  const term = (q || "").trim().toLowerCase();
  let visible = 0;
  document.querySelectorAll(".board .column").forEach((col) => {
    let shown = 0;
    col.querySelectorAll(".card").forEach((card) => {
      const match = !term || card.dataset.search.includes(term);
      card.classList.toggle("hidden", !match);
      if (match) shown++;
    });
    if (!col.classList.contains("add-col")) col.classList.toggle("hidden", term && shown === 0);
    visible += shown;
  });
  const c = document.getElementById("count");
  if (c) c.textContent = term ? visible : STATE.total;
}

function wsButton(id) {
  const ws = el("button", "ws-pill", "@ws");
  ws.title = "Copiar comando @ws para o jogo";
  ws.addEventListener("click", (e) => { e.stopPropagation(); copyWs(id); });
  return ws;
}

function alertButton(item) {
  const btn = el("button", "alert-btn", "🔔 Alerta");
  btn.title = "Criar alerta de preço";
  btn.addEventListener("click", (e) => { e.stopPropagation(); openAlertModal(item); });
  return btn;
}

function isCatalogIdSearch(query) {
  return /^\d+$/.test(String(query || "").trim());
}

// ── Monitorar (compartilhado: busca, drawer, loja do vendedor) ──
function getMonitoredIds() {
  const ids = new Set();
  for (const cat of STATE.categories || []) {
    for (const it of cat.items || []) {
      if (it.id != null) ids.add(Number(it.id));
    }
  }
  return ids;
}

function isItemMonitored(itemId) {
  const id = Number(itemId);
  return id > 0 && getMonitoredIds().has(id);
}

function defaultMonitorCategory() {
  const cats = (STATE.categories || []).map((c) => c.name);
  return cats[0] || "Gerais";
}

function applyMonitorButtonState(btn, monitored) {
  const compact = btn.classList.contains("result-add-compact");
  btn.disabled = !!monitored;
  btn.classList.toggle("done", !!monitored);
  if (compact) {
    btn.textContent = monitored ? "✓" : "+";
    btn.title = monitored ? "Item monitorado" : "Monitorar item";
  } else {
    btn.textContent = monitored ? "Monitorado" : "+ Monitorar";
    btn.title = monitored ? "Item monitorado" : "Adicionar aos monitorados";
  }
}

function syncMonitorButtonsForItem(itemId, monitored) {
  document.querySelectorAll(`[data-monitor-id="${String(itemId)}"]`).forEach((btn) => {
    applyMonitorButtonState(btn, monitored);
  });
}

async function addItemToMonitor(item, btn) {
  if (isItemMonitored(item.id)) {
    syncMonitorButtonsForItem(item.id, true);
    return;
  }
  btn.disabled = true;
  const compact = btn.classList.contains("result-add-compact");
  btn.textContent = compact ? "…" : "Adicionando…";
  try {
    const category = defaultMonitorCategory();
    let payload = { ...item, category };
    try {
      const d = await window.pywebview.api.get_item_detail(item.id);
      if (d?.ok) {
        payload = {
          ...payload,
          name: d.name || payload.name,
          item_icon_url: d.item_icon_url || payload.item_icon_url,
          prices: d.min_prices || payload.prices,
        };
      }
    } catch (_) { /* mantém payload original */ }
    const res = await window.pywebview.api.add_item(payload);
    if (res?.categories) STATE = res;
    syncMonitorButtonsForItem(item.id, isItemMonitored(item.id));
    updateNavBadge();
  } catch (_) {
    applyMonitorButtonState(btn, isItemMonitored(item.id));
    toast("Erro ao monitorar item.");
  }
}

function createMonitorButton(item, monitoredOverride) {
  const monitored = monitoredOverride ?? item.monitored ?? isItemMonitored(item.id);
  const btn = el("button", "result-add", monitored ? "Monitorado" : "+ Monitorar");
  btn.dataset.monitorId = String(item.id);
  applyMonitorButtonState(btn, !!monitored);
  if (!monitored) {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      addItemToMonitor(item, btn);
    });
  }
  return btn;
}

function createMonitorButtonCompact(item) {
  const monitored = item.monitored ?? isItemMonitored(item.id);
  const btn = el("button", "result-add result-add-compact", monitored ? "✓" : "+");
  btn.dataset.monitorId = String(item.id);
  applyMonitorButtonState(btn, !!monitored);
  if (!monitored) {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      addItemToMonitor(item, btn);
    });
  }
  return btn;
}

function cardNode(item, category) {
  const card = el("div", "card");
  card.dataset.search = (item.name + " " + (item.id ?? "")).toLowerCase();
  card.dataset.id = item.id;
  card.draggable = true;
  card.addEventListener("click", () => openDetail(item));
  card.addEventListener("dragstart", (e) => {
    DRAG = { id: item.id, from: category };
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", String(item.id)); } catch (_) {}
  });
  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    DRAG = null;
    clearDropIndicator();
  });

  const thumb = el("div", "thumb");
  if (item.icon) {
    const img = el("img");
    img.src = item.icon; img.alt = item.name; img.loading = "lazy";
    thumb.appendChild(img);
  }

  const info = el("div", "info");
  info.appendChild(el("div", "name", escapeHtml(item.name)));
  info.appendChild(el("div", "id", "ID " + (item.id ?? "—")));
  info.appendChild(el("div", "chips", priceChips(item.prices)));

  const remove = el("button", "card-x", "×");
  remove.title = "Remover dos monitorados";
  remove.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!(await modalConfirm(`Remover «${item.name}» dos monitorados?`))) return;
    applyHome(await window.pywebview.api.remove_item(item.id));
  });

  const ws = wsButton(item.id);
  ws.classList.add("ws-ear");

  card.appendChild(thumb);
  card.appendChild(info);
  card.appendChild(remove);
  card.appendChild(ws);
  return card;
}

function columnNode(cat, index) {
  const col = el("div", "column");
  col.style.animationDelay = index * 55 + "ms";
  col.dataset.cat = cat.name;

  const h = el("div", "col-head");
  const left = el("div", "col-head-l");
  left.appendChild(el("h2", null, escapeHtml(cat.name)));
  left.appendChild(el("span", "tag", String(cat.items.length)));
  h.appendChild(left);
  if (cat.name !== "Gerais") {
    const del = el("button", "col-x", "×");
    del.title = "Remover categoria (itens vão para Gerais)";
    del.addEventListener("click", async () => {
      if (!(await modalConfirm(`Remover a categoria «${cat.name}»?\nOs itens dela passam para «Gerais».`))) return;
      applyHome(await window.pywebview.api.remove_category(cat.name));
    });
    h.appendChild(del);
  }
  col.appendChild(h);

  const body = el("div", "col-body");
  if (cat.items.length === 0) body.appendChild(el("div", "col-empty", "Arraste itens para aqui"));
  else for (const it of cat.items) body.appendChild(cardNode(it, cat.name));

  body.addEventListener("dragover", (e) => {
    if (!DRAG) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    showDropIndicator(body, e.clientY);
  });
  body.addEventListener("drop", async (e) => {
    if (!DRAG) return;
    e.preventDefault();
    const index = dropIndexFor(body, e.clientY);
    const id = DRAG.id;
    clearDropIndicator();
    applyHome(await window.pywebview.api.place_item(id, cat.name, index));
  });

  col.appendChild(body);
  return col;
}

function cardsIn(body) { return [...body.querySelectorAll(".card:not(.dragging)")]; }
function dropIndexFor(body, y) {
  const cards = cardsIn(body);
  for (let i = 0; i < cards.length; i++) {
    const r = cards[i].getBoundingClientRect();
    if (y < r.top + r.height / 2) return i;
  }
  return cards.length;
}
function clearDropIndicator() { document.querySelectorAll(".drop-line").forEach((n) => n.remove()); }
function showDropIndicator(body, y) {
  clearDropIndicator();
  const line = el("div", "drop-line");
  const cards = cardsIn(body);
  const idx = dropIndexFor(body, y);
  if (idx >= cards.length) body.appendChild(line);
  else body.insertBefore(line, cards[idx]);
}

function addCategoryColumn() {
  const col = el("div", "column add-col");
  const btn = el("button", "add-cat-btn", '<span class="plus">+</span>Nova categoria');
  btn.addEventListener("click", async () => {
    const name = await modalPrompt("Nova categoria", "Nome da categoria");
    if (!name) return;
    applyHome(await window.pywebview.api.add_category(name));
  });
  col.appendChild(btn);
  return col;
}

function applyHome(data) {
  if (!data) return;
  STATE = data;
  updateNavBadge();
  rerenderCurrent();
}

async function refreshPrices() {
  const btn = document.getElementById("refresh");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  const label = btn.querySelector("span");
  const prev = label.textContent;
  label.textContent = "Atualizando…";
  try {
    const data = await window.pywebview.api.refresh_prices();
    STATE = data;
    rerenderCurrent();
    const b2 = document.getElementById("refresh");
    if (b2) {
      const l2 = b2.querySelector("span");
      l2.textContent = `${data.refreshed ?? 0} atualizados`;
      setTimeout(() => (l2.textContent = prev), 2200);
    }
  } catch (err) {
    label.textContent = "Erro ao atualizar";
    setTimeout(() => (label.textContent = prev), 2600);
  } finally {
    const b3 = document.getElementById("refresh");
    if (b3) { b3.disabled = false; b3.classList.remove("spinning"); }
  }
}

// ── Busca no catálogo ──────────────────────────────────────
async function catalogSearch(query) {
  const q = String(query || "").trim();
  if (!q) return { ok: true, query: q, items: [], empty: true };
  try {
    return await window.pywebview.api.search_items(q);
  } catch (err) {
    return { ok: false, error: String(err), query: q, items: [] };
  }
}

function pickCatalogSearchItem(items, query) {
  if (!items?.length) return null;
  const q = String(query || "").trim();
  const qLower = q.toLowerCase();
  if (/^\d+$/.test(q)) {
    const id = Number(q);
    const byId = items.find((it) => Number(it.id) === id);
    if (byId) return byId;
  }
  if (items.length === 1) return items[0];
  const exact = items.find((it) => String(it.name || "").toLowerCase() === qLower);
  return exact || items[0];
}

function clearHomeCatalogMsg() {
  const msg = document.getElementById("home-catalog-msg");
  if (!msg) return;
  msg.textContent = "";
  msg.className = "home-catalog-msg hidden";
}

function showHomeCatalogMsg(text, kind) {
  const msg = document.getElementById("home-catalog-msg");
  if (!msg) return;
  msg.textContent = text;
  msg.className = `home-catalog-msg${kind ? ` ${kind}` : ""}`;
}

function setHomeCatalogLoading(on) {
  const wrap = document.getElementById("home-catalog-wrap");
  const input = document.getElementById("home-catalog-input");
  const btn = document.getElementById("home-catalog-btn");
  if (!wrap || !input || !btn) return;
  wrap.classList.toggle("is-loading", on);
  input.disabled = on;
  btn.disabled = on;
  if (on) {
    btn.innerHTML = '<span class="spinner-inline" aria-hidden="true"></span><span class="btn-catalog-label">Buscando…</span>';
  } else {
    btn.innerHTML = `<svg viewBox="0 0 24 24" class="search-ic"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span class="btn-catalog-label">Buscar novo item</span>`;
  }
}

function bindHomeCatalogSearch() {
  const input = document.getElementById("home-catalog-input");
  const btn = document.getElementById("home-catalog-btn");
  if (!input || !btn) return;
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runHomeCatalogSearch();
    }
  });
  input.addEventListener("input", () => clearHomeCatalogMsg());
  btn.addEventListener("click", () => runHomeCatalogSearch());
}

async function runHomeCatalogSearch() {
  const input = document.getElementById("home-catalog-input");
  if (!input || input.disabled) return;
  const q = input.value.trim();
  clearHomeCatalogMsg();
  if (!q) {
    showHomeCatalogMsg("Digite o nome ou ID do item.", "hint");
    input.focus();
    return;
  }
  if (!isCatalogIdSearch(q)) {
    openItemSelectionWindow(q);
    return;
  }
  setHomeCatalogLoading(true);
  try {
    const res = await catalogSearch(q);
    if (!res.ok) {
      showHomeCatalogMsg(`Erro na busca: ${res.error || "tente novamente."}`, "err");
      return;
    }
    if (!res.items?.length) {
      showHomeCatalogMsg("Item não encontrado. Verifique o nome ou ID.", "err");
      return;
    }
    const item = pickCatalogSearchItem(res.items, q);
    openDetail(item);
  } catch (err) {
    showHomeCatalogMsg(`Erro: ${err}`, "err");
  } finally {
    setHomeCatalogLoading(false);
  }
}

function searchPickLayer() {
  return document.getElementById("search-pick-layer");
}

function searchPickStack() {
  return document.getElementById("search-pick-stack");
}

function syncSearchPickLayer() {
  const layer = searchPickLayer();
  const stack = searchPickStack();
  if (!layer || !stack) return;
  const open = stack.children.length > 0;
  layer.classList.toggle("open", open);
  layer.setAttribute("aria-hidden", open ? "false" : "true");
}

function closeSearchPickModal() {
  const stack = searchPickStack();
  if (!stack) return;
  stack.innerHTML = "";
  syncSearchPickLayer();
}

function itemIconUrl(item) {
  if (item?.icon) return item.icon;
  if (item?.item_icon_url) return item.item_icon_url;
  return "";
}

function buildSearchPickCard(item) {
  const row = el("div", "search-pick-card");
  const main = el("div", "search-pick-main");
  main.title = "Abrir detalhes do item";

  const thumb = el("div", "search-pick-thumb");
  const img = el("img");
  img.src = itemIconUrl(item);
  img.alt = item.name || "Item";
  img.loading = "lazy";
  thumb.appendChild(img);

  const info = el("div", "search-pick-info");
  info.appendChild(el("div", "search-pick-name", escapeHtml(item.name || "Item")));
  info.appendChild(el("div", "search-pick-id", `ID ${item.id ?? "—"}`));

  main.appendChild(thumb);
  main.appendChild(info);

  const actions = el("div", "search-pick-actions");
  actions.appendChild(wsButton(item.id));
  actions.appendChild(alertButton(item));
  actions.appendChild(createMonitorButton(item, item.monitored));

  const openFromCard = () => {
    closeSearchPickModal();
    openDetail(item);
  };
  row.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    openFromCard();
  });

  row.appendChild(main);
  row.appendChild(actions);
  return row;
}

function renderSearchPickModal(modalEl, query, res) {
  const subEl = modalEl.querySelector(".search-pick-sub");
  const bodyEl = modalEl.querySelector(".search-pick-body");
  if (!bodyEl) return;

  if (!res.ok) {
    if (subEl) subEl.textContent = "Erro na busca";
    bodyEl.innerHTML = `<div class="vshop-state err">${escapeHtml(res.error || "Não foi possível buscar no catálogo.")}</div>`;
    return;
  }

  const items = res.items || [];
  if (subEl) subEl.textContent = `${items.length} ${items.length === 1 ? "item encontrado" : "itens encontrados"}`;

  if (!items.length) {
    bodyEl.innerHTML = `<div class="vshop-state search-pick-empty">
      <div>Nenhum item encontrado para «${escapeHtml(query)}».</div>
      <div class="search-pick-empty-hint">Tente um nome diferente ou busque pelo ID.</div>
    </div>`;
    return;
  }

  const list = el("div", "search-pick-list");
  items.forEach((item) => list.appendChild(buildSearchPickCard(item)));
  bodyEl.innerHTML = "";
  bodyEl.appendChild(list);
}

function openItemSelectionWindow(query) {
  const layer = searchPickLayer();
  const stack = searchPickStack();
  if (!layer || !stack) return;

  closeSearchPickModal();

  const modal = document.createElement("div");
  modal.className = "vendor-shop-modal search-pick-modal";
  modal.innerHTML = `
    <div class="vshop-head">
      <div class="vshop-meta">
        <h3>Resultados para: ${escapeHtml(query)}</h3>
        <div class="vshop-sub search-pick-sub">Buscando…</div>
      </div>
      <button type="button" class="vshop-close search-pick-close" aria-label="Fechar">×</button>
    </div>
    <div class="vshop-body search-pick-body">
      <div class="vshop-state"><div class="spinner"></div>Buscando no catálogo…</div>
    </div>`;

  stack.appendChild(modal);
  syncSearchPickLayer();
  modal.querySelector(".search-pick-close")?.addEventListener("click", closeSearchPickModal);

  catalogSearch(query)
    .then((res) => renderSearchPickModal(modal, query, res))
    .catch((err) => renderSearchPickModal(modal, query, { ok: false, error: String(err), items: [] }));
}

document.getElementById("search-pick-backdrop")?.addEventListener("click", closeSearchPickModal);

// ── Linha de item (snapshot reutilizável: Monitorados / Alertas) ──
function snapshotRow(item, { sub, footerHtml, actions }) {
  const row = el("div", "lrow");
  row.dataset.search = ((item.name || "") + " " + (item.id ?? "")).toLowerCase();

  const thumb = el("div", "lthumb");
  if (item.icon) {
    const img = el("img");
    img.src = item.icon; img.alt = item.name; img.loading = "lazy";
    thumb.appendChild(img);
  }
  thumb.style.cursor = "pointer";
  thumb.title = "Abrir detalhes";
  thumb.addEventListener("click", () => openDetail(item));

  const info = el("div", "linfo");
  const nm = el("div", "lname", escapeHtml(item.name));
  nm.style.cursor = "pointer";
  nm.title = "Abrir detalhes";
  nm.addEventListener("click", () => openDetail(item));
  info.appendChild(nm);
  if (sub) info.appendChild(el("div", "lsub", sub));
  info.appendChild(el("div", "chips", priceChips(item.prices)));
  if (footerHtml) info.appendChild(el("div", "lfoot", footerHtml));

  const acts = el("div", "lacts");
  (actions || []).forEach((a) => acts.appendChild(a));

  row.appendChild(thumb);
  row.appendChild(info);
  row.appendChild(acts);
  return row;
}

function listFilter(q) {
  const term = (q || "").trim().toLowerCase();
  let shown = 0, total = 0;
  document.querySelectorAll("#view .lrow, #view .al-group").forEach((r) => {
    total++;
    const match = !term || (r.dataset.search || "").includes(term);
    r.classList.toggle("hidden", !match);
    if (match) shown++;
  });
  const hint = document.getElementById("list-hint");
  if (hint) hint.textContent = term ? (shown ? `${shown} de ${total}` : "Nenhum resultado") : "";
}

function actionBtn(label, cls, fn) {
  const b = el("button", "lbtn " + cls, label);
  b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
  return b;
}

// ── Alertas ─────────────────────────────────────────────────
async function renderAlerts() {
  head().innerHTML = `
    <div class="ph-title">
      <h2>Alertas de Preço</h2>
      <p>Verificação automática a cada 5 min (ou intervalo em Config). Notificações no sino lateral e por e-mail.</p>
    </div>
    <div class="ph-actions">
      <div class="search">
        <svg viewBox="0 0 24 24" class="search-ic"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        <input id="list-search" type="text" placeholder="Buscar item (nome ou ID)…" autocomplete="off" />
      </div>
      <span id="list-hint" class="list-hint"></span>
      <button id="al-check-now" class="lbtn ghost" type="button">Verificar agora</button>
      <div class="count-pill"><span id="al-status">…</span></div>
    </div>`;
  view().innerHTML = '<div class="sp-state"><div class="spinner"></div>Carregando alertas…</div>';

  const data = await window.pywebview.api.get_alerts();
  drawAlerts(data, false);

  document.getElementById("list-search").addEventListener("input", (e) => listFilter(e.target.value));
  document.getElementById("al-check-now").addEventListener("click", async (btn) => {
    btn.disabled = true;
    btn.textContent = "A verificar…";
    try {
      const r = await window.pywebview.api.run_alert_check_now();
      toast(r && r.fired ? `${r.fired} alerta(s) disparado(s)` : "Nenhum alerta novo");
      await refreshNotifyUI();
      if (CURRENT === "alerts") {
        const fresh = await window.pywebview.api.refresh_alerts_prices();
        drawAlerts(fresh, true);
      }
    } catch (err) {
      toast("Erro: " + String(err));
    } finally {
      btn.disabled = false;
      btn.textContent = "Verificar agora";
    }
  });
  setStatus("al-status", "atualizando preços…");
  try {
    const fresh = await window.pywebview.api.refresh_alerts_prices();
    if (CURRENT === "alerts") drawAlerts(fresh, true);
  } catch (_) { setStatus("al-status", alertStatusLabel(data.items || [])); }
}

function formatAlertTimestamp(iso) {
  const s = String(iso || "").trim();
  if (!s) return null;
  const d = new Date(s.includes("T") ? s : s.replace(" ", "T"));
  if (!Number.isNaN(d.getTime())) {
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  const m = s.replace("T", " ").match(/^(\d{4})-(\d{2})-(\d{2})\s(\d{2}):(\d{2})/);
  if (m) return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}`;
  return null;
}

function alertCurrentPrice(a) {
  const prices = a.prices || {};
  const key = a.currency || "zeny";
  const v = prices[key];
  return v != null && Number.isFinite(Number(v)) ? Number(v) : null;
}

function alertCriterionStatus(a) {
  const cur = alertCurrentPrice(a);
  const lim = Number(a.threshold) || 0;
  if (cur == null || lim <= 0) return "normal";
  if (a.type === "below") {
    if (cur <= lim) return "satisfeito";
    if (cur <= lim * 1.2) return "proximo";
    return "normal";
  }
  if (cur >= lim) return "satisfeito";
  if (cur >= lim * 0.8) return "proximo";
  return "normal";
}

function alertCriterionDesc(a) {
  const cur = CURRENCY[a.currency] || CURRENCY.zeny;
  const cond = a.type === "below" ? "cair abaixo de" : "subir acima de";
  const color = a.type === "below" ? "#34d399" : "#f87171";
  return { cond, color, label: cur.label, fmt: cur.fmt(a.threshold) };
}

function groupAlertsByItem(items) {
  const map = new Map();
  (items || []).forEach((a) => {
    const id = a.id ?? a.item_id ?? 0;
    if (!map.has(id)) {
      map.set(id, {
        id,
        name: a.name || `Item ${id}`,
        icon: a.icon || "",
        prices: a.prices || {},
        alerts: [],
      });
    }
    const g = map.get(id);
    g.alerts.push(a);
    if (!g.icon && a.icon) g.icon = a.icon;
    if (a.name) g.name = a.name;
    Object.entries(a.prices || {}).forEach(([k, v]) => {
      if (v == null) return;
      if (g.prices[k] == null || v < g.prices[k]) g.prices[k] = v;
    });
  });
  return [...map.values()].sort((a, b) => (a.name || "").localeCompare(b.name || "", "pt-BR"));
}

function alertStatusLabel(items) {
  const n = (items || []).length;
  if (!n) return "0 alertas";
  const groups = groupAlertsByItem(items);
  return groups.length === n ? `${n} alertas` : `${groups.length} itens · ${n} critérios`;
}

function buildAlertCriterionRow(a) {
  const { cond, color, label, fmt } = alertCriterionDesc(a);
  const status = alertCriterionStatus(a);
  const fired = formatAlertTimestamp(a.last_fired_at);
  const meta = [];
  if (a.condition_met) meta.push('<span class="al-ref al-meta-active">● critério activo</span>');
  if (a.refinement != null) meta.push(`<span class="al-ref">⚔ refino +${a.refinement} ou superior</span>`);
  if (a.notify_email) meta.push(`<span class="al-mail">✉ ${escapeHtml(a.notify_email)}</span>`);
  const row = el("div", "al-crit-row");
  row.innerHTML = `
    <span class="al-status-dot ${status}" title="${status === "satisfeito" ? "Critério satisfeito" : status === "proximo" ? "Próximo do limite" : "Normal"}"></span>
    <div class="al-crit-body">
      <div class="al-crit-desc"><span class="al-bell" style="color:${color}">${escapeHtml(label)} · ${cond} ${fmt}</span></div>
      ${meta.length ? `<div class="al-crit-meta">${meta.join("")}</div>` : ""}
      <div class="al-crit-fired${fired ? "" : " never"}">${fired ? `Último disparo: ${escapeHtml(fired)}` : "Nunca disparado"}</div>
    </div>`;
  const rem = el("button", "lbtn ghost al-crit-remove", "Remover");
  rem.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!(await modalConfirm(`Remover este critério de «${a.name}»?`))) return;
    drawAlerts(await window.pywebview.api.remove_alert(a.key), true);
  });
  row.appendChild(rem);
  return row;
}

function buildAlertGroupCard(group) {
  const card = el("div", "al-group lrow");
  card.dataset.search = `${group.name} ${group.id} ${group.alerts.map((a) => `${a.name} ${a.key}`).join(" ")}`.toLowerCase();

  const head = el("div", "al-group-head");
  const thumb = el("div", "lthumb");
  const itemStub = { id: group.id, name: group.name, icon: group.icon, prices: group.prices };
  if (group.icon) {
    const img = el("img");
    img.src = group.icon; img.alt = group.name; img.loading = "lazy";
    thumb.appendChild(img);
  }
  thumb.style.cursor = "pointer";
  thumb.title = "Abrir detalhes";
  thumb.addEventListener("click", () => openDetail(itemStub));

  const info = el("div", "linfo");
  const nm = el("div", "lname", escapeHtml(group.name));
  nm.style.cursor = "pointer";
  nm.title = "Abrir detalhes";
  nm.addEventListener("click", () => openDetail(itemStub));
  info.appendChild(nm);
  info.appendChild(el("div", "lsub", `ID ${group.id} · ${group.alerts.length} critério${group.alerts.length === 1 ? "" : "s"}`));
  info.appendChild(el("div", "chips", priceChips(group.prices)));

  const acts = el("div", "lacts");
  acts.appendChild(actionBtn("Ver preços", "ghost", () => openDetail(itemStub)));
  acts.appendChild(actionBtn("Remover", "danger", async () => {
    if (!(await modalBase({
      message: `Remover todos os alertas de «${group.name}»?`,
      confirm: "Remover todos",
      input: false,
      danger: true,
    }))) return;
    let data = null;
    for (const a of group.alerts) {
      data = await window.pywebview.api.remove_alert(a.key);
    }
    drawAlerts(data, true);
  }));

  head.appendChild(thumb);
  head.appendChild(info);
  head.appendChild(acts);

  const criteria = el("div", "al-criteria");
  group.alerts.forEach((a) => criteria.appendChild(buildAlertCriterionRow(a)));

  card.appendChild(head);
  card.appendChild(criteria);
  return card;
}

function drawAlerts(data, keepFilter) {
  const items = (data && data.items) || [];
  setStatus("al-status", alertStatusLabel(items));
  const wrap = el("div", "lwrap");
  if (!items.length) {
    wrap.appendChild(el("div", "empty-box", "Nenhum alerta configurado.<br>Abra um item e toque em « Criar alerta »."));
  } else {
    groupAlertsByItem(items).forEach((g) => wrap.appendChild(buildAlertGroupCard(g)));
  }
  view().innerHTML = "";
  view().appendChild(wrap);
  if (keepFilter) {
    const s = document.getElementById("list-search");
    if (s && s.value) listFilter(s.value);
  }
}

// ── Configurações ───────────────────────────────────────────
async function renderConfig() {
  head().innerHTML = `<div class="ph-title"><h2>Configurações</h2><p>E-mail, SMTP, Divine Pride, tema e início com o Windows. Role para ver todas as opções.</p></div>`;
  view().innerHTML = '<div class="sp-state"><div class="spinner"></div>Carregando…</div>';
  const res = await window.pywebview.api.get_settings();
  const s = (res && res.settings) || {};
  const txt = (k, v) => `<input id="cfg-${k}" type="text" value="${escapeHtml(v == null ? "" : String(v))}">`;
  const pw = (k, v) => `<input id="cfg-${k}" type="password" value="${escapeHtml(v == null ? "" : String(v))}">`;
  view().innerHTML = `
    <div class="cfg">
      <section class="cfg-card cfg-card-smtp">
        <h3>Notificações por e-mail (SMTP)</h3>
        <p class="cfg-note">Usados para enviar os alertas de preço por e-mail.</p>
        <label>E-mail destino (padrão)${txt("notify_email", s.notify_email)}</label>
        <label>SMTP servidor${txt("smtp_host", s.smtp_host)}</label>
        <div class="cfg-grid2">
          <label>SMTP porta${txt("smtp_port", s.smtp_port)}</label>
          <label>SMTP utilizador${txt("smtp_user", s.smtp_user)}</label>
        </div>
        <label>SMTP palavra-passe${pw("smtp_password", s.smtp_password)}</label>
        <p class="cfg-note cfg-note-tight">A senha fica salva apenas neste computador.</p>
        <label class="cfg-check"><input id="cfg-smtp_use_tls" type="checkbox" ${s.smtp_use_tls ? "checked" : ""}> Usar TLS (STARTTLS, porta 587 — recomendado)</label>
      </section>

      <section class="cfg-card cfg-card-dp">
        <h3>Divine Pride (API opcional)</h3>
        <p class="cfg-note">Traz nomes dos MVPs em inglês. Peça a chave em divine-pride.net/api.</p>
        <label>Chave API${pw("divine_pride_api_key", s.divine_pride_api_key)}</label>
        <label>Servidor (iRO, bRO…)${txt("divine_pride_server", s.divine_pride_server)}</label>
      </section>

      <section class="cfg-card cfg-card-wide">
        <h3>Interface</h3>
        <div class="cfg-grid3">
          <label>Tema
            <select id="cfg-ui_theme">
              <option value="dark" ${s.ui_theme !== "light" ? "selected" : ""}>Escuro</option>
              <option value="light" ${s.ui_theme === "light" ? "selected" : ""}>Claro</option>
            </select>
          </label>
          <label>Intervalo verificação alertas (s)${txt("alert_interval_seconds", s.alert_interval_seconds)}</label>
          <label>Som de alerta MVP (caminho)${txt("mvp_alert_sound_path", s.mvp_alert_sound_path)}</label>
        </div>
        <label class="cfg-check"><input id="cfg-start_with_windows" type="checkbox" ${s.start_with_windows ? "checked" : ""}> Iniciar o GDZ Monitor com o Windows</label>
      </section>

      <div class="cfg-actions">
        <button id="cfg-save" class="lbtn success">Guardar</button>
        <button id="cfg-test-email" class="lbtn ghost">Enviar e-mail de teste</button>
        <button id="cfg-test-dp" class="lbtn ghost">Testar Divine Pride</button>
        <span id="cfg-msg" class="cfg-msg"></span>
      </div>
    </div>`;

  document.getElementById("cfg-save").addEventListener("click", saveConfig);
  document.getElementById("cfg-test-email").addEventListener("click", testEmail);
  document.getElementById("cfg-test-dp").addEventListener("click", testDivinePride);
  const themeSel = document.getElementById("cfg-ui_theme");
  if (themeSel) themeSel.addEventListener("change", (e) => applyTheme(e.target.value));
}

function readConfigForm() {
  const v = (k) => { const e = document.getElementById("cfg-" + k); return e ? e.value : ""; };
  const c = (k) => { const e = document.getElementById("cfg-" + k); return e ? e.checked : false; };
  return {
    notify_email: v("notify_email"), smtp_host: v("smtp_host"), smtp_port: v("smtp_port"),
    smtp_user: v("smtp_user"), smtp_password: v("smtp_password"), smtp_use_tls: c("smtp_use_tls"),
    alert_interval_seconds: v("alert_interval_seconds"), start_with_windows: c("start_with_windows"),
    ui_theme: v("ui_theme"),
    divine_pride_api_key: v("divine_pride_api_key"), divine_pride_server: v("divine_pride_server"),
    mvp_alert_sound_path: v("mvp_alert_sound_path"),
  };
}

function cfgMsg(text, ok) {
  const m = document.getElementById("cfg-msg");
  if (!m) return;
  m.textContent = text;
  m.style.color = ok ? "#34d399" : "#f87171";
}

async function saveConfig() {
  cfgMsg("Guardando…", true);
  const payload = readConfigForm();
  const res = await window.pywebview.api.save_settings_web(payload);
  if (res && res.ok) applyTheme(payload.ui_theme);
  cfgMsg(res.ok ? (res.message || "Guardado.") : ("Erro: " + (res.error || "")), res.ok);
}

async function testEmail() {
  cfgMsg("Enviando e-mail de teste…", true);
  const res = await window.pywebview.api.test_email(readConfigForm());
  cfgMsg(res.ok ? "E-mail de teste enviado." : ("Falhou: " + (res.error || "")), res.ok);
}

async function testDivinePride() {
  cfgMsg("Testando Divine Pride…", true);
  const res = await window.pywebview.api.test_divine_pride(readConfigForm());
  cfgMsg(res.ok ? (res.message || "OK.") : ("Falhou: " + (res.error || "")), res.ok);
}

// ── Simulação de Build ──────────────────────────────────────
let BUILD_META = null;
let BUILD = null;
let BUILD_LAYER = "equip";
let BUILD_MARKET = { hp_per_rmt: 30, rmt_per_100k_hp: null, samples: 0, source: "", reference_item_id: 40111 };

function emptyCellState() {
  return {
    item_id: null, item_name: "", refine: 0, is_2h: false, icon: "", item_icon_url: "",
    manual_price: false, price_rmt: null, price_hp: null,
    item_stats: null, item_description: "", weapon_base: null,
  };
}

function emptyBaseStats() {
  const prim = {}, tal = {};
  (BUILD_META?.stats?.primary || []).forEach((s) => { prim[s.key] = 0; });
  (BUILD_META?.stats?.talents || []).forEach((s) => { tal[s.key] = 0; });
  if (!Object.keys(prim).length) ["STR", "AGI", "VIT", "INT", "DEX", "LUK"].forEach((k) => { prim[k] = 0; });
  if (!Object.keys(tal).length) ["POW", "STA", "WIS", "SPL", "CON", "CRT", "CRATE"].forEach((k) => { tal[k] = 0; });
  return { primary: prim, talents: tal };
}

function fmtStatBonus(v) {
  const n = Number(v) || 0;
  if (n > 0) return `+${n}`;
  if (n < 0) return String(n);
  return "+0";
}

function sumBuildEquipmentStats() {
  const out = {
    primary: {}, talents: {}, derived_attr: {}, derived_talent: {},
  };
  ["primary", "talents", "derived_attr", "derived_talent"].forEach((bk) => {
    (BUILD_META?.stats?.[bk === "derived_attr" || bk === "derived_talent" ? bk : bk] || []).forEach((s) => {
      out[bk][s.key] = 0;
    });
  });
  if (!Object.keys(out.primary).length) ["STR", "AGI", "VIT", "INT", "DEX", "LUK"].forEach((k) => { out.primary[k] = 0; });
  if (!Object.keys(out.talents).length) ["POW", "STA", "WIS", "SPL", "CON", "CRT", "CRATE"].forEach((k) => { out.talents[k] = 0; });
  ["ATK", "MATK", "HIT", "CRIT", "DEF", "MDEF", "FLEE", "ASPD"].forEach((k) => { out.derived_attr[k] = 0; });
  ["PATK", "SMATK", "HPLUS", "RES", "MRES"].forEach((k) => { out.derived_talent[k] = 0; });

  const addLegacy = (st) => {
    if (!st || typeof st !== "object") return;
    if (st.primary) Object.keys(out.primary).forEach((k) => { out.primary[k] += Number(st.primary[k]) || 0; });
    if (st.talents) Object.keys(out.talents).forEach((k) => { out.talents[k] += Number(st.talents[k]) || 0; });
    if (st.derived_attr) Object.keys(out.derived_attr).forEach((k) => { out.derived_attr[k] += Number(st.derived_attr[k]) || 0; });
    if (st.derived_talent) Object.keys(out.derived_talent).forEach((k) => { out.derived_talent[k] += Number(st.derived_talent[k]) || 0; });
    if (st.secondary) {
      const leg = st.secondary;
      Object.entries(leg).forEach(([k, v]) => {
        const ku = k.toUpperCase();
        const n = Number(v) || 0;
        if (out.primary[ku] != null) out.primary[ku] += n;
        else if (out.talents[ku] != null) out.talents[ku] += n;
        else if (out.derived_attr[ku] != null) out.derived_attr[ku] += n;
        else if (out.derived_talent[ku] != null) out.derived_talent[ku] += n;
        else if (ku === "PATK") out.derived_talent.PATK += n;
      });
    }
  };

  ["equip", "visual"].forEach((layer) => {
    [...(BUILD_META?.left || []), ...(BUILD_META?.right || [])].forEach((sk) => {
      addLegacy(BUILD.cells?.[layer]?.[sk]?.item_stats);
    });
  });
  return out;
}

function buildEditableRowHtml(def, baseVal, equipVal) {
  const base = Number(baseVal) || 0;
  const eq = Number(equipVal) || 0;
  const total = base + eq;
  const tip = `Base: ${base} | Equipamentos: ${fmtStatBonus(eq)} | Total: ${total}`;
  return `<div class="bro-edit-row" data-key="${escapeHtml(def.key)}" data-kind="${escapeHtml(def.kind || "primary")}" title="${escapeHtml(tip)}">
    <span class="bro-abbr">${escapeHtml(def.label)}</span>
    <div class="bro-edit-val">
      <input class="bro-base" type="text" inputmode="numeric" maxlength="3" autocomplete="off" value="${base}" aria-label="${escapeHtml(def.label)}" title="${escapeHtml(tip)}">
      <span class="bro-eq" title="${escapeHtml(tip)}">${fmtStatBonus(eq)}</span>
    </div>
  </div>`;
}

function readBaseStatsFromUIForPreview() {
  const prim = { ...(BUILD.base_stats?.primary || emptyBaseStats().primary) };
  const tal = { ...(BUILD.base_stats?.talents || emptyBaseStats().talents) };
  const parse = (raw) => {
    const s = String(raw ?? "").trim();
    if (!s) return 0;
    const v = Number(s);
    return Number.isFinite(v) ? Math.max(0, Math.trunc(v)) : 0;
  };
  document.querySelectorAll('.bro-edit-row[data-kind="primary"]').forEach((row) => {
    const key = row.dataset.key;
    if (key) prim[key] = parse(row.querySelector(".bro-base")?.value);
  });
  document.querySelectorAll('.bro-edit-row[data-kind="talents"]').forEach((row) => {
    const key = row.dataset.key;
    if (key) tal[key] = parse(row.querySelector(".bro-base")?.value);
  });
  return { primary: prim, talents: tal };
}

function readCharacterFromUIForPreview() {
  const out = { ...(BUILD.character || emptyCharacter()) };
  const bl = document.getElementById("bchar-bl");
  const jl = document.getElementById("bchar-jl");
  const cls = document.getElementById("bchar-class");
  if (cls) out.class_id = cls.value;
  const parseLvl = (el, fallback) => {
    if (!el) return fallback;
    const s = String(el.value ?? "").trim();
    if (!s) return fallback;
    const v = Number(s);
    return Number.isFinite(v) ? Math.max(1, Math.trunc(v)) : fallback;
  };
  out.base_level = parseLvl(bl, out.base_level ?? 275);
  out.job_level = parseLvl(jl, out.job_level ?? 65);
  return out;
}

function talentCrateEquipBonus(eq) {
  return (Number(eq?.talents?.CRATE) || 0) + (Number(eq?.derived_talent?.CRATE) || 0);
}

function talentCrateDef() {
  return (BUILD_META?.stats?.talents || []).find((d) => d.key === "CRATE")
    || { key: "CRATE", label: "C.Rate", kind: "talents" };
}

function buildTalentDerivedLeftHtml(eq, derived, baseStats) {
  const leftKeys = ["PATK", "SMATK", "HPLUS"];
  const dTal = BUILD_META?.stats?.derived_talent || [];
  return dTal.filter((d) => leftKeys.includes(d.key))
    .map((d) => buildDerivedRowHtml(d, derived.derived_talent?.[d.key])).join("")
    + buildEditableRowHtml(
      { ...talentCrateDef(), kind: "talents" },
      baseStats?.talents?.CRATE,
      talentCrateEquipBonus(eq),
    );
}

function buildTalentDerivedRightHtml(eq, derived) {
  const rightKeys = ["RES", "MRES"];
  const dTal = BUILD_META?.stats?.derived_talent || [];
  return dTal.filter((d) => rightKeys.includes(d.key))
    .map((d) => buildDerivedRowHtml(d, derived.derived_talent?.[d.key])).join("");
}

function patchDerivedRow(row, def, parts) {
  if (!row || !def) return;
  const tmp = document.createElement("div");
  tmp.innerHTML = buildDerivedRowHtml(def, parts);
  const next = tmp.firstElementChild;
  if (next) row.replaceWith(next);
}

function refreshBuildDerivedStats() {
  const host = document.getElementById("build-stats-panels");
  if (!host || !BUILD_META?.stats) return;
  const eq = sumBuildEquipmentStats();
  const derived = computeDerivedDisplay(
    readCharacterFromUIForPreview(),
    readBaseStatsFromUIForPreview(),
    eq,
  );
  const dAttr = BUILD_META.stats.derived_attr || [];
  const dTal = BUILD_META.stats.derived_talent || [];
  const half = Math.ceil(dAttr.length / 2);
  const cards = host.querySelectorAll(".bstats-card");
  if (cards.length < 2) {
    renderBuildStatsPanel();
    return;
  }
  const attrCols = cards[0].querySelectorAll(".bstats-derived-col");
  const talCols = cards[1].querySelectorAll(".bstats-derived-col");
  if (attrCols.length >= 2) {
    attrCols[0].innerHTML = dAttr.slice(0, half).map((d) => buildDerivedRowHtml(d, derived.derived_attr?.[d.key])).join("");
    attrCols[1].innerHTML = dAttr.slice(half).map((d) => buildDerivedRowHtml(d, derived.derived_attr?.[d.key])).join("");
  }
  if (talCols.length >= 2) {
    ["PATK", "SMATK", "HPLUS"].forEach((key) => {
      const def = dTal.find((d) => d.key === key);
      patchDerivedRow(talCols[0].querySelector(`.bro-ro-row[data-key="${key}"]`), def, derived.derived_talent?.[key]);
    });
    const crateEq = talCols[0].querySelector('.bro-edit-row[data-key="CRATE"] .bro-eq');
    if (crateEq) crateEq.textContent = fmtStatBonus(talentCrateEquipBonus(eq));
    ["RES", "MRES"].forEach((key) => {
      const def = dTal.find((d) => d.key === key);
      patchDerivedRow(talCols[1].querySelector(`.bro-ro-row[data-key="${key}"]`), def, derived.derived_talent?.[key]);
    });
  }
}

function bindBuildStatInputs() {
  document.querySelectorAll(".bro-base").forEach((inp) => {
    inp.addEventListener("input", () => {
      inp.value = inp.value.replace(/\D/g, "").slice(0, 3);
      refreshBuildDerivedStats();
      scheduleBuildAutoSave();
    });
    inp.addEventListener("blur", () => {
      mergeBuildBaseStatsFromUI();
      const row = inp.closest(".bro-edit-row");
      const key = row?.dataset.key;
      const kind = row?.dataset.kind;
      if (key) {
        const v = kind === "talents" ? BUILD.base_stats.talents[key] : BUILD.base_stats.primary[key];
        inp.value = String(v ?? 0);
      }
      refreshBuildDerivedStats();
      scheduleBuildAutoSave();
    });
  });
}

function emptyCharacter() {
  const d = BUILD_META?.default_character || {};
  return {
    class_id: d.class_id || (BUILD_META?.classes?.[0]?.id || ""),
    base_level: d.base_level ?? 275,
    job_level: d.job_level ?? 65,
  };
}

function classInfoById(id) {
  return (BUILD_META?.classes || []).find((c) => c.id === id) || null;
}

function weaponFromBuildCells() {
  const equip = BUILD?.cells?.equip || {};
  const parse = (cell, slot) => {
    if (!cell?.item_id) return null;
    const wb = cell.weapon_base || {};
    const baseAtk = Number(wb.base_atk) || 0;
    const baseMatk = Number(wb.base_matk) || 0;
    if (wb.is_shield && slot === "weapon_left") return null;
    if (!baseAtk && !baseMatk) return null;
    return {
      slot,
      item_id: cell.item_id,
      item_name: cell.item_name || cell.item_id,
      base_atk: baseAtk,
      base_matk: baseMatk,
      refine_atk: Number(wb.refine_atk) || 0,
      refine_matk: Number(wb.refine_matk) || 0,
      ranged: !!wb.ranged,
    };
  };
  return parse(equip.weapon_right, "weapon_right")
    || parse(equip.weapon_left, "weapon_left")
    || { slot: null, item_id: null, item_name: "", base_atk: 0, base_matk: 0, refine_atk: 0, refine_matk: 0, ranged: false };
}

function flo(x) {
  const n = Number(x);
  return Number.isFinite(n) ? Math.trunc(n) : 0;
}

function computeDerivedDisplay(character, baseStats, eq) {
  const srv = BUILD_META?.server || {};
  const maxBl = srv.max_base_level || 275;
  const cls = classInfoById(character?.class_id);
  const prim = baseStats?.primary || {};
  const tal = baseStats?.talents || {};
  const g = (k) => (Number(prim[k]) || 0) + (Number(eq.primary?.[k]) || 0);
  const gt = (k) => (Number(tal[k]) || 0) + (Number(eq.talents?.[k]) || 0);
  const bl = Math.max(1, Math.min(maxBl, Number(character?.base_level) || 1));
  const weapon = weaponFromBuildCells();

  let ranged = !!weapon.ranged;
  if (cls?.weapon_type === "ranged" && !weapon.base_atk) ranged = true;

  const strT = g("STR"), dexT = g("DEX"), lukT = g("LUK"), intT = g("INT");
  const agiT = g("AGI"), vitT = g("VIT");
  const powT = gt("POW"), conT = gt("CON"), crtT = gt("CRT");
  const staT = gt("STA"), wisT = gt("WIS"), splT = gt("SPL");

  let statusAtk;
  let statForWeapon;
  if (ranged) {
    statusAtk = flo(bl / 4) + flo(strT / 5) + dexT + flo(lukT / 3);
    statForWeapon = dexT;
  } else {
    statusAtk = flo(bl / 4) + strT + flo(dexT / 5) + flo(lukT / 3);
    statForWeapon = strT;
  }
  statusAtk += powT * 5;

  const baseW = weapon.base_atk || 0;
  const refW = weapon.refine_atk || 0;
  const statBonus = baseW ? Math.trunc((baseW * statForWeapon) / 200) : 0;
  const weaponAtk = baseW + refW + statBonus;
  const equipAtk = Number(eq.derived_attr?.ATK) || 0;

  let statusMatk = intT + flo(flo(intT / 7) ** 2) + flo(dexT / 5) + flo(lukT / 3);
  statusMatk += splT * 5;
  const weaponMatk = (weapon.base_matk || 0) + (weapon.refine_matk || 0);
  const equipMatk = Number(eq.derived_attr?.MATK) || 0;

  const softDef = flo(vitT / 2) + Math.trunc(agiT / 5);
  const hardDef = Number(eq.derived_attr?.DEF) || 0;
  const softMdef = intT + flo(intT / 7) + flo(dexT / 5);
  const hardMdef = Number(eq.derived_attr?.MDEF) || 0;

  const hit = 175 + bl + dexT + flo(lukT / 3) + 2 * conT + (Number(eq.derived_attr?.HIT) || 0);
  const crit = flo(lukT / 3) + (Number(eq.derived_attr?.CRIT) || 0);
  const flee = 100 + bl + agiT + flo(lukT / 5) + (Number(eq.derived_attr?.FLEE) || 0);

  const tier = cls?.tier_label || "";
  const aspCap = srv.max_aspd || 193;
  const aspBase = ["3ª", "4ª", "Avanç.", "Exp.+"].includes(tier) ? 150 : 146;
  const aspd = Math.min(aspCap, aspBase + flo(agiT / 4) + flo(dexT / 10) + (Number(eq.derived_attr?.ASPD) || 0));

  return {
    derived_attr: {
      ATK: { base: statusAtk, bonus: weaponAtk + equipAtk },
      MATK: { base: statusMatk, bonus: weaponMatk + equipMatk },
      HIT: { base: hit, bonus: 0 },
      CRIT: { base: crit, bonus: 0 },
      DEF: { base: softDef, bonus: hardDef },
      MDEF: { base: softMdef, bonus: hardMdef },
      FLEE: { base: flee, bonus: 0 },
      ASPD: { base: aspd, bonus: 0 },
    },
    derived_talent: {
      PATK: { base: flo(conT / 5) + (Number(eq.derived_talent?.PATK) || 0), bonus: 0 },
      SMATK: { base: flo(conT / 5) + (Number(eq.derived_talent?.SMATK) || 0), bonus: 0 },
      HPLUS: { base: crtT + (Number(eq.derived_talent?.HPLUS) || 0), bonus: 0 },
      RES: { base: staT + (Number(eq.derived_talent?.RES) || 0), bonus: 0 },
      MRES: { base: wisT + (Number(eq.derived_talent?.MRES) || 0), bonus: 0 },
    },
    weapon: { ...weapon, stat_bonus: statBonus, total_weapon_atk: weaponAtk },
  };
}

function buildDerivedRowHtml(def, parts) {
  const base = Number(parts?.base) || 0;
  const bonus = Number(parts?.bonus) || 0;
  const total = base + bonus;
  const tip = `Base: ${base} | Equipamentos: ${fmtStatBonus(bonus)} | Total: ${total}`;
  const split = ["ATK", "MATK", "DEF", "MDEF"].includes(def.key);
  if (split && bonus !== 0) {
    return `<div class="bro-ro-row" data-key="${escapeHtml(def.key)}" title="${escapeHtml(tip)}">
      <span class="bro-abbr">${escapeHtml(def.label)}</span>
      <span class="bro-ro-val"><span class="bro-base-part">${base}</span> <span class="bro-eq-part">${fmtStatBonus(bonus)}</span></span>
    </div>`;
  }
  return `<div class="bro-ro-row" data-key="${escapeHtml(def.key)}" title="${escapeHtml(tip)}">
    <span class="bro-abbr">${escapeHtml(def.label)}</span>
    <span class="bro-ro-val">${base}${bonus ? ` <span class="bro-eq-part">${fmtStatBonus(bonus)}</span>` : ""}</span>
  </div>`;
}

function renderBuildCharacterPanel() {
  const host = document.getElementById("build-character-zone");
  if (!host || !BUILD_META) return;
  if (!BUILD.character) BUILD.character = emptyCharacter();
  const clsOpts = (BUILD_META.classes || []).map((c) =>
    `<option value="${escapeHtml(c.id)}" ${c.id === BUILD.character.class_id ? "selected" : ""}>${escapeHtml(c.label)}</option>`,
  ).join("");
  host.innerHTML = `
    <div class="bchar-card">
      <h3>Personagem</h3>
      <div class="bchar-grid">
        <label class="bchar-field bchar-class">
          <span>Classe</span>
          <select id="bchar-class">${clsOpts}</select>
        </label>
        <div class="bchar-levels-row">
          <label class="bchar-field">
            <span>Base</span>
            <input id="bchar-bl" type="text" inputmode="numeric" maxlength="3" autocomplete="off" value="${BUILD.character.base_level ?? 275}">
          </label>
          <label class="bchar-field">
            <span>Job</span>
            <input id="bchar-jl" type="text" inputmode="numeric" maxlength="2" autocomplete="off" value="${BUILD.character.job_level ?? 65}">
          </label>
        </div>
      </div>
    </div>`;

  const onClassChange = () => {
    mergeBuildCharacterFromUI();
    refreshBuildDerivedStats();
    scheduleBuildAutoSave();
  };
  const onLevelInput = (el, maxLen) => {
    el.addEventListener("input", () => {
      el.value = el.value.replace(/\D/g, "").slice(0, maxLen);
      refreshBuildDerivedStats();
    });
    el.addEventListener("blur", () => {
      mergeBuildCharacterFromUI();
      el.value = String(
        el.id === "bchar-bl" ? BUILD.character.base_level : BUILD.character.job_level,
      );
      refreshBuildDerivedStats();
      scheduleBuildAutoSave();
    });
  };
  host.querySelector("#bchar-class").addEventListener("change", onClassChange);
  onLevelInput(host.querySelector("#bchar-bl"), 3);
  onLevelInput(host.querySelector("#bchar-jl"), 2);
}

function mergeBuildCharacterFromUI() {
  if (!BUILD.character) BUILD.character = emptyCharacter();
  const cls = document.getElementById("bchar-class");
  const bl = document.getElementById("bchar-bl");
  const jl = document.getElementById("bchar-jl");
  const srv = BUILD_META?.server || {};
  if (cls) BUILD.character.class_id = cls.value;
  if (bl) {
    const v = Number(bl.value);
    BUILD.character.base_level = Number.isFinite(v)
      ? Math.max(1, Math.min(srv.max_base_level || 275, Math.trunc(v))) : 275;
  }
  if (jl) {
    const v = Number(jl.value);
    BUILD.character.job_level = Number.isFinite(v)
      ? Math.max(1, Math.min(srv.max_job_level || 65, Math.trunc(v))) : 65;
  }
}

function renderBuildStatsPanel() {
  const host = document.getElementById("build-stats-panels");
  if (!host || !BUILD_META?.stats) return;
  if (!BUILD.base_stats) BUILD.base_stats = emptyBaseStats();
  if (!BUILD.character) BUILD.character = emptyCharacter();
  const eq = sumBuildEquipmentStats();
  const derived = computeDerivedDisplay(BUILD.character, BUILD.base_stats, eq);
  const primDefs = (BUILD_META.stats.primary || []).map((d) => ({ ...d, kind: "primary" }));
  const talDefs = (BUILD_META.stats.talents || [])
    .filter((d) => d.key !== "CRATE")
    .map((d) => ({ ...d, kind: "talents" }));
  const dAttr = BUILD_META.stats.derived_attr || [];
  const half = Math.ceil(dAttr.length / 2);
  const dAttrL = dAttr.slice(0, half);
  const dAttrR = dAttr.slice(half);

  host.innerHTML = `
    <div class="bstats-card bstats-ro">
      <h3>Atributos</h3>
      <div class="bstats-ro-grid">
        <div class="bstats-editable-col">${primDefs.map((d) => buildEditableRowHtml(d, BUILD.base_stats.primary?.[d.key], eq.primary?.[d.key])).join("")}</div>
        <div class="bstats-derived-col">${dAttrL.map((d) => buildDerivedRowHtml(d, derived.derived_attr?.[d.key])).join("")}</div>
        <div class="bstats-derived-col">${dAttrR.map((d) => buildDerivedRowHtml(d, derived.derived_attr?.[d.key])).join("")}</div>
      </div>
    </div>
    <div class="bstats-card bstats-ro">
      <h3>Talentos</h3>
      <div class="bstats-ro-grid">
        <div class="bstats-editable-col">${talDefs.map((d) => buildEditableRowHtml(d, BUILD.base_stats.talents?.[d.key], eq.talents?.[d.key])).join("")}</div>
        <div class="bstats-derived-col">${buildTalentDerivedLeftHtml(eq, derived, BUILD.base_stats)}</div>
        <div class="bstats-derived-col">${buildTalentDerivedRightHtml(eq, derived)}</div>
      </div>
      <p class="bstats-footnote">Fórmulas IRO simplificadas · ATQ base da arma vem do slot equipado (mão direita)</p>
    </div>`;

  bindBuildStatInputs();
}

function buildStatsItemListHtml() {
  return "";
}

function mergeBuildBaseStatsFromUI() {
  if (!BUILD.base_stats) BUILD.base_stats = emptyBaseStats();
  if (!BUILD.base_stats.talents) BUILD.base_stats.talents = {};
  const maxP = BUILD_META?.server?.max_primary_stat || 130;
  const maxT = BUILD_META?.server?.max_talent_stat || 110;
  document.querySelectorAll('.bro-edit-row[data-kind="primary"]').forEach((row) => {
    const key = row.dataset.key;
    const v = Number(row.querySelector(".bro-base")?.value);
    if (key) BUILD.base_stats.primary[key] = Number.isFinite(v) ? Math.max(0, Math.min(maxP, Math.trunc(v))) : 0;
  });
  document.querySelectorAll('.bro-edit-row[data-kind="talents"]').forEach((row) => {
    const key = row.dataset.key;
    const v = Number(row.querySelector(".bro-base")?.value);
    if (key) BUILD.base_stats.talents[key] = Number.isFinite(v) ? Math.max(0, Math.min(maxT, Math.trunc(v))) : 0;
  });
}

function emptyCells() {
  const all = [...BUILD_META.left, ...BUILD_META.right];
  const layer = () => Object.fromEntries(all.map((k) => [k, emptyCellState()]));
  return { equip: layer(), visual: layer() };
}

function parseBuildPrice(raw) {
  const s = String(raw ?? "").trim();
  if (!s || s === "—") return null;
  const n = Number(s.replace(/\./g, "").replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function formatBuildPriceInput(v) {
  if (v == null || v === "") return "";
  return coin(v);
}

function ensureBuildCellsIntegrity() {
  if (!BUILD_META || !BUILD?.cells) return;
  if (!BUILD.cells.equip) BUILD.cells.equip = {};
  if (!BUILD.cells.visual) BUILD.cells.visual = {};
  const all = [...BUILD_META.left, ...BUILD_META.right];
  all.forEach((sk) => {
    if (!BUILD.cells.equip[sk] || typeof BUILD.cells.equip[sk] !== "object") {
      BUILD.cells.equip[sk] = emptyCellState();
    }
    if (!BUILD.cells.visual[sk] || typeof BUILD.cells.visual[sk] !== "object") {
      BUILD.cells.visual[sk] = emptyCellState();
    }
  });
}

function cellPriceFields(cell) {
  const manual = !!cell?.manual_price && !!cell?.item_id;
  const hasItem = !!cell?.item_id;
  return {
    manual,
    rmt: hasItem && cell.price_rmt != null ? formatBuildPriceInput(cell.price_rmt) : "",
    hp: hasItem && cell.price_hp != null ? formatBuildPriceInput(cell.price_hp) : "",
  };
}

function writeAutoPricesToCell(cell, pr) {
  if (!cell || cell.manual_price) return;
  cell.price_rmt = pr && pr.rmt != null ? pr.rmt : null;
  cell.price_hp = pr && pr.hp != null ? pr.hp : null;
}

function flushVisibleLayerToBuildState() {
  if (!BUILD_META || !BUILD?.cells) return;
  ensureBuildCellsIntegrity();
  const layer = activeBuildLayer();
  [...BUILD_META.left, ...BUILD_META.right].forEach((sk) => {
    const slot = slotEl(layer, sk);
    if (!slot) return;
    const cell = BUILD.cells[layer][sk];
    if (!cell) return;

    const raw = slot.querySelector(".bslot-id")?.value.replace(/\D/g, "") ?? "";
    const ref = Math.max(0, Math.min(20, Number(slot.querySelector(".bslot-ref")?.value) || 0));
    const pid = raw ? Number(raw) : null;
    if (pid == null) {
      if (cell.item_id) cell.refine = ref;
    } else {
      if (cell.item_id !== pid) cell.item_name = "";
      cell.item_id = pid;
      cell.refine = ref;
    }

    if (!cell.item_id) return;

    const manualChk = slot.querySelector(".bslot-manual-chk");
    cell.manual_price = !!(manualChk?.checked) && !!cell.item_id;

    const rmtStr = String(slot.querySelector(".bslot-price-rmt")?.value ?? "").trim();
    const hpStr = String(slot.querySelector(".bslot-price-hp")?.value ?? "").trim();

    if (cell.manual_price) {
      cell.price_rmt = rmtStr && rmtStr !== "—" ? parseBuildPrice(rmtStr) : null;
      cell.price_hp = hpStr && hpStr !== "—" ? parseBuildPrice(hpStr) : null;
      return;
    }

    // Preços automáticos: gravar no estado da build; nunca apagar por campo vazio no DOM.
    if (rmtStr && rmtStr !== "—") {
      const parsed = parseBuildPrice(rmtStr);
      if (parsed != null) cell.price_rmt = parsed;
    }
    if (hpStr && hpStr !== "—") {
      const parsed = parseBuildPrice(hpStr);
      if (parsed != null) cell.price_hp = parsed;
    }
  });
}

let BUILD_LIST = { builds: [], primary_id: "" };

function buildHeadToolsHtml() {
  return `
    <div class="build-head-tools" id="build-head-tools">
      <button type="button" id="b-primary-star" class="build-icon-btn" title="Definir como build principal" aria-label="Definir como build principal">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>
      </button>
      <button type="button" id="b-delete" class="build-icon-btn" title="Excluir build" aria-label="Excluir build">−</button>
      <select id="b-saved" class="build-selector"></select>
      <button type="button" id="b-add" class="build-icon-btn" title="Criar nova build" aria-label="Criar nova build">+</button>
    </div>`;
}

function syncBuildHeaderControls(list) {
  if (list?.builds) BUILD_LIST = list;
  const sel = document.getElementById("b-saved");
  const star = document.getElementById("b-primary-star");
  const del = document.getElementById("b-delete");
  if (!sel) return;

  const builds = BUILD_LIST.builds || [];
  sel.innerHTML = builds.length
    ? builds.map((b) => `<option value="${escapeHtml(b.id)}" ${b.id === BUILD.id ? "selected" : ""}>${escapeHtml(b.name)}</option>`).join("")
    : `<option value="">Sem builds salvas</option>`;

  if (BUILD.id && builds.some((b) => b.id === BUILD.id)) sel.value = BUILD.id;
  else if (builds.length) sel.value = builds[0].id;

  const activeId = sel.value;
  const isPrimary = !!(activeId && activeId === BUILD_LIST.primary_id);

  if (star) {
    star.classList.toggle("is-primary", isPrimary);
    star.disabled = !activeId;
    star.title = !activeId ? "Nenhuma build selecionada" : (isPrimary ? "Já é a build principal" : "Definir como build principal");
    const path = star.querySelector("path");
    if (path) path.setAttribute("fill", isPrimary ? "currentColor" : "none");
  }
  if (del) {
    const canDelete = builds.length > 1 && !!activeId;
    del.disabled = !canDelete;
    del.title = canDelete ? "Excluir build" : "Não é possível excluir a única build";
  }
}

async function loadBuildById(id) {
  if (!id) {
    BUILD = { id: "", name: "", hp_per_rmt: 30, cells: emptyCells(), base_stats: emptyBaseStats(), character: emptyCharacter() };
    BUILD_LAYER = "equip";
    return;
  }
  const loaded = await window.pywebview.api.build_load(id);
  if (!loaded.ok) return;
  BUILD = {
    id: loaded.id, name: loaded.name, hp_per_rmt: loaded.hp_per_rmt,
    cells: loaded.cells, base_stats: loaded.base_stats || emptyBaseStats(),
    character: loaded.character || emptyCharacter(),
  };
  BUILD_LAYER = "equip";
  BUILD_MARKET.hp_per_rmt = loaded.hp_per_rmt || 30;
  ensureBuildCellsIntegrity();
  await ensureBuildItemStats();
}

async function buildOnSavedChange() {
  const sel = document.getElementById("b-saved");
  if (!sel) return;
  await loadBuildById(sel.value);
  renderBuildCharacterPanel();
  renderBuildSlotPanel();
  renderBuildStatsPanel();
  buildDisplaySavedPrices();
  syncBuildHeaderControls(BUILD_LIST);
}

async function buildSetPrimaryClick() {
  const id = BUILD.id || document.getElementById("b-saved")?.value;
  if (!id || id === BUILD_LIST.primary_id) return;
  BUILD_LIST = await window.pywebview.api.build_set_primary(id);
  syncBuildHeaderControls(BUILD_LIST);
  toast("Definida como build principal");
}

async function buildCreateNew() {
  const name = await modalPrompt("Nova build", "Nome da build...", "Criar");
  if (!name) return;
  const res = await window.pywebview.api.build_save({
    id: "",
    name: name.trim(),
    hp_per_rmt: 30,
    cells: emptyCells(),
    base_stats: emptyBaseStats(),
    character: emptyCharacter(),
    make_primary: false,
  });
  if (!res.ok) { toast("Erro ao criar build"); return; }
  BUILD_LIST = res;
  await loadBuildById(res.id);
  syncBuildHeaderControls(BUILD_LIST);
  renderBuildCharacterPanel();
  renderBuildSlotPanel();
  renderBuildStatsPanel();
  buildDisplaySavedPrices();
}

async function buildDeleteCurrent() {
  const builds = BUILD_LIST.builds || [];
  if (builds.length <= 1) return;
  const id = BUILD.id || document.getElementById("b-saved")?.value;
  if (!id) return;
  const current = builds.find((b) => b.id === id);
  const name = current?.name || "Build";
  if (!(await modalConfirmDanger(`Excluir build «${name}»?\n\nEsta ação não pode ser desfeita.`))) return;

  const idx = builds.findIndex((b) => b.id === id);
  const res = await window.pywebview.api.build_delete(id);
  if (!res.ok) { toast(res.error || "Erro ao excluir build"); return; }

  BUILD_LIST = res;
  const remaining = BUILD_LIST.builds || [];
  const nextId = remaining[Math.max(0, idx - 1)]?.id || remaining[0]?.id || "";
  await loadBuildById(nextId);
  syncBuildHeaderControls(BUILD_LIST);
  renderBuildCharacterPanel();
  renderBuildSlotPanel();
  renderBuildStatsPanel();
  buildDisplaySavedPrices();
  toast("Build excluída");
}

function bindBuildHeaderControls() {
  document.getElementById("b-saved")?.addEventListener("change", buildOnSavedChange);
  document.getElementById("b-primary-star")?.addEventListener("click", buildSetPrimaryClick);
  document.getElementById("b-delete")?.addEventListener("click", buildDeleteCurrent);
  document.getElementById("b-add")?.addEventListener("click", buildCreateNew);
}

async function renderBuild() {
  head().innerHTML = `
    <div class="ph-title">
      <h2>Simulação de Build</h2>
      <p>Equipamento, visuais (shadows) e atributos IRO</p>
    </div>
    ${buildHeadToolsHtml()}`;
  view().innerHTML = '<div class="sp-state"><div class="spinner"></div>Carregando…</div>';
  if (!BUILD_META) BUILD_META = await window.pywebview.api.build_meta();

  const list = await window.pywebview.api.build_list();
  BUILD_LIST = list;
  if (!BUILD) {
    BUILD = { id: "", name: "", hp_per_rmt: 30, cells: emptyCells(), base_stats: emptyBaseStats(), character: emptyCharacter() };
    BUILD_LAYER = "equip";
    if (list.primary_id) await loadBuildById(list.primary_id);
    else if (list.builds?.length) await loadBuildById(list.builds[0].id);
  } else {
    await ensureBuildItemStats();
  }

  view().innerHTML = `
    <div class="build">
      <div class="build-totals">
        <div class="bt-rate bt-rate-head">
          <div class="bt-rate-copy">
            <span class="bt-rate-label">Valor total</span>
            <span class="bt-rate-val" id="b-rate-val">—</span>
          </div>
          <button id="b-refresh" class="lbtn ghost bt-refresh-btn" type="button">Atualizar preços</button>
        </div>
        <div class="bt-summary-row">
          <div class="bt-summary">
            <h4>Preços das lojas</h4>
            <div class="bt-line"><span>Total RMT</span><strong class="bt-rmt" id="bt-market-rmt">—</strong></div>
            <div class="bt-line"><span>Total HP</span><strong class="bt-hp" id="bt-market-hp">—</strong></div>
          </div>
          <div class="bt-summary">
            <h4>Preços manuais</h4>
            <div class="bt-line"><span>Total RMT</span><strong class="bt-rmt" id="bt-manual-rmt">—</strong></div>
            <div class="bt-line"><span>Total HP</span><strong class="bt-hp" id="bt-manual-hp">—</strong></div>
          </div>
          <div class="bt-summary bt-summary-total">
            <h4>Total Geral</h4>
            <div class="bt-line"><span>Total RMT</span><strong class="bt-total-rmt" id="bt-total-rmt">—</strong></div>
            <div class="bt-line"><span>Total HP</span><strong class="bt-total-hp bt-hp" id="bt-total-hp">—</strong></div>
          </div>
        </div>
      </div>
      <div class="build-main">
        <div class="build-equip-zone">
          <div class="build-equip-head">
            <div>
              <h3 id="b-layer-title">Equipamento</h3>
              <p class="build-equip-sub" id="b-layer-sub">Slots principais — clique em ↻ para ver visuais (shadows)</p>
            </div>
            <button type="button" id="b-rotate" class="lbtn ghost b-rotate-btn" title="Alternar equipamento / visuais">↻ Visuais</button>
          </div>
          <div class="bpanel-cols" id="bp-slots"></div>
        </div>
        <div class="build-stats-zone">
          <div id="build-character-zone"></div>
          <div id="build-stats-panels"></div>
        </div>
      </div>
    </div>`;

  syncBuildHeaderControls(list);
  bindBuildHeaderControls();
  renderBuildCharacterPanel();
  renderBuildSlotPanel();
  renderBuildStatsPanel();
  document.getElementById("b-refresh").addEventListener("click", buildRefreshPrices);
  document.getElementById("b-rotate").addEventListener("click", buildRotateLayer);
  buildDisplaySavedPrices();
}

function buildSavedDropdown(list) {
  syncBuildHeaderControls(list);
}

function activeBuildLayer() {
  return BUILD_LAYER === "visual" ? "visual" : "equip";
}

function mergeBuildVisibleLayerFromUI() {
  flushVisibleLayerToBuildState();
}

function syncBuildVisibleSlotPrices() {
  if (!BUILD_META) return;
  const layer = activeBuildLayer();
  [...BUILD_META.left, ...BUILD_META.right].forEach((sk) => syncSlotPriceUI(layer, sk));
}

async function ensureBuildItemStats() {
  if (!BUILD_META || !BUILD?.cells) return;
  const pending = [];
  ["equip", "visual"].forEach((layer) => {
    [...BUILD_META.left, ...BUILD_META.right].forEach((sk) => {
      const cell = BUILD.cells[layer]?.[sk];
      if (!cell?.item_id) return;
      if (cell.item_stats && typeof cell.item_stats === "object") return;
      pending.push((async () => {
        const res = await window.pywebview.api.build_resolve(cell.item_id, cell.refine || 0);
        if (!res?.ok) return;
        cell.item_stats = res.item_stats || null;
        cell.item_description = res.description || cell.item_description || "";
        cell.weapon_base = res.weapon_base || cell.weapon_base || null;
        if (!cell.item_name) cell.item_name = res.item_name || "";
        if (cell.price_rmt == null && cell.price_hp == null && !cell.manual_price && res.prices) {
          cell.price_rmt = res.prices.rmt != null ? res.prices.rmt : null;
          cell.price_hp = res.prices.hp != null ? res.prices.hp : null;
        }
      })());
    });
  });
  if (pending.length) await Promise.all(pending);
}

function buildRotateLayer() {
  flushVisibleLayerToBuildState();
  BUILD_LAYER = BUILD_LAYER === "equip" ? "visual" : "equip";
  const title = document.getElementById("b-layer-title");
  const sub = document.getElementById("b-layer-sub");
  const btn = document.getElementById("b-rotate");
  if (BUILD_LAYER === "visual") {
    if (title) title.textContent = "Visuais (shadows)";
    if (sub) sub.textContent = "Equipamento cosmético — clique em ↻ para voltar ao equipamento principal";
    if (btn) btn.textContent = "↻ Equipamento";
  } else {
    if (title) title.textContent = "Equipamento";
    if (sub) sub.textContent = "Slots principais — clique em ↻ para ver visuais (shadows)";
    if (btn) btn.textContent = "↻ Visuais";
  }
  renderBuildSlotPanel();
  buildRecalcTotalsLocal();
}

function renderBuildSlotPanel() {
  const host = document.getElementById("bp-slots");
  if (!host || !BUILD_META) return;
  ensureBuildCellsIntegrity();
  const layer = BUILD_LAYER === "visual" ? "visual" : "equip";
  host.innerHTML = "";
  const colL = el("div", "bcol"), colR = el("div", "bcol");
  BUILD_META.left.forEach((sk) => colL.appendChild(buildSlot(layer, sk)));
  BUILD_META.right.forEach((sk) => colR.appendChild(buildSlot(layer, sk)));
  host.appendChild(colL);
  host.appendChild(colR);
  if (layer === "equip") buildSyncTwoHand();
}

function renderBuildPanels() {
  renderBuildCharacterPanel();
  renderBuildSlotPanel();
  renderBuildStatsPanel();
}

function buildSlot(layer, sk) {
  const cell = BUILD.cells[layer][sk];
  const prices = cellPriceFields(cell);
  const slot = el("div", `bslot${prices.manual ? " bslot-manual" : ""}`);
  slot.dataset.layer = layer; slot.dataset.slot = sk;
  const nm = cell.item_id ? (cell.item_name || `Item ${cell.item_id}`) : "—";
  const manualTag = prices.manual ? '<span class="bslot-manual-tag">MANUAL</span>' : "";
  slot.innerHTML = `
    <div class="bslot-label">${escapeHtml(BUILD_META.labels[sk] || sk)}${manualTag}</div>
    <div class="bslot-name">${escapeHtml(nm)}</div>
    <div class="bslot-row1">
      <div class="bslot-ic">${cell.icon ? `<img src="${cell.icon}" alt="">` : "·"}</div>
      <input class="bslot-id" type="text" placeholder="ID" maxlength="12" value="${cell.item_id || ""}">
      <span class="bslot-reflbl">+</span>
      <input class="bslot-ref" type="number" min="0" max="20" value="${cell.refine || 0}">
      <div class="bslot-row-actions">
        <button class="bslot-go lbtn success">Buscar</button>
      </div>
    </div>
    <div class="bslot-prices">
      <label class="bslot-manual-toggle" title="Usar preços definidos por si; deixa de actualizar automaticamente">
        <input type="checkbox" class="bslot-manual-chk"${prices.manual ? " checked" : ""}${cell.item_id ? "" : " disabled"}> Manual
      </label>
      <label class="bslot-price-field">
        <span class="bp-rmt-lbl">RMT</span>
        <input class="bslot-price-rmt" type="text" inputmode="decimal"${prices.manual ? "" : " disabled"} placeholder="${prices.manual ? "0" : "—"}" value="${escapeHtml(prices.rmt)}">
      </label>
      <label class="bslot-price-field">
        <span class="bp-hp-lbl">HP</span>
        <input class="bslot-price-hp" type="text" inputmode="decimal"${prices.manual ? "" : " disabled"} placeholder="${prices.manual ? "0" : "—"}" value="${escapeHtml(prices.hp)}">
      </label>
    </div>`;
  slot.querySelector(".bslot-go").addEventListener("click", () => buildSearchSlot(layer, sk, slot));
  slot.querySelector(".bslot-manual-chk").addEventListener("change", (e) => {
    buildToggleManual(layer, sk, e.target.checked);
  });
  slot.querySelector(".bslot-price-rmt").addEventListener("input", () => buildManualPriceChanged(layer, sk));
  slot.querySelector(".bslot-price-hp").addEventListener("input", () => buildManualPriceChanged(layer, sk));
  syncSlotPriceUI(layer, sk);
  return slot;
}

function slotEl(layer, sk) {
  return document.querySelector(`.bslot[data-layer="${layer}"][data-slot="${sk}"]`);
}

function buildSyncTwoHand() {
  const block = !!BUILD.cells.equip.weapon_right.is_2h;
  const left = slotEl("equip", "weapon_left");
  if (!left) return;
  left.classList.toggle("disabled", block);
  left.querySelectorAll("input, button").forEach((i) => (i.disabled = block));
}

async function buildSearchSlot(layer, sk, slot) {
  if (layer === "equip" && sk === "weapon_left" && BUILD.cells.equip.weapon_right.is_2h) {
    toast("A arma na mão direita ocupa as duas mãos"); return;
  }
  const idVal = slot.querySelector(".bslot-id").value.trim();
  const refVal = Number(slot.querySelector(".bslot-ref").value) || 0;
  if (!idVal) {
    BUILD.cells[layer][sk] = emptyCellState();
    refreshSlotUI(layer, sk);
    renderBuildCharacterPanel();
    renderBuildStatsPanel();
    buildRecalcTotalsLocal();
    await buildAutoSave();
    return;
  }
  const go = slot.querySelector(".bslot-go");
  go.disabled = true; go.textContent = "…";
  const res = await window.pywebview.api.build_resolve(idVal, refVal);
  go.disabled = false; go.textContent = "Buscar";
  if (!res.ok) { toast("Erro: " + (res.error || "")); return; }
  BUILD.cells[layer][sk] = {
    item_id: res.id, item_name: res.item_name, refine: res.refine, is_2h: res.is_2h,
    icon: res.icon, item_icon_url: res.item_icon_url,
    manual_price: false,
    price_rmt: res.prices && res.prices.rmt != null ? res.prices.rmt : null,
    price_hp: res.prices && res.prices.hp != null ? res.prices.hp : null,
    item_stats: res.item_stats || null,
    item_description: res.description || "",
    weapon_base: res.weapon_base || null,
  };
  if (layer === "equip" && sk === "weapon_right" && res.is_2h) {
    BUILD.cells.equip.weapon_left = emptyCellState();
    refreshSlotUI("equip", "weapon_left");
  }
  refreshSlotUI(layer, sk);
  buildSyncTwoHand();
  syncSlotPriceUI(layer, sk);
  renderBuildCharacterPanel();
  renderBuildStatsPanel();
  buildRecalcTotalsLocal();
  await buildAutoSave();
}

function refreshSlotUI(layer, sk) {
  const slot = slotEl(layer, sk);
  if (!slot) return;
  const cell = BUILD.cells[layer][sk];
  slot.querySelector(".bslot-id").value = cell.item_id || "";
  slot.querySelector(".bslot-ref").value = cell.refine || 0;
  slot.querySelector(".bslot-ic").innerHTML = cell.icon ? `<img src="${cell.icon}" alt="">` : "·";
  slot.querySelector(".bslot-name").textContent = cell.item_id ? (cell.item_name || `Item ${cell.item_id}`) : "—";
  if (!cell.item_id) {
    cell.manual_price = false;
    cell.price_rmt = null;
    cell.price_hp = null;
    cell.item_stats = null;
    cell.item_description = "";
  }
  syncSlotPriceUI(layer, sk);
}

function syncSlotPriceUI(layer, sk) {
  const slot = slotEl(layer, sk);
  const cell = BUILD.cells?.[layer]?.[sk];
  if (!slot || !cell) return;
  const prices = cellPriceFields(cell);
  cell.manual_price = prices.manual;
  slot.classList.toggle("bslot-manual", prices.manual);
  const lbl = slot.querySelector(".bslot-label");
  if (lbl) {
    const base = escapeHtml(BUILD_META.labels[sk] || sk);
    lbl.innerHTML = base + (prices.manual ? '<span class="bslot-manual-tag">MANUAL</span>' : "");
  }
  const chk = slot.querySelector(".bslot-manual-chk");
  const rmtIn = slot.querySelector(".bslot-price-rmt");
  const hpIn = slot.querySelector(".bslot-price-hp");
  if (chk) {
    chk.checked = prices.manual;
    chk.disabled = !cell.item_id;
  }
  if (rmtIn) {
    rmtIn.disabled = !prices.manual;
    rmtIn.value = prices.rmt;
    rmtIn.placeholder = prices.manual ? "0" : "—";
  }
  if (hpIn) {
    hpIn.disabled = !prices.manual;
    hpIn.value = prices.hp;
    hpIn.placeholder = prices.manual ? "0" : "—";
  }
}

function applyAutoSlotPrice(layer, sk, pr) {
  const cell = BUILD.cells?.[layer]?.[sk];
  writeAutoPricesToCell(cell, pr);
  syncSlotPriceUI(layer, sk);
}

function mergeBuildInputs() {
  flushVisibleLayerToBuildState();
}

function mergeBuildPricesFromUI() {
  flushVisibleLayerToBuildState();
}

async function buildToggleManual(layer, sk, checked) {
  const cell = BUILD.cells[layer][sk];
  if (!cell?.item_id) return;
  if (checked) {
    cell.manual_price = true;
    syncSlotPriceUI(layer, sk);
    buildRecalcTotalsLocal();
    await buildAutoSave();
    return;
  }
  cell.manual_price = false;
  const res = await window.pywebview.api.build_resolve(cell.item_id, cell.refine);
  if (res && res.ok) {
    cell.price_rmt = res.prices && res.prices.rmt != null ? res.prices.rmt : null;
    cell.price_hp = res.prices && res.prices.hp != null ? res.prices.hp : null;
  }
  syncSlotPriceUI(layer, sk);
  buildRecalcTotalsLocal();
  await buildAutoSave();
}

let _buildManualSaveTimer = null;
let _buildAutoSaveTimer = null;

function scheduleBuildAutoSave() {
  clearTimeout(_buildAutoSaveTimer);
  _buildAutoSaveTimer = setTimeout(() => buildAutoSave(), 450);
}

function buildManualPriceChanged(layer, sk) {
  const cell = BUILD.cells[layer][sk];
  if (!cell?.manual_price) return;
  mergeBuildPricesFromUI();
  buildRecalcTotalsLocal();
  clearTimeout(_buildManualSaveTimer);
  _buildManualSaveTimer = setTimeout(() => buildAutoSave(), 450);
}

async function buildRefreshPrices() {
  flushVisibleLayerToBuildState();
  const btn = document.getElementById("b-refresh");
  if (btn) { btn.disabled = true; btn.textContent = "Atualizando…"; }
  const res = await window.pywebview.api.build_prices(BUILD.cells, BUILD.hp_per_rmt || BUILD_MARKET.hp_per_rmt);
  if (btn) { btn.disabled = false; btn.textContent = "Atualizar preços"; }
  if (!res.ok) return;
  ensureBuildCellsIntegrity();
  ["equip", "visual"].forEach((layer) => {
    Object.entries(res.slots[layer] || {}).forEach(([sk, pr]) => {
      writeAutoPricesToCell(BUILD.cells[layer][sk], pr);
    });
  });
  buildApplyTotalsPayload(res);
  syncBuildVisibleSlotPrices();
  buildRecalcTotalsLocal();
  await buildAutoSave();
}

function buildDisplaySavedPrices() {
  BUILD_MARKET.hp_per_rmt = BUILD.hp_per_rmt || BUILD_MARKET.hp_per_rmt || 30;
  updateBuildRateDisplay();
  syncBuildVisibleSlotPrices();
  buildRecalcTotalsLocal();
}

function buildCollectEntries(manualOnly) {
  const entries = [];
  if (!BUILD_META || !BUILD?.cells) return entries;
  ["equip", "visual"].forEach((layer) => {
    [...BUILD_META.left, ...BUILD_META.right].forEach((sk) => {
      const cell = BUILD.cells[layer][sk];
      if (!cell?.item_id) return;
      if (manualOnly && !cell.manual_price) return;
      if (!manualOnly && cell.manual_price) return;
      entries.push({ rmt: cell.price_rmt, hp: cell.price_hp });
    });
  });
  return entries;
}

function buildAccumulateTotals(entries, rate) {
  const r = rate > 0 ? rate : 30;
  let totalRmt = 0;
  let totalHp = 0;
  let slots = 0;
  entries.forEach((ent) => {
    const rv = ent.rmt != null && ent.rmt !== "" ? Number(ent.rmt) : null;
    const hv = ent.hp != null && ent.hp !== "" ? Number(ent.hp) : null;
    const rValid = rv != null && !isNaN(rv) && rv > 0 ? rv : null;
    const hValid = hv != null && !isNaN(hv) && hv > 0 ? hv : null;
    if (rValid == null && hValid == null) return;
    slots += 1;
    if (rValid != null && hValid != null) {
      totalRmt += Math.min(rValid, hValid / r);
      totalHp += Math.min(hValid, rValid * r);
    } else if (rValid != null) {
      totalRmt += rValid;
      totalHp += rValid * r;
    } else {
      totalHp += hValid;
      totalRmt += hValid / r;
    }
  });
  return { total_rmt: totalRmt, total_hp: totalHp, slots };
}

function buildApplyTotalsPayload(res) {
  if (!res) return;
  BUILD_MARKET.hp_per_rmt = res.hp_per_rmt || 30;
  BUILD_MARKET.rmt_per_100k_hp = res.rmt_per_100k_hp;
  BUILD_MARKET.samples = res.conversion_samples || 0;
  BUILD_MARKET.source = res.conversion_source || "";
  BUILD_MARKET.reference_item_id = res.reference_item_id || 40111;
  BUILD.hp_per_rmt = BUILD_MARKET.hp_per_rmt;
  updateBuildRateDisplay();
  updateBuildTotalsDisplay(res.market_totals, res.manual_totals);
}

function updateBuildRateDisplay() {
  const el = document.getElementById("b-rate-val");
  if (!el) return;
  const r100 = BUILD_MARKET.rmt_per_100k_hp;
  const rate = BUILD_MARKET.hp_per_rmt || 30;
  const rmt = r100 != null ? r100 : rate > 0 ? 100_000 / rate : null;
  el.textContent = rmt != null ? `100.000 HP = ${coin(rmt)} RMT` : "—";
}

function updateBuildTotalsDisplay(market, manual) {
  const set = (id, val) => {
    const e = document.getElementById(id);
    if (e) e.textContent = val;
  };
  const fmtBlock = (t) => {
    if (!t || !t.slots) return { rmt: "—", hp: "—", rmtNum: 0, hpNum: 0, hasData: false };
    const rmtNum = Number(t.total_rmt) || 0;
    const hpNum = Number(t.total_hp) || 0;
    return { rmt: coin(rmtNum), hp: coin(hpNum), rmtNum, hpNum, hasData: true };
  };
  const m = fmtBlock(market);
  const mn = fmtBlock(manual);
  set("bt-market-rmt", m.rmt);
  set("bt-market-hp", m.hp);
  set("bt-manual-rmt", mn.rmt);
  set("bt-manual-hp", mn.hp);
  const hasAny = m.hasData || mn.hasData;
  const totalRmt = m.rmtNum + mn.rmtNum;
  const totalHp = m.hpNum + mn.hpNum;
  set("bt-total-rmt", hasAny ? coin(totalRmt) : "—");
  set("bt-total-hp", hasAny ? coin(totalHp) : "—");
}

function buildRecalcTotalsLocal() {
  mergeBuildPricesFromUI();
  const rate = BUILD_MARKET.hp_per_rmt || 30;
  updateBuildTotalsDisplay(
    buildAccumulateTotals(buildCollectEntries(false), rate),
    buildAccumulateTotals(buildCollectEntries(true), rate),
  );
}

async function buildAutoSave() {
  mergeBuildInputs();
  mergeBuildPricesFromUI();
  mergeBuildBaseStatsFromUI();
  mergeBuildCharacterFromUI();
  BUILD.hp_per_rmt = BUILD_MARKET.hp_per_rmt || BUILD.hp_per_rmt || 30;
  if (!BUILD.name) BUILD.name = "Minha build";
  const res = await window.pywebview.api.build_save({
    id: BUILD.id || "",
    name: BUILD.name,
    hp_per_rmt: BUILD.hp_per_rmt,
    cells: BUILD.cells,
    base_stats: BUILD.base_stats,
    character: BUILD.character,
    make_primary: !BUILD.id,
  });
  if (!res.ok) return false;
  BUILD.id = res.id;
  buildSavedDropdown(res);
  return true;
}

// ── Auto Loot ───────────────────────────────────────────────
let LOOT = { groups: [] };
let LOOT_RESULTS = [];
let LOOT_TARGET = null;

async function renderLoot() {
  head().innerHTML = `<div class="ph-title"><h2>Auto Loot</h2><p>Monte grupos @alootid2 e copie comandos com 1 clique</p></div>`;
  view().innerHTML = `
    <div class="loot-search">
      <div class="loot-srow">
        <div class="search loot-input">
          <svg viewBox="0 0 24 24" class="search-ic"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          <input id="loot-q" type="text" placeholder="Nome, um ID ou vários IDs separados por vírgula (ex.: 522, 2610, 2613)…" autocomplete="off" />
        </div>
        <button id="loot-go" class="lbtn success">Buscar</button>
        <label class="loot-target">Adicionar na lista <select id="loot-target"></select></label>
      </div>
      <div id="loot-chips" class="loot-chips"></div>
    </div>
    <div id="loot-board" class="loot-board"><div class="sp-state"><div class="spinner"></div>Carregando listas…</div></div>`;

  const q = document.getElementById("loot-q");
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") lootSearch(); });
  document.getElementById("loot-go").addEventListener("click", lootSearch);

  LOOT = await window.pywebview.api.loot_get();
  drawLootTargets();
  drawLootBoard();
}

function drawLootTargets() {
  const sel = document.getElementById("loot-target");
  if (!sel) return;
  const groups = LOOT.groups || [];
  sel.innerHTML = groups.map((g) => `<option value="${g.number}">Lista ${g.number} — ${escapeHtml(g.name)}</option>`).join("");
  if (LOOT_TARGET && groups.some((g) => g.number === LOOT_TARGET)) sel.value = String(LOOT_TARGET);
  else LOOT_TARGET = groups.length ? groups[0].number : null;
}

async function lootSearch() {
  const q = document.getElementById("loot-q").value.trim();
  const out = document.getElementById("loot-chips");
  if (!q) { out.innerHTML = ""; return; }
  out.innerHTML = '<div class="loot-state"><div class="spinner"></div>Buscando…</div>';
  try {
    const res = await window.pywebview.api.loot_search(q);
    if (!res.ok) { out.innerHTML = `<div class="loot-state err">Erro: ${escapeHtml(res.error || "")}</div>`; return; }
    LOOT_RESULTS = res.items || [];
    drawLootChips();
  } catch (err) {
    out.innerHTML = `<div class="loot-state err">Erro: ${escapeHtml(String(err))}</div>`;
  }
}

function drawLootChips() {
  const out = document.getElementById("loot-chips");
  if (!LOOT_RESULTS.length) { out.innerHTML = '<div class="loot-state">Nenhum item encontrado.</div>'; return; }
  out.innerHTML = "";
  LOOT_RESULTS.forEach((it) => {
    const chip = el("div", "loot-chip");
    chip.title = "Adicionar à lista selecionada";
    chip.innerHTML = `${it.icon ? `<img src="${it.icon}" alt="">` : '<span class="lc-ph">?</span>'}<span class="lc-nm">${escapeHtml(it.name)} (${it.id})</span><span class="lc-add">+</span>`;
    chip.addEventListener("click", () => lootAdd(it));
    out.appendChild(chip);
  });
}

async function lootAdd(it) {
  const sel = document.getElementById("loot-target");
  const target = sel ? Number(sel.value) : LOOT_TARGET;
  if (!target) return;
  const res = await window.pywebview.api.loot_add(target, it);
  if (!res.ok && res.error) toast(res.error);
  else toast(`Adicionado à Lista ${target}`);
  LOOT = res; drawLootTargets(); drawLootBoard();
}

function drawLootBoard() {
  const board = document.getElementById("loot-board");
  if (!board) return;
  board.innerHTML = "";
  (LOOT.groups || []).forEach((g) => board.appendChild(lootCard(g)));
  const ghost = el("div", "loot-card loot-ghost");
  if ((LOOT.groups || []).length < (LOOT.max_groups || 9)) {
    ghost.innerHTML = '<div class="lg-plus">+</div><div>Nova lista</div>';
    ghost.addEventListener("click", async () => { LOOT = await window.pywebview.api.loot_add_group(); drawLootTargets(); drawLootBoard(); });
  } else {
    ghost.innerHTML = '<div class="lg-lim">Limite de 9 listas</div>';
  }
  board.appendChild(ghost);
}

function lootCard(g) {
  const card = el("div", "loot-card");
  const cnt = (g.items || []).length;
  const pct = Math.round((cnt / (LOOT.max_items || 10)) * 100);
  const barColor = cnt >= 9 ? "#ef4444" : cnt >= 5 ? "#f59e0b" : "#3b82f6";

  const head = el("div", "lg-head");
  const nameEl = el("span", "lg-name", escapeHtml(g.name));
  nameEl.title = "Clique para renomear";
  nameEl.addEventListener("click", () => lootRename(g, nameEl));
  head.appendChild(nameEl);
  head.appendChild(el("span", "lg-count", `${cnt}/${LOOT.max_items || 10}`));
  card.appendChild(head);

  const bar = el("div", "lg-bar");
  const fill = el("div", "lg-fill");
  fill.style.width = pct + "%"; fill.style.background = barColor;
  bar.appendChild(fill);
  card.appendChild(bar);

  const body = el("div", "lg-body");
  (g.items || []).forEach((it) => {
    const r = el("div", "lg-item");
    r.innerHTML = `<div class="lg-ic">${it.icon ? `<img src="${it.icon}" alt="">` : "?"}</div>
      <div class="lg-info"><div class="lg-it-name">${escapeHtml(it.name)}</div><div class="lg-it-sub">ID ${it.id} · NPC ${it.npc_sell_price ? fmtZeny(it.npc_sell_price) : "—"}</div></div>`;
    const rm = el("button", "lg-rm", "✕");
    rm.title = "Remover item";
    rm.addEventListener("click", async () => { LOOT = await window.pywebview.api.loot_remove(g.number, it.id); drawLootBoard(); });
    r.appendChild(rm);
    body.appendChild(r);
  });
  const vagas = (LOOT.max_items || 10) - cnt;
  if (vagas > 0) body.appendChild(el("div", "lg-empty", `···· ${vagas} vaga(s) ····`));
  card.appendChild(body);

  const foot = el("div", "lg-foot");
  foot.appendChild(el("div", "lg-cmd", escapeHtml(g.save_cmd)));
  const btns = el("div", "lg-btns");
  const bsave = el("button", "lbtn ghost", "Copiar save");
  bsave.addEventListener("click", () => copyLoot(bsave, g.save_cmd, "Copiar save"));
  const bload = el("button", "lbtn success", "Copiar load");
  bload.addEventListener("click", () => copyLoot(bload, g.load_cmd, "Copiar load"));
  btns.appendChild(bsave); btns.appendChild(bload);
  foot.appendChild(btns);
  const del = el("button", "lg-del", "Excluir lista");
  del.addEventListener("click", async () => {
    if (!(await modalConfirm(`Excluir a lista «${g.name}» (${cnt} item(ns))?`))) return;
    const res = await window.pywebview.api.loot_delete_group(g.number);
    if (!res.ok && res.error) { toast(res.error); return; }
    LOOT = res; drawLootTargets(); drawLootBoard();
  });
  foot.appendChild(del);
  card.appendChild(foot);
  return card;
}

async function lootRename(g, nameEl) {
  const newName = await modalPrompt("Renomear lista", g.name);
  if (!newName) return;
  LOOT = await window.pywebview.api.loot_rename(g.number, newName);
  drawLootTargets(); drawLootBoard();
}

async function copyLoot(btn, cmd, original) {
  const ok = await copyText(cmd);
  btn.textContent = ok ? "✓ Copiado!" : "Erro";
  setTimeout(() => (btn.textContent = original), 1400);
}

function fmtZeny(v) { return (Number(v) || 0).toLocaleString("pt-BR") + "z"; }

function setStatus(id, text) { const e = document.getElementById(id); if (e) e.textContent = text; }
function updateNavBadge() {
  const b = document.getElementById("nav-badge");
  if (b) b.textContent = STATE && STATE.total ? String(STATE.total) : "";
}

// ── Páginas por portar ─────────────────────────────────────
const PH_ICONS = {
  timer: '<path d="M12 8v4l3 2M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  bell: '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  gear: '<path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" fill="none" stroke="currentColor" stroke-width="2"/>',
};
// ── Timer MVP ───────────────────────────────────────────────
let MVP = { filter: "todos", query: "", cards: [], shown: 0, total: 0, gen: 0 };
let _mvpTick = null;
let _mvpSearchTimer = null;
const MVP_FILTERS = [
  ["todos", "Todos os MVPs"],
  ["ativos", "Timers ativos"],
  ["pendente", "Respawn pendente"],
  ["disponiveis", "Disponíveis"],
];

function localNowStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function mvpDeathToBR(iso) {
  const s = String(iso || "").trim();
  if (!s) return "";
  const norm = s.replace("T", " ").slice(0, 16);
  const m = norm.match(/^(\d{4})-(\d{2})-(\d{2})\s(\d{2}):(\d{2})/);
  if (m) return `${m[2]}/${m[3]}/${m[1]} ${m[4]}:${m[5]}`;
  if (/^\d{2}\/\d{2}\/\d{4}/.test(norm)) return norm.slice(0, 16);
  return norm;
}

function mvpDeathToISO(masked) {
  const s = String(masked || "").trim();
  if (!s) return "";
  const m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})\s(\d{2}):(\d{2})/);
  if (m) return `${m[3]}-${m[2]}-${m[1]} ${m[4]}:${m[5]}`;
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.replace("T", " ").slice(0, 16);
  return s;
}

function localNowStrBR() {
  return mvpDeathToBR(localNowStr());
}

function bindMvpDeathMaskInput(input) {
  if (!input) return;
  input.setAttribute("maxlength", "16");
  input.setAttribute("inputmode", "numeric");
  input.setAttribute("placeholder", "DD/MM/AAAA HH:MM");
  input.addEventListener("input", () => {
    const value = input.value.replace(/\D/g, "");
    let masked = "";
    if (value.length > 0) masked += value.substring(0, 2);
    if (value.length > 2) masked += "/" + value.substring(2, 4);
    if (value.length > 4) masked += "/" + value.substring(4, 8);
    if (value.length > 8) masked += " " + value.substring(8, 10);
    if (value.length > 10) masked += ":" + value.substring(10, 12);
    input.value = masked;
  });
}
function mvpClock(su) {
  if (su == null || Number.isNaN(su)) return "-- : -- : --";
  const neg = su < 0;
  let s = Math.floor(Math.abs(su));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  const pad = (n) => String(n).padStart(2, "0");
  const body = (d > 0 ? `${d}d ` : "") + `${pad(h)} : ${pad(m)} : ${pad(s)}`;
  if (su === 0) return "00 : 00 : 00";
  return (neg ? "-" : "") + body;
}
function mvpStatus(nextMs) {
  if (nextMs == null) return "NÃO REGISTRADO";
  return nextMs - Date.now() > 0 ? "RESPAWN PENDENTE" : "DISPONÍVEL";
}
function mvpClockColor(nextMs) {
  if (nextMs == null) return "var(--text3)";
  return nextMs - Date.now() > 0 ? "#34d399" : "#f87171";
}

async function renderMvp() {
  head().innerHTML = `
    <div class="ph-title">
      <h2>Timer MVP</h2>
      <p>Catálogo de MVPs. «Registrar» marca a morte; o timer começa após «Salvar».</p>
    </div>
    <div class="ph-actions">
      <div class="mvp-filters" id="mvp-filters">
        ${MVP_FILTERS.map(([v, l]) => `<button class="mvp-fbtn${v === MVP.filter ? " active" : ""}" data-f="${v}">${l}</button>`).join("")}
      </div>
      <button class="lbtn danger" id="mvp-reset">Resetar timers</button>
      <div class="count-pill"><span id="mvp-status">…</span></div>
    </div>
    <div class="ph-actions">
      <div class="search">
        <svg viewBox="0 0 24 24" class="search-ic"><path d="M21 21l-4.3-4.3M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        <input id="mvp-search" type="text" placeholder="Buscar MVP (nome ou ID)…" autocomplete="off" value="${escapeHtml(MVP.query)}" />
      </div>
    </div>`;
  view().innerHTML = '<div class="sp-state"><div class="spinner"></div>Carregando catálogo de MVPs…</div>';

  document.getElementById("mvp-filters").addEventListener("click", (e) => {
    const b = e.target.closest(".mvp-fbtn");
    if (!b) return;
    MVP.filter = b.dataset.f;
    document.querySelectorAll(".mvp-fbtn").forEach((x) => x.classList.toggle("active", x.dataset.f === MVP.filter));
    loadMvpCards();
  });
  document.getElementById("mvp-reset").addEventListener("click", mvpResetAll);
  document.getElementById("mvp-search").addEventListener("input", (e) => {
    MVP.query = e.target.value;
    clearTimeout(_mvpSearchTimer);
    _mvpSearchTimer = setTimeout(loadMvpCards, 280);
  });

  await loadMvpCards();
  startMvpTick();
}

async function loadMvpCards() {
  const grid = document.getElementById("view");
  const gen = ++MVP.gen;
  try {
    const res = await window.pywebview.api.mvp_cards(MVP.filter, MVP.query);
    if (gen !== MVP.gen || CURRENT !== "mvp") return;
    MVP.cards = (res && res.cards) || [];
    MVP.total = (res && res.total) || 0;
    setStatus("mvp-status", `${MVP.cards.length} de ${MVP.total} MVPs`);
    drawMvpGrid();
    loadMvpSprites(gen);
  } catch (err) {
    if (grid) grid.innerHTML = `<div class="sp-state err">Erro: ${escapeHtml(String(err))}</div>`;
  }
}

function drawMvpGrid() {
  const wrap = el("div", "mvp-grid");
  if (!MVP.cards.length) {
    wrap.appendChild(el("div", "empty-box", MVP.query
      ? `Nenhum MVP encontrado para «${escapeHtml(MVP.query)}».`
      : "Nenhum MVP neste filtro."));
  } else {
    MVP.cards.forEach((c) => wrap.appendChild(mvpCard(c)));
  }
  view().innerHTML = "";
  view().appendChild(wrap);
}

function mvpCard(c) {
  const card = el("div", "mvp-card");
  card.dataset.id = c.id;
  if (c.next_ms != null) card.dataset.next = c.next_ms;
  const dm = c.death_map || "—";
  const coords = c.coords || "—";
  card.innerHTML = `
    <div class="mvp-sprite" data-sprite="${c.id}"><span class="mvp-sp-ph">…</span></div>
    <div class="mvp-name">${escapeHtml(c.name)}</div>
    <div class="mvp-id">ID ${c.id}</div>
    <div class="mvp-map">${escapeHtml(dm)}</div>
    <div class="mvp-coords">Coords ${escapeHtml(coords)}</div>
    ${c.respawn_min ? `<div class="mvp-resp">Respawn ${c.respawn_min} min</div>` : ""}
    <div class="mvp-box">
      <div class="mvp-st">${mvpStatus(c.next_ms)}</div>
      <div class="mvp-clock" style="color:${mvpClockColor(c.next_ms)}">${mvpClock(c.next_ms != null ? (c.next_ms - Date.now()) / 1000 : null)}</div>
    </div>`;
  const btn = el("button", "mvp-btn", c.registered ? "⏱ Editar timer" : "⏱ Registrar");
  btn.addEventListener("click", () => c.registered ? openMvpEdit(c.entry_id) : mvpRegister(c));
  card.appendChild(btn);
  return card;
}

async function loadMvpSprites(gen) {
  for (const c of MVP.cards) {
    if (gen !== MVP.gen || CURRENT !== "mvp") return;
    const host = document.querySelector(`.mvp-sprite[data-sprite="${c.id}"]`);
    if (!host) continue;
    try {
      const r = await window.pywebview.api.mvp_sprite(c.id, c.name);
      if (gen !== MVP.gen) return;
      if (r && r.ok && r.icon) host.innerHTML = `<img src="${r.icon}" alt="">`;
      else host.innerHTML = '<span class="mvp-sp-ph">—</span>';
    } catch (_) { host.innerHTML = '<span class="mvp-sp-ph">—</span>'; }
  }
}

function startMvpTick() {
  stopMvpTick();
  _mvpTick = setInterval(() => {
    if (CURRENT !== "mvp") { stopMvpTick(); return; }
    document.querySelectorAll("#view .mvp-card").forEach((card) => {
      const nm = card.dataset.next ? Number(card.dataset.next) : null;
      const clk = card.querySelector(".mvp-clock");
      const st = card.querySelector(".mvp-st");
      if (clk) {
        clk.textContent = mvpClock(nm != null ? (nm - Date.now()) / 1000 : null);
        clk.style.color = mvpClockColor(nm);
      }
      if (st) st.textContent = mvpStatus(nm);
    });
  }, 1000);
}
function stopMvpTick() { if (_mvpTick) { clearInterval(_mvpTick); _mvpTick = null; } }

async function mvpRegister(c) {
  toast("Registrando MVP…");
  const res = await window.pywebview.api.mvp_register(c.id);
  if (!res || !res.ok) { toast("Erro: " + ((res && res.error) || "")); return; }
  await loadMvpCards();
  openMvpEdit(res.entry_id);
}

async function mvpResetAll() {
  if (!(await modalConfirm("Resetar todos os timers? Isto remove a hora de morte e as coordenadas de cada MVP registado."))) return;
  const res = await window.pywebview.api.mvp_reset_all();
  toast(res && res.ok ? "Timers resetados" : "Erro ao resetar");
  loadMvpCards();
}

async function openMvpEdit(entryId) {
  const e = await window.pywebview.api.mvp_get_entry(entryId);
  if (!e || !e.ok) { toast("Timer não encontrado"); return; }
  const back = el("div", "modal-back");
  const box = el("div", "modal-box mvp-edit");
  const maps = e.maps || [];
  const defDeath = e.death_at ? mvpDeathToBR(e.death_at) : localNowStrBR();
  const lastDeath = e.death_at ? `Última morte registada: ${mvpDeathToBR(e.death_at)}` : "";
  box.innerHTML = `
    <p class="modal-msg">⏱ Editar timer — ${escapeHtml(e.name)}</p>
    <p class="mvp-help">Marque o mapa e a hora da morte. Ao «Salvar», o timer reinicia a partir dessa hora + respawn.</p>
    ${lastDeath ? `<p class="mvp-help mvp-last">${escapeHtml(lastDeath)}</p>` : ""}
    <div class="me-row">
      <label class="me-col">Mapa da morte
        <select id="me-map" class="modal-input">
          ${maps.length ? maps.map((m) => `<option value="${escapeHtml(m)}"${m === e.death_map ? " selected" : ""}>${escapeHtml(m)}</option>`).join("") : '<option value="">(sem mapa)</option>'}
        </select>
      </label>
      <label class="me-col">Respawn (min)<input id="me-resp" class="modal-input" type="number" min="1" value="${e.respawn_min}"></label>
    </div>
    <div class="me-row">
      <div class="me-col me-grow">
        <input id="me-death" class="modal-input" type="text" value="${escapeHtml(defDeath)}">
      </div>
      <div class="me-col me-xy"><input id="me-x" class="modal-input coord-input" type="text" placeholder="X" value="${e.death_x != null ? e.death_x : ""}"></div>
      <div class="me-col me-xy"><input id="me-y" class="modal-input coord-input" type="text" placeholder="Y" value="${e.death_y != null ? e.death_y : ""}"></div>
    </div>
    <div class="me-mapbox" id="me-mapbox"><div class="me-map-state">Escolha o mapa…</div></div>
    <div class="me-status" id="me-status"></div>`;
  const actions = el("div", "modal-actions");
  const cancel = el("button", "modal-btn ghost", "Fechar");
  const save = el("button", "modal-btn primary", "Salvar");
  actions.appendChild(cancel); actions.appendChild(save);
  box.appendChild(actions); back.appendChild(box); document.body.appendChild(back);
  requestAnimationFrame(() => back.classList.add("show"));
  const close = () => { back.classList.remove("show"); setTimeout(() => back.remove(), 200); };
  cancel.addEventListener("click", close);
  back.addEventListener("click", (ev) => { if (ev.target === back) close(); });

  const mapSel = box.querySelector("#me-map");
  const xIn = box.querySelector("#me-x");
  const yIn = box.querySelector("#me-y");
  const deathIn = box.querySelector("#me-death");
  bindMvpDeathMaskInput(deathIn);
  const statusEl = box.querySelector("#me-status");
  const mapbox = box.querySelector("#me-mapbox");
  let MAP = null;

  async function loadMap() {
    const dm = mapSel.value.trim();
    mapbox.innerHTML = '<div class="me-map-state">Carregando mapa…</div>';
    MAP = null;
    if (!dm) { mapbox.innerHTML = '<div class="me-map-state">Sem mapa para este MVP.</div>'; return; }
    let r;
    try { r = await window.pywebview.api.mvp_map(dm); } catch (err) { r = { ok: false, error: String(err) }; }
    if (!r || !r.ok) { mapbox.innerHTML = `<div class="me-map-state">${escapeHtml((r && r.error) || "Sem imagem do mapa.")}</div>`; return; }
    const bin = atob(r.mask);
    const mask = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) mask[i] = bin.charCodeAt(i);
    const box_side = 360;
    const scale = box_side / Math.max(r.nw, r.nh);
    const dw = Math.round(r.nw * scale), dh = Math.round(r.nh * scale);
    MAP = { nw: r.nw, nh: r.nh, mask, scale, dw, dh };
    mapbox.innerHTML = `
      <div class="me-map-frame" id="me-frame" style="width:${dw}px;height:${dh}px">
        <img src="${r.image}" style="width:${dw}px;height:${dh}px;image-rendering:pixelated" draggable="false">
        <div class="me-marker" id="me-marker" style="display:none"></div>
      </div>`;
    const frame = box.querySelector("#me-frame");
    frame.addEventListener("mousemove", (ev) => {
      const g = frameToGame(ev, frame);
      if (g && isClickable(g.gx, g.gy)) {
        frame.style.cursor = "crosshair";
        statusEl.textContent = `X=${g.gx}  Y=${g.gy}  (${MAP.nw}×${MAP.nh}) — clique para marcar`;
      } else {
        frame.style.cursor = "not-allowed";
        statusEl.textContent = "Fora da área jogável — clique nas zonas coloridas";
      }
    });
    frame.addEventListener("click", (ev) => {
      const g = frameToGame(ev, frame);
      if (!g || !isClickable(g.gx, g.gy)) { statusEl.textContent = "Clique fora do mapa: toque na área colorida."; return; }
      xIn.value = g.gx; yIn.value = g.gy;
      drawMarker(g.gx, g.gy);
      statusEl.textContent = `Posição marcada: X=${g.gx}  Y=${g.gy}`;
    });
    if (xIn.value !== "" && yIn.value !== "" && dm === e.death_map) {
      drawMarker(Number(xIn.value), Number(yIn.value));
    }
  }
  function frameToGame(ev, frame) {
    const rect = frame.getBoundingClientRect();
    const lx = ev.clientX - rect.left, ly = ev.clientY - rect.top;
    if (lx < 0 || ly < 0 || lx >= MAP.dw || ly >= MAP.dh) return null;
    const gx = Math.max(0, Math.min(MAP.nw - 1, Math.floor(lx / MAP.scale)));
    const iy = Math.max(0, Math.min(MAP.nh - 1, Math.floor(ly / MAP.scale)));
    return { gx, gy: MAP.nh - 1 - iy };
  }
  function isClickable(gx, gy) {
    if (!MAP || gx < 0 || gy < 0 || gx >= MAP.nw || gy >= MAP.nh) return false;
    const iy = MAP.nh - 1 - gy;
    return MAP.mask[iy * MAP.nw + gx] !== 0;
  }
  function drawMarker(gx, gy) {
    const marker = box.querySelector("#me-marker");
    if (!marker || !MAP) return;
    const iy = MAP.nh - 1 - gy;
    marker.style.left = ((gx + 0.5) * MAP.scale) + "px";
    marker.style.top = ((iy + 0.5) * MAP.scale) + "px";
    marker.style.display = "block";
  }

  mapSel.addEventListener("change", loadMap);
  await loadMap();

  save.addEventListener("click", async () => {
    save.disabled = true; save.textContent = "Salvando…";
    let deathAt = deathIn.value.trim();
    if (!deathAt) deathAt = localNowStrBR();
    deathAt = mvpDeathToISO(deathAt);
    const payload = {
      death_at: deathAt,
      respawn_min: Number(box.querySelector("#me-resp").value) || 60,
      death_map: mapSel.value.trim(),
      death_x: xIn.value.trim(),
      death_y: yIn.value.trim(),
    };
    const res = await window.pywebview.api.mvp_save_entry(entryId, payload);
    if (res && res.ok) {
      toast(res.next_ms ? "Timer reiniciado" : "Timer salvo (sem contagem — falta hora de morte)");
      close();
      await loadMvpCards();
    } else {
      toast("Erro: " + ((res && res.error) || ""));
      save.disabled = false;
      save.textContent = "Salvar";
    }
  });
}

// Vigia global de spawn (som + aviso) — corre em qualquer página.
let _mvpSpawnWatch = null;
let _alertNotifyWatch = null;
let _knownNotifIds = new Set();
let _notifyDrawerOpen = false;

function fmtNotifTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return String(ts);
    return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return String(ts);
  }
}

function updateNotifyBadge(unread) {
  const b = document.getElementById("notify-badge");
  if (!b) return;
  const n = Number(unread) || 0;
  b.textContent = n > 99 ? "99+" : String(n);
  b.classList.toggle("show", n > 0);
}

function notifyMetaHtml(n) {
  const sale = n.sale_type || "zeny";
  const cur = CURRENCY[sale] || CURRENCY.zeny;
  const cond = n.alert_type === "below" ? "abaixo de" : "acima de";
  const priceChip = `<span class="chip ${escapeHtml(sale)}">${cur.fmt(n.price)} ${cur.label}</span>`;
  const th = `<span class="notify-th">${cond} ${cur.fmt(n.threshold)} ${cur.label}</span>`;
  return `${priceChip}<span class="notify-dot">·</span>${th}`;
}

function notifyCardHtml(n) {
  const icon = n.icon
    ? `<img src="${escapeHtml(n.icon)}" alt="">`
    : `<span class="notify-thumb-ph">?</span>`;
  return `<div class="notify-card ${n.read ? "" : "unread"}" data-id="${escapeHtml(n.id)}" data-item-id="${Number(n.item_id) || ""}" role="button" tabindex="0">
    <div class="notify-thumb">${icon}</div>
    <div class="notify-body">
      <div class="notify-item-title">${escapeHtml(n.item_name || "Item")}</div>
      <div class="notify-item-meta">${notifyMetaHtml(n)}</div>
      <div class="notify-item-ts">${escapeHtml(fmtNotifTime(n.ts))}</div>
    </div>
    <button type="button" class="notify-card-x" data-id="${escapeHtml(n.id)}" aria-label="Remover notificação" title="Remover">×</button>
  </div>`;
}

function renderNotifyDrawerContent(items) {
  const drawer = document.getElementById("notify-drawer");
  if (!drawer) return;
  const list = items || [];
  const unread = list.filter((n) => !n.read).length;
  const bodyHtml = list.length
    ? `<div class="notify-list">${list.map((n) => notifyCardHtml(n)).join("")}</div>`
    : `<div class="notify-empty">Sem notificações de alerta.<br>Quando um preço cumprir o critério, aparece aqui.</div>`;
  drawer.innerHTML = `
    <div class="notify-drawer-head">
      <div class="notify-drawer-title">
        <h3>Notificações</h3>
        <p>${list.length ? `${list.length} alerta(s) · ${unread} não lida(s)` : "Nenhum alerta recente"}</p>
      </div>
      <div class="notify-drawer-actions">
        <button type="button" class="notify-clear-all" id="notify-clear-all" ${list.length ? "" : "disabled"}>Limpar todas</button>
        <button type="button" class="drawer-close" id="notify-drawer-close" aria-label="Fechar">×</button>
      </div>
    </div>
    <div class="notify-drawer-body">${bodyHtml}</div>`;

  drawer.querySelector("#notify-drawer-close")?.addEventListener("click", closeNotifyDrawer);
  drawer.querySelector("#notify-clear-all")?.addEventListener("click", clearAllNotifications);

  const listEl = drawer.querySelector(".notify-list");
  if (listEl) {
    listEl.addEventListener("click", async (e) => {
      const xBtn = e.target.closest(".notify-card-x");
      if (xBtn) {
        e.preventDefault();
        e.stopPropagation();
        const id = xBtn.dataset.id;
        if (!id) return;
        await window.pywebview.api.remove_alert_notification(id);
        toast("Notificação removida");
        await refreshNotifyUI();
        return;
      }
      const card = e.target.closest(".notify-card");
      if (!card) return;
      const id = card.dataset.id;
      const itemId = Number(card.dataset.itemId);
      const name = card.querySelector(".notify-item-title")?.textContent || "Item";
      const icon = card.querySelector(".notify-thumb img")?.getAttribute("src") || "";
      if (id) await window.pywebview.api.mark_alert_notifications_read([id]);
      closeNotifyDrawer();
      await refreshNotifyUI();
      if (itemId > 0) openDetail({ id: itemId, name, icon });
      else go("alerts");
    });
  }
}

async function clearAllNotifications() {
  const drawer = document.getElementById("notify-drawer");
  const count = drawer?.querySelectorAll(".notify-card").length || 0;
  if (!count) return;
  if (!(await modalConfirm(`Remover todas as ${count} notificações?`))) return;
  await window.pywebview.api.clear_alert_notifications();
  toast("Notificações removidas");
  await refreshNotifyUI();
}

async function refreshNotifyUI() {
  try {
    const r = await window.pywebview.api.get_alert_notifications(false);
    updateNotifyBadge(r.unread || 0);
    if (_notifyDrawerOpen) renderNotifyDrawerContent(r.items || []);
    return r;
  } catch (_) {
    return { unread: 0, items: [] };
  }
}

function openNotifyDrawer() {
  const drawer = document.getElementById("notify-drawer");
  const overlay = document.getElementById("overlay");
  const bell = document.getElementById("notify-bell");
  if (!drawer || !overlay) return;
  closeDetail();
  _notifyDrawerOpen = true;
  overlay.classList.remove("hidden");
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  if (bell) {
    bell.classList.add("open");
    bell.setAttribute("aria-expanded", "true");
  }
  refreshNotifyUI();
}

function closeNotifyDrawer() {
  const drawer = document.getElementById("notify-drawer");
  const overlay = document.getElementById("overlay");
  const bell = document.getElementById("notify-bell");
  const detailOpen = document.getElementById("drawer")?.classList.contains("open");
  _notifyDrawerOpen = false;
  if (drawer) {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
  }
  if (bell) {
    bell.classList.remove("open");
    bell.setAttribute("aria-expanded", "false");
  }
  if (!detailOpen && overlay) overlay.classList.add("hidden");
}

function initNotifications() {
  const bell = document.getElementById("notify-bell");
  if (!bell) return;
  bell.addEventListener("click", (e) => {
    e.stopPropagation();
    if (_notifyDrawerOpen) closeNotifyDrawer();
    else openNotifyDrawer();
  });
}

function showPriceAlertPopup(n) {
  let host = document.getElementById("spawn-host");
  if (!host) { host = el("div"); host.id = "spawn-host"; document.body.appendChild(host); }
  const cur = CURRENCY[n.sale_type] || CURRENCY.zeny;
  const card = el("div", "spawn-pop price-alert-pop");
  card.innerHTML = `
    <div class="sp-tag">ALERTA DE PREÇO</div>
    <div class="sp-name">${escapeHtml(n.item_name || "Item")}</div>
    <div class="sp-map">${escapeHtml(n.shop || "Loja")} · ${cur.fmt(n.price)} ${cur.label}</div>
    <div class="sp-born">CRITÉRIO CUMPRIDO</div>
    <button class="sp-close">Fechar</button>`;
  card.querySelector(".sp-close").addEventListener("click", () => card.remove());
  host.appendChild(card);
  requestAnimationFrame(() => card.classList.add("show"));
  setTimeout(() => { card.classList.remove("show"); setTimeout(() => card.remove(), 300); }, 28000);
}

async function pollAlertNotifications() {
  try {
    const r = await window.pywebview.api.get_alert_notifications(true);
    updateNotifyBadge(r.unread || 0);
    (r.items || []).forEach((n) => {
      if (!n.id || _knownNotifIds.has(n.id)) return;
      _knownNotifIds.add(n.id);
      beep();
      showPriceAlertPopup(n);
      toast(n.message || "Alerta de preço");
    });
    if (_notifyDrawerOpen) {
      const all = await window.pywebview.api.get_alert_notifications(false);
      renderNotifyDrawerContent(all.items || []);
    }
  } catch (_) {}
}

function startAlertNotifyWatch() {
  if (_alertNotifyWatch) return;
  refreshNotifyUI().then((r) => {
    (r.items || []).forEach((n) => { if (n.id) _knownNotifIds.add(n.id); });
  });
  pollAlertNotifications();
  _alertNotifyWatch = setInterval(pollAlertNotifications, 12000);
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.type = "sine"; o.frequency.value = 880;
    g.gain.setValueAtTime(0.12, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
    o.start(); o.stop(ctx.currentTime + 0.6);
  } catch (_) {}
}
function showSpawnPopup(name, map) {
  let host = document.getElementById("spawn-host");
  if (!host) { host = el("div"); host.id = "spawn-host"; document.body.appendChild(host); }
  const card = el("div", "spawn-pop");
  card.innerHTML = `
    <div class="sp-tag">MVP — RESPAWN</div>
    <div class="sp-name">${escapeHtml(name || "MVP")}</div>
    ${map ? `<div class="sp-map">Mapa: ${escapeHtml(map)}</div>` : ""}
    <div class="sp-born">NASCEU!</div>
    <button class="sp-close">Fechar</button>`;
  card.querySelector(".sp-close").addEventListener("click", () => card.remove());
  host.appendChild(card);
  requestAnimationFrame(() => card.classList.add("show"));
  setTimeout(() => { card.classList.remove("show"); setTimeout(() => card.remove(), 300); }, 30000);
}
function startMvpSpawnWatch() {
  if (_mvpSpawnWatch) return;
  _mvpSpawnWatch = setInterval(async () => {
    try {
      const r = await window.pywebview.api.mvp_check_spawns();
      if (r && r.fired && r.fired.length) {
        r.fired.forEach((f) => { beep(); showSpawnPopup(f.name, f.map); });
        if (CURRENT === "mvp") loadMvpCards();
      }
    } catch (_) {}
  }, 2000);
}

function placeholder(title, msg, icon) {
  head().innerHTML = `<div class="ph-title"><h2>${escapeHtml(title)}</h2><p>Página em migração para a versão web</p></div>`;
  view().innerHTML = `
    <div class="placeholder">
      <div class="ph-ic"><svg viewBox="0 0 24 24">${PH_ICONS[icon] || ""}</svg></div>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(msg)}</p>
      <span class="soon">Em breve nesta versão</span>
    </div>`;
}

// ── Drawer de detalhe ──────────────────────────────────────
function closeDetail() {
  _drawerId = null;
  _histData = null;
  _histCur = null;
  document.getElementById("drawer").classList.remove("open");
  if (!_notifyDrawerOpen) document.getElementById("overlay").classList.add("hidden");
}
const COLOR = { zeny: "#fbbf24", rmt: "#c084fc", hero_points: "#f472b6" };

function priceChart(points, currencyKey) {
  if (!points || points.length < 2) return '<div class="chart-empty">Histórico insuficiente para o gráfico.</div>';
  const prices = points.map((p) => p.price);
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || 1;
  const W = 100, H = 42;
  const stepX = W / (points.length - 1);
  const coords = points.map((p, i) => `${(i * stepX).toFixed(2)},${(H - ((p.price - min) / range) * H).toFixed(2)}`);
  const color = COLOR[currencyKey] || COLOR.zeny;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon points="0,${H} ${coords.join(" ")} ${W},${H}" fill="url(#cg)"/>
    <polyline points="${coords.join(" ")}" fill="none" stroke="${color}" stroke-width="1.4" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
  </svg>`;
}

function statBox(label, value, key) {
  const fmt = (CURRENCY[key] || CURRENCY.zeny).fmt;
  return `<div class="stat"><span class="s-l">${label}</span><span class="s-v">${fmt(value)}</span></div>`;
}

function descriptionBlock(desc, weight) {
  if (!desc && !weight) return '<div class="chart-empty">Sem descrição disponível.</div>';
  const lines = (desc || "").split("\n").map((l) => l.trim()).filter(Boolean);
  const body = lines.map((l) => `<div class="d-line">${escapeHtml(l)}</div>`).join("");
  const w = weight ? `<div class="d-line d-weight">Peso: ${escapeHtml(weight)}</div>` : "";
  return `<div class="desc">${body}${w}</div>`;
}

let _vendorShopSeq = 0;

function vendorShopLayer() {
  return document.getElementById("vendor-shop-layer");
}

function vendorShopStack() {
  return document.getElementById("vendor-shop-stack");
}

function syncVendorShopLayer() {
  const layer = vendorShopLayer();
  const stack = vendorShopStack();
  if (!layer || !stack) return;
  const open = stack.children.length > 0;
  layer.classList.toggle("open", open);
  layer.setAttribute("aria-hidden", open ? "false" : "true");
}

function closeVendorShopModal(modalEl) {
  if (!modalEl) return;
  modalEl.remove();
  syncVendorShopLayer();
}

function closeTopVendorShopModal() {
  const stack = vendorShopStack();
  if (!stack || !stack.lastElementChild) return;
  closeVendorShopModal(stack.lastElementChild);
}

function bindVendorShopModal(modalEl) {
  modalEl.querySelector(".vshop-close")?.addEventListener("click", () => closeVendorShopModal(modalEl));
}

function vendorShopLoadingHtml() {
  return `<div class="vshop-body"><div class="vshop-state"><div class="spinner"></div>Carregando loja…</div></div>`;
}

function vendorShopErrorHtml(message, vendorId) {
  return `<div class="vshop-body"><div class="vshop-state err">
    ${escapeHtml(message || "Não foi possível carregar a loja. Tente novamente.")}
    <button type="button" class="lbtn ghost vshop-retry" data-retry="${vendorId}">Tentar novamente</button>
  </div></div>`;
}

function vshopCell(val) {
  const s = String(val ?? "").trim();
  if (!s || s.toLowerCase() === "nenhum" || s.toLowerCase() === "n/a") {
    return `<span class="vshop-muted">—</span>`;
  }
  return escapeHtml(s);
}

function renderVendorShopModal(modalEl, data) {
  const badges = [
    data.currency ? `<span class="chip">${escapeHtml(data.currency)}</span>` : "",
    data.autotrade ? `<span class="chip">AUTO</span>` : "",
  ].filter(Boolean).join(" ");
  const loc = [
    data.go_cmd ? `<code>${escapeHtml(data.go_cmd)}</code>` : "",
    data.navi_cmd ? `<code>${escapeHtml(data.navi_cmd)}</code>` : "",
  ].filter(Boolean).join("");
  const avatar = data.avatar_url
    ? `<img src="${escapeHtml(data.avatar_url)}" alt="">`
    : `<span class="vshop-muted">?</span>`;

  if (data.empty || !data.items?.length) {
    modalEl.innerHTML = `
      <div class="vshop-head">
        <div class="vshop-avatar">${avatar}</div>
        <div class="vshop-meta">
          <div class="vshop-vendor">${escapeHtml(data.vendor_name || "Vendedor")}</div>
          <h3>${escapeHtml(data.shop_title || "Loja")}</h3>
          ${badges ? `<div class="vshop-sub">${badges}</div>` : ""}
          ${loc ? `<div class="vshop-loc">${loc}</div>` : ""}
        </div>
        <button type="button" class="vshop-close" aria-label="Fechar">×</button>
      </div>
      <div class="vshop-body"><div class="vshop-state">Esta loja não possui itens no momento.</div></div>`;
    bindVendorShopModal(modalEl);
    return;
  }

  const rows = data.items.map((it) => {
    const ref = it.refinement > 0 ? `<span class="refine-badge">+${it.refinement}</span>` : `<span class="vshop-muted">—</span>`;
    return `<tr class="vshop-item-row" data-item-id="${it.item_id || ""}" data-item-name="${String(it.item_name || "").replace(/"/g, "&quot;")}">
      <td><div class="vshop-item-name">${it.icon ? `<img src="${it.icon}" alt="">` : ""}<span>${escapeHtml(it.item_name || "—")}</span><span class="vshop-monitor-slot"></span></div></td>
      <td>${ref}</td>
      <td>${vshopCell(it.slots)}</td>
      <td>${vshopCell(it.slot1)}</td>
      <td>${vshopCell(it.slot2)}</td>
      <td>${vshopCell(it.slot3)}</td>
      <td>${vshopCell(it.slot4)}</td>
      <td>${vshopCell(it.random_options)}</td>
      <td class="vshop-price">${escapeHtml(it.price_text || "—")}</td>
      <td>${escapeHtml(String(it.quantity ?? 1))}</td>
    </tr>`;
  }).join("");

  modalEl.innerHTML = `
    <div class="vshop-head">
      <div class="vshop-avatar">${avatar}</div>
      <div class="vshop-meta">
        <div class="vshop-vendor">${escapeHtml(data.vendor_name || "Vendedor")}</div>
        <h3>${escapeHtml(data.shop_title || "Loja")}</h3>
        ${badges ? `<div class="vshop-sub">${badges}</div>` : ""}
        ${loc ? `<div class="vshop-loc">${loc}</div>` : ""}
      </div>
      <button type="button" class="vshop-close" aria-label="Fechar">×</button>
    </div>
    <div class="vshop-body">
      <div class="vshop-table-wrap">
        <table class="vshop-table">
          <thead><tr>
            <th>Nome</th><th>Ref.</th><th>Slots</th><th>S1</th><th>S2</th><th>S3</th><th>S4</th><th>Random</th><th>Preço</th><th>Qtd</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;

  bindVendorShopModal(modalEl);
  modalEl.querySelectorAll(".vshop-item-row").forEach((row) => {
    const iid = Number(row.dataset.itemId);
    const slot = row.querySelector(".vshop-monitor-slot");
    if (slot && iid) {
      slot.appendChild(createMonitorButtonCompact({
        id: iid,
        name: row.dataset.itemName || `Item ${iid}`,
        icon: row.querySelector("img")?.src || "",
      }));
    }
    row.addEventListener("click", (e) => {
      if (e.target.closest(".result-add")) return;
      if (!iid) return;
      openDetail({ id: iid, name: row.dataset.itemName || `Item ${iid}`, icon: row.querySelector("img")?.src || "" });
    });
  });
}

async function openVendorShop(vendorId, shopHint) {
  const vid = Number(vendorId);
  if (!vid) {
    toast("Loja indisponível (sem ID de vendedor).");
    return;
  }
  const layer = vendorShopLayer();
  const stack = vendorShopStack();
  if (!layer || !stack) return;

  const modal = document.createElement("div");
  modal.className = "vendor-shop-modal";
  modal.dataset.vendorId = String(vid);
  modal.innerHTML = `
    <div class="vshop-head">
      <div class="vshop-meta" style="flex:1">
        <div class="vshop-vendor">${escapeHtml(shopHint || "Vendedor")}</div>
        <h3>Carregando loja…</h3>
      </div>
      <button type="button" class="vshop-close" aria-label="Fechar">×</button>
    </div>
    ${vendorShopLoadingHtml()}`;
  bindVendorShopModal(modal);
  stack.appendChild(modal);
  syncVendorShopLayer();

  try {
    const data = await window.pywebview.api.get_vendor_shop(vid);
    if (!stack.contains(modal)) return;
    if (!data.ok) {
      modal.innerHTML = `
        <div class="vshop-head">
          <div class="vshop-meta" style="flex:1"><h3>${escapeHtml(shopHint || "Loja")}</h3></div>
          <button type="button" class="vshop-close" aria-label="Fechar">×</button>
        </div>
        ${vendorShopErrorHtml(data.error, vid)}`;
      bindVendorShopModal(modal);
      modal.querySelector(".vshop-retry")?.addEventListener("click", () => {
        closeVendorShopModal(modal);
        openVendorShop(vid, shopHint);
      });
      return;
    }
    if (data.avatar_url && !data.avatar) data.avatar = data.avatar_url;
    renderVendorShopModal(modal, data);
  } catch (err) {
    if (!stack.contains(modal)) return;
    modal.innerHTML = `
      <div class="vshop-head">
        <div class="vshop-meta" style="flex:1"><h3>${escapeHtml(shopHint || "Loja")}</h3></div>
        <button type="button" class="vshop-close" aria-label="Fechar">×</button>
      </div>
      ${vendorShopErrorHtml(String(err), vid)}`;
    bindVendorShopModal(modal);
    modal.querySelector(".vshop-retry")?.addEventListener("click", () => {
      closeVendorShopModal(modal);
      openVendorShop(vid, shopHint);
    });
  }
}

function bindVendorStoreRows(container) {
  if (!container) return;
  container.querySelectorAll(".store-row-clickable").forEach((row) => {
    row.addEventListener("click", (e) => {
      e.stopPropagation();
      openVendorShop(row.dataset.vendorId, row.dataset.shop || "");
    });
  });
}

document.getElementById("vendor-shop-backdrop")?.addEventListener("click", closeTopVendorShopModal);

async function openDetail(item) {
  closeNotifyDrawer();
  const drawer = document.getElementById("drawer");
  const overlay = document.getElementById("overlay");
  drawer.innerHTML = `
    <div class="drawer-head">
      <div class="thumb">${item.icon ? `<img src="${item.icon}" alt="">` : ""}</div>
      <div class="d-title"><h3>${escapeHtml(item.name)}</h3><div class="id">ID ${item.id ?? "—"}</div></div>
      <button class="drawer-close" id="drawer-close" aria-label="Fechar">×</button>
    </div>
    <div class="drawer-min">
      <div class="dm-chips" id="dm-chips">${priceChips(item.prices)}</div>
      <button class="alert-btn" id="d-alert" title="Criar alerta de preço">🔔 Alerta</button>
      <button class="ws-btn" id="d-ws" title="Copiar comando @ws para o jogo">@ws</button>
    </div>
    <div class="drawer-body">
      <div class="d-cols">
        <aside class="d-left">
          <div class="sec-label">Descrição & status</div>
          <div id="d-desc"><div class="drawer-state"><div class="spinner"></div></div></div>
        </aside>
        <div class="d-right">
          <div class="sec-label">Lojas online</div>
          <div id="d-stores"><div class="drawer-state"><div class="spinner"></div>Buscando lojas ao vivo…</div></div>
          <div class="sec-row">
            <span class="sec-label">Vendas por moeda</span>
            <div class="cur-tabs" id="cur-tabs"></div>
          </div>
          <div id="d-chart" class="hist-box"><div class="drawer-state"><div class="spinner"></div>Carregando gráfico…</div></div>
          <div class="sec-label">Histórico das vendas</div>
          <div id="d-sales"><div class="drawer-state"><div class="spinner"></div>Carregando vendas…</div></div>
        </div>
      </div>
    </div>`;
  overlay.classList.remove("hidden");
  drawer.classList.add("open");
  document.getElementById("drawer-close").addEventListener("click", closeDetail);
  document.getElementById("d-ws").addEventListener("click", () => copyWs(item.id));
  document.getElementById("d-alert").addEventListener("click", () => openAlertModal(item));
  document.getElementById("d-ws").before(createMonitorButton(item));

  _drawerId = item.id;
  loadDetailStores(item, item.id);
  loadDetailHistory(item.id);
}

async function loadDetailStores(item, reqId) {
  try {
    const d = await window.pywebview.api.get_item_detail(item.id);
    if (reqId !== currentDrawerId()) return;
    const storesEl = document.getElementById("d-stores");
    const descEl = document.getElementById("d-desc");
    if (!d.ok) {
      if (storesEl) storesEl.innerHTML = `<div class="drawer-state err">Não foi possível carregar: ${escapeHtml(d.error || "erro")}</div>`;
      return;
    }
    const chipsEl = document.getElementById("dm-chips");
    if (chipsEl) chipsEl.innerHTML = priceChips(d.min_prices);
    if (d.monitored) syncMonitorButtonsForItem(item.id, true);
    if (descEl) descEl.innerHTML = descriptionBlock(d.description, d.weight);
    if (!storesEl) return;
    if (!d.stores.length) {
      storesEl.innerHTML = '<div class="drawer-state">Nenhuma loja online neste momento.</div>';
      return;
    }
    storesEl.innerHTML = d.stores.map((s, i) => {
      const cur = CURRENCY[s.currency] || CURRENCY.zeny;
      const ref = s.refinement > 0 ? `<span class="refine-badge">+${s.refinement}</span>` : "";
      const extra = [s.quantity > 1 ? `${s.quantity}x` : "", s.cards > 0 ? "com carta" : ""].filter(Boolean).join(" · ");
      const clickable = s.vendor_id ? " store-row-clickable" : "";
      const vendorAttr = s.vendor_id
        ? ` data-vendor-id="${s.vendor_id}" data-shop="${String(s.shop || "").replace(/"/g, "&quot;")}" title="Ver loja completa"`
        : "";
      return `<div class="store-row${clickable}"${vendorAttr} style="animation-delay:${i * 30}ms">
        ${ref}
        <div class="shop"><div class="nm">${escapeHtml(s.shop)}</div><div class="meta">${escapeHtml(extra || "unidade")}${s.vendor_id ? " · clique para abrir loja" : ""}</div></div>
        <div class="pr" style="color:var(--${s.currency})">${cur.fmt(s.price)} ${cur.label}</div>
      </div>`;
    }).join("");
    bindVendorStoreRows(storesEl);
  } catch (err) {
    const storesEl = document.getElementById("d-stores");
    if (storesEl && reqId === currentDrawerId()) storesEl.innerHTML = `<div class="drawer-state err">Erro: ${escapeHtml(String(err))}</div>`;
  }
}

const CUR_TAB_LABEL = { zeny: "ZENY", rmt: "RMT", hero_points: "HP" };
let _histData = null;
let _histCur = null;

async function loadDetailHistory(reqId) {
  try {
    const h = await window.pywebview.api.get_price_history(reqId);
    if (reqId !== currentDrawerId()) return;
    const cb = document.getElementById("d-chart");
    const sb = document.getElementById("d-sales");
    const tabs = document.getElementById("cur-tabs");
    if (!h.ok) {
      if (tabs) tabs.innerHTML = "";
      if (cb) cb.innerHTML = `<div class="chart-empty">Sem histórico (${escapeHtml(h.error || "erro")}).</div>`;
      if (sb) sb.innerHTML = "";
      return;
    }
    _histData = h;
    _histCur = h.default || "zeny";
    renderCurTabs();
    renderHistoryFor(_histCur);
  } catch (err) {
    if (reqId !== currentDrawerId()) return;
    const cb = document.getElementById("d-chart");
    if (cb) cb.innerHTML = `<div class="chart-empty">Erro no histórico.</div>`;
  }
}

function renderCurTabs() {
  const tabs = document.getElementById("cur-tabs");
  if (!tabs || !_histData) return;
  tabs.innerHTML = ORDER.map((k) => {
    const has = (_histData.currencies[k] && _histData.currencies[k].count) ? "" : " empty";
    const active = k === _histCur ? " active" : "";
    return `<button class="cur-tab${active}${has}" data-cur="${k}" style="--c:${COLOR[k]}">${CUR_TAB_LABEL[k]}</button>`;
  }).join("");
  tabs.querySelectorAll(".cur-tab").forEach((b) =>
    b.addEventListener("click", () => {
      _histCur = b.dataset.cur;
      renderCurTabs();
      renderHistoryFor(_histCur);
    }));
}

function renderHistoryFor(cur) {
  const cb = document.getElementById("d-chart");
  const sb = document.getElementById("d-sales");
  const data = _histData && _histData.currencies ? _histData.currencies[cur] : null;
  const label = CURRENCY[cur] || CURRENCY.zeny;

  if (cb) {
    if (!data || !data.points || data.points.length < 2) {
      cb.innerHTML = '<div class="chart-empty">Histórico insuficiente nesta moeda.</div>';
    } else {
      const st = data.stats || {};
      cb.innerHTML = `
        ${priceChart(data.points, cur)}
        <div class="stats">
          ${statBox("Último", st.last || 0, cur)}
          ${statBox("Mínimo", st.min || 0, cur)}
          ${statBox("Médio", st.avg || 0, cur)}
          ${statBox("Máximo", st.max || 0, cur)}
        </div>`;
    }
  }
  if (sb) {
    const sales = (data && data.sales) || [];
    if (!sales.length) sb.innerHTML = '<div class="chart-empty">Sem vendas registadas nesta moeda.</div>';
    else sb.innerHTML = sales.map((s) => `
      <div class="sale-row">
        <div class="sl">
          <div class="sl-when">${escapeHtml(shortDate(s.date))}</div>
          <div class="sl-who">${escapeHtml(s.seller || "?")} → ${escapeHtml(s.buyer || "?")}${s.qty > 1 ? ` · ${s.qty}x` : ""}</div>
        </div>
        <div class="sl-pr" style="color:${COLOR[cur]}">${label.fmt(s.price)} ${label.label}</div>
      </div>`).join("");
  }
}

function shortDate(s) {
  const str = String(s || "");
  // "2026-06-05 20:15:05" → "05/06 20:15"
  const m = str.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (m) return `${m[3]}/${m[2]} ${m[4]}:${m[5]}`;
  return str.slice(0, 16);
}

async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; } catch (_) {}
  try {
    const ta = document.createElement("textarea");
    ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok;
  } catch (_) { return false; }
}
async function copyWs(id) {
  const cmd = `@ws ${id}`;
  const ok = await copyText(cmd);
  toast(ok ? `Copiado: ${cmd}` : "Não foi possível copiar");
}

let _toastTimer = null;
function toast(msg) {
  let t = document.getElementById("toast");
  if (!t) { t = el("div", "toast"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
}

let _drawerId = null;
function currentDrawerId() { return _drawerId; }

// ── Modais ─────────────────────────────────────────────────
function modalConfirm(message) { return modalBase({ message, confirm: "Confirmar", input: false }); }
function modalConfirmDanger(message) { return modalBase({ message, confirm: "Excluir", input: false, danger: true }); }
function modalPrompt(title, placeholder, confirmLabel) {
  return modalBase({ message: title, confirm: confirmLabel || "Adicionar", input: true, placeholder });
}
function modalBase({ message, confirm, input, placeholder, danger }) {
  return new Promise((resolve) => {
    const back = el("div", "modal-back");
    const box = el("div", "modal-box");
    box.innerHTML = `<p class="modal-msg">${escapeHtml(message)}</p>` +
      (input ? `<input class="modal-input" type="text" placeholder="${escapeHtml(placeholder || "")}">` : "");
    const actions = el("div", "modal-actions");
    const cancel = el("button", "modal-btn ghost", "Cancelar");
    const ok = el("button", `modal-btn ${danger ? "danger" : "primary"}`, confirm);
    actions.appendChild(cancel); actions.appendChild(ok);
    box.appendChild(actions); back.appendChild(box); document.body.appendChild(back);
    requestAnimationFrame(() => back.classList.add("show"));
    const field = box.querySelector(".modal-input");
    if (field) setTimeout(() => field.focus(), 60);
    const done = (val) => { back.classList.remove("show"); setTimeout(() => back.remove(), 200); resolve(val); };
    cancel.addEventListener("click", () => done(input ? null : false));
    ok.addEventListener("click", () => done(input ? (field.value.trim() || null) : true));
    back.addEventListener("click", (e) => { if (e.target === back) done(input ? null : false); });
    box.addEventListener("keydown", (e) => { if (e.key === "Enter") ok.click(); if (e.key === "Escape") cancel.click(); });
  });
}

// ── Modal de alerta de preço ───────────────────────────────
async function openAlertModal(item) {
  let defEmail = "";
  try { const r = await window.pywebview.api.get_settings(); defEmail = (r.settings && r.settings.notify_email) || ""; } catch (_) {}
  const back = el("div", "modal-back");
  const box = el("div", "modal-box alert-modal");
  box.innerHTML = `
    <p class="modal-msg">🔔 Alerta de preço — ${escapeHtml(item.name || "Item")}</p>
    <div class="am-field"><span class="am-label">Alertar quando o preço:</span>
      <label class="am-radio"><input type="radio" name="am-type" value="below" checked> Cair abaixo de</label>
      <label class="am-radio"><input type="radio" name="am-type" value="above"> Subir acima de</label>
    </div>
    <div class="am-row">
      <label class="am-col">Valor<input id="am-price" class="modal-input" type="text" placeholder="ex.: 500000"></label>
      <label class="am-col">Moeda
        <select id="am-cur" class="modal-input">
          <option value="zeny">ZENY</option>
          <option value="rmt">RMT</option>
          <option value="hero_points">HERO POINTS</option>
        </select>
      </label>
    </div>
    <label class="am-full">E-mail (opcional, usa o padrão se vazio)<input id="am-email" class="modal-input" type="text" value="${escapeHtml(defEmail)}"></label>
    <label class="am-full">Refino mínimo (opcional, 0–20)<input id="am-ref" class="modal-input" type="text" placeholder="vazio = qualquer refino"></label>`;
  const actions = el("div", "modal-actions");
  const cancel = el("button", "modal-btn ghost", "Cancelar");
  const ok = el("button", "modal-btn primary", "Salvar alerta");
  actions.appendChild(cancel); actions.appendChild(ok);
  box.appendChild(actions); back.appendChild(box); document.body.appendChild(back);
  requestAnimationFrame(() => back.classList.add("show"));
  setTimeout(() => box.querySelector("#am-price").focus(), 60);
  const close = () => { back.classList.remove("show"); setTimeout(() => back.remove(), 200); };
  cancel.addEventListener("click", close);
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  ok.addEventListener("click", async () => {
    const price = box.querySelector("#am-price").value.replace(/[^\d.,]/g, "").replace(/\./g, "").replace(",", ".");
    if (!price || Number(price) <= 0) { toast("Digite um valor válido"); return; }
    ok.disabled = true; ok.textContent = "Salvando…";
    const payload = {
      item_id: item.id, name: item.name, item_icon_url: item.item_icon_url || "",
      type: box.querySelector('input[name="am-type"]:checked').value,
      sale_type: box.querySelector("#am-cur").value,
      price: Number(price),
      notify_email: box.querySelector("#am-email").value.trim(),
      refinement: box.querySelector("#am-ref").value.trim(),
    };
    const res = await window.pywebview.api.add_alert(payload);
    if (res && res.ok) {
      toast("Alerta criado");
      close();
      await refreshNotifyUI();
      await pollAlertNotifications();
    }
    else { toast("Erro: " + ((res && res.error) || "")); ok.disabled = false; ok.textContent = "Salvar alerta"; }
  });
}

// ── Boot ───────────────────────────────────────────────────
initSidebar();
initNotifications();
document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => go(b.dataset.route)));
document.getElementById("overlay").addEventListener("click", () => {
  if (_notifyDrawerOpen) closeNotifyDrawer();
  else closeDetail();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (_notifyDrawerOpen) closeNotifyDrawer();
  else closeDetail();
});

async function boot() {
  try {
    try {
      const cfg = await window.pywebview.api.get_settings();
      applyTheme((cfg.settings && cfg.settings.ui_theme) || "dark");
    } catch (_) { applyTheme("dark"); }
    STATE = await window.pywebview.api.get_home();
    try {
      const repaired = await window.pywebview.api.repair_monitored_generic_names();
      if (repaired?.categories) STATE = repaired;
    } catch (_) { /* ignora falha de correção */ }
    updateNavBadge();
    go("home");
    startMvpSpawnWatch();
    startAlertNotifyWatch();
    document.getElementById("loading").classList.add("hidden");
  } catch (err) {
    document.getElementById("loading").innerHTML =
      '<span style="color:#f87171">Erro ao carregar dados: ' + escapeHtml(String(err)) + "</span>";
  }
}

if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);
