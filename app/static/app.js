/* Dashboard de Oportunidades — filtros e renderização */
(function () {
  const $ = (id) => document.getElementById(id);
  const cards = $("cards"), empty = $("empty");
  let t = null;

  const els = {
    q: $("f-q"), regiao: $("f-regiao"), uf: $("f-uf"),
    inscricaoAte: $("f-inscricao-ate"), provaDe: $("f-prova-de"), provaAte: $("f-prova-ate"),
    order: $("f-order"), status: $("f-status"),
  };

  function materiasSelecionadas() {
    return Array.from(document.querySelectorAll(".f-materia:checked")).map(c => c.value);
  }

  function fmtData(iso) {
    if (!iso) return null;
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }

  function diasRestantes(iso) {
    if (!iso) return null;
    const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
    const alvo = new Date(iso + "T00:00:00");
    return Math.round((alvo - hoje) / 86400000);
  }

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function cardHTML(c) {
    const dias = diasRestantes(c.inscricao_fim);
    let deadlineCls = "", deadlineTxt = "";
    if (c.inscricao_fim) {
      if (dias < 0) { deadlineTxt = "inscrições encerradas"; }
      else if (dias === 0) { deadlineTxt = "último dia de inscrição!"; deadlineCls = "vence-hoje"; }
      else if (dias <= 3) { deadlineTxt = `inscrições até ${fmtData(c.inscricao_fim)} (${dias} dia${dias > 1 ? "s" : ""}!)`; deadlineCls = "d3"; }
      else if (dias <= 7) { deadlineTxt = `inscrições até ${fmtData(c.inscricao_fim)} (${dias} dias)`; deadlineCls = "d7"; }
      else { deadlineTxt = `inscrições até ${fmtData(c.inscricao_fim)}`; }
    } else if (c.inscricao_texto) {
      deadlineTxt = esc(c.inscricao_texto);
    }
    const urgente = dias !== null && dias >= 0 && dias <= 7;

    const tags = (c.materias || []).slice(0, 6).map(m => `<span class="tag">${esc(m)}</span>`).join("");
    const mais = (c.materias || []).length > 6 ? `<span class="tag mais">+${c.materias.length - 6}</span>` : "";

    const meta = [];
    if (c.vagas) meta.push(`<span><b>${c.vagas.toLocaleString("pt-BR")}</b> vaga${c.vagas > 1 ? "s" : ""}</span>`);
    if (c.salario) meta.push(`<span>até <b>${esc(c.salario)}</b></span>`);
    if (c.escolaridade) meta.push(`<span>${esc(c.escolaridade)}</span>`);
    if (c.banca) meta.push(`<span>banca: <b>${esc(c.banca)}</b></span>`);
    if (c.taxa) meta.push(`<span>taxa: ${esc(c.taxa)}</span>`);

    const prova = c.prova_data
      ? `<span class="prova-chip">📝 prova: <b>${fmtData(c.prova_data)}</b></span>`
      : `<span class="prova-chip" title="${esc(c.prova_texto || '')}">prova: a divulgar</span>`;

    const link = c.url_inscricao || c.url_fonte;
    const fonte = c.url_fonte && !c.url_fonte.startsWith("manual:")
      ? `<a href="${esc(c.url_fonte)}" target="_blank" rel="noopener">${esc(c.orgao)}</a>`
      : esc(c.orgao);

    const ufPill = c.uf === "BR"
      ? `<span class="uf-pill nacional">Nacional</span>`
      : (c.uf ? `<span class="uf-pill">${esc(c.uf)}</span>` : "");

    return `<article class="card ${urgente ? "urgente" : ""}">
      <div class="card-head"><h3 class="card-title">${fonte}</h3>${ufPill}</div>
      ${c.cargos ? `<div class="card-cargos">${esc(c.cargos)}</div>` : ""}
      <div class="card-meta">${meta.join("")}</div>
      ${deadlineTxt ? `<div class="deadline ${deadlineCls}">⏳ ${deadlineTxt}</div>` : ""}
      ${(tags || mais) ? `<div class="tags">${tags}${mais}</div>` : ""}
      <div class="card-foot">${prova}
        ${link ? `<a class="btn-insc" href="${esc(link)}" target="_blank" rel="noopener">Ver edital ↗</a>` : ""}
      </div>
    </article>`;
  }

  async function carregar() {
    const p = new URLSearchParams();
    if (els.q.value.trim()) p.set("q", els.q.value.trim());
    if (els.regiao.value) p.set("regiao", els.regiao.value);
    if (els.uf.value) p.set("uf", els.uf.value);
    if (els.inscricaoAte.value) p.set("inscricao_ate", els.inscricaoAte.value);
    if (els.provaDe.value) p.set("prova_de", els.provaDe.value);
    if (els.provaAte.value) p.set("prova_ate", els.provaAte.value);
    p.set("status", els.status.value);
    p.set("order", els.order.value);
    const mats = materiasSelecionadas();
    if (mats.length) p.set("materia", mats.join("|"));

    cards.style.opacity = ".5";
    try {
      const r = await fetch("/api/concursos?" + p.toString());
      if (r.status === 401) { location.href = "/login"; return; }
      const data = await r.json();
      cards.innerHTML = data.concursos.map(cardHTML).join("");
      empty.hidden = data.concursos.length > 0;
      $("st-count").textContent = data.count.toLocaleString("pt-BR");
      $("st-vagas").textContent = (data.stats.vagas || 0).toLocaleString("pt-BR");
      $("st-prova").textContent = (data.stats.com_prova || 0).toLocaleString("pt-BR");
      $("st-coleta").textContent = data.stats.ultima_coleta
        ? new Date(data.stats.ultima_coleta).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
        : "aguardando 1ª coleta";
    } finally {
      cards.style.opacity = "1";
    }
  }

  function debounced() { clearTimeout(t); t = setTimeout(carregar, 300); }

  els.q.addEventListener("input", debounced);
  ["regiao", "uf", "inscricaoAte", "provaDe", "provaAte", "order", "status"].forEach(k =>
    els[k].addEventListener("change", carregar));
  document.querySelectorAll(".f-materia").forEach(c => c.addEventListener("change", carregar));

  const buscaMateria = $("f-materia-busca");
  if (buscaMateria) buscaMateria.addEventListener("input", () => {
    const q = buscaMateria.value.toLowerCase();
    document.querySelectorAll("#materias-box .chk").forEach(l => {
      l.style.display = l.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });

  $("f-limpar").addEventListener("click", () => {
    els.q.value = ""; els.regiao.value = ""; els.uf.value = "";
    els.inscricaoAte.value = ""; els.provaDe.value = ""; els.provaAte.value = "";
    els.order.value = "inscricao_fim"; els.status.value = "aberto";
    document.querySelectorAll(".f-materia:checked").forEach(c => (c.checked = false));
    if (buscaMateria) { buscaMateria.value = ""; }
    document.querySelectorAll("#materias-box .chk").forEach(l => (l.style.display = ""));
    carregar();
  });

  carregar();
  setInterval(carregar, 5 * 60 * 1000); // atualiza a cada 5 min
})();
