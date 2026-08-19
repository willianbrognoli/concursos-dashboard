"""Detecção de matérias e mapeamento de regiões/UFs."""
import re
import unicodedata

# UF -> (nome, região)
UFS = {
    "AC": ("Acre", "Norte"), "AL": ("Alagoas", "Nordeste"), "AP": ("Amapá", "Norte"),
    "AM": ("Amazonas", "Norte"), "BA": ("Bahia", "Nordeste"), "CE": ("Ceará", "Nordeste"),
    "DF": ("Distrito Federal", "Centro-Oeste"), "ES": ("Espírito Santo", "Sudeste"),
    "GO": ("Goiás", "Centro-Oeste"), "MA": ("Maranhão", "Nordeste"),
    "MT": ("Mato Grosso", "Centro-Oeste"), "MS": ("Mato Grosso do Sul", "Centro-Oeste"),
    "MG": ("Minas Gerais", "Sudeste"), "PA": ("Pará", "Norte"), "PB": ("Paraíba", "Nordeste"),
    "PR": ("Paraná", "Sul"), "PE": ("Pernambuco", "Nordeste"), "PI": ("Piauí", "Nordeste"),
    "RJ": ("Rio de Janeiro", "Sudeste"), "RN": ("Rio Grande do Norte", "Nordeste"),
    "RS": ("Rio Grande do Sul", "Sul"), "RO": ("Rondônia", "Norte"), "RR": ("Roraima", "Norte"),
    "SC": ("Santa Catarina", "Sul"), "SP": ("São Paulo", "Sudeste"),
    "SE": ("Sergipe", "Nordeste"), "TO": ("Tocantins", "Norte"),
    "BR": ("Nacional", "Nacional"),
}

REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul", "Nacional"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower())


