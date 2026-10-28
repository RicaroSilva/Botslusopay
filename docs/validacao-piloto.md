# Validação no servidor de bots e piloto

> **Estado atual: nenhum bot real foi executado pelo Bot Manager.** Os testes automáticos usam um adaptador simulado e
> um `taskt.exe` falso que imita o formato do log. Provam o comportamento do Bot Manager, **não** que os bots reais
> funcionem. Os passos abaixo têm de ser feitos no servidor de bots, por alguém com acesso, antes de marcar qualquer bot
> como `validated: true`.

## Passo 0 — Recolher informação (sem executar nada)

Na sessão da conta que corre hoje os bots:

1. Versão do taskt: propriedades do `taskt.exe` → Detalhes, ou Ajuda/About no Studio. Anotar o caminho completo do
   executável.
2. Pasta raiz do taskt: `%APPDATA%\taskt\AppSettings.xml` → `ClientSettings/RootFolder`. Os logs ficam em
   `<RootFolder>\Logs`. Confirmar que existem ficheiros `taskt Engine Logs<AAAAMMDD>.txt`.
3. Versão e instalação do OpenBots (Studio/Agent) e a pasta `Documents\OpenBotsStudio\My Scripts\` com os dois projetos.
4. Agendador de Tarefas: que tarefas lançam `taskt.exe`/OpenBots, com que horário, conta e opção "executar apenas com
   sessão iniciada". **Guardar uma exportação** (`schtasks /query /xml`).
5. Confirmar que a versão de cada XML em `My Scripts` é a do ZIP analisado (SHA-256:
   `Get-FileHash "<ficheiro>" -Algorithm SHA256`). Os dois bots piloto têm o hash registado na definição YAML.

## Passo 1 — Confirmar o mecanismo à mão (fora do Bot Manager)

Numa janela PowerShell na sessão da conta dos bots:

```powershell
$log = Join-Path "<RootFolder>\Logs" ("taskt Engine Logs" + (Get-Date -Format yyyyMMdd) + ".txt")
$antes = (Get-Item $log -ErrorAction SilentlyContinue).Length
& "<caminho>\taskt.exe" "<RootFolder>\My Scripts\OK Recolhe senha API de RPAtaskt.xml"
# esperar que a janela do motor feche
Get-Content $log -Tail 30
```

Confirmar:

- [ ] o motor abre, executa e **fecha sozinho**;
- [ ] o log contém `Script Path: …OK Recolhe senha API de RPAtaskt.xml` e `Result Code: Successful`;
- [ ] com o `Config.txt` temporariamente renomeado, aparece `Result Code: Error` (repor o ficheiro de seguida);
- [ ] o formato das linhas é `AAAA-MM-DD hh:mm:ss.fff +hh:mm [INF] mensagem`.

Se alguma destas condições falhar, **parar**. O adaptador `taskt_cli` (`worker/lusopay_worker/tasktlog.py`) tem de
ser ajustado à versão instalada.

## Passo 2 — Instalar o worker e correr o piloto fase 1

1. Instalar conforme [instalacao-windows.md](instalacao-windows.md), com `WORKER_ADAPTERS=taskt_cli`.
2. Com `BM_REGISTRY_DIR` a apontar para `bots/registry-taskt`, no ficheiro `bots/registry-taskt/taskt-smoke-config.yaml`, mudar `validated: true` (por revisão de código; o commit
   documenta a validação feita no passo 1) e, na Administração, carregar em **Recarregar registo** e **Ativar**.
3. Executar `taskt-smoke-config` pela interface. Resultado esperado: `Concluída`, `runtime_result: Successful` e as
   linhas `[runtime]` do log do taskt visíveis.
4. Teste de falha: renomear o `Config.txt` e executar de novo. Esperado: `Falhou / O bot reportou erro`. Repor o
   ficheiro.
5. Teste de timeout: não é possível com este script. Fica coberto pelos testes automáticos e é verificado no passo 3
   se necessário.

## Passo 3 — Piloto fase 2 (primeiro bot real, só leitura)

`cyclos-recolher-ids`. Efeitos: apenas GET à API Cyclos produtiva. Não escreve ficheiros nem envia emails.

- [ ] Confirmar com a equipa Cyclos que a carga de um GET a `/web/api/users` filtrado por grupos é aceitável em horário
      laboral.
- [ ] `validated: true`, recarregar o registo, ativar e executar.
- [ ] Confirmar `Concluída` e, no log `[runtime]`, a ausência de erros.

## Passo 4 — Alargar

Para cada bot seguinte, documentar no pull request que muda `validated: true`:

- pré-requisitos confirmados (ficheiros, rede, Config.txt, componentes auxiliares);
- efeitos externos e ambiente de teste disponível (ex.: Cyclos de teste `web_dev`);
- se o bot tem MessageBox/Prompt for Input ativos (ver o inventário detalhado), tem de ser corrigido antes ou fica
  apenas manual e assistido;
- com quem foi acordada a primeira execução real (risco médio/elevado).

## OpenBots

O adaptador `openbots_studio` recusa executar. Para o ativar é preciso:

1. Identificar na instalação um mecanismo **suportado** de execução sem interface (ex.: executável de execução/Agent
   da versão instalada, ou a API do OpenBots Server, se existir) e como esse mecanismo reporta o resultado.
2. Testá-lo à mão, como no passo 1.
3. Implementar `prepare`/`evaluate` em `worker/lusopay_worker/adapters/openbots.py` com testes, e só depois mudar
   `validated` nos dois projetos.

Até lá, os projetos OpenBots continuam a ser lançados pelo orquestrador atual.
