// Fluxo da operação: Pesca → Motor Editor → Publicador.
// Cada bloco abre um painel com formulário. O JSON salvo continua sendo o grafo da operação
// ({nodes, edges}): os blocos internos (fontes, rede, aprovação, contas) e as ligações são
// gerados aqui, então o servidor e os workers não mudam.
(function () {
  "use strict";

  const boot = JSON.parse(document.getElementById("canvas-data").textContent);
  const original = boot.config;
  const RO = boot.readOnly;
  const panel = document.getElementById("panel");
  const statusEl = document.getElementById("canvas-status");
  let selected = sessionStorageGet() || "pesca";
  let dirty = false;

  // ---- Modelo ----------------------------------------------------------------------------
  const byType = (t) => (original.nodes || []).filter((n) => n.type === t);
  const one = (t) => byType(t)[0] || { id: t, type: t, config: {} };
  const clone = (v) => JSON.parse(JSON.stringify(v || {}));
  const ids = {
    fishing: one("fishing").id || "pesca",
    edit: one("edit").id || "edicao",
    approval: one("approval").id || "aprovacao",
    publish: one("publish").id || "postagem",
    network: one("network").id || "rede",
  };
  const net = clone(one("network").config);
  const model = {
    fishing: clone(one("fishing").config),
    sources: byType("source").map((n) => ({ id: n.id, ...clone(n.config) })),
    automation: clone(original.automation),
    edit: clone(one("edit").config),
    approval: clone(one("approval").config),
    publish: clone(one("publish").config),
    profiles: (net.profiles && net.profiles.length ? net.profiles : [net.profile || "youtube_shorts"]).slice(),
    accountIds: byType("account").map((n) => (n.config || {}).account_id).filter((v) => Number.isInteger(v)),
    retention: clone(original.retention),
  };
  model.edit.preset = model.edit.preset || {};
  ["video", "mask", "audio"].forEach((k) => { model.edit.preset[k] = model.edit.preset[k] || {}; });
  model.publish.window = model.publish.window || { start: "08:00", end: "23:00" };
  model.publish.titles = model.publish.titles || {};

  function exportConfig() {
    const nodes = [
      { id: ids.fishing, type: "fishing", config: model.fishing },
      { id: ids.edit, type: "edit", config: model.edit },
      { id: ids.approval, type: "approval", config: model.approval },
      { id: ids.publish, type: "publish", config: model.publish },
      { id: ids.network, type: "network", config: { profile: model.profiles[0], profiles: model.profiles } },
    ];
    const edges = [
      { from: ids.fishing, to: ids.edit },
      { from: ids.edit, to: ids.approval },
      { from: ids.approval, to: ids.publish },
      { from: ids.network, to: ids.edit },
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
    return { ...original, nodes, edges, automation: model.automation, retention: model.retention };
  }

  // ---- Utilidades ------------------------------------------------------------------------
  function sessionStorageGet() { try { return sessionStorage.getItem("fea-block"); } catch (e) { return null; } }
  function remember(v) { try { sessionStorage.setItem("fea-block", v); } catch (e) { /* sem storage */ } }
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const list = (v) => (Array.isArray(v) ? v.join(", ") : "");
  const parseList = (t) => t.split(",").map((s) => s.trim()).filter(Boolean);
  const lines = (v) => (Array.isArray(v) ? v.join("\n") : "");
  const parseLines = (t) => t.split("\n").map((s) => s.trim()).filter(Boolean);
  const profileById = Object.fromEntries(boot.profiles.map((p) => [p.id, p]));
  const platformsChosen = () => model.profiles.map((id) => (profileById[id] || {}).platform);
  function common() {
    const ps = model.profiles.map((id) => profileById[id]).filter(Boolean);
    const first = ps[0] || boot.profiles[0];
    const same = (a, b) => a[0] === b[0] && a[1] === b[1];
    const res = first.resolutions.filter((r) => ps.every((p) => p.resolutions.some((x) => same(x, r))));
    const fps = first.fps.filter((f) => ps.every((p) => p.fps.includes(f)));
    return { resolutions: res.length ? res : first.resolutions, fps: fps.length ? fps : first.fps,
      maxDuration: Math.min(...ps.map((p) => p.maxDuration)) };
  }

  function markDirty() {
    dirty = true;
    statusEl.textContent = "Alterações não salvas.";
    statusEl.className = "";
    renderSummaries();
  }

  // Liga um campo do formulário a um caminho do modelo: data-bind="publish.window.start".
  function bindInputs(root) {
    root.querySelectorAll("[data-bind]").forEach((el) => {
      const path = el.dataset.bind.split(".");
      const kind = el.dataset.kind || (el.type === "checkbox" ? "bool" : el.type === "number" ? "num" : "text");
      let target = model;
      path.slice(0, -1).forEach((k) => { target[k] = target[k] || {}; target = target[k]; });
      const key = path[path.length - 1];
      const value = target[key];
      if (kind === "bool") el.checked = value == null ? el.dataset.default === "true" : !!value;
      else if (kind === "list") el.value = list(value);
      else if (kind === "lines") el.value = lines(value);
      else if (kind === "pct") el.value = value == null ? (el.dataset.default || "") : Math.round(value * 100);
      else el.value = value == null ? (el.dataset.default || "") : value;
      if (RO) el.disabled = true;
      el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", () => {
        let v;
        if (kind === "bool") v = el.checked;
        else if (kind === "num") v = el.value === "" ? null : Number(el.value);
        else if (kind === "pct") v = el.value === "" ? null : Number(el.value) / 100;
        else if (kind === "list") v = parseList(el.value);
        else if (kind === "lines") v = parseLines(el.value);
        else if (kind === "nullable") v = el.value || null;
        else v = el.value;
        target[key] = v;
        markDirty();
      });
    });
  }

  const opt = (value, label, current) => `<option value="${esc(value)}"${String(value) === String(current) ? " selected" : ""}>${esc(label)}</option>`;

  // ---- Resumos nos blocos ----------------------------------------------------------------
  function summary(rows) {
    return rows.map(([k, v]) => `<li><span>${esc(k)}</span><span>${esc(v)}</span></li>`).join("");
  }
  function renderSummaries() {
    const f = model.fishing;
    const srcs = model.sources.map((s) => `${(boot.sourceTypes[s.type] || s.type).split(" ")[0]} ${s.reference || ""}`.trim());
    const auto = model.automation || {};
    document.querySelector('[data-summary="pesca"]').innerHTML = summary([
      ["Fontes", srcs.length ? srcs.join(", ") : "nenhuma"],
      ["Tags", list(f.tags) || "todas"],
      ["Por Play", `${f.target_x || 10} vídeos`],
      ["Automático", auto.daily_play_at ? `todo dia ${auto.daily_play_at}` : "desligado"],
    ]);
    const p = model.edit.preset;
    const mask = boot.masks.find((m) => m.id === (p.mask || {}).mask_id);
    const fits = { cover: "preencher", contain: "ajustar", blur: "fundo desfocado" };
    const v = p.video || {};
    document.querySelector('[data-summary="editor"]').innerHTML = summary([
      ["Formato", `${v.width || 1080}×${v.height || 1920} · ${v.fps || 30} fps`],
      ["Enquadrar", fits[v.fit || "blur"]],
      ["Máscara", mask ? mask.name : "sem máscara"],
      ["Áudio", { keep: "original", remove: "sem áudio", replace: "substituído" }[(p.audio || {}).mode || "keep"]],
    ]);
    const accs = boot.accounts.filter((a) => model.accountIds.includes(a.id));
    const pub = model.publish;
    document.querySelector('[data-summary="publicador"]').innerHTML = summary([
      ["Redes", model.profiles.map((id) => (profileById[id] || {}).name || id).join(", ")],
      ["Contas", accs.length ? accs.map((a) => a.name).join(", ") : "nenhuma"],
      ["Aprovação", model.approval.auto_approve ? "automática" : "manual"],
      ["Envio", `${pub.automatic ? "automático" : "manual"} · ${pub.mode === "all" ? "todas as contas" : "rodízio"} · ${pub.interval_min || 0} min`],
    ]);
  }

  // ---- Painéis ---------------------------------------------------------------------------
  function readyNote(service, label) {
    if (boot.ready[service]) return "";
    return `<p class="callout">${esc(label)}: chaves não preenchidas. <a href="/contas#${service}">Preencher em Acessos</a>.</p>`;
  }

  function sourceRow(s, i) {
    const types = Object.entries(boot.sourceTypes).map(([k, v]) => opt(k, v, s.type || "reddit")).join("");
    const ph = { reddit: "r/comunidade", x: "@usuario ou termo de busca", upload: "nome da pasta (opcional)" }[s.type || "reddit"];
    return `<div class="list-item" data-source="${i}">
      <label class="field">Rede de busca<select class="input" data-src="type">${types}</select></label>
      <label class="field">Onde buscar<input class="input" data-src="reference" value="${esc(s.reference)}" placeholder="${esc(ph)}"></label>
      <label class="field">Permissão de uso<input class="input" data-src="permission_note" value="${esc(s.permission_note)}" placeholder="licença, autorização do criador…"></label>
      ${RO ? "" : `<button class="btn sm ghost danger" type="button" data-remove-source="${i}">Remover</button>`}
    </div>`;
  }

  function panelPesca() {
    const used = new Set(model.sources.map((s) => s.type || "reddit"));
    const notes = [used.has("reddit") ? readyNote("reddit", "Reddit") : "", used.has("x") ? readyNote("x", "X") : ""].join("");
    return `<div class="panel-head"><div><h2>Pesca</h2><p class="sub">De onde buscar, o que aceitar e quanto trazer a cada Play.</p></div></div>
    <div class="group"><h3>Fontes de busca</h3>${notes}
      <div id="sources">${model.sources.map(sourceRow).join("") || '<p class="sub">Nenhuma fonte. Adicione ao menos uma.</p>'}</div>
      ${RO ? "" : '<div class="row"><button class="btn sm" type="button" id="add-source">+ Adicionar fonte</button></div>'}
      <p class="sub">Sem permissão registrada, os itens entram como pendentes e não são baixados até você liberar na Fila.</p>
    </div>
    <div class="group"><h3>O que buscar</h3>
      <div class="grid">
        <label class="field">Tags<input class="input" data-bind="fishing.tags" data-kind="list" placeholder="academia, treino"><small>separadas por vírgula</small></label>
        <label class="field">Heat tags<input class="input" data-bind="fishing.heat_tags" data-kind="list" placeholder="supino"><small>valem 2 pontos no score</small></label>
        <label class="field">Palavras bloqueadas<input class="input" data-bind="fishing.blocked_words" data-kind="list" placeholder="nsfw"></label>
        <label class="field">Duração máxima (s)<input class="input" type="number" min="1" data-bind="fishing.max_duration_s"></label>
      </div>
      <div class="row">
        <label class="check"><input type="checkbox" data-media="video"> Vídeos</label>
        <label class="check"><input type="checkbox" data-media="image"> Imagens</label>
        <label class="check"><input type="checkbox" data-bind="fishing.reject_watermarks" data-default="true"> Recusar vídeos com marca d'água de terceiros</label>
      </div>
    </div>
    <div class="group"><h3>Quantidade por Play</h3>
      <div class="grid">
        <label class="field">Meta de vídeos<input class="input" type="number" min="1" data-bind="fishing.target_x" data-default="10"></label>
        <label class="field">Posts examinados no máximo<input class="input" type="number" min="1" data-bind="fishing.search_budget" data-default="300"></label>
        <label class="field">Critério<select class="input" data-bind="fishing.criteria" data-default="recent">${opt("recent", "Mais recentes")}${opt("heat", "Priorizar heat tags")}</select></label>
      </div>
    </div>
    <div class="group"><h3>Modo automático</h3>
      <div class="grid">
        <label class="field">Play diário às<input class="input" type="time" data-bind="automation.daily_play_at" data-kind="nullable"><small>vazio = desligado</small></label>
        <label class="field">Meta diária<input class="input" type="number" min="1" data-bind="automation.daily_target" data-default="30"></label>
        <label class="field">Estoque mínimo (dias)<input class="input" type="number" min="1" max="14" data-bind="automation.stock_min_days" data-default="3"></label>
      </div>
      <label class="check"><input type="checkbox" data-bind="automation.stock_enabled"> Repor estoque de editados automaticamente</label>
    </div>`;
  }

  function maskOptions() {
    const current = (model.edit.preset.mask || {}).mask_id || null;
    const none = `<label class="opt"><input type="radio" name="mask" value="" ${current ? "" : "checked"} ${RO ? "disabled" : ""}><span><strong>Sem máscara</strong><small class="sub">só o vídeo padronizado</small></span></label>`;
    return none + boot.masks.map((m) => `<label class="opt"><input type="radio" name="mask" value="${m.id}" ${m.id === current ? "checked" : ""} ${RO ? "disabled" : ""}>
      <img class="mask-thumb" src="${esc(m.url)}" alt="">
      <span><strong>${esc(m.name)}</strong><small class="sub">v${m.version} · ${esc(m.size)}${m.alpha ? "" : " · sem transparência"}</small></span></label>`).join("");
  }

  function panelEditor() {
    const c = common();
    const v = model.edit.preset.video;
    const current = `${v.width || 1080}x${v.height || 1920}`;
    const res = c.resolutions.map(([w, h]) => opt(`${w}x${h}`, `${w}×${h}`, current)).join("");
    const fps = c.fps.map((f) => opt(f, `${f} fps`, v.fps || 30)).join("");
    return `<div class="panel-head"><div><h2>Motor Editor</h2><p class="sub">Padroniza todo vídeo pelo mesmo preset: tamanho, enquadramento, máscara PNG e áudio. Sem área de edição.</p></div>
      <a class="btn sm" href="${esc(boot.presetUrl)}">Textos, logo, áudio e Testar preset →</a></div>
    <div class="group"><h3>Redimensionamento</h3>
      <div class="grid">
        <label class="field">Resolução<select class="input" id="resolution" ${RO ? "disabled" : ""}>${res}</select><small>padrão comum às redes escolhidas no Publicador</small></label>
        <label class="field">FPS<select class="input" data-bind="edit.preset.video.fps" data-kind="num" data-default="30">${fps}</select></label>
        <label class="field">Enquadramento<select class="input" data-bind="edit.preset.video.fit" data-default="blur">${opt("blur", "Fundo desfocado")}${opt("cover", "Preencher (corta)")}${opt("contain", "Ajustar (barras)")}</select></label>
        <label class="field">Posição do corte<select class="input" data-bind="edit.preset.video.crop_position" data-default="center">${opt("center", "Centro")}${opt("top", "Topo")}${opt("bottom", "Base")}</select></label>
        <label class="field">Cor das barras<input class="input" type="color" data-bind="edit.preset.video.background" data-default="#000000"></label>
      </div>
      <p class="sub">Duração máxima do vídeo final: ${Math.round(c.maxDuration)} s (a menor entre as redes escolhidas).</p>
    </div>
    <div class="group"><h3>Máscara PNG</h3>
      <div class="opt-grid" id="masks">${maskOptions()}</div>
      ${RO ? "" : `<div class="row"><label class="btn sm">Importar PNG<input type="file" accept="image/png" id="mask-file" hidden></label><span class="sub" id="mask-status">${c.resolutions[0][0]}×${c.resolutions[0][1]} com transparência. Nova importação com o mesmo nome vira versão nova.</span></div>`}
      <div class="grid">
        <label class="field">Opacidade (%)<input class="input" type="number" min="0" max="100" data-bind="edit.preset.mask.opacity" data-kind="pct" data-default="100"></label>
        <label class="field">Escala (%)<input class="input" type="number" min="1" max="400" data-bind="edit.preset.mask.scale" data-kind="pct" data-default="100"></label>
        <label class="field">Alinhamento<select class="input" data-bind="edit.preset.mask.align" data-default="center">${opt("center", "Centro")}${opt("top", "Topo")}${opt("bottom", "Base")}</select></label>
      </div>
    </div>
    <div class="group"><h3>Áudio</h3>
      <div class="grid">
        <label class="field">Modo<select class="input" data-bind="edit.preset.audio.mode" data-default="keep">${opt("keep", "Manter o original")}${opt("remove", "Remover")}${opt("replace", "Substituir (arquivo na tela completa)")}</select></label>
        <label class="field">Volume (%)<input class="input" type="number" min="0" max="200" data-bind="edit.preset.audio.volume" data-kind="pct" data-default="100"></label>
      </div>
      <label class="check"><input type="checkbox" data-bind="edit.preset.audio.normalize" data-default="true"> Normalizar volume</label>
    </div>`;
  }

  function panelPublicador() {
    const plats = platformsChosen();
    const networks = boot.profiles.map((p) => `<label class="opt"><input type="checkbox" data-profile="${p.id}" ${model.profiles.includes(p.id) ? "checked" : ""} ${RO ? "disabled" : ""}>
      <span><strong>${esc(p.name)}</strong><small class="sub">${esc(p.notes || "")}</small></span></label>`).join("");
    const notes = [...new Set(plats)].map((pl) => readyNote(pl, boot.platformLabel[pl] || pl)).join("");
    const accs = boot.accounts.filter((a) => plats.includes(a.platform));
    const accounts = accs.map((a) => {
      const label = { connected: "conectada", error: "com erro", paused: "pausada", revoked: "revogada" }[a.status];
      const off = a.status === "revoked";
      return `<label class="opt${off ? " disabled" : ""}"><input type="checkbox" data-account="${a.id}" ${model.accountIds.includes(a.id) ? "checked" : ""} ${RO || off ? "disabled" : ""}>
        <span><strong>${esc(a.name)}</strong><small class="sub">${esc(boot.platformLabel[a.platform] || a.platform)} · ${label}</small></span></label>`;
    }).join("");
    const tz = model.publish.timezone || "America/Sao_Paulo";
    const zones = ["America/Sao_Paulo", "America/Manaus", "America/New_York", "Europe/Lisbon", "UTC"];
    if (!zones.includes(tz)) zones.push(tz);
    return `<div class="panel-head"><div><h2>Publicador</h2><p class="sub">Onde publicar, com quais contas, quando e com que título. O título é gerado na hora da publicação e nunca vai para dentro do vídeo.</p></div>
      <a class="btn sm" href="/contas">Conectar contas →</a></div>
    <div class="group"><h3>Redes sociais</h3><div class="opt-grid">${networks}</div>${notes}</div>
    <div class="group"><h3>Contas que publicam</h3>
      ${accounts ? `<div class="opt-grid">${accounts}</div>` : '<p class="sub">Nenhuma conta conectada nessas redes. Conecte em <a href="/contas">Acessos</a> e volte aqui.</p>'}
    </div>
    <div class="group"><h3>Aprovação</h3>
      <div class="opt-grid">
        <label class="opt"><input type="radio" name="approval" value="manual" ${model.approval.auto_approve ? "" : "checked"} ${RO ? "disabled" : ""}><span><strong>Manual</strong><small class="sub">você aprova cada vídeo na tela Aprovação</small></span></label>
        <label class="opt"><input type="radio" name="approval" value="auto" ${model.approval.auto_approve ? "checked" : ""} ${RO ? "disabled" : ""}><span><strong>Automática</strong><small class="sub">aprova quem passa no controle de qualidade e tem permissão</small></span></label>
      </div>
    </div>
    <div class="group"><h3>Distribuição e agenda</h3>
      <label class="check"><input type="checkbox" data-bind="publish.automatic"> Distribuir automaticamente os vídeos aprovados</label>
      <div class="grid">
        <label class="field">Modo<select class="input" data-bind="publish.mode" data-default="rotation">${opt("rotation", "Rodízio")}${opt("all", "Todas as contas")}</select></label>
        <label class="field">Intervalo (min)<input class="input" type="number" min="0" data-bind="publish.interval_min" data-default="30"></label>
        <label class="field">Janela: início<input class="input" type="time" data-bind="publish.window.start"></label>
        <label class="field">Janela: fim<input class="input" type="time" data-bind="publish.window.end"></label>
        <label class="field">Fuso<select class="input" data-bind="publish.timezone">${zones.map((z) => opt(z, z, tz)).join("")}</select></label>
        <label class="field">Privacidade<select class="input" data-bind="publish.privacy" data-default="public">${opt("public", "Público")}${opt("unlisted", "Não listado")}${opt("private", "Privado")}</select></label>
      </div>
      <label class="check"><input type="checkbox" data-bind="publish.first_immediate"> Primeira publicação imediata</label>
    </div>
    <div class="group"><h3>Título, legenda e hashtags</h3>
      <div class="grid">
        <label class="field">Método do título<select class="input" data-bind="publish.titles.method" data-default="markov">${opt("markov", "Gerado (Markov) com modelos de reserva")}${opt("templates", "Só os modelos")}</select></label>
        <label class="field">Hashtags<input class="input" data-bind="publish.titles.hashtags" data-kind="list" placeholder="shorts, academia"></label>
        <label class="field">Palavras proibidas no título<input class="input" data-bind="publish.titles.blocked_words" data-kind="list"></label>
      </div>
      <div class="grid">
        <label class="field">Modelos de título<textarea class="input" data-bind="publish.titles.templates" data-kind="lines" placeholder="{texto}"></textarea><small>um por linha; {texto} = texto do post original</small></label>
        <label class="field">Frases de referência<textarea class="input" data-bind="publish.titles.corpus" data-kind="lines"></textarea><small>um por linha; alimentam o gerador</small></label>
        <label class="field">Modelo da descrição<textarea class="input" data-bind="publish.titles.description_template" placeholder="{titulo}&#10;&#10;{hashtags}"></textarea><small>{titulo}, {hashtags}, {texto}</small></label>
      </div>
    </div>
    <div class="group"><h3>Limpeza</h3>
      <div class="grid"><label class="field">Apagar arquivos após publicar (min)<input class="input" type="number" min="0" data-bind="retention.delete_after_minutes" data-default="30"></label></div>
    </div>`;
  }

  const PANELS = { pesca: panelPesca, editor: panelEditor, publicador: panelPublicador };

  function renderPanel() {
    document.querySelectorAll("[data-block]").forEach((b) => {
      b.classList.toggle("on", b.dataset.block === selected);
      b.setAttribute("aria-expanded", b.dataset.block === selected ? "true" : "false");
    });
    panel.innerHTML = PANELS[selected]();
    bindInputs(panel);
    wirePanel();
  }

  function wirePanel() {
    // Fontes
    panel.querySelectorAll("[data-source]").forEach((row) => {
      const s = model.sources[Number(row.dataset.source)];
      row.querySelectorAll("[data-src]").forEach((el) => {
        if (RO) el.disabled = true;
        el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
          s[el.dataset.src] = el.value;
          markDirty();
          if (el.dataset.src === "type") renderPanel();
        });
      });
    });
    panel.querySelectorAll("[data-remove-source]").forEach((b) => b.addEventListener("click", () => {
      model.sources.splice(Number(b.dataset.removeSource), 1);
      markDirty();
      renderPanel();
    }));
    const add = panel.querySelector("#add-source");
    if (add) add.addEventListener("click", () => {
      model.sources.push({ id: `f${Date.now().toString(36)}`, type: "reddit", reference: "", permission_note: "" });
      markDirty();
      renderPanel();
    });
    // Mídias aceitas
    panel.querySelectorAll("[data-media]").forEach((el) => {
      const accepted = model.fishing.accepted_media || ["video"];
      el.checked = accepted.includes(el.dataset.media);
      if (RO) el.disabled = true;
      el.addEventListener("change", () => {
        const set = new Set(model.fishing.accepted_media || []);
        if (el.checked) set.add(el.dataset.media); else set.delete(el.dataset.media);
        model.fishing.accepted_media = [...set];
        markDirty();
      });
    });
    // Resolução
    const res = panel.querySelector("#resolution");
    if (res) res.addEventListener("change", () => {
      const [w, h] = res.value.split("x").map(Number);
      Object.assign(model.edit.preset.video, { width: w, height: h });
      markDirty();
    });
    // Máscara
    panel.querySelectorAll('input[name="mask"]').forEach((el) => el.addEventListener("change", () => {
      model.edit.preset.mask.mask_id = el.value ? Number(el.value) : null;
      markDirty();
    }));
    const file = panel.querySelector("#mask-file");
    if (file) file.addEventListener("change", uploadMask);
    // Redes e contas
    panel.querySelectorAll("[data-profile]").forEach((el) => el.addEventListener("change", () => {
      const set = model.profiles.filter((p) => p !== el.dataset.profile);
      if (el.checked) set.push(el.dataset.profile);
      model.profiles = boot.profiles.map((p) => p.id).filter((id) => set.includes(id));
      if (!model.profiles.length) { model.profiles = [el.dataset.profile]; el.checked = true; }
      const plats = platformsChosen();
      model.accountIds = model.accountIds.filter((id) => {
        const a = boot.accounts.find((x) => x.id === id);
        return a && plats.includes(a.platform);
      });
      markDirty();
      renderPanel();
    }));
    panel.querySelectorAll("[data-account]").forEach((el) => el.addEventListener("change", () => {
      const id = Number(el.dataset.account);
      model.accountIds = model.accountIds.filter((x) => x !== id);
      if (el.checked) model.accountIds.push(id);
      markDirty();
    }));
    panel.querySelectorAll('input[name="approval"]').forEach((el) => el.addEventListener("change", () => {
      model.approval.auto_approve = el.value === "auto";
      markDirty();
    }));
  }

  async function uploadMask(event) {
    const input = event.target;
    const status = panel.querySelector("#mask-status");
    const f = input.files[0];
    if (!f) return;
    status.textContent = `Enviando ${f.name}…`;
    const form = new FormData();
    form.append("file", f);
    form.append("name", f.name.replace(/\.png$/i, ""));
    const same = boot.masks.find((m) => `${m.name}.png`.toLowerCase() === f.name.toLowerCase());
    if (same) form.append("mask_id", same.id);
    try {
      const resp = await fetch(boot.maskUploadUrl, { method: "POST", body: form, headers: { Accept: "application/json" } });
      const body = await resp.json();
      if (body.masks) boot.masks = body.masks;
      if (resp.ok) {
        const latest = boot.masks.find((m) => m.name === f.name.replace(/\.png$/i, "")) || boot.masks[boot.masks.length - 1];
        if (latest) { model.edit.preset.mask.mask_id = latest.id; markDirty(); }
      }
      renderPanel();
      const after = panel.querySelector("#mask-status");
      if (after) { after.textContent = body.message; after.style.color = resp.ok ? "var(--ok)" : "var(--error)"; }
    } catch (err) {
      status.textContent = `Falhou: ${err.message}`;
    }
  }

  // ---- Validação -------------------------------------------------------------------------
  const BLOCK_OF = { source: "pesca", fishing: "pesca", edit: "editor", network: "editor", approval: "publicador", publish: "publicador", account: "publicador" };
  function blockOfIssue(issue) {
    const node = (original.nodes || []).find((n) => n.id === issue.node_id);
    if (node) return BLOCK_OF[node.type];
    if (issue.node_id && issue.node_id.startsWith("f")) return "pesca";
    const m = issue.message.toLowerCase();
    if (m.includes("pesca") || m.includes("fonte")) return "pesca";
    if (m.includes("motor editor") || m.includes("rede")) return "editor";
    return "publicador";
  }
  function showIssues(issues) {
    const box = document.getElementById("canvas-issues");
    const errors = issues.filter((i) => i.level === "error");
    document.querySelectorAll("[data-dot]").forEach((d) => {
      const mine = issues.filter((i) => blockOfIssue(i) === d.dataset.dot);
      const bad = mine.some((i) => i.level === "error");
      d.className = `dot ${bad ? "bad" : mine.length ? "warn" : "ok"}`;
      document.querySelector(`[data-block="${d.dataset.dot}"]`).classList.toggle("has-error", bad);
    });
    if (!issues.length) {
      box.innerHTML = '<p class="issue ok"><strong>Pronto.</strong> O fluxo está completo e pode ser ativado.</p>';
      return;
    }
    box.innerHTML = issues.map((i) => `<p class="issue ${i.level}"><strong>${i.level === "error" ? "Erro" : "Aviso"}</strong> · ${esc(i.message)}</p>`).join("")
      + (errors.length ? '<p class="sub">Rascunho pode ser salvo com erros; para ativar, corrija os erros.</p>' : "");
  }

  async function save() {
    statusEl.textContent = "Salvando…";
    statusEl.className = "";
    try {
      const resp = await fetch(boot.saveUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(exportConfig()) });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
      original.nodes = exportConfig().nodes;
      document.getElementById("version").textContent = `v${body.version}`;
      dirty = false;
      statusEl.textContent = `Versão v${body.version} salva.`;
      statusEl.className = "ok";
      showIssues(body.issues);
    } catch (err) {
      statusEl.textContent = `Não salvou: ${err.message}`;
      statusEl.className = "error";
    }
  }

  // ---- Início ----------------------------------------------------------------------------
  document.querySelectorAll("[data-block]").forEach((b) => b.addEventListener("click", () => {
    selected = b.dataset.block;
    remember(selected);
    renderPanel();
    if (window.matchMedia("(max-width: 760px)").matches) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  const saveBtn = document.getElementById("save");
  if (saveBtn) saveBtn.addEventListener("click", save);
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  if (!PANELS[selected]) selected = "pesca";
  renderSummaries();
  renderPanel();
  showIssues(boot.issues || []);
  window.feaFlow = { model, exportConfig, save };
})();
