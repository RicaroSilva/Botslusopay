import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBox } from "../components/ui";

interface ReportRow { level: string; line: number; command: string; message: string }
interface Conversion {
  name: string; key: string; source_format: string; risk_level: string;
  definition: Record<string, unknown>; report: ReportRow[]; stats: Record<string, number>;
  credentials: { name: string; kind: string; exists: boolean }[]; notes: string[];
  valid: boolean; validation_error: string | null; key_taken: boolean;
  data_files: { name: string; size: number; content_b64: string }[];
}
interface BatchRow {
  file: string; key?: string; name?: string; status: string; stats?: Record<string, number>; version?: number;
  missing_credentials?: string[]; error?: string; persistent_files?: string[]; files_loaded?: string[];
}
const BATCH_STATUS: Record<string, string> = {
  criado: "✅ criado", nova_versao: "✅ nova versão", faltam_credenciais: "⚠️ faltam credenciais", erro: "❌ erro",
};

const LEVEL_LABEL: Record<string, string> = {
  convertido: "Convertido", aproximado: "Aproximado — rever", ignorado: "Ignorado (não necessário)",
  nao_convertivel: "Não convertível", info: "Informação",
};
const KIND_LABEL: Record<string, string> = { http_basic: "API (Basic)", smtp: "Email (SMTP)", mssql: "SQL Server" };

