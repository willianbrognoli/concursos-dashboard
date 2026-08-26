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

# nome do estado (normalizado, sem acento, minúsculo) -> UF
NOMES_UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso do sul": "MS", "mato grosso": "MT",
    "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
    "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO",
    "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}


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
    # Constitucional cai em praticamente toda carreira jurídica/legislativa/policial,
    # então além da menção direta inferimos pelo tipo de órgão/cargo.
    "Direito Constitucional": [r"direito constitucional", r"constituicao federal",
                               r"nocoes de direito", r"\btribunal\b", r"ministerio publico",
                               r"\bdefensoria\b", r"\bprocurador", r"\badvogad",
                               r"\bjuridic[oa]\b", r"\bdelegad[oa]\b", r"\bpolicia\b",
                               r"policial", r"guarda (municipal|civil)", r"\bbombeiro",
                               r"legislativ[oa]", r"assembleia legislativa",
                               r"\bjuiz\b", r"\bpromotor", r"analista judiciari",
                               r"tecnico judiciari", r"oficial de justica"],
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
    "Medicina": [r"(?<!exame )(?<!junta )(?<!pericia )(?<!avaliacao )(?<!inspecao )\bmedic[oa]s?\b(?! veterinari)", r"\bmedicina\b(?! veterinaria)"],
    "Odontologia": [r"\bodontolog", r"\bdentista\b", r"cirurgiao[- ]dentista"],
    "Psicologia": [r"\bpsicolog[oa]s?\b", r"\bpsicologia\b"],
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
    "Física": [r"(professor|licenciad[oa]|licenciatura|bacharel|graduacao) (de|em) fisica", r"(?<!teste )(?<!condicionamento )(?<!preparo )(?<!esforco )\bfisicos?\b(?!terap)"],
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


# ------------------------------------------------------- status do edital
# ordem do pipeline (do mais cedo ao mais tarde)
STATUS_EDITAL = [
    "Em Estudo", "Previsto", "Autorizado", "Comissão Formada", "Banca Definida",
    "Edital Aberto", "Inscrições Abertas", "Inscrições Encerradas",
    "Prova Realizada", "Homologado",
]

STATUS_EDITAL_PATTERNS = {
    "Em Estudo": [r"\bem estudos?\b", r"estudos (?:iniciais|para o concurso)",
                  r"intencao de realizar", r"planeja (?:realizar|abrir) concurso"],
    "Previsto": [r"edital[^.]{0,30}(?:previsto|iminente|aguardado|a caminho|deve (?:sair|ser publicado))",
                 r"concurso[^.]{0,30}(?:previsto|iminente|confirmado para)",
                 r"expectativa d[eo] (?:edital|concurso)", r"aguarda (?:o )?(?:novo )?edital",
                 r"novo concurso[^.]{0,20}previsto", r"edital pode (?:sair|ser publicado)"],
    "Autorizado": [r"\bautorizad[oa]\b", r"autorizacao d[oe] concurso",
                   r"concurso[^.]{0,30}autorizad"],
    "Comissão Formada": [r"comissao[^.]{0,40}(?:formada|instituida|constituida|definida|criada|nomeada)",
                         r"(?:formacao|criacao|instituicao) da comissao",
                         r"grupo de trabalho[^.]{0,30}(?:formado|instituido|criado)"],
    "Banca Definida": [r"banca[^.]{0,40}(?:definida|contratada|escolhida|selecionada|confirmada)",
                       r"sera a banca", r"e a banca (?:organizadora|do concurso)",
                       r"contratacao da banca[^.]{0,30}(?:concluida|finalizada|assinada)"],
    "Edital Aberto": [r"edital[^.]{0,30}(?:publicado|divulgado|lancado|liberado|no ar)",
                      r"saiu o edital", r"edital saiu", r"publicacao do edital",
                      r"edital esta disponivel"],
    "Inscrições Abertas": [r"inscricoes (?:estao )?abertas", r"inscricoes comecam",
                           r"periodo de inscricao aberto"],
    "Inscrições Encerradas": [r"inscricoes (?:estao )?encerradas", r"fim das inscricoes",
                              r"inscricoes terminaram"],
    "Prova Realizada": [r"provas? (?:foi|foram) (?:aplicada|realizada)s?",
                        r"apos a aplicacao das provas", r"gabarito (?:preliminar|oficial)"],
    "Homologado": [r"\bhomologad[oa]\b", r"homologacao do (?:resultado|concurso)"],
}

