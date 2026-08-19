# Dashboard de Oportunidades

Dashboard de concursos públicos abertos em todo o Brasil, com:

- Coleta automática diária do **PCI Concursos** (6 regiões + nacional):
  órgão, UF, vagas, salário, cargos, escolaridade, prazo de inscrição,
  **data da prova**, banca, taxa e link do edital.
- Notícias de editais via RSS do **Gran Cursos** e **Estratégia**.
- **Login e registro** de usuários (senha bcrypt, sessão em cookie assinado)
  com **registro de acessos** (logins, falhas, IP, user-agent).
- Filtros por **matéria/área** (detecção automática por palavras-chave),
  **data** (prazo de inscrição e período da prova), **região e UF**, busca
  livre e ordenação (prazo, prova, vagas, salário).
- **Painel admin**: usuários (promover/bloquear), logs de acesso, histórico
  de coletas, coleta manual e cadastro manual de concursos.

## Stack

FastAPI · SQLite (arquivo único em `/data`) · Jinja2 · APScheduler ·
BeautifulSoup · Docker.

## Rodar localmente

```bash
pip install -r requirements.txt
DB_PATH=./dev.db SECRET_KEY=dev uvicorn app.main:app --reload
# demo sem esperar a coleta:
DB_PATH=./dev.db python tests/seed_demo.py
```

## Testes do parser

```bash
python tests/test_parser.py
```

## Implantação

Ver **GUIA-EASYPANEL.md**.
