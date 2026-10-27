import type { RunStatus } from "./types";

export const STATUS_LABEL: Record<RunStatus, string> = {
  PENDING: "Pendente",
  WAITING_APPROVAL: "A aguardar aprovação",
  QUEUED: "Em fila",
  RUNNING: "Em execução",
  SUCCEEDED: "Concluída",
  FAILED: "Falhou",
  CANCELLED: "Cancelada",
};

export const AVAILABILITY_LABEL: Record<string, string> = {
  available: "Disponível",
  disabled: "Desativado",
  unvalidated: "Por validar",
  maintenance: "Manutenção",
};

export const RISK_LABEL: Record<string, string> = { low: "Baixo", medium: "Médio", high: "Elevado" };

export const TRIGGER_LABEL: Record<string, string> = {
  manual: "Manual",
  retry: "Repetição",
  schedule: "Agendamento",
  webhook: "Webhook / evento",
  after_bot: "Após outro bot",
  poll_http: "Consulta periódica",
};

export const FAILURE_LABEL: Record<string, string> = {
  bot_reported_error: "O bot reportou erro",
  exit_code: "Código de saída inesperado",
  timeout: "Timeout",
  result_undetermined: "Resultado não confirmado",
  success_check_failed: "Validação do resultado falhou",
  worker_lost: "Worker perdido",
  worker_rejected: "Recusada pelo worker",
  launch_error: "Erro ao iniciar",
  dependency_unmet: "Dependência não satisfeita",
};

export function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "medium" });
}

export function fmtDuration(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime();
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
}
