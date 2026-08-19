"""Popula o banco com concursos de demonstração (apenas para teste local)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dbm
from app.materias import detectar_materias, regiao_da_uf

DEMO = [
    dict(url_fonte="demo:agepar", orgao="AGEPAR - Agência Reguladora do Paraná", uf="PR",
         vagas=23, salario="R$ 9.500,00", salario_num=9500.0,
         cargos="Especialista em Regulação", escolaridade="Superior",
         inscricao_inicio="2026-07-23", inscricao_fim="2026-08-21",
         prova_data="2026-10-18", banca="Cebraspe", taxa="R$ 130,00",
         url_inscricao="https://www.cebraspe.org.br/concursos/agepar_pr_26",
         resumo="Concurso com provas objetivas e discursivas previstas para outubro em Curitiba."),
    dict(url_fonte="demo:inss", orgao="INSS - Instituto Nacional do Seguro Social", uf="BR",
         vagas=8500, salario="R$ 12.000,00", salario_num=12000.0,
         cargos="Técnico do Seguro Social, Analista do Seguro Social", escolaridade="Médio / Superior",
         inscricao_fim="2026-10-15", prova_data="2026-12-06", banca="Cebraspe",
         resumo="Concurso nacional do seguro social."),
    dict(url_fonte="demo:tjsp", orgao="TJ-SP - Tribunal de Justiça de São Paulo", uf="SP",
         vagas=320, salario="R$ 8.100,00", salario_num=8100.0,
         cargos="Escrevente Técnico Judiciário", escolaridade="Médio",
         inscricao_fim="2026-09-01", prova_data="2026-11-08", banca="Vunesp",
         resumo="Provas com Direito Penal, Processo Penal, Constitucional e Administrativo."),
    dict(url_fonte="demo:sefaz-ba", orgao="SEFAZ-BA - Secretaria da Fazenda da Bahia", uf="BA",
         vagas=80, salario="R$ 19.000,00", salario_num=19000.0,
         cargos="Auditor Fiscal", escolaridade="Superior",
         inscricao_fim="2026-08-25", prova_data="2026-10-25", banca="FGV",
         resumo="Auditoria, contabilidade e direito tributário."),
    dict(url_fonte="demo:pm-am", orgao="PM-AM - Polícia Militar do Amazonas", uf="AM",
         vagas=1200, salario="R$ 6.500,00", salario_num=6500.0,
         cargos="Soldado", escolaridade="Médio",
         inscricao_fim="2026-08-20", banca="IBFC",
         resumo="Concurso para soldado da polícia militar."),
]

def main():
    dbm.init_db()
    with dbm.get_db() as db:
        for c in DEMO:
            c["regiao"] = regiao_da_uf(c["uf"])
            c["materias"] = detectar_materias(c.get("cargos"), c.get("orgao"), c.get("resumo"))
            c["detalhado"] = 1
            dbm.upsert_concurso(db, c)
        dbm.upsert_noticia(db, url="https://blog.grancursosonline.com.br/demo-edital",
                           titulo="Concurso INSS: edital publicado com 8.500 vagas!",
                           fonte="Gran Cursos", publicado_em="2026-08-18T10:00:00")
        dbm.upsert_noticia(db, url="https://www.estrategiaconcursos.com.br/blog/demo",
                           titulo="TJ-SP: inscrições abertas para Escrevente; prova em novembro",
                           fonte="Estratégia", publicado_em="2026-08-19T08:30:00")
    print("seed ok")

if __name__ == "__main__":
    main()
