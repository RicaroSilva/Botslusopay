import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api";
import { AvailabilityBadge, Card, Empty, ErrorBox, RiskBadge } from "../components/ui";
import { TRIGGER_LABEL, fmtDate } from "../format";
import { useResource } from "../hooks";
import type { Bot, Dependency, Role, Rule, User } from "../types";

const TABS = ["Bots", "Regras de disparo", "Dependências", "Utilizadores", "Permissões", "Workers", "Configurações"] as const;
type Tab = (typeof TABS)[number];

function useAction(reload: () => void) {
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      reload();
      return true;
    } catch (e) {
      setError((e as ApiError).message);
      return false;
    }
  };
  return { error, run };
}

function BotsAdmin() {
  const { data, reload } = useResource<Bot[]>("/api/admin/bots");
  const { error, run } = useAction(reload);
  return (
    <Card title="Bots registados" actions={
      <button className="btn" onClick={() => run(() => api.post("/api/admin/registry/sync"))}>Recarregar registo</button>}>
      <p className="muted small">
        As definições técnicas (ficheiro de entrada, adaptador, timeout, permissões por função) vêm dos ficheiros YAML em
        <code> bots/registry/</code> e só mudam por revisão de código. Aqui controla-se a ativação operacional.
      </p>
      <ErrorBox error={error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Bot</th><th>Estado</th><th>Risco</th><th>Adaptador</th><th>Validado</th><th>Ações</th></tr></thead>
          <tbody>
            {(data ?? []).map((b) => (
              <tr key={b.key} className={b.in_registry ? "" : "row-muted"}>
                <td><strong>{b.name}</strong><br /><code className="small">{b.key}</code>{!b.in_registry && " (removido do registo)"}</td>
                <td><AvailabilityBadge value={b.availability} enabled={b.enabled} /></td>
                <td><RiskBadge level={b.risk_level} /></td>
                <td><code>{b.adapter}</code></td>
                <td>{b.execution_validated ? "Sim" : "Não"}</td>
                <td className="actions">
                  <button className="btn btn-small" disabled={!b.in_registry}
                    onClick={() => run(() => api.patch(`/api/admin/bots/${b.key}`, { enabled: !b.enabled }))}>
                    {b.enabled ? "Desativar" : "Ativar"}
                  </button>
                  {b.availability !== "unvalidated" && (
                    <select value={b.availability} aria-label="Disponibilidade"
                      onChange={(e) => run(() => api.patch(`/api/admin/bots/${b.key}`, { availability: e.target.value }))}>
                      <option value="available">Disponível</option>
                      <option value="maintenance">Manutenção</option>
                      <option value="disabled">Desativado</option>
                    </select>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

const RULE_TEMPLATES: Record<string, string> = {
  schedule: JSON.stringify({ cron: "0 6 * * 1-5", timezone: "Europe/Lisbon" }, null, 2),
  webhook: JSON.stringify({ description: "Processo externo concluído" }, null, 2),
  after_bot: JSON.stringify({ upstream_bot_key: "" }, null, 2),
  poll_http: JSON.stringify({ url: "https://", interval_seconds: 300, json_path: "status", equals: "done", dedup_path: "id" }, null, 2),
};

function RulesAdmin() {
  const { data: rules, reload } = useResource<Rule[]>("/api/admin/rules");
  const { data: bots } = useResource<Bot[]>("/api/admin/bots");
  const { error, run } = useAction(reload);
  const [form, setForm] = useState({ bot_key: "", name: "", trigger_type: "schedule", config: RULE_TEMPLATES.schedule, requires_approval: false });
  const [secret, setSecret] = useState<{ url: string; secret: string } | null>(null);
  const bot = bots?.find((b) => b.key === form.bot_key);

  async function create(e: FormEvent) {
    e.preventDefault();
    let config: unknown;
    try { config = JSON.parse(form.config); } catch { return run(async () => { throw new Error("Configuração JSON inválida"); }); }
    await run(async () => {
      const r = await api.post<Rule>("/api/admin/rules", { ...form, config, enabled: false });
      if (r.webhook_secret) setSecret({ url: r.webhook_url!, secret: r.webhook_secret });
    });
  }

  return (
    <>
      <Card title="Regras de disparo automático">
        <ErrorBox error={error} />
        {secret && (
          <div className="alert alert-warn">
            Segredo do webhook (mostrado uma única vez; guarde-o no sistema emissor):<br />
            URL: <code>{secret.url}</code><br />Segredo: <code>{secret.secret}</code>{" "}
            <button className="btn btn-small" onClick={() => setSecret(null)}>Fechar</button>
          </div>
        )}
        {rules?.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Regra</th><th>Bot</th><th>Tipo</th><th>Configuração</th><th>Próximo</th><th>Estado</th><th></th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}{r.requires_approval && <span className="badge">aprovação</span>}</td>
                    <td>{r.bot_key}</td>
                    <td>{TRIGGER_LABEL[r.trigger_type] ?? r.trigger_type}</td>
                    <td><code className="small">{JSON.stringify(r.config)}</code></td>
                    <td>{fmtDate(r.next_fire_at)}</td>
                    <td>{r.enabled ? "Ativa" : "Inativa"}</td>
                    <td className="actions">
                      <button className="btn btn-small" onClick={() => run(() => api.patch(`/api/admin/rules/${r.id}`, { enabled: !r.enabled }))}>
                        {r.enabled ? "Desativar" : "Ativar"}
                      </button>
                      {r.trigger_type === "webhook" && (
                        <button className="btn btn-small" onClick={() => run(async () => {
                          const s = await api.post<{ webhook_secret: string }>(`/api/admin/rules/${r.id}/rotate-secret`);
                          setSecret({ url: `/api/hooks/${r.id}`, secret: s.webhook_secret });
                        })}>Rodar segredo</button>
                      )}
                      <button className="btn btn-small btn-danger" onClick={() => confirm("Eliminar regra?") && run(() => api.del(`/api/admin/rules/${r.id}`))}>Eliminar</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>Sem regras. Nenhum bot é executado automaticamente.</Empty>}
      </Card>
      <Card title="Nova regra (criada inativa)">
        <form className="form-grid" onSubmit={create}>
          <label>Bot
            <select required value={form.bot_key} onChange={(e) => setForm({ ...form, bot_key: e.target.value })}>
              <option value="">—</option>
              {(bots ?? []).filter((b) => b.in_registry).map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
            </select>
          </label>
          <label>Nome<input required minLength={3} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>Tipo
            <select value={form.trigger_type} onChange={(e) => setForm({ ...form, trigger_type: e.target.value, config: RULE_TEMPLATES[e.target.value] })}>
              {Object.keys(RULE_TEMPLATES).map((t) => (
                <option key={t} value={t} disabled={!!bot && !bot.triggers_allowed.includes(t)}>{TRIGGER_LABEL[t]}</option>
              ))}
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={form.requires_approval} onChange={(e) => setForm({ ...form, requires_approval: e.target.checked })} />
            Exigir aprovação manual
          </label>
          <label className="span-2">Configuração (JSON)
            <textarea rows={6} value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />
          </label>
          <button className="btn btn-primary">Criar regra</button>
        </form>
      </Card>
    </>
  );
}

function DependenciesAdmin() {
  const { data, reload } = useResource<Dependency[]>("/api/admin/dependencies");
  const { data: bots } = useResource<Bot[]>("/api/admin/bots");
  const { error, run } = useAction(reload);
  const [form, setForm] = useState({ bot_key: "", depends_on: "", condition: "succeeded_within", within_hours: 24 });
  const opts = (bots ?? []).filter((b) => b.in_registry).map((b) => <option key={b.key} value={b.key}>{b.name}</option>);
  return (
    <Card title="Dependências entre processos">
      <ErrorBox error={error} />
      {data?.length ? (
        <ul>
          {data.map((d) => (
            <li key={d.id}>
              <strong>{d.bot_key}</strong> só executa se <strong>{d.depends_on}</strong> tiver concluído com sucesso{" "}
              {d.condition === "succeeded_today" ? "hoje" : `nas últimas ${d.within_hours} h`}{" "}
              <button className="btn btn-small btn-danger" onClick={() => run(() => api.del(`/api/admin/dependencies/${d.id}`))}>Remover</button>
            </li>
          ))}
        </ul>
      ) : <Empty>Sem dependências configuradas.</Empty>}
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/api/admin/dependencies", form)); }}>
        <label>Bot<select required value={form.bot_key} onChange={(e) => setForm({ ...form, bot_key: e.target.value })}><option value="">—</option>{opts}</select></label>
        <label>Depende de<select required value={form.depends_on} onChange={(e) => setForm({ ...form, depends_on: e.target.value })}><option value="">—</option>{opts}</select></label>
        <label>Condição
          <select value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
            <option value="succeeded_within">Sucesso nas últimas N horas</option>
            <option value="succeeded_today">Sucesso hoje</option>
          </select>
        </label>
        <label>Horas<input type="number" min={1} value={form.within_hours} onChange={(e) => setForm({ ...form, within_hours: Number(e.target.value) })} /></label>
        <button className="btn btn-primary">Adicionar dependência</button>
      </form>
    </Card>
  );
}

const ROLES: Role[] = ["viewer", "operator", "approver", "admin"];

function UsersAdmin() {
  const { data, reload } = useResource<User[]>("/api/admin/users");
  const { error, run } = useAction(reload);
  const [form, setForm] = useState({ username: "", display_name: "", email: "", role: "viewer" as Role, password: "" });
  return (
    <>
      <Card title="Utilizadores">
        <ErrorBox error={error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Utilizador</th><th>Nome</th><th>Função</th><th>Último acesso</th><th>Estado</th><th></th></tr></thead>
            <tbody>
              {(data ?? []).map((u) => (
                <tr key={u.id} className={u.is_active ? "" : "row-muted"}>
                  <td><code>{u.username}</code></td>
                  <td>{u.display_name}</td>
                  <td>
                    <select value={u.role} onChange={(e) => run(() => api.patch(`/api/admin/users/${u.id}`, { role: e.target.value }))}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>{fmtDate(u.last_login_at)}</td>
                  <td>{u.is_active ? "Ativo" : "Inativo"}</td>
                  <td className="actions">
                    <button className="btn btn-small" onClick={() => run(() => api.patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }))}>
                      {u.is_active ? "Desativar" : "Ativar"}
                    </button>
                    <button className="btn btn-small" onClick={() => {
                      const p = prompt("Nova password (mín. 12 caracteres):");
                      if (p) run(() => api.patch(`/api/admin/users/${u.id}`, { new_password: p }));
                    }}>Redefinir password</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Novo utilizador">
        <form className="form-grid" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/api/admin/users", { ...form, email: form.email || null })); }}>
          <label>Utilizador<input required pattern="[a-z0-9._@-]{3,}" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
          <label>Nome<input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Função<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></label>
          <label>Password inicial<input type="password" minLength={12} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          <button className="btn btn-primary">Criar</button>
        </form>
      </Card>
    </>
  );
}

function PermissionsAdmin() {
  const { data, reload } = useResource<{ id: number; username: string; bot_key: string; permission: string }[]>("/api/admin/permissions");
  const { data: users } = useResource<User[]>("/api/admin/users");
  const { data: bots } = useResource<Bot[]>("/api/admin/bots");
  const { error, run } = useAction(reload);
  const [form, setForm] = useState({ user_id: "", bot_key: "", permission: "execute" });
  return (
    <Card title="Permissões individuais por bot">
      <p className="muted small">
        As permissões por função estão no registo de cada bot. Aqui concedem-se exceções a utilizadores concretos.
      </p>
      <ErrorBox error={error} />
      {data?.length ? (
        <ul>{data.map((g) => (
          <li key={g.id}><code>{g.username}</code> → {g.permission} em <strong>{g.bot_key}</strong>{" "}
            <button className="btn btn-small btn-danger" onClick={() => run(() => api.del(`/api/admin/permissions/${g.id}`))}>Revogar</button></li>
        ))}</ul>
      ) : <Empty>Sem concessões individuais.</Empty>}
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/api/admin/permissions", form)); }}>
        <label>Utilizador<select required value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })}>
          <option value="">—</option>{(users ?? []).map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}</select></label>
        <label>Bot<select required value={form.bot_key} onChange={(e) => setForm({ ...form, bot_key: e.target.value })}>
          <option value="">—</option>{(bots ?? []).map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}</select></label>
        <label>Permissão<select value={form.permission} onChange={(e) => setForm({ ...form, permission: e.target.value })}>
          {["view", "execute", "approve", "configure"].map((p) => <option key={p}>{p}</option>)}</select></label>
        <button className="btn btn-primary">Conceder</button>
      </form>
    </Card>
  );
}

function WorkersAdmin() {
  const { data, reload } = useResource<{ id: string; name: string; is_active: boolean; capabilities: string[]; last_seen_at: string | null; version: string }[]>("/api/admin/workers", 10000);
  const { error, run } = useAction(reload);
  const [name, setName] = useState("");
  const [token, setToken] = useState<string | null>(null);
  return (
    <Card title="Workers (serviço de execução Windows)">
      <ErrorBox error={error} />
      {token && (
        <div className="alert alert-warn">
          Token do worker (mostrado uma única vez; guarde-o no ficheiro indicado em WORKER_TOKEN_FILE): <code>{token}</code>{" "}
          <button className="btn btn-small" onClick={() => setToken(null)}>Fechar</button>
        </div>
      )}
      <ul>
        {(data ?? []).map((w) => (
          <li key={w.id}>
            <strong>{w.name}</strong> — {w.capabilities.join(", ")} · visto {fmtDate(w.last_seen_at)} {w.version && `· v${w.version}`}{" "}
            {w.is_active ? "" : "(inativo) "}
            <button className="btn btn-small" onClick={() => run(() => api.patch(`/api/admin/workers/${w.id}?is_active=${!w.is_active}`, {}))}>
              {w.is_active ? "Desativar" : "Ativar"}
            </button>
          </li>
        ))}
      </ul>
      <form className="toolbar" onSubmit={(e) => { e.preventDefault(); run(async () => {
        const r = await api.post<{ token: string }>("/api/admin/workers", { name, capabilities: ["taskt_cli"] });
        setToken(r.token);
      }); }}>
        <input required placeholder="Nome (ex.: SERVIDORBOTS1)" pattern="[A-Za-z0-9._-]{3,}" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn btn-primary">Registar worker</button>
      </form>
    </Card>
  );
}

function SettingsAdmin() {
  const { data, reload } = useResource<{ editable: Record<string, unknown>; runtime: Record<string, unknown> }>("/api/admin/settings");
  const { error, run } = useAction(reload);
  if (!data) return null;
  const paused = !!data.editable.pause_automatic_triggers;
  return (
    <Card title="Configurações operacionais">
      <ErrorBox error={error} />
      <label className="check">
        <input type="checkbox" checked={paused}
          onChange={(e) => run(() => api.put("/api/admin/settings", { key: "pause_automatic_triggers", value: e.target.checked }))} />
        Pausar todos os disparos automáticos (agendamentos, webhooks, consultas)
      </label>
      <h3>Configuração do servidor (só leitura)</h3>
      <pre className="json">{JSON.stringify(data.runtime, null, 2)}</pre>
    </Card>
  );
}

export function Admin() {
  const [tab, setTab] = useState<Tab>("Bots");
  return (
    <>
      <h1>Administração</h1>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === "Bots" && <BotsAdmin />}
      {tab === "Regras de disparo" && <RulesAdmin />}
      {tab === "Dependências" && <DependenciesAdmin />}
      {tab === "Utilizadores" && <UsersAdmin />}
      {tab === "Permissões" && <PermissionsAdmin />}
      {tab === "Workers" && <WorkersAdmin />}
      {tab === "Configurações" && <SettingsAdmin />}
    </>
  );
}