function toBase64(buf: ArrayBuffer): string {
  let bin = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function ImportRobot() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [testEmail, setTestEmail] = useState(user?.email ?? "");
  const [conv, setConv] = useState<Conversion | null>(null);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("problemas");
  const [approval, setApproval] = useState(false);

  async function convert() {
    if (!file) return;
    setBusy(true); setError(null); setConv(null);
    try {
      const r = await api.post<Conversion>("/api/flows/convert", {
        filename: file.name, content_b64: toBase64(await file.arrayBuffer()), test_email: testEmail,
      });
      setConv(r); setKey(r.key); setName(r.name); setApproval(r.risk_level === "high");
    } catch (e) { setError((e as ApiError).message); }
    finally { setBusy(false); }
  }

  async function create() {
    if (!conv) return;
    setBusy(true); setError(null);
    const problems = conv.report.filter((r) => r.level === "nao_convertivel" || r.level === "aproximado");
    try {
      await api.post("/api/flows/import", {
        key, name, category: "Importado", risk_level: conv.risk_level, requires_approval: approval, timeout_seconds: 7200,
        description: `Convertido automaticamente de ${file?.name} (${conv.source_format}). Rever antes de usar.`,
        source_bot: file?.name ?? "", definition: conv.definition,
        persistent_contents: Object.fromEntries(conv.data_files.map((f) => [f.name, f.content_b64])),
        migration_notes: [
          `Conversão: ${conv.stats.convertido ?? 0} convertidos, ${conv.stats.aproximado ?? 0} aproximados, ${conv.stats.nao_convertivel ?? 0} não convertíveis.`,
          ...problems.slice(0, 20).map((r) => `Linha ${r.line} (${r.command}): ${r.message}`),
        ],
      });
      navigate(`/flows/${key}`);
    } catch (e) { setError((e as ApiError).message); setBusy(false); }
  }

  const missing = conv?.credentials.filter((c) => !c.exists) ?? [];
  const rows = (conv?.report ?? []).filter((r) =>
    filter === "todos" ? true : filter === "problemas" ? ["nao_convertivel", "aproximado", "info"].includes(r.level) : r.level === filter);

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/bots" className="muted">← Catálogo</Link>
          <h1>Importar robô do taskt ou OpenBots</h1>
        </div>
      </div>
      <Card title="1. Escolher o ficheiro">
        <p className="muted small">
          Aceita scripts do taskt (<code>.xml</code>), scripts do OpenBots (<code>.obscript</code>/<code>.json</code>) ou um
          projeto OpenBots em <code>.zip</code>. Nada é gravado até carregar em "Criar fluxo". As passwords e chaves que
          estejam no robô <strong>não são copiadas</strong>: são substituídas por credenciais do cofre.
        </p>
        <div className="form-grid">
          <label>Ficheiro
            <input type="file" accept=".xml,.obscript,.json,.zip" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setConv(null); }} />
          </label>
          <label>Email para testes
            <input type="email" value={testEmail} placeholder="vazio = destinatários originais"
              onChange={(e) => setTestEmail(e.target.value)} />
            <span className="muted small">Enquanto testa, todos os emails do fluxo vão para este endereço.</span>
          </label>
          <button className="btn btn-primary" disabled={!file || busy} onClick={convert}>{busy ? "A converter…" : "Converter"}</button>
        </div>
      </Card>
      <BatchImport testEmail={testEmail} />
      <ErrorBox error={error} />
      {conv && (
        <>
          <Card title="2. Resultado da conversão">
            <div className="badges">
              <span className="badge status-succeeded">{conv.stats.convertido ?? 0} convertidos</span>
              <span className="badge status-waiting_approval">{conv.stats.aproximado ?? 0} aproximados</span>
              <span className="badge status-failed">{conv.stats.nao_convertivel ?? 0} não convertíveis</span>
              <span className="badge">{conv.stats.ignorado ?? 0} ignorados</span>
              <span className="badge">origem: {conv.source_format}</span>
              <span className={`badge risk-${conv.risk_level}`}>risco {conv.risk_level}</span>
            </div>
            {(conv.stats.nao_convertivel ?? 0) > 0 && (
              <p className="alert alert-warn">
                Os comandos não convertíveis (browser, teclado, programas do Windows, sub-robôs, http sem TLS…) ficaram como
                passos <strong>"Falhar"</strong> no sítio onde estavam: o fluxo pára aí até os substituir no editor.
              </p>
            )}
            {!conv.valid && <p className="alert alert-error">Estrutura inválida: {conv.validation_error}</p>}
            {conv.notes.map((n) => <p key={n} className="alert alert-info">{n}</p>)}
            {conv.data_files.length > 0 && (
              <p className="alert alert-info">
                Ficheiros de controlo/dados encontrados no projeto, carregados como ficheiros persistentes ao criar o fluxo:{" "}
                {conv.data_files.map((f) => `${f.name} (${f.size} bytes)`).join(", ")}.
              </p>
            )}
            <h3>Credenciais necessárias</h3>
            {conv.credentials.length ? (
              <ul>
                {conv.credentials.map((c) => (
                  <li key={c.name}>
                    {c.exists ? "✅" : "❌"} <code>{c.name}</code> — {KIND_LABEL[c.kind] ?? c.kind}
                    {!c.exists && <span className="muted"> (criar em Administração → Credenciais com este nome)</span>}
                  </li>
                ))}
              </ul>
            ) : <p className="muted">Nenhuma.</p>}
            <h3>Relatório</h3>
            <div className="toolbar">
              <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filtro">
                <option value="problemas">Só o que precisa de atenção</option>
                <option value="todos">Tudo</option>
                {Object.entries(LEVEL_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Linha</th><th>Comando</th><th>Resultado</th><th>Detalhe</th></tr></thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className={r.level === "nao_convertivel" ? "row-bad" : ""}>
                      <td>{r.line || "—"}</td><td><code className="small">{r.command || "—"}</code></td>
                      <td>{LEVEL_LABEL[r.level] ?? r.level}</td><td>{r.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="3. Criar o fluxo">
            <div className="form-grid">
              <label>Chave<input value={key} pattern="[a-z0-9][a-z0-9-]{2,79}" onChange={(e) => setKey(e.target.value)} /></label>
              <label>Nome<input value={name} onChange={(e) => setName(e.target.value)} /></label>
            </div>
            <label className="check"><input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} />
              Exigir aprovação antes de cada execução (outra pessoa tem de aprovar)</label>
            {conv.risk_level === "high" && !approval && (
              <p className="alert alert-warn">Este robô altera dados em sistemas externos e vai correr sem aprovação.</p>
            )}
            {conv.key_taken && key === conv.key && (
              <p className="alert alert-warn">Já existe um fluxo com esta chave: será gravada uma nova versão dele.</p>
            )}
            {missing.length > 0 && (
              <p className="alert alert-error">
                Crie primeiro as credenciais em falta ({missing.map((m) => m.name).join(", ")}) em{" "}
                <Link to="/admin">Administração → Credenciais</Link> e volte a carregar em Converter.
              </p>
            )}
            <button className="btn btn-primary" disabled={busy || !conv.valid || missing.length > 0} onClick={create}>
              Criar fluxo (fica desativado)
            </button>
          </Card>
        </>
      )}
    </>
  );
}

