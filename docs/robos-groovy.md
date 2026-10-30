# Robôs em Java/Groovy

Os robôs podem ser criados de duas formas, na mesma aplicação:

| Método | Para quem | Onde |
|---|---|---|
| **Fluxo visual** | quem não programa | passos (pedido à API, condição, ciclo, email, SQL…) — ver [fluxos.md](fluxos.md) |
| **Java/Groovy** | quem programa (como nos scripts do Cyclos) | editor de código com ajuda, verificação de erros e testes |

**Catálogo → + Novo robô** pergunta qual dos dois usar. Os dois formatos partilham tudo o resto: versões, execução,
aprovações, agendamentos e outras regras, credenciais do cofre, ficheiros persistentes, logs, auditoria e permissões.
No catálogo, cada robô mostra o formato (*Fluxo visual* ou *Java/Groovy*).

## O editor de código

- Realce de sintaxe Groovy, números de linha, **Ctrl+Espaço** sugere as funções da API, **Ctrl+S** grava.
- **Validar** compila o código sem o executar: erros de sintaxe e de segurança ficam marcados na linha, e mostra as
  credenciais que o código usa (✅ existe / ❌ não existe).
- **▶ Testar (simulação)** grava (se houver alterações) e executa no worker **sem efeitos externos**: os GET e as
  consultas SQL são feitos, mas POST/PUT/DELETE, emails e escritas SQL não, e os ficheiros persistentes não mudam.
  A consola mostra o estado e os logs em direto; num erro, clicar em "linha N" leva à linha do código.
  A simulação pode correr com o robô ainda desativado e exige a permissão de configurar o robô.
- **Ajuda** (painel à direita): todas as funções, com exemplos que se inserem no código.
- **Variáveis e configuração**: valores iniciais (ex.: `email_teste`), disponíveis no código pelo nome.
- **Duplicar** (cria um robô novo, desativado, no mesmo ou no outro formato), **Eliminar**, **Versões** (abrir uma
  versão antiga e gravar = reverter).
- O cabeçalho mostra o formato, se o robô está ativo, a versão em uso e "● alterações por guardar"; o browser avisa
  antes de sair com alterações por gravar.

## API disponível no código

```groovy
// HTTP (só https). Opções: credencial, headers: [..], query: [..], esperar: [200], resposta: 'texto', timeout, tentativas
def clientes = http.get("https://app.lusopay.com:8443/web/api/users", credencial: "cyclos-producao", query: [pageSize: 100])
def id = http.post("https://app.lusopay.com:8443/web/api/x", [campo: "valor"], credencial: "cyclos-producao")
// também http.put, http.patch, http.delete; o corpo é JSON (mapa/lista) ou texto (String)

// Email (anexos: ficheiros criados por este robô)
email.enviar(credencial: "smtp-lusopay", para: ["a@lusopay.com"], cc: "b@lusopay.com",
             assunto: "Relatório", corpo: "Em anexo.", anexos: ["relatorio.csv"])

// SQL Server: parâmetros :nome (nunca juntar texto à consulta)
def linhas = sql.consultar("sql-magnimeios", "select id, nome from clientes where id > :ultimo", [ultimo: 10])
sql.executar("sql-magnimeios", "update t set estado = 1 where id = :id", [id: 5])   // grava (commit)

// Ficheiros da execução (e ficheiros persistentes de controlo)
def ultimo = ficheiro.ler("ultimo id.txt") ?: "0"     // null se não existir
ficheiro.gravar("ultimo id.txt", novoUltimo)
ficheiro.acrescentar("log.txt", "linha\n")
ficheiro.csv("relatorio.csv", linhas, colunas: ["id", "nome"])   // ; e UTF-8 com BOM, para o Excel
ficheiro.existe("x.txt")

// Registo e controlo
log "mensagem"; aviso "atenção"; erro "problema"   // println também vai para o log
falhar("motivo")      // termina com erro (FAILED, com a linha)
terminar("motivo")    // termina com sucesso; não é apanhado por try/catch
paralelo(lista, 10) { item -> http.get("…/${item.id}", credencial: "…") }   // até 10 em simultâneo

// Dados: params (parâmetros da execução), run_id e as variáveis do robô pelo nome
// simulacao: true em "▶ Testar (simulação)" — os POST/PUT/DELETE devolvem resposta vazia, por isso
//            não valide a resposta de um POST quando simulacao é true
```

Funções auxiliares (iguais aos filtros dos fluxos, para as conversões darem o mesmo resultado): `text`, `num`
(aceita `1.234,56`), `money`, `decimal`, `date(d, '%Y-%m-%d')`, `now()`, `today()`, `first_day_of_month(-1)`,
`add_days`, `add_time(d, 'months', 1)`, `todate`, `jsonpath(json, '$.a.b')`, `parsejson`, `tojson`, `as_list`,
`between`, `after`, `before`, `regex`, `regex_replace`, `regex_split`, `split_text`, `length`, `taskt_compare`,
`is_numeric`.

