import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, newIdempotencyKey } from "../api";
import { ErrorBox } from "../components/ui";
import type { Bot } from "../types";

/** Botão Executar + diálogo de confirmação com parâmetros, pré-requisitos e efeitos. */
export function RunButton({ bot, onDone }: { bot: Bot; onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  const runnable = bot.enabled && bot.availability === "available" && bot.in_registry;
  return (
    <>
      <button className="btn btn-primary" disabled={!runnable}
        title={runnable ? "" : "Bot indisponível (desativado, por validar ou em manutenção)"}
        onClick={() => setOpen(true)}>
        Executar
      </button>
      {open && <RunDialog botKey={bot.key} onClose={() => { setOpen(false); onDone?.(); }} />}
    </>
  );
}

function RunDialog({ botKey, onClose }: { botKey: string; onClose: () => void }) {
  const navigate = useNavigate();
  const [bot, setBot] = useState<Bot | null>(null);
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  // Uma chave por abertura do diálogo: duplo clique ou reenvio não criam duas execuções.
  const [idem] = useState(newIdempotencyKey);

  useEffect(() => {
    api.get<Bot>(`/api/bots/${botKey}`).then(setBot).catch((e) => setError(e.message));
  }, [botKey]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!bot) return;
    setBusy(true);
    setError(null);
    const parameters: Record<string, unknown> = {};
    for (const p of bot.parameters ?? []) {
      const v = values[p.name];
      if (v === undefined || v === "") continue;
      parameters[p.name] = p.type === "integer" ? Number(v) : v;
    }
    try {
      const r = await api.post<{ run_id: string }>(`/api/bots/${botKey}/run`, { parameters, idempotency_key: idem });
      navigate(`/runs/${r.run_id}`);
    } catch (err) {
      const e2 = err as ApiError;
      const unmet = (e2.details?.unmet as { depends_on: string }[] | undefined)?.map((u) => u.depends_on).join(", ");
      setError(unmet ? `${e2.message}: ${unmet}` : e2.message);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <h2>Executar: {bot?.name ?? botKey}</h2>
        {bot && (
          <>
            {!!bot.parameters?.length && (
              <fieldset>
                <legend>Parâmetros</legend>
                {bot.parameters.map((p) => (
                  <label key={p.name}>
                    {p.name}
                    {p.required && " *"} <span className="muted small">{p.description}</span>
                    {p.type === "enum" ? (
                      <select value={String(values[p.name] ?? p.default ?? "")}
                        onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}>
                        {p.choices.map((c) => <option key={c}>{c}</option>)}
                      </select>
                    ) : p.type === "boolean" ? (
                      <input type="checkbox" checked={!!values[p.name]}
                        onChange={(e) => setValues({ ...values, [p.name]: e.target.checked })} />
                    ) : (
                      <input
                        type={p.sensitive ? "password" : p.type === "date" ? "date" : p.type === "integer" ? "number" : "text"}
                        required={p.required}
                        value={String(values[p.name] ?? "")}
                        onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                      />
                    )}
                  </label>
                ))}
              </fieldset>
            )}
            {!!bot.unmet_dependencies?.length && (
              <div className="alert alert-error">
                Dependências não satisfeitas: {bot.unmet_dependencies.map((u) => u.depends_on).join(", ")}
              </div>
            )}
            {!!bot.prerequisites?.length && (
              <div>
                <h3>Pré-requisitos</h3>
                <ul>{bot.prerequisites.map((p) => <li key={p}>{p}</li>)}</ul>
              </div>
            )}
            {!!bot.external_effects?.length && (
              <div className="alert alert-warn">
                <strong>Efeitos externos</strong>
                <ul>{bot.external_effects.map((p) => <li key={p}>{p}</li>)}</ul>
              </div>
            )}
            {bot.requires_approval && (
              <p className="alert alert-info">Este bot exige aprovação de outro utilizador antes de executar.</p>
            )}
            <label className="check">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              Confirmo que verifiquei os pré-requisitos e os efeitos desta execução.
            </label>
          </>
        )}
        <ErrorBox error={error} />
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={!bot || !confirmed || busy}>
            {busy ? "A pedir…" : bot?.requires_approval ? "Pedir execução" : "Executar"}
          </button>
        </div>
      </form>
    </div>
  );
}