/** Vários robôs de uma vez: um .zip com a pasta dos robôs (cada .xml e cada pasta de projeto é um robô). */
function BatchImport({ testEmail }: { testEmail: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [approval, setApproval] = useState(true);
  const [rows, setRows] = useState<BatchRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!file) return;
    setBusy(true); setError(null); setRows(null);
    try {
      setRows(await api.post<BatchRow[]>("/api/flows/import-batch", {
        content_b64: toBase64(await file.arrayBuffer()), test_email: testEmail, approval_for_high_risk: approval,
      }));
    } catch (e) { setError((e as ApiError).message); }
    finally { setBusy(false); }
  }

  const missing = [...new Set((rows ?? []).flatMap((r) => r.missing_credentials ?? []))];
  return (
    <Card title="Importar vários robôs de uma vez">
      <p className="muted small">
        Comprima a pasta dos robôs em <code>.zip</code> (no Windows: botão direito → Enviar para → Pasta comprimida).
        Cada <code>.xml</code> e cada pasta de projeto passa a um fluxo <strong>desativado</strong>; os ficheiros de
        controlo que estiverem nas pastas são carregados como ficheiros persistentes. O <code>Config.txt</code> nunca é
        lido. Pode repetir: os fluxos que já existem recebem uma nova versão e os ficheiros persistentes não são substituídos.
      </p>
      <div className="form-grid">
        <label>Ficheiro .zip<input type="file" accept=".zip" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRows(null); }} /></label>
        <label className="check"><input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} />
          Exigir aprovação nos robôs de risco elevado</label>
        <button className="btn btn-primary" disabled={!file || busy} onClick={run}>{busy ? "A importar…" : "Converter e importar todos"}</button>
      </div>
      <ErrorBox error={error} />
      {missing.length > 0 && (
        <p className="alert alert-warn">
          Crie estas credenciais em <Link to="/admin">Administração → Credenciais</Link> e importe de novo o mesmo .zip:{" "}
          {missing.map((m) => <code key={m}>{m} </code>)}
        </p>
      )}
      {rows && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Robô</th><th>Resultado</th><th>Conversão</th><th>Ficheiros persistentes</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.file} className={r.status === "erro" ? "row-bad" : ""}>
                  <td>{r.key && ["criado", "nova_versao"].includes(r.status) ? <Link to={`/flows/${r.key}`}>{r.name}</Link> : (r.name ?? r.file)}</td>
                  <td>{BATCH_STATUS[r.status] ?? r.status}{r.error && <div className="muted small">{r.error}</div>}
                    {r.missing_credentials && <div className="muted small">{r.missing_credentials.join(", ")}</div>}</td>
                  <td className="small">{r.stats ? `${r.stats.convertido ?? 0} conv. · ${r.stats.aproximado ?? 0} aprox. · ${r.stats.nao_convertivel ?? 0} não conv.` : "—"}</td>
                  <td className="small">{(r.persistent_files ?? []).length
                    ? `${r.persistent_files!.length} (${(r.files_loaded ?? []).length} carregados do projeto)` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
