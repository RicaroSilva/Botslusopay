import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api";
import { Card, Empty, ErrorBox } from "../components/ui";
import { fmtDate } from "../format";
import { useResource } from "../hooks";

interface Cred { id: string; name: string; kind: string; description: string; public_fields: Record<string, unknown>; secret_fields: string[]; updated_at: string }

const KIND_LABEL: Record<string, string> = {
  http_basic: "API — utilizador e password (Basic)",
  http_bearer: "API — token (Bearer)",
  http_header: "API — cabeçalho com chave",
  smtp: "Email (SMTP)",
  mssql: "SQL Server",
};

const FIELDS: Record<string, { name: string; label: string; secret?: boolean; type?: string; options?: string[] }[]> = {
  http_basic: [{ name: "username", label: "Utilizador" }, { name: "password", label: "Password", secret: true }],
  http_bearer: [{ name: "token", label: "Token", secret: true }],
  http_header: [{ name: "header_name", label: "Nome do cabeçalho" }, { name: "value", label: "Valor", secret: true }],
  smtp: [
    { name: "host", label: "Servidor" }, { name: "port", label: "Porta", type: "number" },
    { name: "security", label: "Segurança", options: ["starttls", "ssl", "none"] },
    { name: "username", label: "Utilizador" }, { name: "password", label: "Password", secret: true },
    { name: "from_address", label: "Remetente" },
  ],
  mssql: [
    { name: "server", label: "Servidor" }, { name: "port", label: "Porta", type: "number" },
    { name: "database", label: "Base de dados" }, { name: "username", label: "Utilizador" },
    { name: "password", label: "Password", secret: true },
  ],
};

export function Credentials() {
  const { data, reload } = useResource<Cred[]>("/api/admin/credentials");
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("http_basic");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({ port: "587", security: "starttls" });
  const [editing, setEditing] = useState<Cred | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const payload: Record<string, unknown> = {};
    for (const f of FIELDS[editing?.kind ?? kind]) {
      const v = fields[f.name];
      if (v === undefined || v === "") continue;
      payload[f.name] = f.type === "number" ? Number(v) : v;
    }
    try {
      if (editing) await api.put(`/api/admin/credentials/${editing.id}`, { description, fields: payload });
      else await api.post("/api/admin/credentials", { name, kind, description, fields: payload });
      setEditing(null); setName(""); setDescription(""); setFields({ port: "587", security: "starttls" });
      reload();
    } catch (err) { setError((err as ApiError).message); }
  }

  const activeKind = editing?.kind ?? kind;
  return (
    <>
      <Card title="Credenciais">
        <p className="muted small">
          Os segredos ficam cifrados na base de dados e nunca são mostrados nem escritos em logs. Os fluxos usam-nos pelo nome.
        </p>
        <ErrorBox error={error} />
        {data?.length ? (
          <table>
            <thead><tr><th>Nome</th><th>Tipo</th><th>Dados visíveis</th><th>Atualizada</th><th></th></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id}>
                  <td><code>{c.name}</code><br /><span className="muted small">{c.description}</span></td>
                  <td>{KIND_LABEL[c.kind] ?? c.kind}</td>
                  <td className="small">{Object.entries(c.public_fields).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}</td>
                  <td>{fmtDate(c.updated_at)}</td>
                  <td className="actions">
                    <button className="btn btn-small" onClick={() => {
                      setEditing(c); setDescription(c.description);
                      setFields(Object.fromEntries(Object.entries(c.public_fields).map(([k, v]) => [k, String(v)])));
                    }}>Alterar</button>
                    <button className="btn btn-small btn-danger" onClick={async () => {
                      if (!confirm(`Eliminar a credencial ${c.name}?`)) return;
                      try { await api.del(`/api/admin/credentials/${c.id}`); reload(); } catch (e) { setError((e as Error).message); }
                    }}>Eliminar</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>Sem credenciais.</Empty>}
      </Card>
      <Card title={editing ? `Alterar ${editing.name}` : "Nova credencial"}>
        <form className="form-grid" onSubmit={submit} autoComplete="off">
          {!editing && (
            <>
              <label>Nome *<input required pattern="[a-z0-9][a-z0-9_-]{1,79}" placeholder="ex.: cyclos-dev" value={name}
                onChange={(e) => setName(e.target.value)} /></label>
              <label>Tipo<select value={kind} onChange={(e) => setKind(e.target.value)}>
                {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            </>
          )}
          <label className="span-2">Descrição<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          {FIELDS[activeKind].map((f) => (
            <label key={f.name}>{f.label}{f.secret && (editing ? " (deixe vazio para manter)" : " *")}
              {f.options ? (
                <select value={fields[f.name] ?? f.options[0]} onChange={(e) => setFields({ ...fields, [f.name]: e.target.value })}>
                  {f.options.map((o) => <option key={o}>{o}</option>)}
                </select>
              ) : (
                <input type={f.secret ? "password" : f.type ?? "text"} autoComplete="new-password"
                  required={!!f.secret && !editing} value={fields[f.name] ?? ""}
                  onChange={(e) => setFields({ ...fields, [f.name]: e.target.value })} />
              )}
            </label>
          ))}
          <div className="actions">
            <button className="btn btn-primary">{editing ? "Gravar" : "Criar"}</button>
            {editing && <button type="button" className="btn" onClick={() => { setEditing(null); setFields({}); }}>Cancelar</button>}
          </div>
        </form>
      </Card>
    </>
  );
}
