import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { ErrorBox } from "./ui";

export type RobotLanguage = "flow" | "groovy";
export const LANGUAGE_LABEL: Record<RobotLanguage, string> = { flow: "Fluxo visual", groovy: "Java/Groovy" };

interface ReportItem { level: string; where: string; message: string }
interface TransformResult { definition: Record<string, unknown>; report: ReportItem[]; complete: boolean }

/** Escolha do método ao criar um robô novo. */
export function NewRobotDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Novo robô">
      <div className="modal">
        <h2>Novo robô</h2>
        <p className="muted">Escolha como quer criar o robô. Pode converter entre os dois formatos mais tarde.</p>
        <div className="choice-grid">
          <button className="choice" onClick={() => navigate("/flows/new?tipo=flow")}>
            <span className="choice-icon" aria-hidden>▦</span>
            <strong>Criar robô por fluxo</strong>
            <span className="muted">Passos visuais (pedidos à API, condições, ciclos, email, SQL). Não é preciso programar.</span>
          </button>
          <button className="choice" onClick={() => navigate("/flows/new?tipo=groovy")}>
            <span className="choice-icon" aria-hidden>{"{ }"}</span>
            <strong>Criar robô por Java/Groovy</strong>
            <span className="muted">Código Groovy (como os scripts do Cyclos), com ajuda, verificação de erros e testes.</span>
          </button>
        </div>
        <div className="modal-actions"><button className="btn" onClick={onClose}>Cancelar</button></div>
      </div>
    </div>
  );
}

function Report({ items }: { items: ReportItem[] }) {
  if (!items.length) return <p className="alert alert-info">Conversão completa, sem avisos.</p>;
  return (
    <ul className="plain report-list">
      {items.map((r, i) => (
        <li key={i} className={`report-${r.level}`}>
          <span className={`badge ${r.level === "erro" ? "status-failed" : r.level === "aviso" ? "status-waiting_approval" : ""}`}>
            {r.level === "erro" ? "sem equivalente" : r.level}
          </span>{" "}
          {r.where && <code className="small">{r.where}</code>} {r.message}
        </li>
      ))}
    </ul>
  );
}

/** Converte a definição que está no editor (mesmo por gravar) e devolve-a para revisão; nada é gravado. */
export function ConvertDialog({ definition, target, onApply, onClose }: {
  definition: Record<string, unknown>; target: RobotLanguage;
  onApply: (definition: Record<string, unknown>, report: ReportItem[]) => void; onClose: () => void;
}) {
  const [result, setResult] = useState<TransformResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(force: boolean) {
    setBusy(true); setError(null);
    try {
      setResult(await api.post<TransformResult>("/api/flows/transform", { definition, target, force }));
    } catch (e) { setError((e as ApiError).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Converter">
      <div className="modal modal-wide">
        <h2>Converter para {LANGUAGE_LABEL[target]}</h2>
        <p className="muted">
          A conversão mantém a lógica, as condições, as variáveis e a ordem dos passos sempre que possível. O resultado
          abre no editor para rever; só fica gravado quando carregar em "Gravar nova versão". A versão atual continua no
          histórico de versões.
        </p>
        <ErrorBox error={error} />
        {!result && <button className="btn btn-primary" disabled={busy} onClick={() => run(false)}>{busy ? "A converter…" : "Converter"}</button>}
        {result && (
          <>
            <Report items={result.report} />
            {!result.complete && (
              <p className="alert alert-warn">
                Há partes sem equivalente em {LANGUAGE_LABEL[target]}. Se continuar, essas partes ficam como passos
                "Falhar" com o código original na mensagem, para as reescrever; nada é apagado em silêncio.
              </p>
            )}
          </>
        )}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Cancelar</button>
          {result && !result.complete && (
            <button className="btn" disabled={busy} onClick={async () => {
              setBusy(true); setError(null);
              try {
                const r = await api.post<TransformResult>("/api/flows/transform", { definition, target, force: true });
                onApply(r.definition, r.report);
              } catch (e) { setError((e as ApiError).message); setBusy(false); }
            }}>{busy ? "A converter…" : "Converter mesmo assim"}</button>
          )}
          {result?.complete && <button className="btn btn-primary" onClick={() => onApply(result.definition, result.report)}>Abrir no editor</button>}
        </div>
      </div>
    </div>
  );
}

/** Duplica a versão em uso para um robô novo (desativado), opcionalmente noutro formato. */
export function DuplicateDialog({ flowKey, name, language, onClose }: {
  flowKey: string; name: string; language: RobotLanguage; onClose: () => void;
}) {
  const navigate = useNavigate();
  const [key, setKey] = useState(`${flowKey}-copia`.slice(0, 80));
  const [newName, setNewName] = useState(`${name} (cópia)`);
  const [target, setTarget] = useState<RobotLanguage>(language);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportItem[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(force: boolean) {
    setBusy(true); setError(null);
    try {
      await api.post(`/api/flows/${flowKey}/duplicate`, { key, name: newName, target: target === language ? null : target, force });
      onClose();
      navigate(`/flows/${key}`);
    } catch (e) {
      const err = e as ApiError;
      const rep = (err.details as { report?: ReportItem[] } | undefined)?.report;
      if (rep) setReport(rep);
      try { const d = JSON.parse(err.message); if (d.report) setReport(d.report); setError(d.message ?? err.message); }
      catch { setError(err.message); }
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Duplicar">
      <div className="modal">
        <h2>Duplicar robô</h2>
        <div className="form-grid">
          <label>Chave do novo robô<input value={key} pattern="[a-z0-9][a-z0-9-]{2,79}" onChange={(e) => setKey(e.target.value)} /></label>
          <label>Nome<input value={newName} onChange={(e) => setNewName(e.target.value)} /></label>
          <label>Formato
            <select value={target} onChange={(e) => setTarget(e.target.value as RobotLanguage)}>
              <option value="flow">{LANGUAGE_LABEL.flow}{language === "flow" ? " (o mesmo)" : " (converter)"}</option>
              <option value="groovy">{LANGUAGE_LABEL.groovy}{language === "groovy" ? " (o mesmo)" : " (converter)"}</option>
            </select>
          </label>
        </div>
        <p className="muted small">O novo robô fica desativado. Os ficheiros persistentes não são copiados.</p>
        <ErrorBox error={error} />
        {report && <Report items={report} />}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Cancelar</button>
          {report && <button className="btn" disabled={busy} onClick={() => submit(true)}>Duplicar mesmo assim</button>}
          <button className="btn btn-primary" disabled={busy} onClick={() => submit(false)}>Duplicar</button>
        </div>
      </div>
    </div>
  );
}
