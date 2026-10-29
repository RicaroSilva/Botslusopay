import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, newIdempotencyKey } from "../api";
import { useAuth, hasRole } from "../auth";
import type { CodeEditorHandle, CodeError } from "../components/CodeEditor";
import { ConvertDialog, DuplicateDialog, LANGUAGE_LABEL, type RobotLanguage } from "../components/RobotDialogs";
import { TestConsole } from "../components/TestConsole";
import { Card, ErrorBox } from "../components/ui";
import { GROOVY_API, NEW_GROOVY_ROBOT } from "../groovyApi";
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
  definition: { language?: string; description?: string; variables?: Record<string, unknown>; persistent_files?: string[];
                steps?: Step[]; code?: string } | null;
  versions: { version: number; comment: string; created_at: string; created_by: string | null }[];
}

const EMPTY_META = {
  key: "", name: "", description: "", category: "", risk_level: "low", timeout_seconds: 1800,
  triggers_allowed: ["manual"], requires_approval: false as boolean, concurrency: "single",
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

// o editor de código (CodeMirror) só é descarregado quando se abre um robô Groovy
const CodeEditor = lazy(() => import("../components/CodeEditor").then((m) => ({ default: m.CodeEditor })));

export function FlowEditor() {
  const { key } = useParams();
  const isNew = !key;
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const { user } = useAuth();
  const [meta, setMeta] = useState({ ...EMPTY_META });
  const [language, setLanguage] = useState<RobotLanguage>(search.get("tipo") === "groovy" ? "groovy" : "flow");
  const [steps, setSteps] = useState<Step[]>([]);
  const [code, setCode] = useState(search.get("tipo") === "groovy" ? NEW_GROOVY_ROBOT : "");
  const [description, setDescription] = useState("");
  // resto da definição (variáveis, ficheiros persistentes…) que o editor não mostra diretamente mas tem de manter
  const [rest, setRest] = useState<Record<string, unknown>>({});
  const [data, setData] = useState<FlowData | null>(null);
  const [credentials, setCredentials] = useState<CredentialRow[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [codeErrors, setCodeErrors] = useState<CodeError[]>([]);
  const [codeCreds, setCodeCreds] = useState<{ name: string; exists: boolean }[] | null>(null);
  const [saved, setSaved] = useState<string>("");  // estado gravado (para detetar alterações por guardar)
  const [testRun, setTestRun] = useState<string | null>(null);
  const [converting, setConverting] = useState<RobotLanguage | null>(null);
  const [duplicating, setDuplicating] = useState(false);
  const [busy, setBusy] = useState(false);
  const editor = useRef<CodeEditorHandle>(null);

  const snapshot = (m: typeof meta, def: unknown) => JSON.stringify({ m, def });

  const load = async (version?: number) => {
    if (isNew) {
      setSaved(snapshot(EMPTY_META, null));
      return;
    }
    const d = await api.get<FlowData>(`/api/flows/${key}${version ? `?version=${version}` : ""}`);
    setData(d);
    const def = d.definition ?? { steps: [] };
    const lang = (def.language as RobotLanguage) ?? "flow";
    setLanguage(lang);
    setSteps((def.steps as Step[]) ?? []);
    setCode((def.code as string) ?? "");
    setDescription(def.description ?? "");
    const { description: _d, steps: _s, code: _c, language: _l, ...others } = def;
    setRest(others);
    setCodeErrors([]);
    const b = d.bot;
    const m = {
      key: b.key, name: b.name, description: b.description, category: b.category, risk_level: b.risk_level,
      timeout_seconds: b.timeout_seconds ?? 1800, triggers_allowed: b.triggers_allowed,
      requires_approval: b.requires_approval, concurrency: b.concurrency?.policy ?? "single",
      external_effects: b.external_effects ?? [], prerequisites: b.prerequisites ?? [],
    };
    setMeta(m);
    setSaved(version && version !== d.current_version ? "" : snapshot(m, buildFrom(lang, others, def.description ?? "", (def.steps as Step[]) ?? [], (def.code as string) ?? "")));
  };

  useEffect(() => {
    load().catch((e) => setError(e.message));
    api.get<CredentialRow[]>("/api/flows/credential-names").then(setCredentials).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const definition = () => {
    if (jsonMode) return JSON.parse(jsonText);
    return buildFrom(language, rest, description, steps, code);
  };
  const currentSnapshot = (() => { try { return snapshot(meta, definition()); } catch { return "json-invalido"; } })();
  const dirty = saved !== "" ? currentSnapshot !== saved : true;

  useEffect(() => {  // aviso ao sair da página com alterações por guardar
    const h = (e: BeforeUnloadEvent) => { if (dirty && !isNew) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty, isNew]);

  const persistentNames = (rest.persistent_files as string[] | undefined) ?? [];
  const variables = (rest.variables as Record<string, unknown> | undefined) ?? {};

  async function validate(): Promise<boolean> {
    setError(null); setInfo(null);
    try {
      if (language === "groovy" && !jsonMode) {
        const r = await api.post<{ checked: boolean; reason: string; errors: CodeError[]; credentials: { name: string; exists: boolean }[] }>(
          "/api/flows/check-code", { code });
        setCodeErrors(r.errors);
        setCodeCreds(r.credentials);
        if (r.errors.length) {
          setError(`${r.errors.length} erro(s) no código: ` + r.errors.slice(0, 3).map((e) => `linha ${e.line}: ${e.message}`).join("; "));
          if (r.errors[0].line) editor.current?.gotoLine(r.errors[0].line);
          return false;
        }
        const missing = r.credentials.filter((c) => !c.exists);
        if (missing.length) { setError(`Credenciais inexistentes: ${missing.map((c) => c.name).join(", ")}`); return false; }
        setInfo(r.checked ? "Código válido (sintaxe e regras de segurança verificadas)."
          : `Estrutura válida. A sintaxe será verificada ao executar (${r.reason}).`);
        return true;
      }
      const r = await api.post<{ valid: boolean; error?: string }>("/api/flows/validate", { definition: definition() });
      if (r.valid) setInfo("Robô válido."); else setError(r.error ?? "inválido");
      return r.valid;
    } catch (e) { setError(e instanceof SyntaxError ? "JSON inválido" : (e as Error).message); return false; }
  }

  async function save(): Promise<boolean> {
    setError(null); setInfo(null); setBusy(true);
    try {
      const def = definition();
      if (isNew) {
        await api.post("/api/flows", { ...meta, definition: def, comment: comment || "versão inicial" });
        setSaved(snapshot(meta, def));
        navigate(`/flows/${meta.key}`);
      } else {
        await api.patch(`/api/flows/${key}`, { ...meta });
        const r = await api.put<{ version: number }>(`/api/flows/${key}`, { definition: def, comment });
        setInfo(`Versão ${r.version} gravada.`);
        setComment("");
        await load();
      }
      return true;
    } catch (e) {
      const msg = e instanceof SyntaxError ? "JSON inválido" : (e as ApiError).message;
      setError(msg);
      const lines = [...msg.matchAll(/linha (\d+): ([^;]+)/g)].map((m) => ({ line: Number(m[1]), message: m[2] }));
      if (language === "groovy" && lines.length) { setCodeErrors(lines); editor.current?.gotoLine(lines[0].line); }
      return false;
    } finally { setBusy(false); }
  }

  async function test() {
    if (isNew) { setError("Crie o robô antes de o testar."); return; }
    if (dirty) {
      if (!confirm("Há alterações por guardar. Gravar uma nova versão e testar?")) return;
      if (!(await save())) return;
    }
    setError(null);
    try {
      const r = await api.post<{ run_id: string }>(`/api/bots/${key}/run`, { parameters: {}, idempotency_key: newIdempotencyKey(), dry_run: true });
      setTestRun(r.run_id);
    } catch (e) { setError((e as ApiError).message); }
  }

  async function remove() {
    if (!confirm(`Eliminar o robô "${meta.name}"? Se já tiver execuções fica arquivado (escondido), para manter o histórico.`)) return;
    try { await api.del(`/api/flows/${key}`); navigate("/bots"); } catch (e) { setError((e as ApiError).message); }
  }

  const toggleJson = () => {
    if (!jsonMode) setJsonText(JSON.stringify(buildFrom(language, rest, description, steps, code), null, 2));
    else {
      try {
        const { description: d, steps: st, code: c, language: l, ...others } = JSON.parse(jsonText);
        setLanguage(l === "groovy" ? "groovy" : "flow");
        setSteps(st ?? []); setCode(c ?? ""); setDescription(d ?? ""); setRest(others);
      }
      catch { setError("JSON inválido"); return; }
    }
    setJsonMode(!jsonMode);
  };

  function applyConversion(def: Record<string, unknown>) {
    const { description: d, steps: st, code: c, language: l, ...others } = def;
    setLanguage(l === "groovy" ? "groovy" : "flow");
    setSteps((st as Step[]) ?? []);
    setCode((c as string) ?? "");
    setDescription((d as string) ?? "");
    setRest(others);
    setCodeErrors([]);
    setConverting(null);
    setComment(`convertido para ${LANGUAGE_LABEL[l === "groovy" ? "groovy" : "flow"]}`);
    setInfo("Conversão aberta no editor. Reveja e carregue em \"Gravar nova versão\"; a versão anterior continua no histórico.");
  }

  const viewingOld = data && data.version !== data.current_version;
  const isAdmin = hasRole(user, "admin");
  const other: RobotLanguage = language === "groovy" ? "flow" : "groovy";
  return (
    <>
      <div className="page-head">
        <div>
          <Link to={isNew ? "/bots" : `/bots/${key}`} className="muted">← {isNew ? "Catálogo" : "Detalhe do bot"}</Link>
          <h1>{isNew ? "Novo robô" : meta.name}</h1>
          <div className="badges">
            <span className={`badge lang-${language}`}>{LANGUAGE_LABEL[language]}</span>
            {data && <span className={`badge ${data.bot.enabled ? "status-succeeded" : "avail-disabled"}`}>{data.bot.enabled ? "Ativo" : "Desativado"}</span>}
            {data && <span className="badge">versão em uso {data.current_version}{viewingOld && ` · a ver a versão ${data.version}`}</span>}
            {dirty && !isNew && <span className="badge status-waiting_approval">● alterações por guardar</span>}
          </div>
        </div>
        <div className="actions">
          {language === "flow" && <button className="btn" onClick={toggleJson}>{jsonMode ? "Editor visual" : "Ver JSON"}</button>}
          <button className="btn" onClick={validate}>Validar</button>
          {!isNew && <button className="btn" onClick={test} title="Executa sem efeitos externos: só leituras">▶ Testar (simulação)</button>}
          <button className="btn" disabled={jsonMode} onClick={() => setConverting(other)}>Converter para {LANGUAGE_LABEL[other]}</button>
          {!isNew && isAdmin && <button className="btn" onClick={() => setDuplicating(true)}>Duplicar</button>}
          {!isNew && isAdmin && <button className="btn btn-danger" onClick={remove}>Eliminar</button>}
          <button className="btn btn-primary" disabled={busy} onClick={save}>{isNew ? "Criar robô" : "Gravar nova versão"}</button>
        </div>
      </div>
      <ErrorBox error={error} />
      {info && <div className="alert alert-info">{info}</div>}
      {testRun && <TestConsole runId={testRun} onClose={() => setTestRun(null)}
        onGotoLine={language === "groovy" ? (n) => editor.current?.gotoLine(n) : undefined} />}
      {language === "groovy" && !jsonMode ? (
        <div className="code-layout">
          <Card title="Código Groovy" actions={<span className="muted small">Ctrl+S grava · Ctrl+Espaço sugere</span>}>
            <label>Descrição<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
            <Suspense fallback={<p className="muted">A carregar o editor…</p>}>
              <CodeEditor ref={editor} value={code} errors={codeErrors} onSave={save}
                onChange={(v) => { setCode(v); if (codeErrors.length) setCodeErrors([]); }} />
            </Suspense>
            <label>Comentário da versão<input value={comment} maxLength={300} placeholder="o que mudou?"
              onChange={(e) => setComment(e.target.value)} /></label>
          </Card>
          <div>
            <Card title="Credenciais usadas">
              {codeCreds === null ? <p className="muted small">Carregue em Validar para ver as credenciais que o código usa.</p>
                : codeCreds.length ? (
                  <ul className="plain">{codeCreds.map((c) => <li key={c.name}>{c.exists ? "✅" : "❌ não existe:"} <code>{c.name}</code></li>)}</ul>
                ) : <p className="muted small">O código não usa credenciais.</p>}
              <p className="muted small">O nome da credencial tem de estar escrito no código (ex.: <code>credencial: "cyclos-producao"</code>).
                As passwords nunca ficam no código.</p>
            </Card>
            <GroovyHelp onInsert={(t) => setCode(code + (code.endsWith("\n") ? "" : "\n") + t + "\n")} />
          </div>
        </div>
      ) : (
        <Card title="Passos do fluxo" actions={<span className="muted small">
          Variáveis: <code>{"{{ resposta }}"}</code> · funções: <code>now()</code>, <code>today()</code>, <code>first_day_of_month(-1)</code> ·
          filtros: <code>date('%Y-%m-%d')</code>, <code>add_days(-1)</code>, <code>money</code>, <code>tojson</code>, <code>length</code></span>}>
          {jsonMode ? (
            <textarea className="mono" rows={30} value={jsonText} onChange={(e) => setJsonText(e.target.value)} />
          ) : (
            <>
              <label>Descrição do fluxo<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
              {!credentials.length && isAdmin && (
                <p className="alert alert-warn">Ainda não há credenciais. Crie-as em Administração → Credenciais antes de usar APIs, email ou SQL.</p>
              )}
              <StepList steps={steps} onChange={setSteps} credentials={credentials} depth={0} />
            </>
          )}
          <label>Comentário da versão<input value={comment} maxLength={300} placeholder="o que mudou?"
            onChange={(e) => setComment(e.target.value)} /></label>
        </Card>
      )}
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
              <select value={meta.risk_level} onChange={(e) => setMeta({
                ...meta, risk_level: e.target.value,
                // ao passar a risco elevado, a aprovação fica marcada (o administrador pode desmarcar)
                requires_approval: e.target.value === "high" && meta.risk_level !== "high" ? true : meta.requires_approval,
              })}>
                <option value="low">Baixo (só leitura)</option>
                <option value="medium">Médio (relatórios, emails)</option>
                <option value="high">Elevado (altera dados)</option>
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
            <label className="check"><input type="checkbox" checked={meta.requires_approval}
              disabled={meta.risk_level === "high" && !isAdmin}
              onChange={(e) => setMeta({ ...meta, requires_approval: e.target.checked })} />
              Exigir aprovação</label>
            {meta.risk_level === "high" && !meta.requires_approval && (
              <p className="alert alert-warn span-2">Robô de risco elevado sem aprovação: qualquer operador com
                permissão de execução o pode correr de imediato. Fica registado na auditoria.</p>
            )}
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
      {!jsonMode && (
        <VariablesCard value={variables} language={language}
          onChange={(v) => setRest({ ...rest, variables: v })} />
      )}
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
                  <td><button className="btn btn-small" onClick={() => {
                    if (dirty && !confirm("Há alterações por guardar que se perdem. Abrir a versão?")) return;
                    load(v.version);
                  }}>Abrir</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Abrir uma versão antiga e gravar cria uma nova versão com esse conteúdo (reverter).
            Também serve para voltar ao formato anterior depois de uma conversão.</p>
        </Card>
      )}
      {converting && (
        <ConvertDialog definition={(() => { try { return definition(); } catch { return {}; } })()} target={converting}
          onApply={applyConversion} onClose={() => setConverting(null)} />
      )}
      {duplicating && key && (
        <DuplicateDialog flowKey={key} name={meta.name} language={language} onClose={() => setDuplicating(false)} />
      )}
    </>
  );
}

function buildFrom(language: RobotLanguage, rest: Record<string, unknown>, description: string, steps: Step[], code: string) {
  const def: Record<string, unknown> = language === "groovy"
    ? { ...rest, language: "groovy", description, code }
    : { ...rest, description, steps: clean(steps) };
  if (!(def.persistent_files as string[] | undefined)?.length) delete def.persistent_files;
  return def;
}

type VarType = "texto" | "número" | "sim/não" | "JSON";
function typeOf(v: unknown): VarType {
  if (typeof v === "number") return "número";
  if (typeof v === "boolean") return "sim/não";
  if (v !== null && typeof v === "object") return "JSON";
  return "texto";
}

/** Variáveis do robô (valores iniciais, não sensíveis). Nos fluxos usam-se como {{ nome }}; no Groovy pelo nome. */
function VariablesCard({ value, language, onChange }: {
  value: Record<string, unknown>; language: RobotLanguage; onChange: (v: Record<string, unknown>) => void;
}) {
  const entries = Object.entries(value);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const set = (name: string, v: unknown) => onChange({ ...value, [name]: v });
  const convert = (raw: string, t: VarType): unknown => {
    if (t === "número") return Number(raw.replace(",", ".")) || 0;
    if (t === "sim/não") return raw === "true";
    if (t === "JSON") { try { return JSON.parse(raw); } catch { return raw; } }
    return raw;
  };
  return (
    <Card title="Variáveis e configuração">
      <p className="muted small">
        Valores iniciais usados pelo robô ({language === "groovy" ? <>no código, pelo nome: <code>email_teste</code></> : <code>{"{{ email_teste }}"}</code>}).
        Não ponha aqui passwords: use as credenciais.
      </p>
      <table>
        <thead><tr><th>Nome</th><th>Tipo</th><th>Valor</th><th></th></tr></thead>
        <tbody>
          {entries.map(([name, v]) => {
            const t = typeOf(v);
            const shown = drafts[name] ?? (t === "JSON" ? JSON.stringify(v) : String(v ?? ""));
            return (
              <tr key={name}>
                <td><code>{name}</code></td>
                <td>
                  <select value={t} onChange={(e) => set(name, convert(shown, e.target.value as VarType))}>
                    {(["texto", "número", "sim/não", "JSON"] as VarType[]).map((x) => <option key={x}>{x}</option>)}
                  </select>
                </td>
                <td>
                  {t === "sim/não" ? (
                    <select value={String(v)} onChange={(e) => set(name, e.target.value === "true")}>
                      <option value="true">sim</option><option value="false">não</option>
                    </select>
                  ) : (
                    <input className={t === "JSON" ? "mono" : ""} value={shown}
                      onChange={(e) => { setDrafts({ ...drafts, [name]: e.target.value }); set(name, convert(e.target.value, t)); }} />
                  )}
                </td>
                <td><button className="btn btn-small" onClick={() => { const { [name]: _x, ...r } = value; onChange(r); }}>Retirar</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button className="btn btn-small" onClick={() => {
        const name = prompt("Nome da variável (letras, números e _):")?.trim();
        if (!name) return;
        if (!/^[A-Za-z_À-ÿ][\wÀ-ÿ]*$/.test(name)) { alert("Nome inválido"); return; }
        if (name in value) { alert("Já existe"); return; }
        set(name, "");
      }}>+ Variável</button>
    </Card>
  );
}

/** Ajuda da API dos robôs Groovy, com exemplos para inserir no código. */
function GroovyHelp({ onInsert }: { onInsert: (text: string) => void }) {
  const groups = [...new Set(GROOVY_API.map((e) => e.group))];
  return (
    <Card title="Ajuda">
      <p className="muted small">Groovy é Java com menos código (como nos scripts do Cyclos). Clique num exemplo para o inserir no fim do código.</p>
      {groups.map((g) => (
        <details key={g} open={g === "HTTP"}>
          <summary><strong>{g}</strong></summary>
          <ul className="plain help-list">
            {GROOVY_API.filter((e) => e.group === g).map((e) => (
              <li key={e.label}>
                <button className="link-button mono" onClick={() => onInsert(e.label)}>{e.label}</button>
                <div className="muted small">{e.detail}{e.info ? ` — ${e.info}` : ""}</div>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </Card>
  );
}