**Credenciais:** o nome tem de estar escrito no código (`credencial: "cyclos-producao"`); a plataforma deteta-o,
confirma que existe e só entrega ao worker as credenciais usadas. As passwords nunca chegam ao código Groovy: os
pedidos, emails e consultas são feitos pelo motor do Bot Manager (ver Segurança).

## Converter entre fluxo e Groovy

No editor: **Converter para Java/Groovy** ou **Converter para Fluxo visual**. A conversão:

- mantém a lógica, as condições, as variáveis, os ciclos, o tratamento de erros e a ordem dos passos;
- mostra um relatório (sem equivalente / aviso / informação) antes de aplicar;
- abre o resultado no editor **sem gravar**: só fica gravado com "Gravar nova versão"; a versão anterior (no formato
  anterior) continua em **Versões**;
- se houver partes sem equivalente, não é aplicada sem confirmação ("Converter mesmo assim"); nesse caso essas partes
  ficam como passos "Falhar" com o código original na mensagem — nunca são apagadas em silêncio.

Também é possível **Duplicar** para o outro formato, mantendo o robô original intacto.

| Fluxo → Groovy | Groovy → Fluxo |
|---|---|
| Todos os tipos de passos. Expressões e modelos Jinja passam a Groovy com as funções auxiliares. | Atribuições, `if/else`, `for (x in lista)`, `while`, `try/catch`, `break/continue`, `paralelo`, `http.*`, `email.enviar`, `sql.*`, `ficheiro.*`, `log/aviso/erro`, `falhar`, `terminar`, `lista << valor`. |
| Avisos: variáveis alteradas dentro de ciclos mantêm o último valor no Groovy; HTTP no Groovy aceita qualquer 2xx. | Sem equivalente: métodos e classes próprios, closures que não sejam `collect { it.campo }` / `findAll { it.campo == v }`, ciclo `for` clássico, `finally`. |

Os 13 robôs importados do servidor de bots foram convertidos para Groovy, compilam, e voltam a fluxo válido; o robô
"diligência reforçada BdP" (150 passos) produz exatamente os mesmos ficheiros, pedidos e emails nos três formatos
(fluxo original, Groovy, fluxo reconvertido) — teste em `backend/tests/test_groovy.py` e `worker/tests/test_groovy_engine.py`.

## Segurança e isolamento

O código corre no worker/runner numa **JVM separada**, com várias camadas:

1. **Verificação antes de compilar** (`lusopay_worker/groovy/BmHost.groovy`, classe `Verificador`): recusa anotações
   (que podem executar código ao compilar), `import` fora de `java.util/time/math/text` e JSON, tipos como `File`,
   `Runtime`, `ProcessBuilder`, `Thread`, `Socket`, `URL`, reflexão, `GroovyShell`, e métodos como `execute`,
   `getClass`, `forName`, `evaluate`, `exit`, nomes de métodos/propriedades dinâmicos.
2. **SecurityManager** (Java 17–23): bloqueia criar processos, ligações de rede diretas, ler ficheiros fora da pasta
   da execução e escrever fora dela, terminar a JVM ou trocar o SecurityManager.
3. **Sem segredos na JVM**: as credenciais ficam no motor Python; a JVM recebe um ambiente mínimo (sem tokens nem
   proxies). HTTP, email e SQL passam pela ponte e seguem as regras dos fluxos (só https, `BM_FLOW_ALLOWED_HOSTS`,
   redação de segredos nos logs, sem repetição de POST/PUT/DELETE).
4. **Limites**: memória `-Xmx512m` (`WORKER_GROOVY_MEMORY`), timeout do robô (o worker termina a árvore de processos),
   máximo de 500 000 operações por execução; se o motor terminar, a JVM termina também.
5. O runner Docker corre com utilizador sem privilégios, numa rede interna.

Só quem tem a permissão de configurar o robô (por omissão, administradores) pode editar o código; cada gravação fica
versionada e auditada.

**Java 24 ou posterior** já não tem SecurityManager: o worker recusa executar robôs Groovy nessas versões. Use o
Java 21.

## Instalação

- **Windows (PC/servidor):** instalar o Java 21 — `winget install EclipseAdoptium.Temurin.21.JRE` — e depois o
  `arrancar.bat`/`iniciar.bat` descarrega o Groovy (`python -m lusopay_worker.groovy setup`, com SHA-256 verificado
  contra o Maven Central). `python -m lusopay_worker.groovy status` mostra o que está instalado.
- **Docker:** as imagens `api` e `runner` já incluem o Java 21 (Eclipse Temurin) e o Groovy.
- Sem Java no servidor da API, o editor continua a funcionar, mas a verificação de sintaxe só acontece ao testar e a
  conversão Groovy → fluxo fica indisponível.
- Variáveis opcionais: `WORKER_JAVA`/`BM_JAVA` (caminho do java), `WORKER_GROOVY_LIB`/`BM_GROOVY_LIB` (pasta dos jars).
