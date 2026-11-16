// Envio de arquivos do preset (logo, marca d'água, áudio, amostra). Com R2 vai direto ao
// bucket pela URL assinada; sem R2, pela interface. A chave volta para o campo indicado.
(function () {
  async function send(file, endpoint) {
    const ask = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name }),
    });
    const plan = await ask.json();
    if (!ask.ok) throw new Error(plan.detail || "recusado");
    if (plan.mode === "direct") {
      const put = await fetch(plan.url, {
        method: "PUT", headers: { "Content-Type": plan.content_type }, body: file,
      });
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

  document.querySelectorAll("[data-asset-target]").forEach((input) => {
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file) return;
      const target = document.getElementById(input.dataset.assetTarget);
      const status = document.getElementById(input.dataset.assetTarget + "-status");
      status.textContent = "enviando…";
      try {
        target.value = await send(file, input.dataset.assetUrl);
        status.textContent = "enviado. Salve o preset para usar.";
        if (target.tagName === "SELECT" || target.dataset.submit) target.form.requestSubmit?.();
      } catch (err) {
        status.textContent = `falhou (${err.message}).`;
      }
      input.value = "";
    });
  });
})();
