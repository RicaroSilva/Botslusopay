import { Link, useParams } from "react-router-dom";
import { AvailabilityBadge, Card, Empty, ErrorBox, KeyValue, RiskBadge, RunsTable } from "../components/ui";
import { TRIGGER_LABEL, fmtDate } from "../format";
import { useResource } from "../hooks";
import type { Bot, RunBrief } from "../types";
import { RunButton } from "./RunDialog";

function List({ items }: { items?: string[] }) {
  return items?.length ? <ul>{items.map((i) => <li key={i}>{i}</li>)}</ul> : <Empty>—</Empty>;
}

export function BotDetail() {
  const { key } = useParams();
  const { data: bot, error, reload } = useResource<Bot>(`/api/bots/${key}`, 15000);
  const { data: runs } = useResource<RunBrief[]>(`/api/bots/${key}/runs?limit=25`, 10000);
  if (error) return <ErrorBox error={error} />;
  if (!bot) return <p className="muted">A carregar…</p>;
  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/bots" className="muted">← Catálogo</Link>
          <h1>{bot.name}</h1>
          <div className="badges">
            <AvailabilityBadge value={bot.availability} enabled={bot.enabled} />
            <RiskBadge level={bot.risk_level} />
            {bot.requires_approval && <span className="badge">Exige aprovação</span>}
          </div>
        </div>
        <div className="actions">
          {bot.adapter === "flow" && bot.permissions.includes("configure") && (
            <Link className="btn" to={`/flows/${bot.key}`}>Editar fluxo</Link>
          )}
          {bot.adapter === "flow" && !bot.permissions.includes("configure") && (
            <Link className="btn" to={`/flows/${bot.key}`}>Ver fluxo</Link>
          )}
          {bot.permissions.includes("execute") && <RunButton bot={bot} onDone={reload} />}
        </div>
      </div>
      <Card title="Descrição">
        <p>{bot.description}</p>
        {bot.availability === "unvalidated" && (
          <p className="alert alert-warn">
            O mecanismo de execução deste bot ainda não foi validado no servidor de bots. Não pode ser executado pelo
            Bot Manager até a validação ser registada (ver docs/validacao-piloto.md).
          </p>
        )}
      </Card>
      <div className="grid-2">
        <Card title="Configuração de execução">
          <KeyValue
            items={[
              ["Identificador", <code>{bot.key}</code>],
              ["Adaptador", <code>{bot.adapter}</code>],
              ["Ficheiro de entrada", bot.adapter === "flow" ? `Fluxo nativo (versão ${bot.current_flow_version})` : <code>{bot.project_ref}</code>],
              ["Mecanismo validado", bot.execution_validated ? "Sim" : "Não"],
              ["Timeout", `${Math.round((bot.timeout_seconds ?? 0) / 60)} min`],
              ["Concorrência", `${bot.concurrency?.policy === "single" ? "Uma execução de cada vez" : "Paralela"}${
                bot.concurrency?.exclusive_resources.length ? ` · recursos: ${bot.concurrency.exclusive_resources.join(", ")}` : ""}`],
              ["Deteção de sucesso", <code>{String(bot.success_detection?.method)}</code>],
              ["Repetição automática", bot.retry?.automatic ? "Só se o processo não chegou a iniciar" : "Não"],
              ["Disparos permitidos", bot.triggers_allowed.map((t) => TRIGGER_LABEL[t] ?? t).join(", ")],
            ]}
          />
        </Card>
        <Card title="Parâmetros permitidos">
          {bot.parameters?.length ? (
            <table>
              <thead><tr><th>Nome</th><th>Tipo</th><th>Obrigatório</th><th>Descrição</th></tr></thead>
              <tbody>
                {bot.parameters.map((p) => (
                  <tr key={p.name}><td><code>{p.name}</code></td><td>{p.type}</td><td>{p.required ? "Sim" : "Não"}</td><td>{p.description}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>Sem parâmetros (o runtime taskt não aceita parâmetros pela linha de comandos).</Empty>
          )}
        </Card>
      </div>
      <div className="grid-2">
        <Card title="Pré-requisitos"><List items={bot.prerequisites} /></Card>
        <Card title="Efeitos externos"><List items={bot.external_effects} /></Card>
      </div>
      <div className="grid-2">
        <Card title="Limitações conhecidas"><List items={bot.known_limitations} /></Card>
        <Card title="Ficheiros de configuração"><List items={bot.config_files} /></Card>
      </div>
      <div className="grid-2">
        <Card title="Dependências">
          {bot.dependencies?.length ? (
            <ul>
              {bot.dependencies.map((d) => (
                <li key={d.id}>
                  Requer <Link to={`/bots/${d.depends_on}`}>{d.depends_on}</Link> concluído com sucesso{" "}
                  {d.condition === "succeeded_today" ? "hoje" : `nas últimas ${d.within_hours} h`}
                  {!d.enabled && " (desativada)"}
                </li>
              ))}
            </ul>
          ) : <Empty>Sem dependências.</Empty>}
          {!!bot.unmet_dependencies?.length && (
            <p className="alert alert-error">Por satisfazer: {bot.unmet_dependencies.map((u) => u.depends_on).join(", ")}</p>
          )}
        </Card>
        <Card title="Regras de disparo automático">
          {bot.rules?.length ? (
            <ul>
              {bot.rules.map((r) => (
                <li key={r.id}>
                  <strong>{r.name}</strong> — {TRIGGER_LABEL[r.trigger_type] ?? r.trigger_type}{" "}
                  {r.enabled ? <span className="badge status-succeeded">Ativa</span> : <span className="badge">Inativa</span>}
                  {r.next_fire_at && <span className="muted"> · próxima: {fmtDate(r.next_fire_at)}</span>}
                </li>
              ))}
            </ul>
          ) : <Empty>Sem regras: só execução manual.</Empty>}
        </Card>
      </div>
      <Card title="Histórico" actions={<Link to={`/runs?bot=${bot.key}`}>Ver tudo</Link>}>
        <RunsTable runs={runs ?? []} showBot={false} />
      </Card>
    </>
  );
}
