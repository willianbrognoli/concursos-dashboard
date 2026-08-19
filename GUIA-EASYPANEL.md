# Guia de implantação — Dashboard de Oportunidades (Easypanel)

Serviço web que coleta diariamente os concursos abertos do **PCI Concursos**
(todas as regiões do Brasil) + notícias de editais dos feeds **Gran Cursos** e
**Estratégia**, com login/registro de usuários, registro de acessos e filtros
por matéria, data e região/UF.

## 1. Subir o código para um repositório Git

O Easypanel builda direto de um repositório com Dockerfile.

```bash
cd concursos-dashboard
git init && git add . && git commit -m "Dashboard de Oportunidades"
# crie um repo (pode ser privado) no GitHub e envie:
git remote add origin git@github.com:SEU_USUARIO/concursos-dashboard.git
git push -u origin main
```

(Alternativa sem GitHub: no servidor, `docker compose up -d --build` usando o
`docker-compose.yml` incluído — mas o fluxo Easypanel abaixo é o recomendado.)

## 2. Criar o app no Easypanel

1. No Easypanel, dentro do seu projeto → **+ Service → App**.
2. Nome: `concursos-dashboard`.
3. **Source**: GitHub → selecione o repositório → branch `main`.
4. **Build**: método **Dockerfile** (ele detecta o `Dockerfile` da raiz).

## 3. Variáveis de ambiente (aba Environment)

```
SECRET_KEY=<cole uma chave longa e aleatória>
ADMIN_EMAIL=emanuel@fauthefreitas.adv.br
OPEN_REGISTRATION=true
SCRAPE_HOUR=6
SCRAPE_ON_START=true
TZ=America/Sao_Paulo
```

Gerar uma SECRET_KEY forte:

```bash
openssl rand -hex 32
```

| Variável | O que faz |
|---|---|
| `SECRET_KEY` | assina os cookies de sessão — **obrigatória e secreta** |
| `ADMIN_EMAIL` | quem se registrar com este e-mail vira admin (o 1º usuário registrado também vira admin automaticamente) |
| `OPEN_REGISTRATION` | `true` = qualquer pessoa pode criar conta; `false` = só quem já tem conta entra |
| `SCRAPE_HOUR` | hora (0–23, horário de Brasília) da coleta diária — roda às HH:15 |
| `SCRAPE_ON_START` | coleta ao subir o container se a base estiver vazia/defasada |

## 4. Volume persistente (aba Mounts)

Sem isso, usuários e concursos são perdidos a cada deploy.

- **Type**: Volume
- **Name**: `concursos-data`
- **Mount Path**: `/data`

## 5. Domínio (aba Domains)

- Adicione o domínio/subdomínio desejado (ex.: `concursos.fauthefreitas.adv.br`
  — crie antes um CNAME/A apontando para a VPS).
- **Port**: `8000` · HTTPS: ativado (Let's Encrypt automático).

## 6. Deploy e primeiro acesso

1. Clique em **Deploy** e acompanhe o log de build.
2. Acesse o domínio → **Criar cadastro** com o seu e-mail
   (`ADMIN_EMAIL` ⇒ você entra já como admin).
3. A primeira coleta dispara sozinha ao subir (leva ~3–5 min: listagens das 6
   regiões + páginas de detalhe de até 80 concursos por vez, com pausa de 1 s
   entre requisições para não sobrecarregar o PCI).
4. No painel **Admin** você acompanha: usuários, registro de acessos (logins,
   falhas, IP), histórico de coletas e pode disparar **Coletar agora**.

## 7. Operação

- **Coleta diária**: automática às `SCRAPE_HOUR`h15 (America/Sao_Paulo).
  Concursos cujo prazo de inscrição passou são marcados como *encerrados*.
- **Matérias**: detectadas por palavras-chave no cargo + texto da notícia do
  concurso (ex.: "Direito Constitucional", "Contabilidade"). Como muitos
  editais não listam disciplinas no resumo, a detecção é uma aproximação —
  dá para complementar qualquer concurso manualmente no Admin.
- **Concurso manual**: Admin → *Adicionar concurso manualmente* (útil para
  editais que o PCI ainda não listou ou para destacar algo para os alunos).
- **Notícias**: painel "Últimas notícias de editais" no topo do dashboard,
  alimentado pelos RSS do Gran Cursos e do Estratégia a cada coleta.
- **Backup**: o banco é um único arquivo SQLite em `/data/concursos.db`
  (volume `concursos-data`). Basta copiá-lo para ter backup completo.

## 8. Se o scraper parar de achar concursos

O parser do PCI é tolerante a mudanças de layout, mas se o site mudar muito:
Admin → *Coletas do scraper* mostra erros por região. Os logs do container
(`Easypanel → Logs`) trazem o detalhe. O RSS e o cadastro manual continuam
funcionando de forma independente.
