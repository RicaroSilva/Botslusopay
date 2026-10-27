# Registar um novo bot (sem alterar o backend)

Um bot é registado com **um ficheiro YAML** em `bots/registry/`. O backend lê a pasta no arranque (ou em
Administração → Recarregar registo, ou `python -m botmanager.cli sync-registry`). O esquema é validado por
`backend/botmanager/registry/schema.py`: um ficheiro inválido é recusado e o erro aparece na auditoria e no comando
`validate-registry`.

## Passos

1. Copiar o XML para a pasta de scripts do servidor de bots (se ainda lá não estiver). **Não** o adicionar ao Git.
2. Analisar o script:
   ```bash
   python tools/inventory/analyze_taskt.py "<pasta com o xml>" -o /tmp/inv.json
   ```
   Ver: Run Task (sub-scripts), APIs com escrita (POST/PUT), email, BD, Selenium/teclado, MessageBox sem auto-fecho,
   Prompt for Input e credenciais literais.
3. Criar `bots/registry/<chave>.yaml` (modelo abaixo).
4. `python -m botmanager.cli validate-registry`.
5. Pull request com revisão. O commit deve dizer como o bot foi validado ([validacao-piloto.md](validacao-piloto.md)).
6. Depois do merge e do deploy: Administração → Recarregar registo → **Ativar** o bot (os bots novos entram
   desativados).

## Modelo

```yaml
key: nome-curto-unico            # [a-z0-9-], 3–80 caracteres; nunca mudar depois de criado
name: "Nome visível"
description: >
  O que faz, que sistemas toca e quando deve ser usado.
category: Compliance             # agrupa no catálogo
risk_level: low                  # low | medium | high  (high exige requires_approval: true)
source_file: "OK Nome do script.xml"
execution:
  adapter: taskt_cli             # taskt_cli | openbots_studio (por validar) | simulated (só dev)
  script: "OK Nome do script.xml"   # relativo a WORKER_TASKT_SCRIPTS_DIR; sem '..' nem unidade
  expected_sha256: <64 hex>      # opcional, recomendado: o worker recusa se o ficheiro mudar
  validated: false               # true só após validação no servidor
prerequisites:                   # texto mostrado antes de executar
  - "Config.txt com credenciais SMTP"
external_effects:                # o que muda fora do servidor (mostrado no diálogo de execução)
  - "Envia email à contabilidade"
config_files:
  - "%USERPROFILE%\\Documents\\Ficheiro config robots\\Config.txt"
known_limitations: []
concurrency:
  policy: single                 # single = no máximo 1 execução ativa; parallel = sem limite
  exclusive_resources: [taskt-desktop]   # OBRIGATÓRIO em todos os bots taskt
timeout_seconds: 3600            # 30 s – 24 h; ao exceder, o processo é terminado e a execução fica "Rever"
success_detection:
  method: taskt_log              # obrigatório para taskt
  taskt_cancelled_is_success: false   # true se o bot usa "Stop Current Task" como fim normal
  fail_on_handled_errors: false       # true para falhar quando há "Error Occured at Line" com Continue Processing
  checks:                        # opcional: validação específica do resultado
    - type: file_exists
      path: "Listas/Pasta/Relatório {date}.csv"   # relativo à pasta de scripts; {date}=AAAA-MM-DD do início
      modified_after_start: true
triggers_allowed: [manual]       # manual | schedule | webhook | after_bot | poll_http
requires_approval: false
retry:
  automatic: false               # só se o processo nem chegou a iniciar; exige idempotent: true
  idempotent: false
permissions:                     # funções com cada permissão (admin tem sempre todas)
  view: [viewer, operator, approver]
  execute: [operator]
  approve: [approver]
  configure: []
```

## Parâmetros

O taskt não aceita parâmetros pela linha de comandos e o esquema recusa `parameters` para `taskt_cli`. Para outros
adaptadores que os suportem:

```yaml
parameters:
  - name: data_inicio
    type: date            # string | integer | date | boolean | enum
    required: true
    description: "Primeiro dia do período"
  - name: modo
    type: enum
    choices: [rapido, completo]
    default: rapido
  - name: token_externo
    type: string
    sensitive: true       # nunca é guardado na BD nem mostrado
```

## Adicionar um novo tipo de disparo

1. Criar `backend/botmanager/triggers/<tipo>.py` com uma subclasse de `TriggerType` (`name`, `config_model` pydantic e,
   se for periódico, `periodic = True` + `evaluate()` que chama `fire_rule(db, rule, dedup_key, …)`).
2. Importá-lo em `backend/botmanager/triggers/__init__.py` e acrescentar o nome a `TRIGGER_TYPES` em
   `registry/schema.py`.
3. Escrever testes de deduplicação e de validação da configuração.

## Adicionar um novo adaptador de execução

1. No worker, criar uma subclasse de `Adapter` (`prepare` sem shell, `evaluate` que **confirma** o resultado) e
   registá-la em `adapters/__init__.py`.
2. No backend, acrescentar o nome a `ADAPTERS` em `registry/schema.py` (e a `ADAPTERS_WITHOUT_PARAMETERS`, se for o
   caso).
3. Testes com um executável falso, como os do taskt (`worker/tests/conftest.py`).
