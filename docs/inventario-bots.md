# Inventário dos bots (Fase A — Análise)

Data da análise: 27-10-2026. Fonte: `codigosbots.zip` (pasta `Ficheiro config robots/`, 64 XML + `Config.txt` vazio),
enviado para esta tarefa. A análise estática foi feita com `tools/inventory/analyze_taskt.py`. A tabela completa,
script a script, está em [inventario-detalhado.md](inventario-detalhado.md).

> **Os XML não estão no repositório Git.** Contêm credenciais em claro (ver [riscos.md](riscos.md)). Ficam no
> servidor de bots, onde já são executados, e o Bot Manager referencia-os pelo nome do ficheiro.

## 1. O que são estes ficheiros (confirmado)

| Facto | Evidência | Estado |
|---|---|---|
| Os 64 XML são scripts **taskt** e não projetos OpenBots Studio | A raiz é `<Script><Commands><ScriptAction><ScriptCommand xsi:type="…Command">` e os comandos (`RunTaskCommand`, `SMTPSendEmailCommand`, `RESTCommand`, `SeleniumBrowser*`…) são os do taskt. Há ficheiros chamados "Recolhe senha API de RPAtaskt" e emails assinados "Taskt robot da LUSOPAY". | Confirmado |
| Existem **projetos OpenBots Studio**, mas não estão no ZIP | O orquestrador `OK processos diarios do servidor de bots.xml` abre `{Folder.Documents}\OpenBotsStudio\My Scripts\…\project.obconfig` (2 projetos). Dois XML têm o prefixo "SUBSTITUÍDO POR OPENBOTS". | Confirmado (conteúdo desconhecido) |
| Os scripts correm a partir de `…\Documents\taskt\My Scripts\` | Usam `{Folder.ScriptPath}` e caminhos absolutos como `C:\Users\Utilizador\Documents\taskt\My Scripts\Listas\…` | Confirmado |
| Há configuração partilhada em `Documents\Ficheiro config robots\Config.txt` | Lida por `Ok Recolha das Configurações.xml` e `OK Recolhe senha API de RPAtaskt.xml` | Confirmado (o ficheiro veio vazio) |

### Formato do `Config.txt` (deduzido dos XML, sem valores)

O ficheiro é uma lista `chave,valor,` lida com "Extract All Between Text". Chaves usadas: `RPATaskt` (cabeçalho
Basic da API Cyclos), `Server`, `BaseDeDados`, `Host` (SMTP), `smtpUser`, `smtpPass`, `smtpPort`, `ServerOnline`,
`Porta`, `BaseDeDadosOnline` e `BDUser`. Se o ficheiro não existir, o script envia um email de alerta a dev@.

## 2. Mecanismo de execução

| Pergunta | Resposta | Confiança |
|---|---|---|
| Como se inicia um script taskt pela linha de comandos? | `taskt.exe "<caminho completo do .xml>"`. Se receber um argumento, o `Program.cs` abre o motor (`frmScriptEngine`) com `closeWhenDone=true`, executa e fecha. | **Confirmado no código-fonte** (saucepleez/taskt, ramo master). **A versão instalada no servidor está por validar.** |
| Aceita parâmetros? | Não. O `Program.cs` só lê `args[0]`. As variáveis são passadas apenas por `Run Task` dentro do próprio taskt. | Confirmado no código-fonte |
| Há código de saída fiável? | Não. É uma aplicação WinForms e `Application.Run` não define o código de saída. Erros não tratados mostram uma MessageBox "Oops", que bloqueia. | Confirmado no código-fonte |
| Como saber o resultado? | Pelo log do motor (Serilog): `<RootFolder>\Logs\taskt Engine Logs<AAAAMMDD>.txt` contém `Script Path: …` no início e `Result Code: Successful/Error/Cancelled` no fim. `Stop Current Task` termina com **Cancelled**. "Error Handling → Continue Processing" regista `Error Occured at Line N` e termina como Successful. | Confirmado no código-fonte; formato exato por validar na versão instalada |
| Precisa de sessão interativa? | Sim. É WinForms; muitos bots usam Selenium/Chrome, `SendKeys`, movimentos do rato e janelas. Não pode correr como serviço do Windows na sessão 0. | Confirmado (natureza dos comandos) |
| Como se iniciam os projetos OpenBots? | O orquestrador usa `Start Process` sobre `project.obconfig` (associação de ficheiro). **Não foi possível confirmar** uma interface de linha de comandos do OpenBots que devolva o resultado. | **Desconhecido** — ver [validacao-piloto.md](validacao-piloto.md) |
| Que versões estão instaladas? | Desconhecido. | Validar no servidor (Ajuda → Acerca, ou propriedades do `taskt.exe` / OpenBots) |
| Como é disparado hoje o orquestrador diário? | Não há evidência no repositório. Provavelmente pelo Agendador de Tarefas do Windows. | **Desconhecido** — verificar o Agendador de Tarefas no servidor |

## 3. Bots registados no Bot Manager

Foram registados os bots "OK" em uso no orquestrador e os mais relevantes; os restantes ficam documentados no
inventário detalhado. **Todos estão `validated: false`**: aparecem na interface, mas não podem ser executados até a
validação no servidor ([validacao-piloto.md](validacao-piloto.md)).

| Chave | Script / projeto | Risco | Efeitos externos | Notas |
|---|---|---|---|---|
| `taskt-smoke-config` | OK Recolhe senha API de RPAtaskt.xml | baixo | nenhum (só lê `Config.txt`) | **Piloto fase 1**: valida o mecanismo |
| `cyclos-recolher-ids` | OK recolher Cyclos ID por API.xml | baixo | GET à API Cyclos | **Piloto fase 2**: primeiro bot real, só leitura |
| `saldos-clientes-fim-mes` | OK Saldos de clientes no Cyclos no final do mês.xml | médio | GET; email com saldos | ~3,5 h |
| `analise-desempenho-fraudes` | OK Análise de desempenho, operações e fraudes… | médio | GET; email | dia 14 |
| `analise-listas-pep-api` | OK Análise Listas PEP por API.xml | médio | download PEP.csv; email | depende das listas do projeto OpenBots BdP |
| `atribuir-tarifa-mbway` | OK Atribuir Tarifa MB Way.xml | **elevado** | **altera clientes no Cyclos** através de `C:\CyclosRESTAPITaskt\CyclosRESTAPITasktConsole.exe` | componente auxiliar desconhecido |
| `bcft-mbway-diaria` / `-semanal` | OK LUSOPAY Análise BCFT MB Way… | **elevado** | **POST de registos no Cyclos**; SQL Server; email | contém "Prompt for Input" (bloqueia sem utilizador) |
| `reenviar-callbacks-2h` / `-5a1h` | OK Reenviar notificações de callback falhadas… | **elevado** | **chama URLs de callback de comerciantes**; email | lê `\\REALTIME\logs`; lista de exclusões obrigatória |
| `processos-diarios` | OK processos diarios do servidor de bots.xml | **elevado** | os de todos os bots chamados | orquestrador atual |
| `processos-fim-de-semana` | OK processos fim de semana do servidor de bots.xml | médio | relatórios/emails | orquestrador |
| `diligencia-reforcada-bdp-openbots` | projeto OpenBots (project.obconfig) | médio | — | adaptador OpenBots por validar |
| `listas-onu-ue-openbots` | projeto OpenBots (project.obconfig) | médio | — | adaptador OpenBots por validar |

## 4. Dependências e sequências identificadas

**Orquestrador diário** (`OK processos diarios…`), lógica atual:

1. `Ok Recolha das Configurações` (lê o Config.txt para variáveis, que passam para os bots seguintes).
2. Se amanhã for dia 01: `OK Saldos de clientes no Cyclos no final do mês`.
3. Todos os dias: `OK Atribuir Tarifa MB Way`.
4. Exceto à sexta e ao sábado (a data da próxima sexta fica em `Listas\Processos diarios servidor de bots\sexta-feira.txt`,
   atualizada pelo próprio bot): projeto OpenBots **diligência reforçada BdP** (espera pelo fim) e projeto OpenBots
   **Listas ONU e UE** (não espera).
5. Dia 14: `OK Análise de desempenho, operações e fraudes`.
6. Dias 1, 8, 15, 22 e 29: `OK Análise Listas PEP por API`.

**Dependências de dados** (ficheiros partilhados):

- A `Análise Listas PEP por API` lê as listas de clientes/gerentes/beneficiários produzidas pelo projeto OpenBots
  *diligência reforçada BdP*, que tem de ter corrido antes.
- `Análise Listas ONU e UE – criação de listas` → `fazer análise das listas` → `criação de relatório e envio para Cyclos`
  (cadeia por ficheiros em `Listas\Análise de sanções ONU e UE\`).
- Muitos bots dependem de `Ok Recolha das Configurações` (sub-script via Run Task, não é uma dependência de execução).
- `Atribuir Tarifa MB Way` depende de `C:\CyclosRESTAPITaskt\CyclosRESTAPITasktConsole.exe` e do seu log.

**Independentes** (podem correr isoladamente, desde que os pré-requisitos de rede/ficheiros existam): smoke config,
recolher Cyclos ID, Saldos, Análise de desempenho, Reenvio de callbacks, BCFT MB Way.

## 5. Bloqueios à execução não assistida (por bot)

- **MessageBox sem auto-fecho** e **Prompt for Input** bloqueiam até alguém clicar. O Bot Manager trata isto com
  timeout e mata a árvore de processos, mas a execução falha. Afeta, entre outros, BCFT MB Way (Prompt for Input),
  `Validação diária de valores carregados no Cyclos` e vários scripts sem prefixo (ver a coluna "Bloqueios
  interativos" do inventário detalhado).
- **Selenium/teclado/rato**: exigem uma sessão de desktop desbloqueada, com resolução estável e Chrome/chromedriver
  compatíveis.

## 6. Outros componentes auxiliares encontrados

| Componente | Onde | Estado |
|---|---|---|
| `C:\CyclosRESTAPITaskt\CyclosRESTAPITasktConsole.exe` | Atribuir Tarifa MB Way | Tecnologia e origem desconhecidas; não está no repositório |
| LibreOffice (`scalc.exe`, ficheiros `.odt`) | relatórios ONU/UE, PEP e extratos | Necessário no servidor |
| Partilha `\\REALTIME\logs` | Reenvio de callbacks | Acesso de rede necessário |
| SQL Server (Magnimeios) | BCFT MB Way, Cria registo de documento | Connection string no XML |
| `services.lusopay.com/PEP.csv`, listas ONU/UE (scsanctions.un.org, webgate.ec.europa.eu) | análises de compliance | Acesso Internet |
| `http://www.randomnumberapi.com` (HTTP sem TLS) | Recolhe transações aleatórias | Dependência externa frágil |

## 7. Ficheiros removidos anteriormente do repositório

O commit `eae0728` (anterior a esta tarefa) tinha `Abrir Cyclos produtivo.xml`,
`Fechar contas de clientes com saldo zero há 12 meses.xml`, `OK Alterar perfil de risco BCFT via API.xml` (versão
que **não** consta do ZIP; faz PUT de perfis de clientes) e 3 documentos Word (lógica de um bot de ativação de clientes,
comprovativos de ações e um relatório PEP de um cliente). Foram apagados a pedido do utilizador e continuam no
histórico do Git — **incluindo credenciais e dados pessoais** (ver [riscos.md](riscos.md)).
