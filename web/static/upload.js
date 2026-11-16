// Upload manual (Task 5.4). Com R2, envia direto ao bucket pela URL assinada; sem R2,
// envia pela própria interface. Mostra o andamento de cada arquivo.
(function () {
  const log = document.getElementById("upload-log");

  function line(text, kind) {
    const li = document.createElement("li");
    li.textContent = text;
    if (kind) li.className = kind;
    log.appendChild(li);
    return li;
  }

  async function send(file, endpoint) {
    const li = line(`${file.name}: enviando…`);
    try {
      const ask = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name }),
      });
      const plan = await ask.json();
      if (!ask.ok) throw new Error(plan.detail || "recusado");
      let done;
      if (plan.mode === "direct") {
        done = await fetch(plan.url, {
          method: "PUT", headers: { "Content-Type": plan.content_type }, body: file,
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        done = await fetch(plan.url, { method: "POST", body: form });
      }
      if (!done.ok) throw new Error(`HTTP ${done.status}`);
      li.textContent = `${file.name}: enviado. Entra na próxima busca.`;
      li.className = "ok";
    } catch (err) {
      li.textContent = `${file.name}: falhou (${err.message}).`;
      li.className = "error";
    }
  }

  document.querySelectorAll("[data-upload-url]").forEach((input) => {
    input.addEventListener("change", async () => {
      for (const file of input.files) await send(file, input.dataset.uploadUrl);
      input.value = "";
    });
  });
})();
