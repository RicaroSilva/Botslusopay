# Arquitetura e decisões técnicas (Fase B — Desenho)

## 1. Visão geral

```
   Browser (React)                 Sistemas externos
        │ HTTPS (cookie de sessão)       │ webhooks HMAC / APIs consultadas
        ▼                                ▼
 ┌──────────────────────────────────────────────┐      ┌───────────────────────┐
 │ Backend web (FastAPI)                        │      │ Scheduler (processo)  │
 │ - autenticação / autorização                 │◄────►│ - cron, polling HTTP  │
 │ - catálogo (registo YAML → BD)               │  BD  │ - reaper (heartbeats) │
 │ - execuções, aprovações, regras, auditoria   │      └───────────────────────┘
 │ - API /api/worker (token por worker)         │
 └───────────────┬──────────────────────────────┘
                 │ PostgreSQL
                 ▼
          ┌──────────────┐
          │  PostgreSQL  │  fila = tabela runs (sem broker externo)
          └──────────────┘
                 ▲
                 │ HTTPS (pull: o worker pede trabalho; nada entra no servidor de bots)
 ┌───────────────┴──────────────────────────────┐
 │ Windows Worker (servidor de bots, sessão     │
 │ interativa da conta de serviço dos bots)     │
 │ - adaptador taskt_cli  → taskt.exe <xml>     │
 │ - adaptador openbots   → (por validar)       │
 │ - lê o log do motor taskt → resultado        │
 │ - timeout, cancelamento, kill da árvore      │
 └──────────────────────────────────────────────┘
```

| Componente | Tecnologia | Onde corre |
|---|---|---|
| Frontend | React 18 + TypeScript (Vite) | servido pelo backend (ficheiros estáticos) |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, Alembic | servidor de aplicações (Windows ou Linux) |
| Base de dados | PostgreSQL 14+ (SQLite só para desenvolvimento/testes) | servidor de BD |
| Scheduler | Python, processo separado (`python -m botmanager.scheduler`) | junto do backend |
| Worker | Python 3.11+, só depende de `httpx` | servidor de bots Windows |

## 2. Decisões principais

1. **Os bots não são reescritos.** O Bot Manager lança os scripts existentes através do runtime existente (taskt). Nenhum
   XML foi modificado.
2. **Os XML não ficam no Git.** Contêm credenciais em claro. Permanecem em `Documents\taskt\My Scripts` no servidor de
   bots, que é onde os `{Folder.ScriptPath}` os esperam. O registo identifica cada script pelo **nome relativo** e,
   opcionalmente, pelo **SHA-256**: um script alterado sem revisão é recusado.
3. **Registo controlado em YAML** (`bots/registry/*.yaml`, versionado e revisto). É a única forma de um bot se tornar
   executável. A interface nunca aceita caminhos, comandos nem XML. Um bot novo entra **desativado** e, enquanto
   `validated: false`, fica "Por validar" e não pode ser executado.
4. **O worker faz pull** (pede trabalho por HTTPS). O servidor de bots não expõe portas e o backend nunca executa nada
   localmente. Cada worker tem um token próprio (guardado com hash) e uma lista de adaptadores autorizados.
5. **Sem broker de mensagens.** A tabela `runs` é a fila (`SELECT … FOR UPDATE SKIP LOCKED` em PostgreSQL). Com um
   servidor de bots e execuções longas e pouco frequentes, um Redis/RabbitMQ só acrescentaria um componente a operar.
   Se o volume crescer, a interface do worker (claim/heartbeat/complete) mantém-se.
6. **O sucesso nunca é inferido do fim do processo.** Para o taskt é obrigatório `success_detection.method: taskt_log`
   (o esquema recusa `exit_code`). Pode haver validações adicionais (ficheiro de saída criado após o início).
7. **Não há repetições automáticas de bots com efeitos.** A repetição automática só é permitida quando o processo
   **nunca chegou a iniciar** e o bot está marcado `idempotent`. Uma execução com resultado incerto fica
   `needs_review` e só pode ser repetida após confirmação explícita de quem a repete (auditada).
