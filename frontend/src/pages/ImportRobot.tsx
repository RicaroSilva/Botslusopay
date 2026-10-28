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
}

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

  async function convert() {
    if (!file) return;
    setBusy(true); setError(null); setConv(null);
    try {
      const r = await api.post<Conversion>("/api/flows/convert", {
        filename: file.name, content_b64: toBase64(await file.arrayBuffer()), test_email: testEmail,
      });
      setConv(r); setKey(r.key); setName(r.name);
    } catch (e) { setError((e as ApiError).message); }
    finally { setBusy(false); }
  }

  async function create() {
    if (!conv) return;
    setBusy(true); setError(null);
    const problems = conv.report.filter((r) => r.level === "nao_convertivel" || r.level === "aproximado");
    try {
      await api.post("/api/flows/import", {
        key, name, category: "Importado", risk_level: conv.risk_level, timeout_seconds: 7200,
        description: `Convertido automaticamente de ${file?.name} (${conv.source_format}). Rever antes de usar.`,
        source_bot: file?.name ?? "", definition: conv.definition,
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
