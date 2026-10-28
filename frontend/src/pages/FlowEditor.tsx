import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { useAuth, hasRole } from "../auth";
import { Card, ErrorBox } from "../components/ui";
import { SPEC_BY_TYPE, STEP_SPECS, newStepId, type FieldSpec } from "../flowSteps";
import { fmtDate } from "../format";
import { FlowFiles } from "./FlowFiles";
import type { Bot } from "../types";

type Step = Record<string, unknown> & { id: string; type: string; name?: string };
interface CredentialRow { name: string; kind: string; description: string }
interface FlowData {
  bot: Bot;
  current_version: number | null;
  version: number | null;
  definition: { description?: string; variables?: Record<string, unknown>; persistent_files?: string[]; steps: Step[] } | null;
  versions: { version: number; comment: string; created_at: string; created_by: string | null }[];
}

const EMPTY_META = {
  key: "", name: "", description: "", category: "", risk_level: "low", timeout_seconds: 1800,
  triggers_allowed: ["manual"], requires_approval: false, concurrency: "single",
  external_effects: [] as string[], prerequisites: [] as string[],
};

/** Remove campos opcionais vazios antes de enviar (o backend valida o resto). */
function isEmpty(v: unknown): boolean {
  if (v === undefined || v === null || v === "") return true;
  if (Array.isArray(v)) return v.length === 0;
  return typeof v === "object" && Object.keys(v as object).length === 0;
}

export function clean(steps: Step[]): Step[] {
  return steps.map((s) => {
    // mantém campos que o formulário não conhece (ex.: 'carry' de fluxos importados)
    const out: Step = { ...s };
    if (!s.name) delete out.name;
    if (!s.continue_on_error) delete out.continue_on_error;
    for (const f of SPEC_BY_TYPE[s.type]?.fields ?? []) {
      let v = s[f.name];
      if (f.kind === "steps") {
        out[f.name] = clean((v as Step[]) ?? []);
        continue;
      }
      if (f.kind === "list") v = ((v as string[]) ?? []).filter((x) => x.trim() !== "");
      if (f.kind === "columns") v = ((v as { header: string }[]) ?? []).filter((c) => c.header.trim() !== "");
      if (isEmpty(v) && !f.required) {
        delete out[f.name];
        continue;
      }
      out[f.name] = v;
    }
    return out;
  });
}

function KV({ value, onChange }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  const rows = Object.entries(value ?? {});
  return (
    <div className="kv-editor">
      {rows.map(([k, v], i) => (
        <div key={i} className="kv-row">
          <input value={k} placeholder="nome" onChange={(e) => {
            const next = [...rows]; next[i] = [e.target.value, v]; onChange(Object.fromEntries(next));
          }} />
          <input value={v} placeholder="valor (aceita {{ }})" onChange={(e) => {
            const next = [...rows]; next[i] = [k, e.target.value]; onChange(Object.fromEntries(next));
          }} />
          <button type="button" className="btn btn-small" onClick={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))}>✕</button>
        </div>
      ))}
      <button type="button" className="btn btn-small" onClick={() => onChange({ ...value, "": "" })}>+ adicionar</button>
    </div>
  );
}