8. **Autenticação local + ponto de extensão para SSO.** Não foi identificado o sistema de identidade corporativo. O MVP
   usa contas locais (argon2, bloqueio após falhas). A tabela `users` já tem `auth_source` para integrar OIDC
   (ex.: Microsoft Entra ID) — ver [riscos.md](riscos.md#questões-em-aberto).

## 3. Adaptadores de execução

Interface comum no worker (`lusopay_worker/adapters/base.py`): `prepare` (validações e comando, **sem shell**),
`progress_lines` (logs em tempo real) e `evaluate` (resultado).

| Adaptador | Comando | Resultado | Estado |
|---|---|---|---|
| `taskt_cli` | `taskt.exe "<scripts_dir>\<script>.xml"` | Log do motor taskt: emparelha `Script Path`/`Result Code` (lida com Run Task aninhado e ficheiros `_001`), recolhe `Error:` e `Error Occured at Line`, aplica `checks` | Confirmado no código-fonte do taskt; **por validar na versão instalada** |
| `openbots_studio` | — | — | **Recusa executar** até haver um mecanismo validado (não se inventaram opções de linha de comandos) |
| `simulated` | processo Python real com cenários | marcador no output | Só desenvolvimento e testes |

Proteções do adaptador taskt: o caminho é resolvido dentro de `WORKER_TASKT_SCRIPTS_DIR` (sem `..`, unidade nem
caminho absoluto), a extensão tem de ser `.xml`, o SHA-256 é verificado quando definido, os parâmetros são recusados e
o processo corre sem shell.

## 4. Máquina de estados

```
PENDING ──► QUEUED ──► RUNNING ──► SUCCEEDED
   │          │           ├──────► FAILED
   │          │           └──────► CANCELLED
   │          ├─► CANCELLED
   │          └─► FAILED   (worker recusou antes de iniciar)
   ├─► WAITING_APPROVAL ──► QUEUED (aprovada)
   │                    └─► CANCELLED (rejeitada/cancelada)
   ├─► CANCELLED
   └─► FAILED
```

- `PENDING`: criada após validação de permissões, parâmetros, dependências e concorrência; passa logo a `QUEUED` ou
  `WAITING_APPROVAL`.
- `RUNNING` só é atribuído quando um worker reclama o trabalho **e** obtém os recursos exclusivos.
- `SUCCEEDED` exige confirmação do runtime (ex.: `Result Code: Successful`) e das validações do bot.
- Os estados terminais são `SUCCEEDED`, `FAILED` e `CANCELLED`. As transições estão em `backend/botmanager/states.py`
  e são verificadas em todas as mudanças (testes em `tests/test_states.py`).
- `failure_reason` normalizado: `bot_reported_error`, `exit_code`, `timeout`, `result_undetermined`,
  `success_check_failed`, `worker_lost`, `worker_rejected`, `launch_error`, `dependency_unmet`.
- `needs_review = true` quando o processo arrancou e o resultado não foi confirmado (`timeout`,
  `result_undetermined`, `worker_lost`).

## 5. Concorrência e duplicados

| Mecanismo | Implementação |
|---|---|
| Uma execução ativa por bot (`policy: single`) | coluna `runs.exclusive_key` = id do bot enquanto ativa, com **restrição única** na BD; passa a NULL no estado terminal |
| Recursos exclusivos partilhados (`exclusive_resources`) | tabela `resource_locks` (chave primária = recurso). Todos os bots taskt partilham `taskt-desktop`: só um taskt de cada vez no servidor (desktop e log do motor partilhados) |
| Duplo clique / reenvio do browser | `idempotency_key` gerada por abertura do diálogo; restrição única em `runs.idempotency_key` |
| Eventos repetidos (webhook, agendamento, polling, após-bot) | `trigger_events` com restrição única `(rule_id, dedup_key)`; o `dedup_key` é o id do evento, o instante agendado, o valor consultado ou o id da execução a montante |
| Scheduler duplicado | lease única em `scheduler_leases` |
| Conclusão enviada duas vezes pelo worker | `complete` é idempotente (se a execução já é terminal, nada muda) |

## 6. Disparos automáticos (extensível)

Cada tipo é uma subclasse de `TriggerType` (`backend/botmanager/triggers/`) com um esquema de configuração próprio.
Adicionar um tipo = criar o módulo e importá-lo em `triggers/__init__.py`. Não é preciso alterar a API, os modelos
nem o frontend (o formulário aceita JSON validado no backend).

| Tipo | Configuração | Deduplicação |
|---|---|---|
| `schedule` | `cron`, `timezone` (Europe/Lisbon por omissão) | instante agendado; disparos perdidos além da margem são registados como `missed` e **não** executados |
| `webhook` | — (segredo HMAC gerado e mostrado uma vez) | cabeçalho `X-BM-Event-Id`; assinatura `X-BM-Signature` com janela anti-replay de 5 min |
| `after_bot` | `upstream_bot_key` | id da execução a montante (só em SUCCEEDED) |
| `poll_http` | `url` (só https e hosts em `BM_POLL_ALLOWED_HOSTS`), `json_path`, `equals`, `dedup_path`, `auth_header_env` | valor em `dedup_path` |
| aprovação manual | `requires_approval` na regra ou no bot (obrigatória em risco elevado) | — |

As regras são criadas **inativas**, só bots que o permitem no registo (`triggers_allowed`) as aceitam e todas as
alterações são auditadas. Um evento recusado (bot ocupado, dependência por satisfazer) fica registado como `rejected`
com o motivo e não é repetido automaticamente. Existe um interruptor global para pausar todos os disparos automáticos.

### Migração do orquestrador atual (recomendação)

A lógica de datas de `OK processos diarios…` pode ser expressa como regras explícitas e auditáveis, por exemplo
Análise de desempenho `0 7 14 * *` e PEP `0 7 1,8,15,22,29 * *`, mais uma dependência PEP → projeto BdP. O cron
padrão não exprime "último dia do mês" (Saldos): essa regra precisa de um novo tipo de disparo ou de ser decidida
com a contabilidade. **Não ativar** regras para bots que o Agendador de Tarefas do Windows continue a
disparar através do orquestrador: duplicaria execuções. A migração deve ser feita bot a bot, depois do piloto.

## 7. Modelo de dados

Migração inicial: `backend/alembic/versions/0001_esquema_inicial.py` (validada em PostgreSQL 16 e SQLite; o teste
`alembic check` garante que os modelos e a migração coincidem).

| Tabela | Conteúdo | Restrições/índices relevantes |
|---|---|---|
| `users` | identidade, função (viewer/operator/approver/admin), hash argon2, bloqueio, `token_version` | `username` único |
| `bots` | chave, nome, descrição, adaptador, referência ao projeto, definição YAML (JSON), hash da definição, disponibilidade, ativo | `key` único |
| `bot_permissions` | concessões individuais (view/execute/approve/configure) | único `(bot, user, permission)` |
| `runs` | execução: bot, estado, origem, utilizador, regra/evento, pai/repetição, parâmetros não sensíveis, tempos, heartbeat, worker, código de saída, motivo, `needs_review`, resumo do resultado | únicos `exclusive_key` e `idempotency_key`; CHECK de estados; índices por bot/data, estado/data, utilizador |
| `run_logs` | linhas de log redigidas | único `(run_id, seq)` |
| `resource_locks` | recursos exclusivos detidos | PK `resource` |
| `trigger_rules` | bot, tipo, configuração, estado, aprovação, próximo disparo | índice `(tipo, ativo)` |
| `trigger_events` | eventos recebidos e resultado (accepted/duplicate/rejected) | único `(rule_id, dedup_key)` |
| `bot_dependencies` | bot → bot a montante, condição (`succeeded_within` N h / `succeeded_today`) | único; CHECK sem auto-dependência; deteção de ciclos na API |
| `audit_events` | ator, ação, recurso, resultado, detalhes redigidos, IP | índices por data e por recurso |
| `workers` | nome, hash do token, capacidades, última presença | `name` único |
| `scheduler_leases`, `settings` | lease do scheduler; configurações operacionais não sensíveis | — |

## 8. Segurança

| Requisito | Implementação |
|---|---|
| Autenticação obrigatória | Todas as rotas `/api/*` exceto login, health, webhooks (HMAC) e worker (token) |
| Sessão | JWT HS256 em cookie `httpOnly`, `Secure`, `SameSite=Strict`; `token_version` invalida sessões no logout, em mudanças de função ou na desativação |
| CSRF | SameSite=Strict + cabeçalho obrigatório `X-Requested-With: botmanager` em pedidos que alteram estado |
| Força bruta | bloqueio temporário após 5 falhas; mesma resposta para utilizador inexistente |
| Autorização | sempre no backend: funções globais + permissões por bot (registo) + concessões individuais; os bots sem permissão de consulta devolvem 404 |
| Separação de funções | viewer / operator / approver / admin; **quatro olhos**: quem pede não pode aprovar (`BM_ALLOW_SELF_APPROVAL=false`) |
| Segredos | fora do código (variáveis de ambiente / ficheiro com ACL); tokens de worker com hash; segredos de webhook só mostrados uma vez; credenciais de polling lidas de variáveis `BM_POLL_*` |
| Redação | padrões para Basic/Bearer, `password=`, connection strings, linhas `RPATaskt,`/`smtpPass,` do Config.txt e URLs com credenciais; aplicada no worker **e** no backend (logs, auditoria, resumos) |
| Lista autorizada | só bots do registo; adaptadores conhecidos; caminho confinado; SHA-256 opcional; sem shell |
| Parâmetros | declarados e tipados; não declarados são recusados; sensíveis nunca são guardados; o taskt recusa parâmetros |
| Cabeçalhos HTTP | CSP restritiva, `X-Frame-Options: DENY`, `nosniff`, `no-store` na API; documentação OpenAPI desligada em produção |
| Conta Windows | conta dedicada sem privilégios de administrador (ver [instalacao-windows.md](instalacao-windows.md)) |
| Recuperação | estado local do worker (execução em curso, conclusão pendente); no arranque reenvia a conclusão, termina o processo órfão e o backend marca as execuções perdidas como `FAILED/worker_lost/needs_review`; o reaper faz o mesmo sem heartbeat |

## 9. Logs e resultados

- O worker envia em lotes (a cada heartbeat) as linhas do próprio worker, do stdout do processo e **do log do motor taskt**
  (`source=runtime`), já redigidas e numeradas (`seq`), de forma idempotente.
- `result_summary` guarda o resultado do runtime, os erros reportados, os sub-scripts executados, os avisos de erros
  tratados e as falhas das validações.
- Os ficheiros produzidos pelos bots (CSV, relatórios) **não** são copiados para o Bot Manager. Podem conter dados
  pessoais e financeiros e já são distribuídos por email. Ver [riscos.md](riscos.md).
