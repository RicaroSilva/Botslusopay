// Referência da API disponível no código dos robôs Groovy (ajuda do editor e autocompletar).
// A implementação está em worker/lusopay_worker/groovy/BmHost.groovy; as operações com efeitos externos
// (http, email, sql, ficheiros) são executadas pelo motor do Bot Manager com as credenciais do cofre.

export interface ApiEntry {
  label: string;      // texto inserido pelo autocompletar
  detail: string;     // assinatura curta
  info: string;       // explicação
  group: string;
}

export const GROOVY_API: ApiEntry[] = [
  { group: "HTTP", label: 'http.get("https://…", credencial: "cyclos-producao")', detail: "→ resposta (JSON já lido, ou texto)",
    info: "Pedido GET. Opções: credencial, headers: [nome: valor], query: [nome: valor], esperar: [200], resposta: 'texto', timeout: 60, tentativas: 2. Só https; repete até 2 vezes em caso de falha de rede." },
  { group: "HTTP", label: 'http.post("https://…", [campo: valor], credencial: "cyclos-producao")', detail: "→ resposta",
    info: "POST com corpo JSON (mapa ou lista) ou texto (String). Nunca é repetido automaticamente. Também http.put, http.patch e http.delete." },
  { group: "Email", label: 'email.enviar(credencial: "smtp-lusopay", para: ["a@lusopay.com"], assunto: "…", corpo: "…")', detail: "envia email",
    info: "Opções: para, cc (texto ou lista; aceita vários endereços separados por ; ou ,), assunto, corpo, anexos: [\"ficheiro.csv\"] (ficheiros criados por este robô)." },
  { group: "SQL Server", label: 'sql.consultar("sql-magnimeios", "select … where id > :ultimo", [ultimo: 10])', detail: "→ lista de linhas (mapas)",
    info: "Consulta só de leitura (é sempre desfeita no fim). Os valores vão como parâmetros :nome — nunca junte texto à consulta." },
  { group: "SQL Server", label: 'sql.executar("sql-magnimeios", "update … where id = :id", [id: 5])', detail: "escreve na base de dados",
    info: "Alterações gravadas (commit). Torna o robô de risco elevado; em simulação a alteração é desfeita." },
  { group: "Ficheiros", label: 'ficheiro.ler("ultimo id.txt")', detail: "→ texto ou null", info: "Lê um ficheiro desta execução ou um ficheiro persistente (controlo)." },
  { group: "Ficheiros", label: 'ficheiro.gravar("relatorio.txt", texto)', detail: "cria/substitui", info: "Os ficheiros criados ficam disponíveis na página da execução; os persistentes são guardados para a execução seguinte." },
  { group: "Ficheiros", label: 'ficheiro.acrescentar("log.txt", texto)', detail: "acrescenta no fim", info: "" },
  { group: "Ficheiros", label: 'ficheiro.existe("nome.txt")', detail: "→ true/false", info: "" },
  { group: "Ficheiros", label: 'ficheiro.csv("relatorio.csv", linhas, colunas: ["id", "nome"])', detail: "CSV para Excel", info: "linhas: lista de mapas (ou de listas). Separador ; e UTF-8 com BOM, com proteção contra fórmulas." },
  { group: "Registo e controlo", label: 'log "mensagem"', detail: "linha no log", info: "Também println. aviso \"…\" e erro \"…\" registam com outro nível." },
  { group: "Registo e controlo", label: 'aviso "mensagem"', detail: "aviso no log", info: "" },
  { group: "Registo e controlo", label: 'falhar("motivo")', detail: "termina com erro", info: "A execução fica FAILED com o motivo e a linha." },
  { group: "Registo e controlo", label: 'terminar("motivo")', detail: "termina com sucesso", info: "Não é apanhado por try/catch." },
  { group: "Registo e controlo", label: "paralelo(lista, 10) { item ->\n    \n}", detail: "repete em paralelo", info: "Corre o bloco para cada elemento, até N em simultâneo (útil para muitos pedidos à API)." },
  { group: "Dados", label: "params", detail: "parâmetros da execução", info: "Mapa com os parâmetros. As variáveis do robô estão disponíveis diretamente pelo nome; run_id identifica a execução." },
  { group: "Dados", label: "simulacao", detail: "true num teste", info: "true em ▶ Testar (simulação): os POST/PUT/DELETE devolvem uma resposta vazia, os emails e as escritas SQL não são feitos. Use, por exemplo, if (!simulacao) para validar a resposta de um POST." },
  { group: "Funções", label: "text(valor)", detail: "→ texto", info: "Listas e mapas passam a JSON; null passa a \"\"." },
  { group: "Funções", label: "num(valor)", detail: "→ número", info: "Aceita 1234.56 e o formato português 1.234,56." },
  { group: "Funções", label: "money(valor)", detail: "→ \"1234,50\"", info: "Duas casas decimais com vírgula." },
  { group: "Funções", label: "date(now(), '%Y-%m-%d')", detail: "→ texto da data", info: "Formatos %Y %m %d %H %M %S %B %A. Também now(), today(), first_day_of_month(-1), add_days(d, n), add_time(d, 'months', n), todate(texto)." },
  { group: "Funções", label: "jsonpath(json, '$.items[*].id')", detail: "→ valor", info: "Caminho simples: $.a.b, $..chave, a[0].b, items[*].id." },
  { group: "Funções", label: "parsejson(texto)", detail: "→ mapa/lista", info: "Também tojson(valor) e as_list(valor)." },
  { group: "Funções", label: "between(texto, 'início', 'fim')", detail: "→ texto entre", info: "Também after(texto, 'x') e before(texto, 'x')." },
  { group: "Funções", label: "regex_replace(texto, '[0-9]+', '#')", detail: "→ texto", info: "Também regex(texto, padrão, grupo) e regex_split(texto, padrão)." },
];

export const NEW_GROOVY_ROBOT = `// Robô em Groovy. Tem disponíveis: http, email, sql, ficheiro, log, aviso, falhar, terminar, params
// e as variáveis do robô. As passwords nunca ficam no código: use o nome da credencial (Administração → Credenciais).

def clientes = http.get("https://dev.lusopay.com:8444/web_dev/api/users",
                        credencial: "cyclos-dev", query: [pageSize: 100])
log "Recebidos \${clientes.size()} clientes"

def linhas = clientes.collect { c -> [id: c.id, nome: c.display] }
ficheiro.csv("clientes.csv", linhas, colunas: ["id", "nome"])

// email.enviar(credencial: "smtp-lusopay", para: "eu@lusopay.com",
//              assunto: "Clientes", corpo: "Em anexo.", anexos: ["clientes.csv"])
`;