# matéria -> lista de padrões (regex, aplicados sobre texto normalizado sem acento)
MATERIAS_PATTERNS = {
    "Língua Portuguesa": [r"lingua portuguesa", r"\bportugues\b", r"interpretacao de texto"],
    "Matemática": [r"\bmatematica\b"],
    "Raciocínio Lógico": [r"raciocinio logico"],
    "Informática": [r"\binformatica\b", r"nocoes de informatica"],
    "Conhecimentos Gerais": [r"conhecimentos gerais", r"\batualidades\b"],
    "Legislação": [r"\blegislacao\b", r"estatuto do servidor", r"regime juridico"],
    "Direito Constitucional": [r"direito constitucional", r"constituicao federal"],
    "Direito Administrativo": [r"direito administrativo", r"lei de licitacoes", r"improbidade administrativa"],
    "Direito Penal": [r"direito penal"],
    "Direito Processual Penal": [r"process(o|ual) penal"],
    "Direito Civil": [r"direito civil"],
    "Direito Processual Civil": [r"process(o|ual) civil"],
    "Direito do Trabalho": [r"direito do trabalho", r"direito trabalhista"],
    "Direito Tributário": [r"direito tributario"],
    "Direito Previdenciário": [r"direito previdenciario", r"\bprevidenciari[oa]\b", r"seguro social", r"\binss\b", r"\bprevidencia\b", r"regime proprio de previdencia", r"\brpps\b"],
    "Direito Eleitoral": [r"direito eleitoral"],
    "Direito Ambiental": [r"direito ambiental"],
    "Contabilidade": [r"\bcontabilidade\b", r"\bcontador(a)?\b", r"ciencias contabeis"],
    "Administração Pública": [r"administracao publica", r"gestao publica"],
    "Administração Financeira e Orçamentária": [r"orcament(o|aria)", r"\bafo\b", r"financas publicas"],
    "Auditoria": [r"\bauditoria\b", r"\bauditor\b"],
    "Economia": [r"\beconomia\b", r"\beconomista\b"],
    "Estatística": [r"\bestatistica\b"],
    "Inglês": [r"lingua inglesa", r"\bingles\b"],
    "Tecnologia da Informação": [r"tecnologia da informacao", r"analista de sistemas", r"desenvolvimento de sistemas", r"\bti\b(?![a-z])", r"engenheir[oa] de software"],
    "Saúde Pública / SUS": [r"\bsus\b", r"saude publica", r"saude coletiva", r"sistema unico de saude"],
    "Enfermagem": [r"\benfermeir[oa]\b", r"\benfermagem\b"],
    "Medicina": [r"\bmedic[oa]\b(?! veterinari)", r"\bmedicina\b"],
    "Odontologia": [r"\bodontolog", r"\bdentista\b", r"cirurgiao[- ]dentista"],
    "Psicologia": [r"\bpsicolog"],
    "Farmácia": [r"\bfarmac"],
    "Fisioterapia": [r"\bfisioterap"],
    "Nutrição": [r"\bnutricao\b", r"\bnutricionista\b"],
    "Medicina Veterinária": [r"veterinari[oa]"],
    "Serviço Social": [r"servico social", r"assistente social"],
    "Pedagogia / Educação": [r"\bpedagog", r"\bprofessor", r"\bdocente\b", r"magisterio", r"educacao basica", r"conhecimentos pedagogicos", r"ldb\b"],
    "Educação Física": [r"educacao fisica"],
    "Engenharia Civil": [r"engenharia civil", r"engenheir[oa] civil"],
    "Engenharia (outras)": [r"engenheir[oa] (eletricista|agronomo|ambiental|mecanic|florestal|de seguranca|quimic|cartograf)", r"engenharia (eletrica|mecanica|ambiental|agronomica|quimica|de producao)"],
    "Arquitetura": [r"\barquitet"],
    "Agronomia": [r"\bagronom"],
    "Segurança Pública": [r"\bpolicia\b", r"policial", r"\bsoldado\b", r"guarda (municipal|civil)", r"agente de transito", r"\bbombeiro", r"agente penitenciario", r"policia penal", r"investigador", r"\bdelegad[oa]\b", r"perito criminal"],
    "Biblioteconomia": [r"bibliotecari[oa]", r"biblioteconomia"],
    "Arquivologia": [r"arquivolog", r"\barquivista\b"],
    "Jornalismo / Comunicação": [r"\bjornalis", r"comunicacao social", r"\bpublicitari[oa]\b", r"relacoes publicas"],
    "Fonoaudiologia": [r"\bfonoaudiolog"],
    "Biologia / Biomedicina": [r"\bbiolog[oi]", r"\bbiomedic"],
    "Química": [r"\bquimic[oa]\b(?! industrial)"],
    "Física": [r"\bfisic[oa]\b(?!terap)"],
    "Geografia": [r"\bgeograf"],
    "História": [r"\bhistoria\b(?! do)", r"\bhistoriador"],
    "Sociologia / Filosofia": [r"\bsociolog", r"\bfilosof"],
    "Direito (geral)": [r"\badvogad[oa]\b", r"\bprocurador", r"\bjuridic[oa]\b", r"bacharel em direito", r"analista juridico", r"\bdefensor", r"\bjuiz\b", r"\bpromotor"],
    "Gestão / Administração": [r"\badministrador(a)?\b", r"assistente administrativo", r"tecnico administrativo", r"analista administrativo", r"\brecursos humanos\b", r"\bgestao\b"],
}

_COMPILED = {m: [re.compile(p) for p in pats] for m, pats in MATERIAS_PATTERNS.items()}


def detectar_materias(*textos) -> list:
    """Detecta matérias/áreas prováveis a partir de cargo, resumo e texto do edital."""
    texto = _norm(" \n ".join(t for t in textos if t))
    found = []
    for materia, pats in _COMPILED.items():
        if any(p.search(texto) for p in pats):
            found.append(materia)
    return sorted(found)


def regiao_da_uf(uf: str) -> str:
    info = UFS.get((uf or "").upper())
    return info[1] if info else None