function ListField({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const items = value?.length ? value : [""];
  return (
    <div className="kv-editor">
      {items.map((v, i) => (
        <div key={i} className="kv-row">
          <input value={v} onChange={(e) => { const n = [...items]; n[i] = e.target.value; onChange(n); }} />
          <button type="button" className="btn btn-small" onClick={() => onChange(items.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" className="btn btn-small" onClick={() => onChange([...items, ""])}>+ adicionar</button>
    </div>
  );
}

function Field({ f, step, onChange, credentials, depth }: {
  f: FieldSpec; step: Step; onChange: (s: Step) => void; credentials: CredentialRow[]; depth: number;
}) {
  const v = step[f.name];
  const set = (val: unknown) => onChange({ ...step, [f.name]: val });
  let input;
  switch (f.kind) {
    case "textarea":
      input = <textarea rows={4} value={String(v ?? "")} onChange={(e) => set(e.target.value)} />;
      break;
    case "number":
      input = <input type="number" value={v === undefined ? "" : String(v)} onChange={(e) => set(e.target.value === "" ? undefined : Number(e.target.value))} />;
      break;
    case "bool":
      input = <input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} />;
      break;
    case "select":
      input = (
        <select value={String(v ?? f.options?.[0] ?? "")} onChange={(e) => set(e.target.value)}>
          {f.options?.map((o) => <option key={o} value={o}>{o === "\t" ? "TAB" : o}</option>)}
        </select>
      );
      break;
    case "credential":
      input = (
        <select value={String(v ?? "")} onChange={(e) => set(e.target.value)}>
          <option value="">— nenhuma —</option>
          {credentials.filter((c) => f.credentialKinds?.includes(c.kind)).map((c) => (
            <option key={c.name} value={c.name}>{c.name} ({c.kind})</option>
          ))}
        </select>
      );
      break;
    case "list":
      input = <ListField value={(v as string[]) ?? []} onChange={set} />;
      break;
    case "statuses":
      input = <input value={((v as number[]) ?? [200]).join(", ")} onChange={(e) =>
        set(e.target.value.split(/[ ,]+/).filter(Boolean).map(Number).filter((n) => !Number.isNaN(n)))} />;
      break;
    case "kv":
      input = <KV value={(v as Record<string, string>) ?? {}} onChange={set} />;
      break;
    case "columns": {
      const cols = (v as { header: string; value: string }[]) ?? [];
      input = (
        <div className="kv-editor">
          {cols.map((c, i) => (
            <div key={i} className="kv-row">
              <input value={c.header} placeholder="Cabeçalho" onChange={(e) => { const n = [...cols]; n[i] = { ...c, header: e.target.value }; set(n); }} />
              <input value={c.value} placeholder="{{ row.campo }}" onChange={(e) => { const n = [...cols]; n[i] = { ...c, value: e.target.value }; set(n); }} />
              <button type="button" className="btn btn-small" onClick={() => set(cols.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button type="button" className="btn btn-small" onClick={() => set([...cols, { header: "", value: "" }])}>+ coluna</button>
        </div>
      );
      break;
    }
    case "steps":
      input = <StepList steps={(v as Step[]) ?? []} onChange={set} credentials={credentials} depth={depth + 1} />;
      break;
    default:
      input = <input className={f.kind === "expr" ? "mono" : ""} value={String(v ?? "")} placeholder={f.placeholder}
        onChange={(e) => set(e.target.value)} />;
  }
  return (
    <label className={f.kind === "steps" ? "field-steps" : f.kind === "bool" ? "check" : ""}>
      <span>{f.label}{f.required && " *"} {f.kind === "expr" && <span className="muted small">(expressão)</span>}</span>
      {input}
      {f.help && <span className="muted small">{f.help}</span>}
    </label>
  );
}

function StepCard({ step, index, total, onChange, onMove, onRemove, credentials, depth }: {
  step: Step; index: number; total: number; onChange: (s: Step) => void; onMove: (d: number) => void;
  onRemove: () => void; credentials: CredentialRow[]; depth: number;
}) {
  const [open, setOpen] = useState(true);
  const spec = SPEC_BY_TYPE[step.type];
  return (
    <div className={`step-card depth-${depth}`}>
      <div className="step-head">
        <button type="button" className="btn btn-small" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"}</button>
        <strong>{index + 1}. {spec?.label ?? step.type}</strong>
        <input className="step-name" placeholder="nome do passo (opcional)" value={step.name ?? ""}
          onChange={(e) => onChange({ ...step, name: e.target.value })} />
        <code className="muted small">{step.id}</code>
        <span className="actions">
          <button type="button" className="btn btn-small" disabled={index === 0} onClick={() => onMove(-1)}>↑</button>
          <button type="button" className="btn btn-small" disabled={index === total - 1} onClick={() => onMove(1)}>↓</button>
          <button type="button" className="btn btn-small btn-danger" onClick={onRemove}>Remover</button>
        </span>
      </div>
      {open && (
        <div className="step-body">
          <p className="muted small">{spec?.description}</p>
          <div className="step-fields">
            {spec?.fields.map((f) => (
              <Field key={f.name} f={f} step={step} onChange={onChange} credentials={credentials} depth={depth} />
            ))}
            <label className="check">
              <input type="checkbox" checked={!!step.continue_on_error} onChange={(e) => onChange({ ...step, continue_on_error: e.target.checked })} />
              Continuar se este passo falhar
            </label>
          </div>
        </div>
      )}
    </div>
  );
}

function StepList({ steps, onChange, credentials, depth }: {
  steps: Step[]; onChange: (s: Step[]) => void; credentials: CredentialRow[]; depth: number;
}) {
  const [adding, setAdding] = useState("");
  const add = (type: string) => {
    const spec = SPEC_BY_TYPE[type];
    onChange([...steps, { id: newStepId(type), type, ...structuredClone(spec.defaults) }]);
    setAdding("");
  };
  return (
    <div className="step-list">
      {steps.map((s, i) => (
        <StepCard key={s.id} step={s} index={i} total={steps.length} credentials={credentials} depth={depth}
          onChange={(ns) => onChange(steps.map((x, j) => (j === i ? ns : x)))}
          onMove={(d) => { const n = [...steps]; [n[i], n[i + d]] = [n[i + d], n[i]]; onChange(n); }}
          onRemove={() => onChange(steps.filter((_, j) => j !== i))} />
      ))}
      <div className="add-step">
        <select value={adding} onChange={(e) => e.target.value && add(e.target.value)} aria-label="Adicionar passo">
          <option value="">+ Adicionar passo…</option>
          {STEP_SPECS.map((s) => <option key={s.type} value={s.type}>{s.label}</option>)}
        </select>
      </div>
    </div>
  );
}

export function FlowEditor() {
  const { key } = useParams();
  const isNew = !key;
  const navigate = useNavigate();
  const { user } = useAuth();
  const [meta, setMeta] = useState({ ...EMPTY_META });
  const [steps, setSteps] = useState<Step[]>([]);
  const [description, setDescription] = useState("");
  // resto da definição (variáveis, ficheiros persistentes…) que o editor visual não mostra mas tem de manter
  const [rest, setRest] = useState<Record<string, unknown>>({});
  const [data, setData] = useState<FlowData | null>(null);
  const [credentials, setCredentials] = useState<CredentialRow[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState("");

  const load = async (version?: number) => {
    if (isNew) return;
    const d = await api.get<FlowData>(`/api/flows/${key}${version ? `?version=${version}` : ""}`);
    setData(d);
    setSteps((d.definition?.steps as Step[]) ?? []);
    setDescription(d.definition?.description ?? "");
    const { description: _d, steps: _s, ...others } = d.definition ?? { steps: [] };
    setRest(others);
    const b = d.bot;
    setMeta({
      key: b.key, name: b.name, description: b.description, category: b.category, risk_level: b.risk_level,
      timeout_seconds: b.timeout_seconds ?? 1800, triggers_allowed: b.triggers_allowed,
      requires_approval: b.requires_approval, concurrency: b.concurrency?.policy ?? "single",
      external_effects: b.external_effects ?? [], prerequisites: b.prerequisites ?? [],
    });
  };

  useEffect(() => {
    load().catch((e) => setError(e.message));
    api.get<CredentialRow[]>("/api/flows/credential-names").then(setCredentials).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const definition = () => {
    if (jsonMode) return JSON.parse(jsonText);
    return buildDefinition();
  };
  const buildDefinition = () => {
    const def: Record<string, unknown> = { ...rest, description, steps: clean(steps) };
    if (!(def.persistent_files as string[] | undefined)?.length) delete def.persistent_files;
    return def;
  };
  const persistentNames = (rest.persistent_files as string[] | undefined) ?? [];

  async function validate() {
    setError(null); setInfo(null);
    try {
      const r = await api.post<{ valid: boolean; error?: string }>("/api/flows/validate", { definition: definition() });
      if (r.valid) setInfo("Fluxo válido."); else setError(r.error ?? "inválido");
    } catch (e) { setError((e as Error).message); }
  }

  async function save() {
    setError(null); setInfo(null);
    try {
      const def = definition();
      if (isNew) {
        await api.post("/api/flows", { ...meta, definition: def, comment: comment || "versão inicial" });
        navigate(`/flows/${meta.key}`);
      } else {
        await api.patch(`/api/flows/${key}`, { ...meta });
        const r = await api.put<{ version: number }>(`/api/flows/${key}`, { definition: def, comment });
        setInfo(`Versão ${r.version} gravada.`);
        setComment("");
        await load();
      }
    } catch (e) {
      setError(e instanceof SyntaxError ? "JSON inválido" : (e as ApiError).message);
    }
  }

  const toggleJson = () => {
    if (!jsonMode) setJsonText(JSON.stringify(buildDefinition(), null, 2));
    else {
      try {
        const { description: d, steps: st, ...others } = JSON.parse(jsonText);
        setSteps(st ?? []); setDescription(d ?? ""); setRest(others);
      }
      catch { setError("JSON inválido"); return; }
    }
    setJsonMode(!jsonMode);
  };

  const viewingOld = data && data.version !== data.current_version;
  return (
    <>
      <div className="page-head">
        <div>
          <Link to={isNew ? "/bots" : `/bots/${key}`} className="muted">← {isNew ? "Catálogo" : "Detalhe do bot"}</Link>
          <h1>{isNew ? "Novo fluxo" : `Editar fluxo: ${meta.name}`}</h1>
          {data && <span className="muted">Versão em uso: {data.current_version}{viewingOld && ` · a ver versão ${data.version}`}</span>}
        </div>
        <div className="actions">
          <button className="btn" onClick={toggleJson}>{jsonMode ? "Editor visual" : "Ver JSON"}</button>
          <button className="btn" onClick={validate}>Validar</button>
          <button className="btn btn-primary" onClick={save}>{isNew ? "Criar fluxo" : "Gravar nova versão"}</button>
        </div>
      </div>
      <ErrorBox error={error} />
      {info && <div className="alert alert-info">{info}</div>}
      <div className="grid-2">
        <Card title="Identificação">
          <div className="form-grid">
            <label>Chave{isNew && " *"}<input disabled={!isNew} value={meta.key} pattern="[a-z0-9][a-z0-9-]{2,79}"
              placeholder="ex.: transacoes-dev-email" onChange={(e) => setMeta({ ...meta, key: e.target.value })} /></label>
            <label>Nome *<input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></label>
            <label>Categoria<input value={meta.category} onChange={(e) => setMeta({ ...meta, category: e.target.value })} /></label>
            <label className="span-2">Descrição<textarea rows={2} value={meta.description}
              onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></label>
          </div>
        </Card>
        <Card title="Execução e controlo">
          <div className="form-grid">
            <label>Risco
              <select value={meta.risk_level} onChange={(e) => setMeta({ ...meta, risk_level: e.target.value })}>
                <option value="low">Baixo (só leitura)</option>
                <option value="medium">Médio (relatórios, emails)</option>
                <option value="high">Elevado (altera dados) — exige aprovação</option>
              </select>
            </label>
            <label>Timeout (minutos)<input type="number" min={1} value={Math.round(meta.timeout_seconds / 60)}
              onChange={(e) => setMeta({ ...meta, timeout_seconds: Number(e.target.value) * 60 })} /></label>
            <label>Concorrência
              <select value={meta.concurrency} onChange={(e) => setMeta({ ...meta, concurrency: e.target.value })}>
                <option value="single">Uma execução de cada vez</option>
                <option value="parallel">Permitir várias em simultâneo</option>
              </select>
            </label>
            <label className="check"><input type="checkbox" checked={meta.requires_approval || meta.risk_level === "high"}
              disabled={meta.risk_level === "high"} onChange={(e) => setMeta({ ...meta, requires_approval: e.target.checked })} />
              Exigir aprovação</label>
            <fieldset className="span-2">
              <legend>Disparos permitidos</legend>
              {["manual", "schedule", "webhook", "after_bot", "poll_http"].map((t) => (
                <label key={t} className="check inline">
                  <input type="checkbox" checked={meta.triggers_allowed.includes(t)} onChange={(e) => setMeta({
                    ...meta, triggers_allowed: e.target.checked ? [...meta.triggers_allowed, t] : meta.triggers_allowed.filter((x) => x !== t),
                  })} />{{ manual: "Manual", schedule: "Agendamento", webhook: "Webhook", after_bot: "Após outro bot", poll_http: "Consulta periódica" }[t]}
                </label>
              ))}
            </fieldset>
            <label className="span-2">Efeitos externos (um por linha)<textarea rows={2} value={meta.external_effects.join("\n")}
              onChange={(e) => setMeta({ ...meta, external_effects: e.target.value.split("\n").filter(Boolean) })} /></label>
          </div>
        </Card>
      </div>
      <Card title="Passos do fluxo" actions={<span className="muted small">
        Variáveis: <code>{"{{ resposta }}"}</code> · funções: <code>now()</code>, <code>today()</code>, <code>first_day_of_month(-1)</code> ·
        filtros: <code>date('%Y-%m-%d')</code>, <code>add_days(-1)</code>, <code>money</code>, <code>tojson</code>, <code>length</code></span>}>
        {jsonMode ? (
          <textarea className="mono" rows={30} value={jsonText} onChange={(e) => setJsonText(e.target.value)} />
        ) : (
          <>
            <label>Descrição do fluxo<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
            {!credentials.length && hasRole(user, "admin") && (
              <p className="alert alert-warn">Ainda não há credenciais. Crie-as em Administração → Credenciais antes de usar APIs, email ou SQL.</p>
            )}
            <StepList steps={steps} onChange={setSteps} credentials={credentials} depth={0} />
          </>
        )}
        <label>Comentário da versão<input value={comment} maxLength={300} placeholder="o que mudou?"
          onChange={(e) => setComment(e.target.value)} /></label>
      </Card>
      {!isNew && key && (
        <FlowFiles flowKey={key} names={persistentNames} canEdit={!viewingOld}
          onNamesChange={(n) => setRest({ ...rest, persistent_files: n })} />
      )}
      {data && (
        <Card title="Versões">
          <table>
            <thead><tr><th>Versão</th><th>Comentário</th><th>Autor</th><th>Data</th><th></th></tr></thead>
            <tbody>
              {data.versions.map((v) => (
                <tr key={v.version}>
                  <td>{v.version}{v.version === data.current_version && " (em uso)"}</td>
                  <td>{v.comment}</td><td>{v.created_by ?? "—"}</td><td>{fmtDate(v.created_at)}</td>
                  <td><button className="btn btn-small" onClick={() => load(v.version)}>Abrir</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Abrir uma versão antiga e gravar cria uma nova versão com esse conteúdo (reverter).</p>
        </Card>
      )}
    </>
  );
}
