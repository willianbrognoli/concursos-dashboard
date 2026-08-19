"""Testes offline do parser (fixtures que imitam o markup do PCI)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", "/tmp/test-parser.db")

from app.scraper import parse_listing, parse_detail, parse_date_extenso
from app.materias import detectar_materias, regiao_da_uf

LISTING_HTML = """
<html><body><div id="concursos">
<div class="ca">
  <div class="cc"><a href="/noticias/agepar-pr-abre-concurso-publico">AGEPAR - Agência Reguladora do Paraná</a></div>
  <div class="cc">PR</div>
  <div class="cc">23 vagas até R$ 9.500,00</div>
  <div class="cc">Especialista em Regulação</div>
  <div class="cc">Superior</div>
  <div class="ce">21/08/2026</div>
</div>
<div class="ca">
  <div class="cc"><a href="/noticias/camara-de-floresta-pr-abre-concurso">Câmara de Floresta</a></div>
  <div class="cc">PR</div>
  <div class="cc">2 vagas até R$ 3.700,00</div>
  <div class="cc">Analista Legislativo, Técnico Legislativo</div>
  <div class="cc">Médio / Superior</div>
  <div class="ce">20/08 a 09/09/2026</div>
</div>
<div class="ca">
  <div class="cc"><a href="/noticias/inss-abre-concurso-nacional">INSS - Instituto Nacional do Seguro Social</a></div>
  <div class="cc">8.500 vagas até R$ 12.000,00</div>
  <div class="cc">Técnico do Seguro Social, Analista do Seguro Social</div>
  <div class="cc">Médio / Superior</div>
  <div class="ce">15/10/2026</div>
</div>
</div></body></html>
"""

DETAIL_HTML = """
<html><body><article>
<h1>AGEPAR abre concurso público</h1>
<p>A Agência Reguladora de Serviços Públicos Delegados do Paraná (Agepar) abre concurso público
com 23 vagas para Especialista em Regulação. As inscrições podem ser feitas das 10h do dia
23 de julho de 2026 às 18h do dia 21 de agosto de 2026, no site do Cebraspe.</p>
<p>A taxa de inscrição é de R$ 130,00. As seleções serão compostas por provas objetivas e
discursivas, previstas para o dia 18 de outubro de 2026, em Curitiba/PR.</p>
<p>As provas abrangerão as disciplinas de Língua Portuguesa, Raciocínio Lógico, Direito
Constitucional e Direito Administrativo.</p>
<p><a href="https://www.cebraspe.org.br/concursos/agepar_pr_26">Inscreva-se aqui</a></p>
</article></body></html>
"""


def main():
    ok = True

    items = parse_listing(LISTING_HTML, "Sul")
    assert len(items) == 3, f"esperava 3 itens, veio {len(items)}"

    a = items[0]
    assert a["orgao"].startswith("AGEPAR"), a
    assert a["uf"] == "PR", a
    assert a["vagas"] == 23, a
    assert a["salario_num"] == 9500.0, a
    assert a["inscricao_fim"] == "2026-08-21", a
    assert a["escolaridade"] == "Superior", a
    assert a["cargos"] == "Especialista em Regulação", a
    assert a["regiao"] == "Sul", a

    b = items[1]
    assert b["inscricao_inicio"] == "2026-08-20" and b["inscricao_fim"] == "2026-09-09", b

    c = items[2]
    assert c["vagas"] == 8500, c
    assert c["inscricao_fim"] == "2026-10-15", c

    det = parse_detail(DETAIL_HTML)
    assert det.get("prova_data") == "2026-10-18", det
    assert det.get("inscricao_fim") == "2026-08-21", det
    assert det.get("banca") == "Cebraspe", det
    assert det.get("taxa") == "R$ 130,00", det
    assert det.get("url_inscricao", "").startswith("https://www.cebraspe.org.br"), det

    mats = detectar_materias(det["_texto"], "Especialista em Regulação")
    for esperada in ["Língua Portuguesa", "Raciocínio Lógico", "Direito Constitucional", "Direito Administrativo"]:
        assert esperada in mats, f"{esperada} não detectada em {mats}"

    mats2 = detectar_materias("Técnico do Seguro Social", "INSS - Instituto Nacional do Seguro Social")
    assert "Direito Previdenciário" in mats2, mats2

    assert parse_date_extenso("previstas para o dia 18 de outubro de 2026") == "2026-10-18"
    assert regiao_da_uf("PR") == "Sul" and regiao_da_uf("BA") == "Nordeste"

    print("PARSER OK —", len(items), "itens;", "matérias:", mats)


if __name__ == "__main__":
    main()