_STATUS_COMPILED = {s: [re.compile(p) for p in pats] for s, pats in STATUS_EDITAL_PATTERNS.items()}


def detectar_status_edital(*textos):
    """Retorna o status mais avançado do pipeline citado no texto, ou None."""
    texto = _norm(" \n ".join(t for t in textos if t))
    achado = None
    for status in STATUS_EDITAL:  # ordem do pipeline; o último achado vence
        if any(p.search(texto) for p in _STATUS_COMPILED[status]):
            achado = status
    return achado


# ---------------------------------------------------------------- fases
# fase do certame -> padrões (regex sobre texto normalizado sem acento),
# incluindo os sinônimos usuais dos editais/notícias
ETAPAS_PATTERNS = {
    "Prova objetiva": [
        r"provas? objetivas?", r"prova de multipla escolha", r"questoes objetivas",
        r"prova preambular", r"avaliacao objetiva",
    ],
    "Prova discursiva": [
        r"provas? discursivas?", r"prova dissertativa", r"prova de redacao",
        r"\bredacao\b", r"prova escrita discursiva", r"questoes discursivas",
        r"peca (processual|profissional|pratico-profissional)", r"prova subjetiva",
    ],
    "Exames biométricos / avaliação médica": [
        r"exames? toxicologic", r"avaliacao medica", r"exames? medic",
        r"junta medica", r"pericia medica", r"exame de saude", r"inspecao de saude",
        r"exames? laborator", r"exames? biometric", r"avaliacao biopsicossocial",
        r"exames? de sanidade",
    ],
    "Prova prática (digitação etc.)": [
        r"provas? praticas?", r"teste pratico", r"prova de digitacao",
        r"teste de digitacao", r"\bdigitacao\b", r"prova pratica de direcao",
        r"prova de conducao veicular",
    ],
    "Prova de capacidade física (TAF)": [
        r"\btaf\b", r"teste de aptidao fisica", r"prova de aptidao fisica",
        r"exame de aptidao fisica", r"capacidade fisica", r"teste fisico",
        r"prova fisica", r"avaliacao fisica", r"teste de condicionamento fisico",
        r"exame de capacitacao fisica",
    ],
    "Avaliação psicológica": [
        r"avaliacao psicologica", r"exame psicotecnico", r"\bpsicotecnico\b",
        r"teste psicologico", r"exame psicologico", r"avaliacao psiquica",
        r"exame de aptidao mental",
    ],
    "Sindicância de vida pregressa / investigação social": [
        r"investigacao social", r"vida pregressa", r"\bsindicancia\b",
        r"investigacao de conduta", r"pesquisa social", r"investigacao criminal e social",
    ],
    "Avaliação de títulos": [
        r"avaliacao de titulos", r"prova de titulos", r"analise de titulos",
        r"exame de titulos", r"julgamento de titulos", r"avaliacao curricular",
        r"analise curricular", r"prova de experiencia",
    ],
    "Exame admissional": [
        r"exames? admissiona", r"exames? pre[- ]admissiona",
    ],
    "Heteroidentificação": [
        r"heteroidentificacao", r"analise fenotipica", r"\bfenotipic",
        r"banca de verificacao", r"verificacao da autodeclaracao",
        r"afericao da autodeclaracao", r"confirmacao da autodeclaracao",
        r"procedimento de verificacao racial", r"comissao de verificacao",
    ],
}

ETAPAS = list(ETAPAS_PATTERNS.keys())
_ETAPAS_COMPILED = {e: [re.compile(p) for p in pats] for e, pats in ETAPAS_PATTERNS.items()}


def detectar_etapas(*textos) -> list:
    """Detecta as fases do certame citadas no texto da notícia/edital."""
    texto = _norm(" \n ".join(t for t in textos if t))
    return [e for e, pats in _ETAPAS_COMPILED.items() if any(p.search(texto) for p in pats)]


def regiao_da_uf(uf: str) -> str:
    info = UFS.get((uf or "").upper())
    return info[1] if info else None
