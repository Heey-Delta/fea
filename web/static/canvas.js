// Canvas de blocos da operação (Task 4.8 a 4.13), sobre o Drawflow.
// Converte entre a configuração da operação ({nodes, edges}) e o editor, recusa ligações
// fora da tabela de tipos de porta e salva pela API POST /operacoes/{id}/config.
(function () {
  const boot = JSON.parse(document.getElementById("canvas-data").textContent);
  const PORTS = {
    source: [0, 1], fishing: [1, 1], edit: [1, 1], approval: [1, 1],
    publish: [1, 0], network: [0, 1], account: [0, 1],
  };
  // Posição inicial (coluna, linha) de cada tipo, para fluxos salvos sem posição:
  // o fluxo principal numa linha, a Rede abaixo da Edição e as Contas abaixo da Aprovação.
  const SLOT = {
    source: [0, 0], fishing: [1, 0], edit: [2, 0], approval: [3, 0],
    publish: [4, 0], network: [2, 1], account: [3, 1],
  };
  const stacked = {};
  const allowed = new Set(boot.allowedEdges.map(([a, b]) => `${a}>${b}`));

  const el = document.getElementById("drawflow");
  const editor = new Drawflow(el);
  editor.reroute = false;
  editor.start();
  if (boot.readOnly) editor.editor_mode = "fixed";
  window.feaEditor = editor; // usado pelos testes de navegador

  const status = document.getElementById("canvas-status");
  const issuesBox = document.getElementById("canvas-issues");
  const panel = document.getElementById("panel");
  let selected = null;
  let dirty = false;

  function say(text, kind) {
    status.textContent = text;
    status.className = kind || "";
  }

  function nodeHtml(node) {
    const label = boot.labels[node.type] || node.type;
    const name = (node.config && (node.config.reference || node.config.name)) || "";
    return `<div class="node-title">${escapeHtml(label)}</div>` +
      `<div class="node-sub">${escapeHtml(name || node.id)}</div>`;
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function addNode(node) {
    const [ins, outs] = PORTS[node.type];
    let pos = node.pos;
    if (!pos) {
      const [col, row] = SLOT[node.type];
      const n = (stacked[node.type] = (stacked[node.type] || 0) + 1) - 1;
      pos = { x: 30 + col * 190, y: 40 + row * 150 + n * 90 };
    }
    const data = { id: node.id, type: node.type, config: node.config || {}, extra: node.extra || {} };
    return editor.addNode(node.type, ins, outs, pos.x, pos.y, `t-${node.type}`, data, nodeHtml(node));
  }

  // --- carregar --------------------------------------------------------------------------
  const drawflowId = {};
  boot.config.nodes.forEach((node) => { drawflowId[node.id] = addNode(node); });
  boot.config.edges.forEach((edge) => {
    if (drawflowId[edge.from] && drawflowId[edge.to]) {
      editor.addConnection(drawflowId[edge.from], drawflowId[edge.to], "output_1", "input_1");
    }
  });
  dirty = false;
  fitToView();

  // Ajusta o zoom para o fluxo inteiro caber na área visível (nunca aumenta).
  function fitToView() {
    const nodes = Object.values(editor.export().drawflow.Home.data);
    if (!nodes.length) return;
    const right = Math.max(...nodes.map((n) => n.pos_x)) + 200;
    const bottom = Math.max(...nodes.map((n) => n.pos_y)) + 120;
    const zoom = Math.min(1, el.clientWidth / right, el.clientHeight / bottom);
    if (zoom < 1) {
      editor.zoom = Math.max(zoom, editor.zoom_min);
      editor.zoom_refresh();
      // O Drawflow escala a partir do centro: reposiciona para começar no canto.
      const shift = (1 - editor.zoom) / 2;
      editor.canvas_x = -el.clientWidth * shift;
      editor.canvas_y = -el.clientHeight * shift;
      editor.precanvas.style.transform =
        `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    }
  }

  // --- ligações --------------------------------------------------------------------------
  editor.on("connectionCreated", (c) => {
    const from = editor.getNodeFromId(c.output_id).data.type;
    const to = editor.getNodeFromId(c.input_id).data.type;
    if (!allowed.has(`${from}>${to}`)) {
      editor.removeSingleConnection(c.output_id, c.input_id, c.output_class, c.input_class);
      say(`Ligação recusada: ${boot.labels[from]} não pode ligar em ${boot.labels[to]}.`, "error");
      return;
    }
    markDirty();
  });
  editor.on("connectionRemoved", markDirty);
  editor.on("nodeMoved", markDirty);
  editor.on("nodeRemoved", () => { selected = null; renderPanel(); markDirty(); });

  function markDirty() {
    dirty = true;
    say("Alterações não salvas.", "");
  }

  // --- paleta ----------------------------------------------------------------------------
  document.querySelectorAll("[data-add]").forEach((button) => {
    button.addEventListener("click", () => {
      const type = button.dataset.add;
      const id = `${type}_${Date.now().toString(36)}`;
      const config = type === "source" ? { type: "reddit", reference: "", permission_note: "" } : {};
      const newId = addNode({ id, type, config, pos: { x: 40, y: 400 } });
      editor.selectNode && editor.selectNode(`node-${newId}`);
      markDirty();
    });
  });

  // --- painel do bloco -------------------------------------------------------------------
  editor.on("nodeSelected", (id) => { selected = id; renderPanel(); });
  editor.on("nodeUnselected", () => { selected = null; renderPanel(); });

  function renderPanel() {
    if (selected === null) {
      panel.innerHTML = '<p class="sub">Clique num bloco para ver e editar a configuração.</p>';
      return;
    }
    const node = editor.getNodeFromId(selected);
    const label = boot.labels[node.data.type];
    panel.innerHTML = `
      <h2>${escapeHtml(label)}</h2>
      <p class="sub">id: ${escapeHtml(node.data.id)}</p>
      <label class="field" for="node-config">Configuração do bloco (JSON)
        <textarea class="input code" id="node-config" rows="14"></textarea>
      </label>
      <p class="sub">Os formulários específicos de cada bloco chegam com as tasks de Pesca, Edição e Postagem.</p>
      <div class="row">
        <button class="btn sm pri" type="button" id="apply-node">Aplicar ao bloco</button>
        <button class="btn sm" type="button" id="remove-node">Remover bloco</button>
      </div>`;
    const area = document.getElementById("node-config");
    area.value = JSON.stringify(node.data.config, null, 2);
    area.readOnly = boot.readOnly;
    document.getElementById("apply-node").onclick = () => {
      try {
        const config = JSON.parse(area.value);
        editor.updateNodeDataFromId(selected, { ...node.data, config });
        document.querySelector(`#node-${selected} .drawflow_content_node`).innerHTML =
          nodeHtml({ ...node.data, config });
        markDirty();
      } catch (err) {
        say("JSON inválido: " + err.message, "error");
      }
    };
    document.getElementById("remove-node").onclick = () => editor.removeNodeId(`node-${selected}`);
  }
  renderPanel();

  // --- salvar ----------------------------------------------------------------------------
  function exportConfig() {
    const data = editor.export().drawflow.Home.data;
    const nodes = [];
    const edges = [];
    Object.values(data).forEach((n) => {
      nodes.push({
        id: n.data.id, type: n.data.type, config: n.data.config,
        pos: { x: Math.round(n.pos_x), y: Math.round(n.pos_y) },
      });
      Object.values(n.outputs).forEach((out) => out.connections.forEach((c) => {
        edges.push({ from: n.data.id, to: data[c.node].data.id });
      }));
    });
    return { ...boot.config, nodes, edges };
  }
  window.feaExportConfig = exportConfig;

  function showIssues(issues) {
    issuesBox.innerHTML = issues.length
      ? issues.map((i) => `<p class="issue ${i.level}"><strong>${i.level === "error" ? "ERRO" : "AVISO"}</strong> ${escapeHtml(i.message)}</p>`).join("")
      : "<p>Fluxo completo. A operação pode ser ativada.</p>";
    document.querySelectorAll(".drawflow-node").forEach((n) => n.classList.remove("has-error"));
    issues.forEach((i) => {
      if (!i.node_id) return;
      const id = Object.entries(editor.export().drawflow.Home.data)
        .find(([, n]) => n.data.id === i.node_id);
      if (id) document.getElementById(`node-${id[0]}`).classList.add("has-error");
    });
  }
  showIssues(boot.issues);

  const saveButton = document.getElementById("save");
  if (saveButton) {
    saveButton.addEventListener("click", async () => {
      say("Salvando…", "");
      const response = await fetch(boot.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(exportConfig()),
      });
      const body = await response.json();
      if (!response.ok) {
        say(body.error || "Não foi possível salvar.", "error");
        return;
      }
      dirty = false;
      document.getElementById("version").textContent = `v${body.version}`;
      say(`Versão v${body.version} salva.`, "ok");
      showIssues(body.issues);
    });
  }

  window.addEventListener("beforeunload", (e) => {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });
})();
