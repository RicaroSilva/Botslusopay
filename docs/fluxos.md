# Fluxos nativos (substituto do taskt/OpenBots)

Os fluxos nativos são executados pelo próprio Bot Manager, no contentor **runner**, sem taskt, sem OpenBots e sem
desktop Windows. São criados e editados na aplicação: **Catálogo → + Novo fluxo** (administradores) ou
**Detalhe do bot → Editar fluxo** (quem tem a permissão *configure* no bot).

Tudo o que já existia continua a aplicar-se: botão Executar, aprovações (obrigatórias em risco elevado),
agendamentos e outras regras, dependências, histórico, logs e auditoria.

## Porque é mais rápido

- Os pedidos HTTP são feitos diretamente, com ligações reutilizadas, sem pausas entre comandos.
- Os ciclos podem correr **em paralelo** (`parallel` até 20 no passo "Para cada elemento"). Um bot como o "Saldos de
  clientes", que hoje faz cerca de 6000 GET em sequência (~3,5 h), passa a fazer 10–20 em simultâneo. Ajustar o
  paralelismo à capacidade da API Cyclos.
- Vários fluxos correm ao mesmo tempo: `docker compose up -d --scale runner=3`.
- Libertam o servidor de bots Windows.

## Passos disponíveis

| Passo | Para quê |
|---|---|
| Pedido à API (HTTP) | GET/POST/PUT/PATCH/DELETE por **https**; autenticação pela credencial; resposta JSON ou texto guardada numa variável; `retries` só em GET/HEAD |
| Definir variável | texto com modelo (`value`) ou expressão (`expr`) |
| Extrair de JSON | caminho simples: `items[*].id`, `a.b[0].c` |
| Para cada elemento | repete passos para cada item de uma lista; opcionalmente em paralelo |
| Condição | ramos "se verdadeira" / "caso contrário" |
| Acrescentar a lista | junta valores numa lista (útil dentro de ciclos, também em paralelo) |
| Criar ficheiro CSV | separador `;`, UTF-8 com BOM (abre bem no Excel), proteção contra fórmulas maliciosas |
| Criar ficheiro de texto | texto/JSON |
| Enviar email | SMTP (STARTTLS/SSL), anexos produzidos pelo fluxo |
| Consulta SQL Server | consulta **parametrizada** (`%(nome)s`); por omissão só leitura (rollback no fim) |
| Registar no log / Terminar com sucesso / Falhar | controlo e mensagens |

Cada passo tem "Continuar se este passo falhar"; o erro fica em `last_error`.

## Modelos e expressões

- Em campos de texto use `{{ … }}`: `https://app.lusopay.com:8443/web/api/users/{{ cliente.id }}`.
- Campos marcados *(expressão)* não levam chavetas: `transacoes | length > 0`, `{'id': cliente.id, 'valor': 10}`.
- Variáveis: as que os passos guardam (`save_as`, `variable`), `params` (parâmetros da execução), `run_id`, `files`
  (ficheiros já criados), `item`/`loop_index` dentro de ciclos, `row` nas colunas CSV, `last_error`.
- Funções: `now()`, `today()`, `first_day_of_month(0)` (este mês), `first_day_of_month(-1)` (mês anterior).
- Filtros: `date('%Y-%m-%d')`, `add_days(-1)`, `money` (2 casas, vírgula), `tojson`, `fromjson`, `length`,
  `default('x')`, `round`, `sum(attribute='valor')`, `selectattr`, `map(attribute='id')`, entre outros filtros
  padrão do Jinja2.
- Uma variável inexistente faz o passo falhar (não fica vazia sem aviso).
- As expressões correm num *sandbox*: não há acesso a ficheiros, comandos nem internals do Python.

Exemplo — mês anterior: `{{ first_day_of_month(-1) | date('%Y-%m-%d') }}` até
`{{ first_day_of_month(0) | add_days(-1) | date('%Y-%m-%d') }}`.

## Credenciais (Administração → Credenciais)

Tipos: API Basic (utilizador/password), API Bearer (token), API com cabeçalho próprio, SMTP e SQL Server.

- Os segredos são cifrados com `BM_VAULT_KEY` e **nunca** são mostrados, devolvidos pela API ou escritos em logs.
- Os fluxos referem a credencial pelo nome. Não é possível pôr `Authorization` nos cabeçalhos nem usar credenciais em
  modelos.
