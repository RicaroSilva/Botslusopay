// Definição dos tipos de passo para o editor de fluxos (formulário).
// O backend valida sempre o fluxo completo ao gravar.

export type FieldKind =
  | "text" | "template" | "textarea" | "expr" | "number" | "bool" | "select"
  | "list" | "kv" | "columns" | "credential" | "steps" | "statuses";

export interface FieldSpec {
  name: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  options?: string[];
  credentialKinds?: string[];
  help?: string;
  placeholder?: string;
}

export interface StepSpec {
  type: string;
  label: string;
  description: string;
  fields: FieldSpec[];
  defaults: Record<string, unknown>;
}

export const STEP_SPECS: StepSpec[] = [
  {
    type: "http_request",
    label: "Pedido à API (HTTP)",
    description: "Chama uma API por HTTPS e guarda a resposta numa variável.",
    defaults: { method: "GET", url: "https://", headers: { accept: "application/json" }, expect_status: [200], response: "json", save_as: "resposta" },
    fields: [
      { name: "method", label: "Método", kind: "select", options: ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] },
      { name: "url", label: "URL", kind: "template", required: true, placeholder: "https://app.lusopay.com:8443/web/api/users/{{ id }}" },
      { name: "credential", label: "Credencial", kind: "credential", credentialKinds: ["http_basic", "http_bearer", "http_header"] },
      { name: "headers", label: "Cabeçalhos", kind: "kv", help: "Autenticação vai no campo Credencial, nunca aqui." },
      { name: "query", label: "Parâmetros do URL", kind: "kv" },
      { name: "body_json_expr", label: "Corpo JSON (expressão)", kind: "expr", placeholder: "{'id': cliente.id, 'valor': 10}" },
      { name: "body_text", label: "Corpo em texto (modelo)", kind: "textarea" },
      { name: "expect_status", label: "Estados HTTP aceites", kind: "statuses" },
      { name: "response", label: "Resposta", kind: "select", options: ["json", "text"] },
      { name: "save_as", label: "Guardar resposta em", kind: "text", placeholder: "resposta" },
      { name: "timeout_seconds", label: "Timeout (s)", kind: "number" },
      { name: "retries", label: "Repetições (só GET/HEAD)", kind: "number" },
    ],
  },
  {
    type: "set",
    label: "Definir variável",
    description: "Cria ou altera uma variável (texto com modelo, ou expressão).",
    defaults: { variable: "x", value: "" },
    fields: [
      { name: "variable", label: "Variável", kind: "text", required: true },
      { name: "value", label: "Valor (modelo de texto)", kind: "template", placeholder: "{{ now() | date('%Y-%m-%d') }}" },
      { name: "expr", label: "…ou expressão", kind: "expr", placeholder: "resposta | length" },
    ],
  },
  {
    type: "extract",
    label: "Extrair de JSON",
    description: "Extrai valores com um caminho (ex.: items[*].id).",
    defaults: { source_expr: "resposta", path: "", save_as: "valores" },
    fields: [
      { name: "source_expr", label: "Origem (expressão)", kind: "expr", required: true },
      { name: "path", label: "Caminho", kind: "text", required: true, placeholder: "items[*].id" },
      { name: "save_as", label: "Guardar em", kind: "text", required: true },
    ],
  },
  {
    type: "foreach",
    label: "Para cada elemento",
    description: "Repete os passos para cada elemento de uma lista (opcionalmente em paralelo).",
    defaults: { items_expr: "resposta", item_variable: "item", parallel: 1, steps: [] },
    fields: [
      { name: "items_expr", label: "Lista (expressão)", kind: "expr", required: true },
      { name: "item_variable", label: "Nome do elemento", kind: "text" },
      { name: "parallel", label: "Em paralelo (1–20)", kind: "number" },
      { name: "carry", label: "Variáveis que mantêm o valor depois do ciclo (só sem paralelo)", kind: "list" },
      { name: "steps", label: "Passos a repetir", kind: "steps" },
    ],
  },
  {
    type: "if",
    label: "Condição",
    description: "Executa passos diferentes conforme uma condição.",
    defaults: { condition: "", then: [], otherwise: [] },
    fields: [
      { name: "condition", label: "Condição (expressão)", kind: "expr", required: true, placeholder: "item.saldo > 0" },
      { name: "then", label: "Se verdadeira", kind: "steps" },
      { name: "otherwise", label: "Caso contrário", kind: "steps" },
    ],
  },
  {
    type: "append",
    label: "Acrescentar a lista",
    description: "Acrescenta um valor a uma lista (útil dentro de ciclos).",
    defaults: { variable: "lista", expr: "item" },
    fields: [
      { name: "variable", label: "Lista", kind: "text", required: true },
      { name: "expr", label: "Valor (expressão)", kind: "expr", required: true },
    ],
  },
  {
    type: "csv_write",
    label: "Criar ficheiro CSV",
    description: "Escreve um CSV (separador ';', compatível com Excel).",
    defaults: { file: "relatorio {{ now() | date('%Y-%m-%d') }}.csv", rows_expr: "lista", columns: [{ header: "Coluna", value: "{{ row }}" }], delimiter: ";" },
    fields: [
      { name: "file", label: "Nome do ficheiro", kind: "template", required: true },
      { name: "rows_expr", label: "Linhas (expressão que devolve lista)", kind: "expr", required: true },
      { name: "columns", label: "Colunas", kind: "columns", help: "Cada valor é um modelo com a variável 'row'." },
      { name: "delimiter", label: "Separador", kind: "select", options: [";", ",", "\t"] },
    ],
  },
  {
    type: "text_write",
    label: "Criar ficheiro de texto",
    description: "Escreve um ficheiro de texto/JSON.",
    defaults: { file: "resultado.txt", content: "" },
    fields: [
      { name: "file", label: "Nome do ficheiro", kind: "template", required: true },
      { name: "content", label: "Conteúdo (modelo)", kind: "textarea", required: true },
      { name: "append", label: "Acrescentar ao ficheiro (em vez de substituir)", kind: "bool" },
    ],
  },
  {
    type: "text_read",
    label: "Ler ficheiro",
    description: "Lê um ficheiro criado antes nesta mesma execução.",
    defaults: { file: "resultado.txt", save_as: "conteudo" },
    fields: [
      { name: "file", label: "Nome do ficheiro", kind: "template", required: true },
      { name: "save_as", label: "Guardar em", kind: "text", required: true },
      { name: "missing_ok", label: "Se não existir, fica vazio", kind: "bool" },
    ],
  },
  {
    type: "try",
    label: "Tentar / em caso de erro",
    description: "Executa os passos; se algum falhar, executa os passos de erro (mensagem em last_error).",
    defaults: { steps: [], on_error: [] },
    fields: [
      { name: "steps", label: "Tentar", kind: "steps" },
      { name: "on_error", label: "Em caso de erro", kind: "steps" },
    ],
  },
  {
    type: "break",
    label: "Sair do ciclo",
    description: "Termina o ciclo 'Para cada elemento' em que está.",
    defaults: {},
    fields: [],
  },
  {
    type: "continue",
    label: "Próximo elemento",
    description: "Salta para o próximo elemento do ciclo.",
    defaults: {},
    fields: [],
  },
  {
    type: "email",
    label: "Enviar email",
    description: "Envia um email por SMTP, com anexos produzidos pelo fluxo.",
    defaults: { credential: "", to: [""], cc: [], subject: "", body: "", attachments: [] },
    fields: [
      { name: "credential", label: "Conta SMTP", kind: "credential", credentialKinds: ["smtp"], required: true },
      { name: "to", label: "Para", kind: "list", required: true },
      { name: "cc", label: "Cc", kind: "list" },
      { name: "subject", label: "Assunto", kind: "template", required: true },
      { name: "body", label: "Mensagem", kind: "textarea", required: true },
      { name: "attachments", label: "Anexos (nomes de ficheiros criados)", kind: "list" },
    ],
  },
  {
    type: "sql_query",
    label: "Consulta SQL Server",
    description: "Executa uma consulta parametrizada (%(nome)s) e guarda as linhas.",
    defaults: { credential: "", query: "select ... where data >= %(inicio)s", params: {}, save_as: "linhas", read_only: true },
    fields: [
      { name: "credential", label: "Base de dados", kind: "credential", credentialKinds: ["mssql"], required: true },
      { name: "query", label: "Consulta", kind: "textarea", required: true, help: "Use %(nome)s para valores; nunca {{ }} na consulta." },
      { name: "params", label: "Parâmetros", kind: "kv" },
      { name: "save_as", label: "Guardar linhas em", kind: "text" },
      { name: "read_only", label: "Só leitura (recomendado)", kind: "bool" },
    ],
  },
  {
    type: "log",
    label: "Registar no log",
    description: "Escreve uma linha no log da execução.",
    defaults: { message: "", level: "INFO" },
    fields: [
      { name: "message", label: "Mensagem", kind: "template", required: true },
      { name: "level", label: "Nível", kind: "select", options: ["INFO", "WARNING", "ERROR"] },
    ],
  },
  {
    type: "stop",
    label: "Terminar com sucesso",
    description: "Termina o fluxo sem erro (ex.: sem dados para processar).",
    defaults: { message: "" },
    fields: [{ name: "message", label: "Motivo", kind: "template" }],
  },
  {
    type: "fail",
    label: "Falhar",
    description: "Termina o fluxo com erro.",
    defaults: { message: "" },
    fields: [{ name: "message", label: "Mensagem de erro", kind: "template", required: true }],
  },
];

export const SPEC_BY_TYPE = Object.fromEntries(STEP_SPECS.map((s) => [s.type, s]));

let counter = 0;
export function newStepId(type: string): string {
  counter += 1;
  return `${type.split("_")[0]}${Date.now().toString(36).slice(-4)}${counter}`;
}
