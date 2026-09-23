# API de sincronização — Dashboard de Oportunidades

API para um sistema externo receber **todos os concursos** e, depois, **só o que mudou**.
Nada se perde: criações, atualizações e exclusões são entregues em ordem.

- Base: `https://SEU-DOMINIO/api/v1`
- Autenticação: header `X-API-Key: <chave>` (ou `Authorization: Bearer <chave>`)
- Formato: JSON, datas em ISO 8601 (UTC nos campos `*_at` / `removido_em`)
- Os dados são coletados uma vez por dia (06:15, horário de Brasília) e quando o admin cadastra/apaga manualmente.

## Como sincronizar (resumo)

1. **Carga inicial:** chame `GET /concursos` sem cursor e continue com `next_cursor` enquanto `has_more` for `true`. Guarde o último `next_cursor`.
2. **Depois, periodicamente** (ex.: a cada hora, ou quando receber o webhook): chame `GET /concursos?cursor=<último next_cursor>` e repita enquanto `has_more`. Faça *upsert* pelo campo `id`.
3. **Exclusões:** chame `GET /concursos/removidos?desde=<último ate>` e apague do seu lado os `id` retornados.
4. **Notícias (opcional):** `GET /noticias?desde_id=<último ultimo_id>`.

Guarde três marcadores: `cursor_concursos`, `ate_removidos`, `ultimo_id_noticias`.

## Endpoints

### `GET /concursos`
Criações e atualizações, em ordem de `updated_at`, `id`.

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `cursor` | — | `next_cursor` da resposta anterior. Sem ele = desde o início. |
| `limit` | 200 | Máx. 1000 por página. |
| `texto` | false | `true` inclui `texto_base` (texto bruto do artigo, grande). |

Resposta:
```json
{
  "data": [ { "id": 12, "orgao": "Prefeitura de Cascavel", "uf": "PR", "...": "..." } ],
  "count": 200,
  "has_more": true,
  "next_cursor": "MjAyNi0wOS0yM1QxNzowMTowNCswMDowMHw1"
}
```
Um mesmo concurso pode voltar várias vezes (a cada atualização): sempre sobrescreva pelo `id`.

### `GET /concursos/removidos`
| Parâmetro | Descrição |
|---|---|
| `desde` | valor `ate` da resposta anterior (vazio = todos) |
| `limit` | padrão 500, máx. 1000 |

Resposta: `{ "data": [ { "id", "url_fonte", "orgao", "uf", "motivo", "removido_em" } ], "has_more", "ate" }`
`motivo`: `antigo` (limpeza automática após 90 dias), `duplicata` ou `manual`.

### `GET /concursos/{id}`
Um concurso. Retorna **410** com os dados da remoção se ele foi excluído, **404** se nunca existiu.

### `GET /noticias`
Notícias de editais (Gran Cursos, Estratégia, PCI). Parâmetros `desde_id` e `limit`. Resposta com `ultimo_id`.

### `GET /status`
Totais e data da última coleta.

## Campos do concurso

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | int | Identificador estável |
| `url_fonte` | texto | Origem (artigo) |
| `orgao`, `uf`, `regiao` | texto | `uf` = sigla ou `BR` (nacional) |
| `vagas` / `vagas_texto` | int / texto | |
| `salario` / `salario_num` | texto / número | |
| `cargos`, `escolaridade`, `banca`, `taxa` | texto | |
| `inscricao_inicio`, `inscricao_fim` | data ISO | |
| `inscricao_texto`, `prova_texto` | texto | Texto original das datas |
| `prova_data` | data ISO | |
| `materias`, `etapas` | lista de textos | Áreas detectadas e fases do certame |
| `edital_status` | texto | Status citado no texto |
| `status_efetivo` | texto | Status corrigido pelas datas (Inscrições Abertas, Prova Realizada...) |
| `status` | texto | `aberto` / `encerrado` |
| `resumo`, `url_inscricao` | texto | |
| `origem` | texto | `scraper` / `manual` |
| `created_at`, `updated_at` | data-hora ISO | |

## Webhook (opcional)

Se você passar uma URL, ela recebe um **aviso** (não os dados) sempre que houver novidade:

```http
POST https://sua-url
Content-Type: application/json
X-Signature: sha256=<HMAC-SHA256 do corpo com o segredo combinado>

{"evento": "coleta_concluida", "em": "2026-09-23T09:20:11+00:00", "resumo": {"created": 3, "updated": 12}}
```
Eventos: `coleta_concluida`, `concurso_manual`, `concurso_removido`.
Ao receber, responda `200` e rode a sincronização (passos 2 e 3). Até 3 tentativas em caso de erro; se o aviso se perder, a próxima sincronização periódica recupera tudo.

Validação da assinatura (Python):
```python
import hmac, hashlib
esperado = "sha256=" + hmac.new(SEGREDO.encode(), corpo_bruto, hashlib.sha256).hexdigest()
valido = hmac.compare_digest(esperado, request.headers["X-Signature"])
```

## Exemplos

```bash
# carga inicial
curl -H "X-API-Key: SUA_CHAVE" "https://SEU-DOMINIO/api/v1/concursos?limit=500"

# incremental
curl -H "X-API-Key: SUA_CHAVE" "https://SEU-DOMINIO/api/v1/concursos?cursor=MjAyNi0w..."

# exclusões
curl -H "X-API-Key: SUA_CHAVE" "https://SEU-DOMINIO/api/v1/concursos/removidos?desde=2026-09-23T09:20:11+00:00"
```
Em `curl`, codifique o `+` do `desde` como `%2B`.

Sincronização completa em Python:
```python
import requests
BASE, H = "https://SEU-DOMINIO/api/v1", {"X-API-Key": "SUA_CHAVE"}

def sincronizar(estado):  # estado = {"cursor": None, "ate": None}
    while True:
        r = requests.get(f"{BASE}/concursos", headers=H,
                         params={"limit": 500, **({"cursor": estado["cursor"]} if estado["cursor"] else {})}).json()
        for c in r["data"]:
            salvar_ou_atualizar(c)          # upsert pelo c["id"]
        estado["cursor"] = r["next_cursor"]
        if not r["has_more"]: break
    while True:
        r = requests.get(f"{BASE}/concursos/removidos", headers=H,
                         params={"desde": estado["ate"]} if estado["ate"] else {}).json()
        for rem in r["data"]:
            apagar(rem["id"])
        estado["ate"] = r["ate"]
        if not r["has_more"]: break
    return estado
```