- Ao executar, o runner recebe apenas as credenciais usadas por aquele fluxo.
- Não é possível apagar uma credencial em uso por um fluxo.
- Trocar uma password = alterar a credencial num único sítio; todos os fluxos passam a usá-la.

## Versões

Cada gravação cria uma versão nova e imutável. Uma execução fixa a versão **no momento do pedido**, por isso uma
execução aprovada corre exatamente o que foi aprovado. Para reverter, abre-se a versão antiga e grava-se.

## Ficheiros produzidos

Os ficheiros criados pelo fluxo (CSV, texto) ficam associados à execução e podem ser descarregados na página da
execução (limite por ficheiro: `BM_ARTIFACT_MAX_BYTES`, 20 MB por omissão). Os downloads ficam auditados.

## Segurança das chamadas

- Só `https://`; o host não pode vir de uma variável; redireções não são seguidas.
- `BM_FLOW_ALLOWED_HOSTS` limita os hosts que os fluxos podem chamar (recomendado em produção).
- POST/PUT/DELETE nunca são repetidos automaticamente. Se um fluxo falhar depois de alterar dados, a execução fica
  com o motivo da falha e o passo onde ocorreu, para verificação antes de repetir.

## Migrar um bot taskt para um fluxo

1. Ler o bot no inventário (`docs/inventario-detalhado.md`): endpoints, ficheiros, emails, SQL.
2. Criar as credenciais (em vez das passwords escritas no XML).
3. Recriar a lógica com passos; os ficheiros que o bot lia de pastas partilhadas passam a vir de APIs/SQL ou de
   variáveis.
4. Testar contra o ambiente dev (`dev.lusopay.com:8444/web_dev`).
5. **Correr em paralelo** com o bot antigo durante um período e comparar os resultados.
6. Ativar a regra de agendamento do fluxo, desativar a tarefa do Agendador do Windows e marcar o bot antigo como
   desativado.

Ordem sugerida (só leitura primeiro): Saldos de clientes → Análise de desempenho/fraudes → Análise PEP →
Recolhe transações aleatórias → BCFT MB Way (SQL + POST, risco elevado) → Atribuir Tarifa MB Way → reenvio de callbacks.
Os bots que usam o browser (Selenium) precisam primeiro de um equivalente por API.

## Bots já migrados (`bots/flows/`)

| Ficheiro | Substitui o bot taskt | Notas |
|---|---|---|
| `saldos-clientes-nativo.json` | OK Saldos de clientes no Cyclos no final do mês | 10 pedidos em paralelo (o original levava ~3,5 h) |
| `transacoes-aleatorias-nativo.json` | OK Recolhe transações de clientes aleatórios do mês anterior | sorteio local sem repetições (o original usava randomnumberapi.com por HTTP) |
| `desempenho-fraudes-nativo.json` | OK Análise de desempenho, operações e fraudes nas transações LUSOPAY | conta registos reais (o original podia contar a mais); manteve a pesquisa de texto por meio/canal |

Todos usam as credenciais **`cyclos-producao`** (API Basic) e **`smtp-lusopay`** (SMTP), e vêm com a variável
`destinatarios` = `ricardosilva@lusopay.com` para testes. Os destinatários originais estão nas notas de migração de
cada fluxo (visíveis em Pré-requisitos, no detalhe do bot). Para pôr em produção, edite o fluxo, mude a variável no
JSON ("Ver JSON") e grave uma nova versão.

A credencial `cyclos-producao` é a da conta API `RPATaskt` que os bots usam hoje: no `Config.txt` do servidor de bots
está como `RPATaskt,Basic <texto>,`. O `<texto>` é `utilizador:password` codificado em base64. Recomenda-se rodar
essa password, que estava exposta nos XML (ver `riscos.md`), e gravar a nova só no Bot Manager.

**Importar:** Catálogo → **Importar fluxo (JSON)** → escolher o ficheiro. Também pode ser feito pela linha de comandos:
`python -m botmanager.cli import-flows` (importa todos). Os fluxos entram **desativados**; é preciso criar as duas
credenciais antes de importar.

Testes: `worker/tests/test_migrated_flows.py` corre os três contra uma API Cyclos **simulada**. O formato real das
respostas do Cyclos tem de ser confirmado na primeira execução: correr em paralelo com o bot antigo e comparar os
ficheiros.
