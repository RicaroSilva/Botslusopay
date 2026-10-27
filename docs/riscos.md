# Riscos, limitações e questões em aberto

## 1. Credenciais encontradas (ação recomendada: rodar)

A análise estática (`tools/inventory/analyze_taskt.py`) contou, **sem reproduzir valores**:

| Tipo | Ocorrências | Ficheiros |
|---|---|---|
| Cabeçalho `Authorization` Basic **escrito no XML** (API Cyclos produtiva) | 58 | 21 |
| Password SMTP em claro (`v_SMTPPassword`) | 53 | 30 |
| Password escrita no browser por Selenium (login no Cyclos) | 10 | 10 |
| Connection string SQL Server com utilizador + password "encriptada" pelo taskt | 5 | 5 |
| Cabeçalho `Authorization` lido de variável (`{vSenhaApi}` ← `Config.txt`) — boa prática | 80 | — |

No total, 49 dos 64 XML têm pelo menos uma credencial literal. Pontos importantes:

- A password das connection strings é cifrada pelo taskt com uma chave fixa do próprio produto. **Deve ser considerada
  reversível.**
- O histórico do Git deste repositório (commit `eae0728`) contém 3 desses XML com credenciais e um documento com
  dados pessoais de um cliente (relatório PEP). Apagar os ficheiros não os remove do histórico. O repositório é
  privado, mas recomenda-se:
  1. **rodar** a password da conta API `RPATaskt` no Cyclos, as passwords das contas SMTP, a password do utilizador
     Cyclos usado pelo Selenium e a password SQL Server;
  2. avaliar a reescrita do histórico (ex.: `git filter-repo`), que é uma operação destrutiva e exige coordenação.
- Recomendação para os bots (fora do âmbito, porque implica alterar os XML): substituir os valores literais por
  variáveis lidas do `Config.txt`, como já fazem os bots mais recentes (`Ok Recolha das Configurações`), e proteger o
  `Config.txt` com uma ACL que só dê acesso à conta dos bots.

## 2. Riscos operacionais

| Risco | Mitigação no Bot Manager | Residual |
|---|---|---|
| Execução duplicada (Agendador de Tarefas + Bot Manager) | locks e idempotência **só dentro** do Bot Manager | **Alto** enquanto o Agendador continuar a correr os mesmos bots: desativar a tarefa correspondente antes de criar uma regra |
| Dois taskt em simultâneo no mesmo desktop/log | recurso exclusivo `taskt-desktop` em todos os bots taskt | o orquestrador atual (fora do Bot Manager) pode coincidir: ver a linha anterior |
| Bot bloqueado em MessageBox / Prompt for Input / erro "Oops" | timeout por bot + kill da árvore de processos | a execução falha; corrigir o XML ou correr só de forma assistida |
| Resultado incerto após falha de comunicação ou reinício | `needs_review`, sem repetição automática, confirmação explícita para repetir | depende da verificação humana |
| Repetir bots com efeitos (Tarifa MB Way, callbacks, POST BCFT) | aprovação obrigatória em risco elevado; aviso de efeitos externos | os próprios bots não são idempotentes |
| Run Task aninhado não é visível | sub-scripts listados no resumo (`nested_scripts`) | uma falha num sub-script só aparece no log do runtime |
| Alterações não revistas aos XML | SHA-256 opcional na definição (o worker recusa se não coincidir) | só ativo nos bots piloto; alargar a todos |
| Sessão Windows bloqueada / desligada | instruções de sessão interativa permanente | Selenium/teclado falham com o ecrã bloqueado |
| Ficheiros produzidos com dados pessoais/financeiros | não são copiados para o Bot Manager | continuam no servidor de bots e nos emails |
| `poll_http` usado para SSRF | só https, hosts na lista autorizada, sem redirects, só administradores configuram | — |

### Riscos específicos dos fluxos nativos

| Risco | Mitigação |
|---|---|
| Perda da `BM_VAULT_KEY` | sem ela as credenciais não se decifram: guardar a chave num cofre; suporta rotação (`BM_VAULT_KEY_OLD`) |
| Fluxo usado para chamar sistemas internos (SSRF) | só https, host fixo no URL, sem redireções, `BM_FLOW_ALLOWED_HOSTS`, só administradores/configure editam |
| Fluxo com erros a alterar dados reais | risco elevado → aprovação obrigatória; versões fixadas no pedido; testar no ambiente dev; POST nunca repetido automaticamente |
| Ficheiros com dados pessoais guardados na BD | limite de tamanho, downloads auditados; **falta definir retenção** (ver questões em aberto) |
| Lógica de negócio reescrita diferente da original | correr o fluxo em paralelo com o bot taskt e comparar resultados antes de desligar o antigo |

## 3. Limitações conhecidas desta versão

- **O runtime real não foi executado.** Nenhuma integração com bots reais foi validada (ver
  [validacao-piloto.md](validacao-piloto.md)). Os testes com o adaptador simulado e o `taskt.exe` falso não provam que
  os bots funcionam.
- O formato do log do taskt e a escrita em `_001` foram deduzidos do código-fonte do taskt (master) e do Serilog. A
  versão instalada pode ser diferente.
- O adaptador OpenBots não está implementado por falta de um mecanismo confirmado.
- O taskt não aceita parâmetros pela linha de comandos, por isso os bots taskt não têm parâmetros no Bot Manager
  (datas e períodos são calculados pelos próprios scripts ou pedidos com Prompt for Input).
- Um worker executa um trabalho de cada vez (adequado a um servidor de bots com um desktop).
- A autenticação é local. O SSO corporativo ainda não está integrado.
- O cancelamento termina o processo à força: um bot a meio de uma operação externa pode deixá-la incompleta (por isso
  a execução fica `CANCELLED` e deve ser verificada).
- O cron não exprime "último dia do mês".
- A retenção de logs/auditoria e dos ficheiros produzidos não está automatizada (definir a política e uma tarefa de limpeza/arquivo).
- O passo SQL Server usa `pymssql` e foi testado com uma ligação simulada; ainda não contra o SQL Server real.
- O editor de fluxos é por formulário; não há execução "a seco" passo a passo (testar contra o ambiente dev).

## 4. Questões em aberto

| # | Questão | Como validar |
|---|---|---|
| 1 | Versão do taskt instalada e formato do log | [validacao-piloto.md](validacao-piloto.md) passos 0–1 |
| 2 | Versão do OpenBots e mecanismo de execução sem interface | documentação da versão instalada; teste manual |
| 3 | Que tarefas do Agendador lançam bots hoje, com que conta e horário | `schtasks /query /v /fo list` no servidor |
| 4 | Qual é o IdP corporativo (Microsoft Entra ID / AD / outro) para SSO | equipa de IT |
| 5 | Existe PostgreSQL gerido internamente? | equipa de IT; alternativa: PostgreSQL no servidor de aplicações |
| 6 | O que é `CyclosRESTAPITasktConsole.exe` (origem, código, logs) | inspeção no servidor; procurar o código-fonte |
| 7 | Os XML no servidor são iguais aos do ZIP? | comparar SHA-256 |
| 8 | Ambiente Cyclos de teste (`web_dev`) disponível para testar os bots que escrevem? | equipa Cyclos |
| 9 | Política de retenção de logs e auditoria (requisitos BdP/RGPD) | compliance |
| 10 | Quem são os aprovadores para os bots de risco elevado | direção/compliance |
| 11 | Os scripts "sem prefixo" e "REVER" ainda são usados? | responsável dos bots |
