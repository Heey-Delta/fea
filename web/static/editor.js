// Editor de operação: malha de fluxo, inspector contextual, validação e versões.
//
// Módulos nativos: Busca → Edição → Publicação (um nó por rede de destino, em ramificação).
// O JSON salvo continua sendo o grafo da operação ({nodes, edges}); fontes, rede, aprovação e
// contas viram blocos internos ao salvar, então servidor e workers não mudam. A posição dos
// nós fica em `layout`.
(function () {
  "use strict";

  const boot = JSON.parse(document.getElementById("canvas-data").textContent);
  const RO = boot.readOnly;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const clone = (v) => JSON.parse(JSON.stringify(v == null ? {} : v));

  // ---- Modelo ----------------------------------------------------------------------------
  const original = boot.config;
  const byType = (t) => (original.nodes || []).filter((n) => n.type === t);
  const one = (t) => byType(t)[0] || { id: t, type: t, config: {} };
  const ids = {
    fishing: one("fishing").id || "pesca",
    edit: one("edit").id || "edicao",
    approval: one("approval").id || "aprovacao",
    publish: one("publish").id || "postagem",
    network: one("network").id || "rede",
  };
  const net = clone(one("network").config);
  let model = {
    description: original.description || "",
    fishing: clone(one("fishing").config),
    sources: byType("source").map((n) => ({ id: n.id, ...clone(n.config) })),
    automation: clone(original.automation),
    edit: clone(one("edit").config),
    approval: clone(one("approval").config),
    publish: clone(one("publish").config),
    profiles: (net.profiles && net.profiles.length ? net.profiles : [net.profile || "youtube_shorts"]).slice(),
    accountIds: byType("account").map((n) => (n.config || {}).account_id).filter((v) => Number.isInteger(v)),
    retention: clone(original.retention),
    layout: clone(original.layout),
  };
  function normalize(m) {
    m.edit.preset = m.edit.preset || {};
    ["video", "mask", "audio"].forEach((k) => { m.edit.preset[k] = m.edit.preset[k] || {}; });
    m.edit.preset.elements = m.edit.preset.elements || [];
    m.publish.window = m.publish.window || { start: "08:00", end: "23:00" };
    m.publish.titles = m.publish.titles || {};
    m.automation = m.automation || {};
    m.retention = m.retention || {};
    m.layout = m.layout || {};
    return m;
  }
  normalize(model);

  function exportConfig() {
    const nodes = [
      { id: ids.fishing, type: "fishing", config: model.fishing },
      { id: ids.edit, type: "edit", config: model.edit },
      { id: ids.approval, type: "approval", config: model.approval },
      { id: ids.publish, type: "publish", config: model.publish },
      { id: ids.network, type: "network", config: { profile: model.profiles[0], profiles: model.profiles } },
    ];
    const edges = [
      { from: ids.fishing, to: ids.edit }, { from: ids.edit, to: ids.approval },
      { from: ids.approval, to: ids.publish }, { from: ids.network, to: ids.edit },
      { from: ids.network, to: ids.publish },
    ];
    model.sources.forEach((s) => {
      const { id, ...config } = s;
      nodes.push({ id, type: "source", config });
      edges.push({ from: id, to: ids.fishing });
    });
    model.accountIds.forEach((accountId) => {
      const id = `c${accountId}`;
      nodes.push({ id, type: "account", config: { account_id: accountId } });
      edges.push({ from: id, to: ids.publish });
    });
    return {
      ...original, nodes, edges, description: model.description,
      automation: model.automation, retention: model.retention, layout: model.layout,
    };
  }

  // ---- Catálogo --------------------------------------------------------------------------
  const profileById = Object.fromEntries(boot.profiles.map((p) => [p.id, p]));
  const PLATFORM_ICON = { youtube: "youtube", tiktok: "tiktok", instagram: "instagram" };
  const SOURCE_ICON = { reddit: "reddit", x: "x-logo", upload: "upload", drive: "drive" };
  const KIND = {
    busca: { name: "Busca", icon: "search", desc: "Fontes, filtros, tags e quantidade da pesca." },
    edicao: { name: "Edição", icon: "film", desc: "Configure os parâmetros do módulo." },
    pub: { name: "Publicação", icon: "send", desc: "Contas, aprovação, agenda e título." },
  };
  const NODE_W = 124, NODE_H = 122;

  function nodes() {
    const list = [
      { id: "busca", kind: "busca", label: "Busca", icon: SOURCE_ICON[(model.sources[0] || {}).type] || "search" },
      { id: "edicao", kind: "edicao", label: "Edição", icon: "film" },
    ];
    model.profiles.forEach((pid) => {
      const p = profileById[pid] || { name: pid, platform: "" };
      list.push({ id: `dest:${pid}`, kind: "pub", profile: pid, label: model.profiles.length > 1 ? p.name.replace(" Shorts", "").replace(" Reels", "") : "Publicação", badge: p.name, icon: model.profiles.length > 1 ? (PLATFORM_ICON[p.platform] || "send") : "send" });
    });
    const n = model.profiles.length;
    list.forEach((node) => {
      if (!model.layout[node.id]) {
        if (node.kind === "busca") model.layout[node.id] = { x: 150, y: 200 };
        else if (node.kind === "edicao") model.layout[node.id] = { x: 430, y: 200 };
        else {
          const i = model.profiles.indexOf(node.profile);
          model.layout[node.id] = { x: 710, y: Math.round(200 + (i - (n - 1) / 2) * 170) };
        }
      }
      node.pos = model.layout[node.id];
    });
    return list;
  }
  const edgesOf = (list) => {
    const out = [["busca", "edicao"]];
    list.filter((n) => n.kind === "pub").forEach((n) => out.push(["edicao", n.id]));
    return out;
  };

  // ---- Estado da tela --------------------------------------------------------------------
  const stage = $("#stage"), world = $("#world"), edgesSvg = $("#edges");
  const insBody = $("#ins-body"), body = $("#ed-body");
  const statusEl = $("#canvas-status");
  const view = { x: 0, y: 0, k: 1 };
  let selected = null;
  let dirty = false;
  let serverIssues = boot.issues || [];
  let firstPaint = true;

  // ---- Desfazer / refazer ----------------------------------------------------------------
  const history = [JSON.stringify(model)];
  let hIndex = 0;
  let commitTimer = null;
  function commit() {
    clearTimeout(commitTimer);
    commitTimer = setTimeout(() => {
      const snap = JSON.stringify(model);
      if (snap === history[hIndex]) return;
      history.splice(hIndex + 1);
      history.push(snap);
      if (history.length > 100) history.shift();
      hIndex = history.length - 1;
      updateUndo();
    }, 350);
  }
  function restore(i) {
    hIndex = i;
    model = normalize(JSON.parse(history[hIndex]));
    dirty = true;
    updateUndo();
    renderAll();
  }
  function updateUndo() {
    $("#undo").disabled = RO || hIndex <= 0;
    $("#redo").disabled = RO || hIndex >= history.length - 1;
  }
  $("#undo").addEventListener("click", () => hIndex > 0 && restore(hIndex - 1));
  $("#redo").addEventListener("click", () => hIndex < history.length - 1 && restore(hIndex + 1));

  function changed(opts = {}) {
    dirty = true;
    statusEl.textContent = "Alterações não salvas";
    statusEl.className = "when";
    commit();
    renderNodes(false);
    renderValidation();
    if (opts.inspector) renderInspector();
  }

  // ---- Toast -----------------------------------------------------------------------------
  let toastTimer;
  function toast(text, kind = "") {
    const t = $("#toast");
    t.textContent = text;
    t.className = `toast on ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.className = "toast"; }, 2800);
  }

  // ---- Malha: nós, ligações, zoom --------------------------------------------------------
  function applyView(smooth = false) {
    world.classList.toggle("smooth", smooth);
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
    stage.style.backgroundSize = `${22 * view.k}px ${22 * view.k}px`;
    stage.style.backgroundPosition = `${view.x}px ${view.y}px`;
    $("#zoom-level").textContent = `${Math.round(view.k * 100)}%`;
    renderMinimap();
  }
  function zoomAt(k, cx, cy, smooth) {
    k = Math.min(2, Math.max(0.4, k));
    const wx = (cx - view.x) / view.k, wy = (cy - view.y) / view.k;
    view.k = k;
    view.x = cx - wx * k;
    view.y = cy - wy * k;
    applyView(smooth);
  }
  function fit(smooth = true) {
    const list = nodes();
    const xs = list.map((n) => n.pos.x), ys = list.map((n) => n.pos.y);
    const minX = Math.min(...xs) - 40, maxX = Math.max(...xs) + NODE_W + 40;
    const minY = Math.min(...ys) - 40, maxY = Math.max(...ys) + NODE_H + 40;
    // Área útil: desconta a coluna de ferramentas à esquerda.
    const left = 76, w = (stage.clientWidth || 800) - left, h = stage.clientHeight || 500;
    const k = Math.min(1.25, Math.max(0.35, Math.min((w - 30) / (maxX - minX), (h - 40) / (maxY - minY))));
    // Tela estreita: legibilidade antes de caber tudo (arraste para ver o resto).
    view.k = w < 520 ? Math.max(k, 0.6) : k;
    view.x = view.k > k ? left + 10 - minX * view.k : left + (w - (maxX - minX) * k) / 2 - minX * k;
    view.y = (h - (maxY - minY) * view.k) / 2 - minY * view.k;
    applyView(smooth);
  }

  function nodeStatus(node) {
    const issues = clientIssues().filter((i) => i.block === node.id || (i.block === "pub" && node.kind === "pub"));
    if (issues.some((i) => i.level === "error")) return "bad";
    if (issues.length) return "warn";
    return "ok";
  }

  function renderNodes(animate) {
    const list = nodes();
    $$(".node", world).forEach((el) => { if (!list.some((n) => n.id === el.dataset.id)) el.remove(); });
    list.forEach((n, i) => {
      let el = world.querySelector(`.node[data-id="${CSS.escape(n.id)}"]`);
      if (!el) {
        el = document.createElement("div");
        el.className = "node";
        el.dataset.id = n.id;
        el.tabIndex = 0;
        el.setAttribute("role", "button");
        el.style.setProperty("--i", animate ? i : 0);
        if (!animate) el.style.animation = "pop .3s var(--ease) both";
        world.appendChild(el);
      }
      const st = nodeStatus(n);
      const badge = n.kind === "pub" && model.profiles.length === 1 ? (PLATFORM_ICON[(profileById[n.profile] || {}).platform] || "") : "";
      el.innerHTML = `${badge ? `<span class="node-badge" title="${esc(n.badge)}">${icon(badge)}</span>` : ""}
        <span class="dot node-dot ${st}${st === "ok" && boot.op.status === "active" ? " live" : ""}" title="${st === "ok" ? "Configurado" : st === "warn" ? "Com avisos" : "Com erros"}"></span>
        <div class="node-icon">${icon(n.icon)}</div>
        <div class="node-label"><span>${esc(n.label)}</span>${icon("chevron-down")}</div>
        ${!RO && n.kind !== "pub" ? `<button class="node-add" type="button" title="${n.kind === "busca" ? "Adicionar fonte" : "Adicionar destino"}" aria-label="${n.kind === "busca" ? "Adicionar fonte" : "Adicionar destino"}">${icon("plus")}</button>` : ""}`;
      el.setAttribute("aria-label", `${n.label}: ${st === "ok" ? "configurado" : st === "warn" ? "com avisos" : "com erros"}`);
      el.classList.toggle("sel", selected === n.id);
      el.classList.toggle("has-error", st === "bad");
      el.style.left = `${n.pos.x}px`;
      el.style.top = `${n.pos.y}px`;
      const add = el.querySelector(".node-add");
      if (add) add.addEventListener("pointerdown", (e) => e.stopPropagation());
      if (add) add.addEventListener("click", (e) => {
        e.stopPropagation();
        if (n.kind === "busca") { select("busca"); addSource(); } else openPop("library");
      });
    });
    renderEdges(animate);
    renderMinimap();
  }

  function renderEdges(animate) {
    const list = nodes();
    const pos = Object.fromEntries(list.map((n) => [n.id, n.pos]));
    $$("path.edge", edgesSvg).forEach((p) => p.remove());
    edgesOf(list).forEach(([a, b], i) => {
      const A = pos[a], B = pos[b];
      const x1 = A.x + NODE_W, y1 = A.y + NODE_H / 2 - 9, x2 = B.x - 4, y2 = B.y + NODE_H / 2 - 9;
      const dx = Math.max(40, (x2 - x1) / 2);
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`);
      path.setAttribute("class", `edge${animate ? " draw" : ""}${boot.op.status === "active" && !animate ? " flowing" : ""}`);
      if (animate) path.style.animationDelay = `${200 + i * 120}ms`;
      path.setAttribute("marker-end", "url(#arrow)");
      edgesSvg.appendChild(path);
      if (animate && boot.op.status === "active") {
        path.addEventListener("animationend", () => { path.classList.remove("draw"); path.classList.add("flowing"); }, { once: true });
      }
    });
  }

  function renderMinimap() {
    const mm = $("#mm");
    if (!mm) return;
    const list = nodes();
    const w = stage.clientWidth || 800, h = stage.clientHeight || 500;
    const vx = -view.x / view.k, vy = -view.y / view.k, vw = w / view.k, vh = h / view.k;
    const xs = list.map((n) => n.pos.x).concat([vx]), ys = list.map((n) => n.pos.y).concat([vy]);
    const minX = Math.min(...xs) - 40, minY = Math.min(...ys) - 40;
    const maxX = Math.max(...list.map((n) => n.pos.x + NODE_W), vx + vw) + 40;
    const maxY = Math.max(...list.map((n) => n.pos.y + NODE_H), vy + vh) + 40;
    mm.setAttribute("viewBox", `${minX} ${minY} ${maxX - minX} ${maxY - minY}`);
    mm.setAttribute("preserveAspectRatio", "xMidYMid meet");
    const pos = Object.fromEntries(list.map((n) => [n.id, n.pos]));
    mm.innerHTML = edgesOf(list).map(([a, b]) => `<line class="mm-edge" x1="${pos[a].x + NODE_W}" y1="${pos[a].y + NODE_H / 2}" x2="${pos[b].x}" y2="${pos[b].y + NODE_H / 2}" vector-effect="non-scaling-stroke"/>`).join("")
      + list.map((n) => `<rect class="mm-node" x="${n.pos.x + 22}" y="${n.pos.y + 22}" width="${NODE_W - 44}" height="${NODE_H - 44}" rx="8"/>`).join("")
      + `<rect class="mm-view" x="${vx}" y="${vy}" width="${vw}" height="${vh}" rx="10" vector-effect="non-scaling-stroke"/>`;
    mm.dataset.box = JSON.stringify([minX, minY, maxX - minX, maxY - minY]);
  }
  $("#mm").addEventListener("click", (e) => {
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    view.x = stage.clientWidth / 2 - p.x * view.k;
    view.y = stage.clientHeight / 2 - p.y * view.k;
    applyView(true);
  });
  $("#mm-toggle").addEventListener("click", () => $("#minimap").classList.toggle("hidden"));

  // Arrastar nós e mover a malha.
  let drag = null;
  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".tools, .popover, .minimap")) return;
    closePops();
    const nodeEl = e.target.closest(".node");
    if (nodeEl) {
      const id = nodeEl.dataset.id;
      drag = { type: "node", id, el: nodeEl, sx: e.clientX, sy: e.clientY, start: { ...model.layout[id] }, moved: false };
    } else {
      drag = { type: "pan", sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, moved: false };
      stage.classList.add("panning");
    }
    stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    if (drag.type === "pan") {
      view.x = drag.vx + dx;
      view.y = drag.vy + dy;
      applyView(false);
    } else if (!RO) {
      drag.el.classList.add("dragging");
      const p = { x: Math.round(drag.start.x + dx / view.k), y: Math.round(drag.start.y + dy / view.k) };
      model.layout[drag.id] = p;
      drag.el.style.left = `${p.x}px`;
      drag.el.style.top = `${p.y}px`;
      renderEdges(false);
      renderMinimap();
    }
  });
  stage.addEventListener("pointerup", () => {
    if (!drag) return;
    stage.classList.remove("panning");
    if (drag.type === "node") {
      drag.el.classList.remove("dragging");
      if (drag.moved && !RO) { snap(drag.id); changed(); } else select(drag.id);
    } else if (!drag.moved) {
      select(null);
    }
    drag = null;
  });
  function snap(id) {
    const p = model.layout[id];
    p.x = Math.round(p.x / 11) * 11;
    p.y = Math.round(p.y / 11) * 11;
    renderNodes(false);
  }
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = stage.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) zoomAt(view.k * (e.deltaY < 0 ? 1.1 : 0.9), e.clientX - r.left, e.clientY - r.top, false);
    else { view.x -= e.deltaX; view.y -= e.deltaY; applyView(false); }
  }, { passive: false });
  stage.addEventListener("keydown", (e) => {
    const n = e.target.closest && e.target.closest(".node");
    if (n && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(n.dataset.id); }
  });
  const center = () => [stage.clientWidth / 2, stage.clientHeight / 2];
  $("#zoom-in").addEventListener("click", () => zoomAt(view.k * 1.2, ...center(), true));
  $("#zoom-out").addEventListener("click", () => zoomAt(view.k / 1.2, ...center(), true));
  $("#fit").addEventListener("click", () => fit(true));
  $("#fit-top").addEventListener("click", () => fit(true));
  $("#tool-select").addEventListener("click", () => closePops());

  // ---- Popovers: biblioteca, módulos, histórico ------------------------------------------
  function closePops() {
    $$(".popover").forEach((p) => { p.hidden = true; });
    $$(".tool[data-pop]").forEach((t) => t.classList.remove("on"));
    $("#tool-select").classList.add("on");
  }
  function openPop(name) {
    const pop = $(`#pop-${name}`);
    const wasOpen = !pop.hidden;
    closePops();
    if (wasOpen) return;
    pop.innerHTML = POPS[name]();
    pop.hidden = false;
    $("#tool-select").classList.remove("on");
    const tool = $(`.tool[data-pop="${name}"]`);
    if (tool) tool.classList.add("on");
    wirePop(pop);
  }
  $$(".tool[data-pop]").forEach((t) => t.addEventListener("click", () => openPop(t.dataset.pop)));
  const POPS = {
    library() {
      const dests = boot.profiles.map((p) => {
        const has = model.profiles.includes(p.id);
        return `<button class="pop-item" type="button" data-add-dest="${p.id}" ${has ? "disabled" : ""}><span class="ico">${icon(PLATFORM_ICON[p.platform] || "send")}</span><span><strong>Publicação · ${esc(p.name)}</strong><small>${has ? "já está no fluxo" : "novo destino a partir da Edição"}</small></span></button>`;
      }).join("");
      const srcs = Object.entries(boot.sourceTypes).map(([k, v]) => `<button class="pop-item" type="button" data-add-source="${k}"><span class="ico">${icon(SOURCE_ICON[k] || "search")}</span><span><strong>Fonte · ${esc(v)}</strong><small>entra no módulo Busca</small></span></button>`).join("");
      return `<h3>Biblioteca de módulos</h3>${srcs}<h3 style="margin-top:8px">Destinos</h3>${dests}<p class="sub" style="margin:6px 2px 0">Busca e Edição são módulos únicos da operação; destinos podem ser vários.</p>`;
    },
    layers() {
      return `<h3>Módulos do fluxo</h3>` + nodes().map((n) => `<button class="pop-item${selected === n.id ? " cur" : ""}" type="button" data-select="${esc(n.id)}"><span class="ico">${icon(n.icon)}</span><span><strong>${esc(n.label)}</strong><small>${esc(n.badge || KIND[n.kind].desc)}</small></span></button>`).join("");
    },
    history() {
      const rows = boot.versions.map((v) => `<div class="pop-item" style="cursor:default"><span class="ico" style="font:700 12px var(--mono)">V${v.version}</span><span style="flex:1"><strong>Versão ${v.version}${v.current ? " · atual" : ""}</strong><small>${fmt(v.at)}</small></span>${!RO && !v.current ? `<button class="btn sm" type="button" data-restore="${v.version}">Restaurar</button>` : ""}</div>`).join("");
      return `<h3>Histórico de versões</h3>${rows}<p class="sub" style="margin:6px 2px 0">Restaurar cria uma versão nova com a configuração antiga; nenhuma versão é apagada.</p>`;
    },
  };
  function wirePop(pop) {
    $$("[data-add-dest]", pop).forEach((b) => b.addEventListener("click", () => addDest(b.dataset.addDest)));
    $$("[data-add-source]", pop).forEach((b) => b.addEventListener("click", () => { closePops(); select("busca"); addSource(b.dataset.addSource); }));
    $$("[data-select]", pop).forEach((b) => b.addEventListener("click", () => { closePops(); select(b.dataset.select); centerOn(b.dataset.select); }));
    $$("[data-restore]", pop).forEach((b) => b.addEventListener("click", () => restoreVersion(b.dataset.restore)));
  }
  function centerOn(id) {
    const p = model.layout[id];
    if (!p) return;
    view.x = stage.clientWidth / 2 - (p.x + NODE_W / 2) * view.k;
    view.y = stage.clientHeight / 2 - (p.y + NODE_H / 2) * view.k;
    applyView(true);
  }
  function addDest(pid) {
    if (RO || model.profiles.includes(pid)) return;
    // O destino novo entra abaixo do último, alinhado com os outros destinos.
    const dests = model.profiles.map((p) => model.layout[`dest:${p}`]).filter(Boolean);
    if (dests.length) {
      const last = dests.reduce((a, b) => (b.y > a.y ? b : a));
      model.layout[`dest:${pid}`] = { x: last.x, y: last.y + 165 };
    }
    model.profiles.push(pid);
    closePops();
    changed();
    select(`dest:${pid}`);
    toast(`Destino ${profileById[pid].name} adicionado.`);
  }
  function removeDest(pid) {
    if (model.profiles.length <= 1) { toast("A operação precisa de ao menos um destino.", "error"); return; }
    model.profiles = model.profiles.filter((p) => p !== pid);
    delete model.layout[`dest:${pid}`];
    const platforms = model.profiles.map((p) => profileById[p].platform);
    model.accountIds = model.accountIds.filter((id) => {
      const a = boot.accounts.find((x) => x.id === id);
      return a && platforms.includes(a.platform);
    });
    select(null);
    changed();
    toast("Destino removido.");
  }
  async function restoreVersion(v) {
    if (dirty && !confirm("Há alterações não salvas. Restaurar mesmo assim?")) return;
    const resp = await fetch(`/operacoes/${boot.op.id}/versoes/${v}/restaurar`, { method: "POST" });
    const body = await resp.json();
    if (!resp.ok) { toast(body.error || "Não restaurou.", "error"); return; }
    dirty = false;
    location.reload();
  }

  // ---- Inspector -------------------------------------------------------------------------
  function select(id) {
    selected = id;
    $$(".node", world).forEach((el) => el.classList.toggle("sel", el.dataset.id === id));
    renderInspector();
    if (id && body.classList.contains("collapsed")) body.classList.remove("collapsed");
  }
  $("#ins-toggle").addEventListener("click", () => {
    body.classList.toggle("collapsed");
    $("#ins-toggle").setAttribute("aria-label", body.classList.contains("collapsed") ? "Abrir painel" : "Recolher painel");
    setTimeout(renderMinimap, 320);
  });

  const opt = (value, label, current) => `<option value="${esc(value)}"${String(value) === String(current) ? " selected" : ""}>${esc(label)}</option>`;
  const sec = (title, iconName, content, open = false) => `<details class="sec"${open ? " open" : ""}><summary>${icon(iconName)}<span class="grow">${esc(title)}</span>${icon("chevron-down", "chev")}</summary><div class="sec-body">${content}</div></details>`;
  const head = (ic, title, desc) => `<div class="ins-id"><span class="ico">${icon(ic)}</span><div><h3>${esc(title)}</h3><p>${esc(desc)}</p></div></div>`;
  const toggle = (bind, label, hint, def) => `<label class="toggle-row"><span>${esc(label)}${hint ? `<small>${esc(hint)}</small>` : ""}</span><span class="switch"><input type="checkbox" data-bind="${bind}" ${def != null ? `data-default="${def}"` : ""}><span></span></span></label>`;
  function readyNote(service, label) {
    if (boot.ready[service]) return "";
    return `<p class="callout">${esc(label)}: chaves não preenchidas. <a href="/contas#${service}">Preencher em Acessos</a>.</p>`;
  }

  function common() {
    const ps = model.profiles.map((id) => profileById[id]).filter(Boolean);
    const first = ps[0] || boot.profiles[0];
    const same = (a, b) => a[0] === b[0] && a[1] === b[1];
    const res = first.resolutions.filter((r) => ps.every((p) => p.resolutions.some((x) => same(x, r))));
    const fps = first.fps.filter((f) => ps.every((p) => p.fps.includes(f)));
    return { resolutions: res.length ? res : first.resolutions, fps: fps.length ? fps : first.fps, maxDuration: Math.min(...ps.map((p) => p.maxDuration)) };
  }

  function insOverview() {
    const issues = clientIssues();
    return `${head("operations", boot.op.name, "Selecione um módulo na malha para configurar.")}
      <div><div class="kv"><span>Fontes de busca</span><strong>${model.sources.length}</strong></div>
      <div class="kv"><span>Destinos</span><strong>${model.profiles.length}</strong></div>
      <div class="kv"><span>Contas</span><strong>${model.accountIds.length}</strong></div>
      <div class="kv"><span>Erros / avisos</span><strong>${issues.filter((i) => i.level === "error").length} / ${issues.filter((i) => i.level !== "error").length}</strong></div></div>
      <p class="sub">Arraste os módulos para organizar a malha. Use <strong>+</strong> nos módulos para adicionar fontes e destinos.</p>`;
  }

  function sourceItem(s, i) {
    const types = Object.entries(boot.sourceTypes).map(([k, v]) => opt(k, v, s.type || "reddit")).join("");
    const ph = { reddit: "r/comunidade", x: "@usuario ou termo de busca", upload: "nome da pasta (opcional)", drive: "link da pasta do Google Drive" }[s.type || "reddit"];
    const dbId = boot.sourceIds[s.id];
    return `<div class="list-item" data-source="${i}">
      <div class="row"><strong>${icon(SOURCE_ICON[s.type || "reddit"] || "search")} Fonte ${i + 1}</strong>${RO ? "" : `<button class="btn sm ghost danger" type="button" data-remove-source="${i}">${icon("trash")} Remover</button>`}</div>
      <label class="field">Rede<select class="input" data-src="type">${types}</select></label>
      <label class="field">Onde buscar<input class="input" data-src="reference" value="${esc(s.reference)}" placeholder="${esc(ph)}"></label>
      ${dbId ? `<button class="btn sm" type="button" data-test-source="${dbId}">${icon("link")} Testar conexão</button>` : '<small class="sub">Salve a versão para testar a conexão.</small>'}
    </div>`;
  }

  function insBusca() {
    const used = new Set(model.sources.map((s) => s.type || "reddit"));
    return `${head("search", "Busca", KIND.busca.desc)}
      ${used.has("reddit") ? readyNote("reddit", "Reddit") : ""}${used.has("x") ? readyNote("x", "X") : ""}${used.has("drive") ? readyNote("drive", "Google Drive") : ""}
      ${sec("Fontes", "link", `${model.sources.map(sourceItem).join("") || '<p class="sub">Nenhuma fonte ainda.</p>'}${RO ? "" : `<button class="btn" type="button" id="add-source">${icon("plus")} Adicionar fonte</button>`}<small class="sub">Sem permissão registrada, os itens ficam pendentes até você liberar na Fila.</small>`, true)}
      ${sec("Filtros e tags", "search", `
        <label class="field">Tags<input class="input" data-bind="fishing.tags" data-kind="list" placeholder="academia, treino"><small>separadas por vírgula</small></label>
        <label class="field">Heat tags<input class="input" data-bind="fishing.heat_tags" data-kind="list" placeholder="supino"><small>valem 2 pontos no score</small></label>
        <label class="field">Palavras bloqueadas<input class="input" data-bind="fishing.blocked_words" data-kind="list" placeholder="nsfw"></label>
        <label class="field">Duração máxima (s)<input class="input" type="number" min="1" data-bind="fishing.max_duration_s"></label>
        <label class="toggle-row"><span>Aceitar vídeos</span><span class="switch"><input type="checkbox" data-media="video"><span></span></span></label>
        <label class="toggle-row"><span>Aceitar imagens</span><span class="switch"><input type="checkbox" data-media="image"><span></span></span></label>
        ${toggle("fishing.reject_watermarks", "Recusar marca d'água de terceiros", "detectada por OCR", "true")}`)}
      ${sec("Quantidade", "chart", `
        <label class="field">Meta por Play<input class="input" type="number" min="1" data-bind="fishing.target_x" data-default="10"></label>
        <label class="field">Posts examinados no máximo<input class="input" type="number" min="1" data-bind="fishing.search_budget" data-default="300"></label>
        <label class="field">Critério<select class="input" data-bind="fishing.criteria" data-default="recent">${opt("recent", "Mais recentes")}${opt("heat", "Priorizar heat tags")}</select></label>`)}
      ${sec("Automação", "calendar", `
        <label class="field">Play diário às<input class="input" type="time" data-bind="automation.daily_play_at" data-kind="nullable"><small>vazio = desligado</small></label>
        <label class="field">Meta diária<input class="input" type="number" min="1" data-bind="automation.daily_target" data-default="30"></label>
        ${toggle("automation.stock_enabled", "Repor estoque de editados", "mantém vídeos prontos para os próximos dias")}
        <label class="field">Estoque mínimo (dias)<input class="input" type="number" min="1" max="14" data-bind="automation.stock_min_days" data-default="3"></label>`)}
      ${tech("busca", [["Tipo", "fishing"], ["Bloco", ids.fishing], ["Fontes", model.sources.length]])}`;
  }

  function maskOptions() {
    const current = model.edit.preset.mask.mask_id || null;
    return `<label class="opt"><input type="radio" name="mask" value="" ${current ? "" : "checked"} ${RO ? "disabled" : ""}><span><strong>Sem máscara</strong></span></label>`
      + boot.masks.map((m) => `<label class="opt"><input type="radio" name="mask" value="${m.id}" ${m.id === current ? "checked" : ""} ${RO ? "disabled" : ""}><img class="mask-thumb" src="${esc(m.url)}" alt=""><span><strong>${esc(m.name)}</strong><small>v${m.version} · ${esc(m.size)}${m.alpha ? "" : " · sem transparência"}</small></span></label>`).join("");
  }

  function insEdicao() {
    const c = common();
    const v = model.edit.preset.video;
    const current = `${v.width || 1080}x${v.height || 1920}`;
    const wm = model.edit.preset.elements[0];
    const audioMode = model.edit.preset.audio.mode || "keep";
    const grouping = Number(model.edit.preset.video.group_images || 0) >= 2;
    return `${head("film", "Edição", KIND.edicao.desc)}
      <label class="field">Formato<select class="input mono" id="resolution" ${RO ? "disabled" : ""}>${c.resolutions.map(([w, h]) => opt(`${w}x${h}`, `${w} × ${h}`, current)).join("")}</select></label>
      <label class="field">Máscara PNG
        ${RO ? "" : `<span class="file-btn">${icon("image")} <span id="mask-label">Selecionar arquivo</span><input type="file" accept="image/png" id="mask-file" aria-label="Importar máscara PNG"></span>`}
      </label>
      <div class="opt-grid" id="masks">${maskOptions()}</div>
      <label class="toggle-row"><span>Marca d'água<small>sua logo sobre o vídeo</small></span><span class="switch"><input type="checkbox" id="wm-toggle" ${wm || wmPending ? "checked" : ""} ${RO ? "disabled" : ""}><span></span></span></label>
      ${wm || wmPending ? `<div class="list-item">
        ${RO ? "" : `<span class="file-btn">${icon("upload")} <span id="wm-label">${wm ? esc(wm.file_key.split("/").pop()) : "Selecionar imagem"}</span><input type="file" accept="image/png,image/jpeg,image/webp" id="wm-file" aria-label="Enviar marca d'água"></span>`}
        ${wm ? `<label class="field">Posição<select class="input" data-bind="edit.preset.elements.0.position" data-default="bottom_right">${opt("bottom_right", "Inferior direita")}${opt("bottom_left", "Inferior esquerda")}${opt("top_right", "Superior direita")}${opt("top_left", "Superior esquerda")}${opt("center", "Centro")}</select></label>
        <label class="field">Largura (% do vídeo)<input class="input" type="number" min="1" max="100" data-bind="edit.preset.elements.0.scale" data-kind="pct" data-default="20"></label>
        <label class="field">Opacidade (%)<input class="input" type="number" min="0" max="100" data-bind="edit.preset.elements.0.opacity" data-kind="pct" data-default="100"></label>` : ""}
      </div>` : ""}
      <label class="field">Áudio<select class="input" id="audio-mode" ${RO ? "disabled" : ""}>${opt("keep", "Original", audioMode)}${opt("remove", "Nenhum", audioMode)}${opt("replace", "Substituir", audioMode)}${opt("random", "Música aleatória", audioMode)}</select>${audioMode === "replace" ? `<small>Escolha o arquivo em <a href="${esc(boot.presetUrl)}">Avançado</a>.</small>` : ""}</label>
      ${audioMode === "random" ? musicLibrary() : ""}
      <label class="toggle-row"><span>Agrupar imagens<small>junta várias imagens num só vídeo (Short)</small></span><span class="switch"><input type="checkbox" id="group-toggle" ${grouping ? "checked" : ""} ${RO ? "disabled" : ""}><span></span></span></label>
      ${grouping ? `<label class="field">Imagens por vídeo<input class="input" type="number" min="2" max="20" data-bind="edit.preset.video.group_images" data-kind="num" data-default="5"><small>com 5, cada Short leva 5 imagens; o que sobra espera as próximas</small></label>
      <label class="field">Segundos por imagem<input class="input" type="number" min="1" max="30" step="0.5" data-bind="edit.preset.video.image_duration_s" data-kind="num" data-default="3"></label>` : ""}
      ${sec("Enquadramento", "frame", `
        <label class="field">Modo<select class="input" data-bind="edit.preset.video.fit" data-default="blur">${opt("blur", "Fundo desfocado")}${opt("cover", "Preencher (corta)")}${opt("contain", "Ajustar (barras)")}</select></label>
        <label class="field">Posição do corte<select class="input" data-bind="edit.preset.video.crop_position" data-default="center">${opt("center", "Centro")}${opt("top", "Topo")}${opt("bottom", "Base")}</select></label>
        <label class="field">FPS<select class="input" data-bind="edit.preset.video.fps" data-kind="num" data-default="30">${c.fps.map((f) => opt(f, `${f} fps`)).join("")}</select></label>
        <label class="field">Cor das barras<input class="input" type="color" data-bind="edit.preset.video.background" data-default="#000000"></label>
        <small class="sub">Duração máxima do vídeo final: ${Math.round(c.maxDuration)} s (a menor entre os destinos).</small>`)}
      ${sec("Máscara e áudio", "mask", `
        <label class="field">Opacidade da máscara (%)<input class="input" type="number" min="0" max="100" data-bind="edit.preset.mask.opacity" data-kind="pct" data-default="100"></label>
        <label class="field">Escala da máscara (%)<input class="input" type="number" min="1" max="400" data-bind="edit.preset.mask.scale" data-kind="pct" data-default="100"></label>
        <label class="field">Volume (%)<input class="input" type="number" min="0" max="200" data-bind="edit.preset.audio.volume" data-kind="pct" data-default="100"></label>
        ${toggle("edit.preset.audio.normalize", "Normalizar volume", "", "true")}`)}
      ${sec("Avançado", "settings", `<p class="sub">Textos fixos, áudio substituto e o teste de render ficam na tela completa do preset.</p><a class="btn" href="${esc(boot.presetUrl)}">${icon("external")} Textos, áudio e Testar módulo</a>`)}
      ${tech("edicao", [["Tipo", "edit"], ["Bloco", ids.edit], ["Formato", current], ["Máscara", model.edit.preset.mask.mask_id || "—"]])}`;
  }

  // Biblioteca de músicas: o modo "aleatória" sorteia uma a cada vídeo. Sem música: modo "Nenhum".
  function musicLibrary() {
    const lib = model.edit.preset.audio.library || [];
    const rows = lib.map((key, i) => `<div class="row"><span class="mono">${esc(key.split("/").pop().replace(/^\d+_/, ""))}</span>${RO ? "" : `<button class="btn sm ghost danger" type="button" data-drop-music="${i}">${icon("trash")}</button>`}</div>`).join("");
    return `<div class="list-item"><strong>Biblioteca de músicas (${lib.length})</strong>
      ${rows || '<small class="sub">Envie músicas que você pode usar (suas, licenciadas ou da Biblioteca de Áudio do YouTube).</small>'}
      ${RO ? "" : `<span class="file-btn">${icon("upload")} <span id="music-label">Adicionar músicas</span><input type="file" accept="audio/*" multiple id="music-file" aria-label="Adicionar músicas"></span>`}</div>`;
  }

  async function uploadMusic(event) {
    const files = [...event.target.files];
    if (!files.length) return;
    $("#music-label", insBody).textContent = `Enviando ${files.length}…`;
    try {
      const lib = model.edit.preset.audio.library = model.edit.preset.audio.library || [];
      for (const f of files) lib.push(await uploadAsset(f));
      changed({ inspector: true });
      toast(`${files.length} música(s) na biblioteca.`);
    } catch (err) {
      toast(`Falhou: ${err.message}`, "error");
      renderInspector();
    }
  }

  function insPub(pid) {
    const p = profileById[pid] || { name: pid, platform: "", notes: "" };
    const accs = boot.accounts.filter((a) => a.platform === p.platform);
    const tz = model.publish.timezone || "America/Sao_Paulo";
    const zones = ["America/Sao_Paulo", "America/Manaus", "America/New_York", "Europe/Lisbon", "UTC"];
    if (!zones.includes(tz)) zones.push(tz);
    const accounts = accs.map((a) => {
      const label = { connected: "conectada", error: "com erro", paused: "pausada", revoked: "revogada" }[a.status];
      const off = a.status === "revoked";
      return `<label class="opt${off ? " disabled" : ""}"><input type="checkbox" data-account="${a.id}" ${model.accountIds.includes(a.id) ? "checked" : ""} ${RO || off ? "disabled" : ""}><span><strong>${esc(a.name)}</strong><small>${label}</small></span></label>`;
    }).join("");
    return `${head(PLATFORM_ICON[p.platform] || "send", `Publicação · ${p.name}`, p.notes || KIND.pub.desc)}
      ${readyNote(p.platform, p.name)}
      <div class="field">Contas
        ${accounts ? `<div class="opt-grid">${accounts}</div>` : `<p class="sub">Nenhuma conta ${esc(boot.platformLabel[p.platform] || "")} conectada.</p>`}
        <a class="btn sm" href="/contas#${esc(p.platform)}">${icon("account")} Conectar contas</a>
      </div>
      <label class="field">Privacidade<select class="input" data-bind="publish.privacy" data-default="public">${opt("public", "Público")}${opt("unlisted", "Não listado")}${opt("private", "Privado")}</select><small>vale para todos os destinos</small></label>
      <p class="sub" style="margin:0">As regras abaixo valem para todos os destinos da operação.</p>
      ${sec("Aprovação", "approval", `<div class="opt-grid">
        <label class="opt"><input type="radio" name="approval" value="manual" ${model.approval.auto_approve ? "" : "checked"} ${RO ? "disabled" : ""}><span><strong>Manual</strong><small>você revisa e aprova cada vídeo</small></span></label>
        <label class="opt"><input type="radio" name="approval" value="auto" ${model.approval.auto_approve ? "checked" : ""} ${RO ? "disabled" : ""}><span><strong>Autorizar tudo</strong><small>sem depender de você: passou no controle de qualidade, vai para a agenda</small></span></label></div>`, true)}
      ${sec("Agendamento", "calendar", `
        ${toggle("publish.automatic", "Distribuir automaticamente", "os aprovados entram na agenda sozinhos")}
        <label class="field">Modo<select class="input" data-bind="publish.mode" data-default="rotation">${opt("rotation", "Rodízio entre contas")}${opt("all", "Todas as contas")}</select></label>
        <label class="field">Intervalo (min)<input class="input" type="number" min="0" data-bind="publish.interval_min" data-default="30"></label>
        <div class="grid" style="grid-template-columns:1fr 1fr"><label class="field">Início<input class="input" type="time" data-bind="publish.window.start"></label><label class="field">Fim<input class="input" type="time" data-bind="publish.window.end"></label></div>
        <label class="field">Fuso<select class="input" data-bind="publish.timezone">${zones.map((z) => opt(z, z, tz)).join("")}</select></label>
        ${toggle("publish.first_immediate", "Primeira publicação imediata", "")}`)}
      ${sec("Título e descrição", "text", `
        <label class="field">Método<select class="input" data-bind="publish.titles.method" data-default="markov">${opt("markov", "Gerado (Markov) + modelos")}${opt("templates", "Só os modelos")}</select></label>
        <label class="field">Hashtags<input class="input" data-bind="publish.titles.hashtags" data-kind="list" placeholder="shorts, academia"></label>
        <label class="field">Palavras proibidas<input class="input" data-bind="publish.titles.blocked_words" data-kind="list"></label>
        <label class="field">Modelos de título<textarea class="input" data-bind="publish.titles.templates" data-kind="lines" placeholder="{texto}"></textarea><small>um por linha · {texto} = texto do post original</small></label>
        <label class="field">Frases de referência<textarea class="input" data-bind="publish.titles.corpus" data-kind="lines"></textarea></label>
        <label class="field">Modelo da descrição<textarea class="input" data-bind="publish.titles.description_template" placeholder="{titulo}&#10;&#10;{hashtags}"></textarea><small>{titulo}, {hashtags}, {texto}</small></label>`)}
      ${sec("Limpeza de arquivos", "broom", `<label class="field">Apagar após publicar (min)<input class="input" type="number" min="0" data-bind="retention.delete_after_minutes" data-default="30"></label>`)}
      ${!RO && model.profiles.length > 1 ? `<button class="btn danger" type="button" id="remove-dest">${icon("trash")} Remover destino</button>` : ""}
      ${tech(`dest:${pid}`, [["Perfil", pid], ["Plataforma", p.platform], ["Contas", model.accountIds.filter((id) => accs.some((a) => a.id === id)).length]])}`;
  }

  function tech(id, rows) {
    return sec("Informações técnicas", "log", `<div class="tech">${rows.map(([k, v]) => `${esc(k)}: ${esc(v)}`).join("<br>")}<br>Nó: ${esc(id)}</div>`);
  }

  let wmPending = false;
  function renderInspector() {
    let html;
    if (!selected) html = insOverview();
    else if (selected === "busca") html = insBusca();
    else if (selected === "edicao") html = insEdicao();
    else html = insPub(selected.slice(5));
    const open = $$("details.sec[open] > summary", insBody).map((s) => s.textContent.trim());
    insBody.innerHTML = html;
    if (open.length) $$("details.sec > summary", insBody).forEach((s) => { if (open.includes(s.textContent.trim())) s.parentElement.open = true; });
    insBody.style.animation = "none";
    void insBody.offsetWidth;
    insBody.style.animation = "";
    bindInputs(insBody);
    wireInspector();
  }

  function bindInputs(root) {
    $$("[data-bind]", root).forEach((el) => {
      const path = el.dataset.bind.split(".");
      const kind = el.dataset.kind || (el.type === "checkbox" ? "bool" : el.type === "number" ? "num" : "text");
      const parent = () => {
        let t = model;
        path.slice(0, -1).forEach((k) => { if (t[k] == null) t[k] = {}; t = t[k]; });
        return t;
      };
      const key = path[path.length - 1];
      const value = parent()[key];
      if (kind === "bool") el.checked = value == null ? el.dataset.default === "true" : !!value;
      else if (kind === "list") el.value = Array.isArray(value) ? value.join(", ") : "";
      else if (kind === "lines") el.value = Array.isArray(value) ? value.join("\n") : "";
      else if (kind === "pct") el.value = value == null ? (el.dataset.default || "") : Math.round(value * 100);
      else el.value = value == null ? (el.dataset.default || "") : value;
      if (RO) el.disabled = true;
      el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", () => {
        let v;
        if (kind === "bool") v = el.checked;
        else if (kind === "num") v = el.value === "" ? null : Number(el.value);
        else if (kind === "pct") v = el.value === "" ? null : Number(el.value) / 100;
        else if (kind === "list") v = el.value.split(",").map((s) => s.trim()).filter(Boolean);
        else if (kind === "lines") v = el.value.split("\n").map((s) => s.trim()).filter(Boolean);
        else if (kind === "nullable") v = el.value || null;
        else v = el.value;
        parent()[key] = v;
        changed();
      });
    });
  }

  function wireInspector() {
    $$("[data-source]", insBody).forEach((row) => {
      const s = model.sources[Number(row.dataset.source)];
      $$("[data-src]", row).forEach((el) => {
        if (RO) el.disabled = true;
        el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
          s[el.dataset.src] = el.value;
          changed({ inspector: el.dataset.src === "type" });
        });
      });
    });
    $$("[data-remove-source]", insBody).forEach((b) => b.addEventListener("click", () => {
      model.sources.splice(Number(b.dataset.removeSource), 1);
      changed({ inspector: true });
    }));
    $$("[data-test-source]", insBody).forEach((b) => b.addEventListener("click", () => testSource(b)));
    const add = $("#add-source", insBody);
    if (add) add.addEventListener("click", () => addSource());
    $$("[data-media]", insBody).forEach((el) => {
      el.checked = (model.fishing.accepted_media || ["video"]).includes(el.dataset.media);
      if (RO) el.disabled = true;
      el.addEventListener("change", () => {
        const set = new Set(model.fishing.accepted_media || []);
        if (el.checked) set.add(el.dataset.media); else set.delete(el.dataset.media);
        model.fishing.accepted_media = [...set];
        changed();
      });
    });
    const res = $("#resolution", insBody);
    if (res) res.addEventListener("change", () => {
      const [w, h] = res.value.split("x").map(Number);
      Object.assign(model.edit.preset.video, { width: w, height: h });
      changed();
    });
    $$('input[name="mask"]', insBody).forEach((el) => el.addEventListener("change", () => {
      model.edit.preset.mask.mask_id = el.value ? Number(el.value) : null;
      changed();
    }));
    const maskFile = $("#mask-file", insBody);
    if (maskFile) maskFile.addEventListener("change", uploadMask);
    const wmToggle = $("#wm-toggle", insBody);
    if (wmToggle) wmToggle.addEventListener("change", () => {
      if (wmToggle.checked) { wmPending = true; } else { wmPending = false; model.edit.preset.elements = []; changed(); }
      renderInspector();
    });
    const wmFile = $("#wm-file", insBody);
    if (wmFile) wmFile.addEventListener("change", uploadWatermark);
    const groupToggle = $("#group-toggle", insBody);
    if (groupToggle) groupToggle.addEventListener("change", () => {
      const video = model.edit.preset.video;
      video.group_images = groupToggle.checked ? (Number(video.group_images) >= 2 ? video.group_images : 5) : 0;
      if (groupToggle.checked) {
        const set = new Set(model.fishing.accepted_media || ["video"]);
        set.add("image");  // agrupar só faz sentido buscando imagens
        model.fishing.accepted_media = [...set];
        if (!video.image_duration_s || video.image_duration_s > 6) video.image_duration_s = 3;
      }
      changed({ inspector: true });
    });
    const musicFile = $("#music-file", insBody);
    if (musicFile) musicFile.addEventListener("change", uploadMusic);
    $$("[data-drop-music]", insBody).forEach((b) => b.addEventListener("click", () => {
      model.edit.preset.audio.library.splice(Number(b.dataset.dropMusic), 1);
      changed({ inspector: true });
    }));
    const audio = $("#audio-mode", insBody);
    if (audio) audio.addEventListener("change", () => { model.edit.preset.audio.mode = audio.value; changed({ inspector: true }); });
    $$("[data-account]", insBody).forEach((el) => el.addEventListener("change", () => {
      const id = Number(el.dataset.account);
      model.accountIds = model.accountIds.filter((x) => x !== id);
      if (el.checked) model.accountIds.push(id);
      changed();
    }));
    $$('input[name="approval"]', insBody).forEach((el) => el.addEventListener("change", () => {
      model.approval.auto_approve = el.value === "auto";
      // "Autorizar tudo" também liga a distribuição automática: o fluxo segue sozinho até publicar.
      if (model.approval.auto_approve) model.publish.automatic = true;
      changed();
      if (model.approval.auto_approve) renderInspector();
    }));
    const rm = $("#remove-dest", insBody);
    if (rm) rm.addEventListener("click", () => removeDest(selected.slice(5)));
  }

  function addSource(type = "reddit") {
    if (RO) return;
    model.sources.push({ id: `f${Date.now().toString(36)}`, type, reference: "", permission_note: "" });
    changed({ inspector: true });
    const items = $$(".list-item[data-source]", insBody);
    const last = items[items.length - 1];
    if (last) { last.scrollIntoView({ behavior: "smooth", block: "center" }); $('[data-src="reference"]', last).focus(); }
  }

  async function testSource(button) {
    button.disabled = true;
    const before = button.innerHTML;
    button.textContent = "Testando…";
    try {
      const resp = await fetch(`/operacoes/${boot.op.id}/fontes/${button.dataset.testSource}/testar`, { method: "POST", headers: { Accept: "application/json" } });
      const body = await resp.json();
      toast(body.message, body.ok ? "" : "error");
    } catch (err) {
      toast(`Falhou: ${err.message}`, "error");
    }
    button.disabled = false;
    button.innerHTML = before;
  }

  async function uploadMask(event) {
    const f = event.target.files[0];
    if (!f) return;
    $("#mask-label", insBody).textContent = `Enviando ${f.name}…`;
    const form = new FormData();
    form.append("file", f);
    const name = f.name.replace(/\.png$/i, "");
    form.append("name", name);
    const same = boot.masks.find((m) => m.name.toLowerCase() === name.toLowerCase());
    if (same) form.append("mask_id", same.id);
    try {
      const resp = await fetch(boot.maskUploadUrl, { method: "POST", body: form, headers: { Accept: "application/json" } });
      const body = await resp.json();
      if (body.masks) boot.masks = body.masks;
      if (resp.ok) {
        const mask = boot.masks.find((m) => m.name === name) || boot.masks[boot.masks.length - 1];
        if (mask) model.edit.preset.mask.mask_id = mask.id;
        changed({ inspector: true });
      } else renderInspector();
      toast(body.message, resp.ok ? "" : "error");
    } catch (err) {
      toast(`Falhou: ${err.message}`, "error");
      renderInspector();
    }
  }

  async function uploadAsset(file) {
    const ask = await fetch(boot.assetUploadUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name }) });
    const plan = await ask.json();
    if (!ask.ok) throw new Error(plan.detail || "recusado");
    if (plan.mode === "direct") {
      const put = await fetch(plan.url, { method: "PUT", headers: { "Content-Type": plan.content_type }, body: file });
      if (!put.ok) throw new Error(`HTTP ${put.status}`);
      return plan.key;
    }
    const form = new FormData();
    form.append("file", file);
    const post = await fetch(plan.url, { method: "POST", body: form });
    const body = await post.json();
    if (!post.ok) throw new Error(body.detail || `HTTP ${post.status}`);
    return body.key;
  }

  async function uploadWatermark(event) {
    const f = event.target.files[0];
    if (!f) return;
    $("#wm-label", insBody).textContent = `Enviando ${f.name}…`;
    try {
      const key = await uploadAsset(f);
      const prev = model.edit.preset.elements[0] || {};
      model.edit.preset.elements = [{ position: "bottom_right", scale: 0.2, opacity: 1, margin: 60, ...prev, file_key: key }];
      wmPending = false;
      changed({ inspector: true });
      toast("Marca d'água enviada.");
    } catch (err) {
      toast(`Falhou: ${err.message}`, "error");
      renderInspector();
    }
  }

  // ---- Validação -------------------------------------------------------------------------
  function clientIssues() {
    const out = [];
    if (!model.sources.length) out.push({ level: "error", block: "busca", message: "Adicione ao menos uma fonte de busca na Busca." });
    model.sources.forEach((s, i) => {
      const type = s.type || "reddit";
      if (type !== "upload" && !(s.reference || "").trim()) out.push({ level: "error", block: "busca", message: `Fonte ${i + 1}: informe onde buscar.` });
    });
    new Set(model.sources.map((s) => s.type || "reddit")).forEach((t) => {
      if (t !== "upload" && !boot.ready[t]) out.push({ level: "warning", block: "busca", message: `${boot.sourceTypes[t]}: chaves não preenchidas em Acessos.` });
    });
    if (!model.accountIds.length) out.push({ level: "error", block: "pub", message: "Escolha ao menos uma conta na Publicação." });
    model.profiles.forEach((pid) => {
      const p = profileById[pid];
      if (!p) return;
      const has = model.accountIds.some((id) => (boot.accounts.find((a) => a.id === id) || {}).platform === p.platform);
      if (model.accountIds.length && !has) out.push({ level: "warning", block: `dest:${pid}`, message: `${p.name}: nenhuma conta escolhida.` });
      if (!boot.ready[p.platform]) out.push({ level: "warning", block: `dest:${pid}`, message: `${p.name}: chaves do app não preenchidas em Acessos.` });
    });
    if (!dirty) {
      serverIssues.forEach((i) => {
        if (!out.some((o) => o.message === i.message)) out.push({ ...i, block: "" });
      });
    }
    return out;
  }

  function renderValidation() {
    const issues = clientIssues();
    const errors = issues.filter((i) => i.level === "error");
    const warnings = issues.filter((i) => i.level !== "error");
    const dot = $("#val-state .dot");
    dot.className = `dot ${errors.length ? "bad" : warnings.length ? "warn" : "ok"}`;
    $("#val-title").textContent = errors.length ? "Fluxo com erros" : warnings.length ? "Fluxo com avisos" : "Fluxo válido";
    $("#val-msg").textContent = errors.length || warnings.length
      ? `${errors.length} erro(s), ${warnings.length} aviso(s). ${(errors[0] || warnings[0]).message}`
      : "Sem erros ou avisos.";
    $("#issues").innerHTML = `<h2 style="margin-bottom:6px">Validação do fluxo</h2>` + (issues.length
      ? issues.map((i) => `<p class="issue ${i.level === "error" ? "error" : "warning"}"><strong>${i.level === "error" ? "Erro" : "Aviso"}</strong> · ${esc(i.message)}</p>`).join("")
      : '<p class="issue ok"><strong>Pronto.</strong> O fluxo está completo e pode ser ativado.</p>');
    const act = $("#activate");
    if (act && boot.op.status !== "active") act.disabled = errors.length > 0;
  }
  $("#val-state").addEventListener("click", () => {
    const pop = $("#issues");
    pop.hidden = !pop.hidden;
    $("#val-state").setAttribute("aria-expanded", String(!pop.hidden));
  });

  // ---- Salvar, renomear, ativar ----------------------------------------------------------
  const fmt = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  };
  function showSaved(iso) { statusEl.textContent = `Última modificação: ${fmt(iso)}`; }

  async function rename() {
    const h1 = $("#op-name");
    const name = h1.textContent.trim();
    if (RO || !name || name === boot.op.name) { h1.textContent = boot.op.name; return; }
    const resp = await fetch(`/operacoes/${boot.op.id}/renomear`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    const body = await resp.json();
    if (!resp.ok) { toast(body.error || "Não renomeou.", "error"); h1.textContent = boot.op.name; return; }
    boot.op.name = body.name;
    document.title = `${body.name} · FO`;
    toast("Operação renomeada.");
  }
  const h1 = $("#op-name");
  h1.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); h1.blur(); } if (e.key === "Escape") { h1.textContent = boot.op.name; h1.blur(); } });
  h1.addEventListener("blur", rename);

  async function save() {
    if (RO) return false;
    statusEl.textContent = "Salvando…";
    try {
      const resp = await fetch(boot.saveUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(exportConfig()) });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      original.nodes = exportConfig().nodes;
      boot.version = body.version;
      $("#version").textContent = `V${body.version}`;
      boot.versions.forEach((v) => { v.current = false; });
      boot.versions.unshift({ version: body.version, at: new Date().toISOString(), current: true });
      serverIssues = body.issues;
      dirty = false;
      showSaved(new Date().toISOString());
      statusEl.className = "when";
      renderValidation();
      toast(`Versão V${body.version} salva.`);
      return true;
    } catch (err) {
      statusEl.textContent = `Não salvou: ${err.message}`;
      toast(`Não salvou: ${err.message}`, "error");
      return false;
    }
  }
  const saveBtn = $("#save");
  if (saveBtn) saveBtn.addEventListener("click", save);
  const statusForm = $("#status-form");
  if (statusForm) statusForm.addEventListener("submit", async (e) => {
    if (!dirty) return;
    e.preventDefault();
    if (await save()) { dirty = false; statusForm.submit(); }
  });

  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || e.target.isContentEditable;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
    if (typing) return;
    if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); $("#undo").click(); }
    else if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); $("#redo").click(); }
    else if (e.key === "Escape") { closePops(); select(null); $("#issues").hidden = true; }
    else if ((e.key === "Delete" || e.key === "Backspace") && selected && selected.startsWith("dest:") && !RO) removeDest(selected.slice(5));
  });
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  // ---- Abas: Configurações e Logs --------------------------------------------------------
  function renderConfigView() {
    const st = boot.op.status;
    const action = (acao, label, cls = "") => `<form method="post" action="/operacoes/${boot.op.id}/status"><input type="hidden" name="acao" value="${acao}"><input type="hidden" name="voltar" value="/operacoes/${boot.op.id}/fluxo"><button class="btn ${cls}" type="submit">${label}</button></form>`;
    $("#view-config").innerHTML = `<div class="grid-2">
      <section class="card"><h2>Identificação</h2>
        <label class="field">Nome<input class="input" id="cfg-name" value="${esc(boot.op.name)}" ${RO ? "disabled" : ""}></label>
        <label class="field">Descrição<textarea class="input" data-bind="description" placeholder="Fluxo para busca, edição e publicação de vídeos automaticamente."></textarea></label>
      </section>
      <section class="card"><h2>Estado da operação</h2>
        <div class="kv"><span>Agora</span><strong>${esc(boot.statusLabel[st])}</strong></div>
        <div class="kv"><span>Versão atual</span><strong>V${boot.version}</strong></div>
        <div class="row">${st === "draft" || st === "paused" ? action("active", "Ativar", "pri") : ""}${st === "active" ? action("paused", "Pausar") : ""}
          <form method="post" action="/operacoes/${boot.op.id}/duplicar"><button class="btn" type="submit">Duplicar</button></form>
          ${st !== "archived" ? action("archived", "Arquivar", "danger") : ""}
          <a class="btn ghost" href="/operacoes/${boot.op.id}?aba=execucoes">${icon("external")} Execuções e detalhes</a></div>
      </section>
      <section class="card"><h2>Automação</h2>
        <label class="field">Play diário às<input class="input" type="time" data-bind="automation.daily_play_at" data-kind="nullable"><small>vazio = desligado</small></label>
        <label class="field">Meta diária<input class="input" type="number" min="1" data-bind="automation.daily_target" data-default="30"></label>
        ${toggle("automation.stock_enabled", "Repor estoque de editados", "")}
        <label class="field">Estoque mínimo (dias)<input class="input" type="number" min="1" max="14" data-bind="automation.stock_min_days" data-default="3"></label>
      </section>
      <section class="card"><h2>Versões</h2>
        ${boot.versions.slice(0, 12).map((v) => `<div class="kv"><span>V${v.version}${v.current ? " · atual" : ""} · ${fmt(v.at)}</span>${!RO && !v.current ? `<button class="btn sm" type="button" data-restore="${v.version}">Restaurar</button>` : ""}</div>`).join("")}
      </section></div>`;
    bindInputs($("#view-config"));
    $$("[data-restore]", $("#view-config")).forEach((b) => b.addEventListener("click", () => restoreVersion(b.dataset.restore)));
    const nameInput = $("#cfg-name");
    if (nameInput) nameInput.addEventListener("change", () => { $("#op-name").textContent = nameInput.value; rename(); });
    const desc = $('[data-bind="description"]', $("#view-config"));
    if (desc) desc.addEventListener("input", () => { $("#op-desc").textContent = desc.value || "Fluxo para busca, edição e publicação de vídeos automaticamente."; });
  }
  const ACTION_LABEL = {
    created: "criada", status_changed: "estado alterado", config_saved: "versão salva", renamed: "renomeada",
    duplicated_from: "duplicada", rendered: "render pronto", failed: "falhou", approved: "aprovado", rejected: "rejeitado",
    published: "publicado", processing: "processando", uncertain: "incerto", files_deleted: "arquivos apagados",
    connection_test: "teste de conexão", version_added: "nova versão", finished: "concluído", retry_wait: "nova tentativa",
  };
  function renderLogs() {
    const rows = boot.events.map((e) => {
      const d = e.detail || {};
      const extra = d.reason || d.message || d.url || (d.version ? `v${d.version}` : "") || "";
      return `<div class="log-row"><time>${esc(fmt(e.at))}</time><strong>${esc(e.entity)}${e.entity_id ? ` #${e.entity_id}` : ""}</strong><span>${esc(ACTION_LABEL[e.action] || e.action)}${extra ? ` · <span class="sub">${esc(String(extra).slice(0, 160))}</span>` : ""}</span></div>`;
    }).join("");
    $("#view-logs").innerHTML = `<section class="card"><div class="row" style="justify-content:space-between"><h2>Últimos eventos da operação</h2><a class="btn sm" href="/fila?op=${boot.op.id}">${icon("queue")} Ver fila da operação</a></div>${rows || '<p class="sub">Nenhum evento ainda.</p>'}</section>`;
  }
  $$(".seg [data-tab]").forEach((b) => b.addEventListener("click", () => {
    $$(".seg [data-tab]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
    const tab = b.dataset.tab;
    body.classList.toggle("tab-flow", tab === "flow");
    $("#view-config").classList.toggle("on", tab === "config");
    $("#view-logs").classList.toggle("on", tab === "logs");
    $("#zoombar").style.visibility = tab === "flow" ? "visible" : "hidden";
    if (tab === "config") renderConfigView();
    if (tab === "logs") renderLogs();
    if (tab === "flow") { renderNodes(false); renderInspector(); }
  }));

  // ---- Início ----------------------------------------------------------------------------
  function renderAll() {
    renderNodes(firstPaint);
    renderInspector();
    renderValidation();
    firstPaint = false;
  }
  showSaved(boot.lastModified);
  renderAll();
  requestAnimationFrame(() => fit(false));
  window.addEventListener("resize", () => renderMinimap());
  const flashEl = document.getElementById("flash-data");
  if (flashEl) { const f = JSON.parse(flashEl.textContent); toast(f.text, f.kind === "error" ? "error" : ""); }
  window.feaFlow = { get model() { return model; }, exportConfig, save, select, fit, addDest };
})();
