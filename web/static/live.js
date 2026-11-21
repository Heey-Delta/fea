// Estado ao vivo das operações (rodinha, estágios, erro) e dicas dos gráficos.
// Atualiza a cada 5 s só enquanto a aba está visível, para não manter o banco acordado à toa.
(function () {
  "use strict";
  const PERIOD = 5000;

  function liveIds() {
    return Array.from(document.querySelectorAll("[data-live]")).map((el) => el.dataset.live);
  }

  async function refresh() {
    const ids = [...new Set(liveIds())];
    if (!ids.length || document.hidden) return;
    try {
      const res = await fetch(`/operacoes/ao-vivo?ids=${ids.join(",")}`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!res.ok) return;
      const data = await res.json();
      for (const [id, st] of Object.entries(data)) {
        document.querySelectorAll(`[data-live="${id}"]`).forEach((el) => {
          if (el.innerHTML.trim() !== st.html.trim()) el.innerHTML = st.html;
        });
        document.querySelectorAll(`[data-live-row="${id}"]`).forEach((row) => {
          row.classList.toggle("run", st.running);
          row.classList.toggle("err", st.error);
        });
      }
    } catch (_) {
      /* sem rede: tenta de novo no próximo ciclo */
    }
  }

  if (liveIds().length) {
    setInterval(refresh, PERIOD);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  }

  // Dica ao passar o mouse / tocar numa coluna ou segmento ([data-tip]).
  const tip = document.getElementById("viz-tip");
  if (!tip) return;
  function show(target, x, y) {
    tip.textContent = target.dataset.tip;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    const left = Math.min(Math.max(8, x - r.width / 2), window.innerWidth - r.width - 8);
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(8, y - r.height - 12)}px`;
  }
  function hide() { tip.hidden = true; }
  document.addEventListener("pointerover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (t) show(t, e.clientX, e.clientY);
  });
  document.addEventListener("pointermove", (e) => {
    const t = e.target.closest("[data-tip]");
    if (t) show(t, e.clientX, e.clientY); else hide();
  });
  document.addEventListener("focusin", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) return;
    const r = t.getBoundingClientRect();
    show(t, r.left + r.width / 2, r.top);
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, { passive: true });
})();
