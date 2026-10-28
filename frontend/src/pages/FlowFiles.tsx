import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBox } from "../components/ui";
import { fmtDate } from "../format";

interface FlowFileRow {
  name: string; declared: boolean; exists: boolean; size_bytes: number;
  updated_at: string | null; updated_by: string | null; has_previous: boolean;
}

export function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

const fileUrl = (flowKey: string, name: string, previous = false) =>
  `/api/flows/${flowKey}/files/${encodeURIComponent(name)}${previous ? "?previous=true" : ""}`;

/** Ficheiros de controlo do fluxo (ex.: último id processado): o fluxo lê-os no início de cada execução e as
 * alterações são gravadas no fim, mesmo que a execução falhe. */
export function FlowFiles({ flowKey, names, onNamesChange, canEdit }: {
  flowKey: string; names: string[]; onNamesChange: (n: string[]) => void; canEdit: boolean;
}) {
  const [rows, setRows] = useState<FlowFileRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ name: string; text: string } | null>(null);
  const [newName, setNewName] = useState("");

  const reload = () => api.get<FlowFileRow[]>(`/api/flows/${flowKey}/files`).then(setRows).catch((e) => setError(e.message));
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [flowKey, names.join("|")]);

  const put = async (name: string, bytes: Uint8Array) => {
    setError(null);
    try {
      await api.put(`/api/flows/${flowKey}/files/${encodeURIComponent(name)}`, { content_b64: bytesToBase64(bytes) });
      await reload();
    } catch (e) { setError((e as Error).message); }
  };

  const upload = (name: string, file: File | undefined) => {
    if (!file) return;
    file.arrayBuffer().then((b) => put(name, new Uint8Array(b)));
  };

  const edit = async (name: string, exists: boolean) => {
    setError(null);
    if (!exists) { setEditing({ name, text: "" }); return; }
    const r = await fetch(fileUrl(flowKey, name), { credentials: "same-origin" });
    if (!r.ok) { setError("não foi possível ler o ficheiro"); return; }
    setEditing({ name, text: await r.text() });
  };

  const restore = async (name: string) => {
    if (!confirm(`Repor a versão anterior de "${name}"?`)) return;
    const r = await fetch(fileUrl(flowKey, name, true), { credentials: "same-origin" });
    if (!r.ok) { setError("versão anterior indisponível"); return; }
    await put(name, new Uint8Array(await r.arrayBuffer()));
  };

  const remove = async (name: string) => {
    if (!confirm(`Apagar o conteúdo guardado de "${name}"? Na próxima execução o fluxo não o vai encontrar.`)) return;
    try { await api.del(`/api/flows/${flowKey}/files/${encodeURIComponent(name)}`); await reload(); }
    catch (e) { setError((e as Error).message); }
  };

  const addName = () => {
    const n = newName.trim();
    if (n && !names.includes(n)) onNamesChange([...names, n]);
    setNewName("");
  };

  return (
    <Card title="Ficheiros persistentes (controlo)">
      <p className="muted small">
        Ficheiros que o fluxo lê e atualiza entre execuções (ex.: último id processado). Antes de cada execução são
        colocados na pasta do fluxo; no fim, as alterações são gravadas aqui, mesmo que a execução falhe a meio. Nos
        passos use só o nome do ficheiro. Novos nomes só ficam ativos depois de "Gravar nova versão".
      </p>
      <ErrorBox error={error} />
      <table>
        <thead><tr><th>Ficheiro</th><th>Tamanho</th><th>Atualizado</th><th></th></tr></thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.name}>
              <td>{f.name}{!f.declared && <span className="muted small"> (não declarado nesta versão)</span>}</td>
              <td>{f.exists ? `${f.size_bytes} bytes` : <span className="muted">sem conteúdo</span>}</td>
              <td>{f.updated_at ? `${fmtDate(f.updated_at)} · ${f.updated_by}` : "—"}</td>
              <td className="actions">
                {f.exists && <a className="btn btn-small" href={fileUrl(flowKey, f.name)} download>Descarregar</a>}
                {canEdit && (
                  <>
                    <label className="btn btn-small">Carregar
                      <input type="file" hidden onChange={(e) => { upload(f.name, e.target.files?.[0]); e.target.value = ""; }} />
                    </label>
                    <button className="btn btn-small" onClick={() => edit(f.name, f.exists)}>Editar</button>
                    {f.has_previous && <button className="btn btn-small" onClick={() => restore(f.name)}>Repor anterior</button>}
                    {f.exists && <button className="btn btn-small" onClick={() => remove(f.name)}>Apagar</button>}
                    {f.declared && (
                      <button className="btn btn-small" title="deixa de ser persistente na próxima versão"
                        onClick={() => onNamesChange(names.filter((n) => n !== f.name))}>Retirar</button>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
          {names.filter((n) => !rows.some((r) => r.name === n)).map((n) => (
            <tr key={n}><td>{n}</td><td colSpan={3} className="muted">novo — grave a versão para poder carregar o conteúdo</td></tr>
          ))}
        </tbody>
      </table>
      {canEdit && (
        <div className="actions">
          <input value={newName} placeholder="nome do ficheiro, ex.: ultimo id processado.txt" maxLength={200}
            onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addName()} />
          <button className="btn btn-small" onClick={addName}>Adicionar ficheiro</button>
        </div>
      )}
      {editing && (
        <div>
          <label>Conteúdo de {editing.name}
            <textarea className="mono" rows={8} value={editing.text}
              onChange={(e) => setEditing({ ...editing, text: e.target.value })} /></label>
          <div className="actions">
            <button className="btn btn-primary" onClick={async () => {
              await put(editing.name, new TextEncoder().encode(editing.text)); setEditing(null);
            }}>Gravar ficheiro</button>
            <button className="btn" onClick={() => setEditing(null)}>Cancelar</button>
          </div>
        </div>
      )}
    </Card>
  );
}
