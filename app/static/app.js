/* Dashboard de Oportunidades — filtros e renderização */
(function () {
  const $ = (id) => document.getElementById(id);
  const cards = $("cards"), empty = $("empty");
  const pagerTop = $("pager-top"), pagerBottom = $("pager-bottom");
  const PAGE_SIZE = 24;
  let t = null;
  let lista = [];       // resultado completo do filtro atual
  let pagina = 1;

  const els = {
    q: $("f-q"), regiao: $("f-regiao"), uf: $("f-uf"),
    inscricaoAte: $("f-inscricao-ate"), provaDe: $("f-prova-de"), provaAte: $("f-prova-ate"),
    order: $("f-order"), fase: $("f-fase"),
  };

  function materiasSelecionadas() {
    return Array.from(document.querySelectorAll(".f-materia:checked")).map(c => c.value);
  }

  function etapasSelecionadas() {
    return Array.from(document.querySelectorAll(".f-etapa:checked")).map(c => c.value);
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

    // fase derivada das datas
    const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
    const provaPassou = c.prova_data && new Date(c.prova_data + "T00:00:00") < hoje;
    const inscricaoPassou = dias !== null && dias < 0;
    let faseBadge = "";
    if (provaPassou) faseBadge = `<span class="fase-badge realizada">Prova realizada</span>`;
    else if (inscricaoPassou) faseBadge = `<span class="fase-badge aguardando">Aguardando prova</span>`;

    const tags = (c.materias || []).slice(0, 6).map(m => `<span class="tag">${esc(m)}</span>`).join("");
    const mais = (c.materias || []).length > 6 ? `<span class="tag mais">+${c.materias.length - 6}</span>` : "";
    const etapaTags = (c.etapas || []).map(e => `<span class="tag etapa">${esc(e)}</span>`).join("");

    const meta = [];
    if (c.vagas) meta.push(`<span><b>${c.vagas.toLocaleString("pt-BR")}</b> vaga${c.vagas > 1 ? "s" : ""}</span>`);
    if (c.salario) meta.push(`<span>até <b>${esc(c.salario)}</b></span>`);
    if (c.escolaridade) meta.push(`<span>${esc(c.escolaridade)}</span>`);
    if (c.banca) meta.push(`<span>banca: <b>${esc(c.banca)}</b></span>`);
    if (c.taxa) meta.push(`<span>taxa: ${esc(c.taxa)}</span>`);

    const prova = c.prova_data
      ? `<span class="prova-chip">📝 prova${provaPassou ? " realizada em" : ":"} <b>${fmtData(c.prova_data)}</b></span>`
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
      ${(deadlineTxt || faseBadge) ? `<div class="deadline ${deadlineCls}">${faseBadge}${deadlineTxt && !inscricaoPassou ? "⏳ " + deadlineTxt : ""}</div>` : ""}
      ${etapaTags ? `<div class="tags">${etapaTags}</div>` : ""}
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
    p.set("fase", els.fase.value);
    p.set("order", els.order.value);
    const mats = materiasSelecionadas();
    if (mats.length) p.set("materia", mats.join("|"));
    const etps = etapasSelecionadas();
    if (etps.length) p.set("etapa", etps.join("|"));

    cards.style.opacity = ".5";
    try {
      const r = await fetch("/api/concursos?" + p.toString());
      if (r.status === 401) { location.href = "/login"; return; }
      const data = await r.json();
      lista = data.concursos;
      pagina = 1;
      renderPagina();
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

  function renderPagina() {
    const totalPag = Math.max(1, Math.ceil(lista.length / PAGE_SIZE));
    if (pagina > totalPag) pagina = totalPag;
    const ini = (pagina - 1) * PAGE_SIZE;
    cards.innerHTML = lista.slice(ini, ini + PAGE_SIZE).map(cardHTML).join("");
    empty.hidden = lista.length > 0;
    renderPager(pagerTop, totalPag);
    renderPager(pagerBottom, totalPag);
  }

  function renderPager(el, totalPag) {
    if (lista.length <= PAGE_SIZE) { el.innerHTML = ""; return; }
    const ini = (pagina - 1) * PAGE_SIZE + 1;
    const fim = Math.min(pagina * PAGE_SIZE, lista.length);
    let html = `<span class="pager-info">${ini}–${fim} de ${lista.length}</span>`;
    html += `<button data-pg="${pagina - 1}" ${pagina === 1 ? "disabled" : ""} aria-label="Página anterior">‹</button>`;
    // janela de páginas: 1 ... p-1 p p+1 ... última
    const pgs = new Set([1, 2, pagina - 1, pagina, pagina + 1, totalPag - 1, totalPag]);
    let ultima = 0;
    for (const p of [...pgs].filter(p => p >= 1 && p <= totalPag).sort((a, b) => a - b)) {
      if (p - ultima > 1) html += `<span class="pager-info">…</span>`;
      html += `<button data-pg="${p}" class="${p === pagina ? "ativa" : ""}">${p}</button>`;
      ultima = p;
    }
    html += `<button data-pg="${pagina + 1}" ${pagina === totalPag ? "disabled" : ""} aria-label="Próxima página">›</button>`;
    el.innerHTML = html;
    el.querySelectorAll("button[data-pg]").forEach(b => b.addEventListener("click", () => {
      const pg = parseInt(b.dataset.pg, 10);
      if (pg >= 1 && pg !== pagina) {
        pagina = pg;
        renderPagina();
        pagerTop.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }));
  }

  function debounced() { clearTimeout(t); t = setTimeout(carregar, 300); }

  els.q.addEventListener("input", debounced);
  ["regiao", "uf", "inscricaoAte", "provaDe", "provaAte", "order", "fase"].forEach(k =>
    els[k].addEventListener("change", carregar));
  document.querySelectorAll(".f-materia").forEach(c => c.addEventListener("change", carregar));
  document.querySelectorAll(".f-etapa").forEach(c => c.addEventListener("change", carregar));

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
    els.order.value = "inscricao_fim"; els.fase.value = "abertas";
    document.querySelectorAll(".f-materia:checked").forEach(c => (c.checked = false));
    document.querySelectorAll(".f-etapa:checked").forEach(c => (c.checked = false));
    if (buscaMateria) { buscaMateria.value = ""; }
    document.querySelectorAll("#materias-box .chk").forEach(l => (l.style.display = ""));
    carregar();
  });

  carregar();
  setInterval(carregar, 5 * 60 * 1000); // atualiza a cada 5 min
})();
