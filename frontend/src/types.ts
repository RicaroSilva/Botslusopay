export type Role = "viewer" | "operator" | "approver" | "admin";
export type RunStatus = "PENDING" | "WAITING_APPROVAL" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface User {
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  role: Role;
  is_active: boolean;
  auth_source: string;
  last_login_at?: string | null;
}

export interface RunBrief {
  id: string;
  bot_key: string;
  bot_name: string;
  status: RunStatus;
  trigger_source: string;
  requested_by?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  failure_reason?: string | null;
  needs_review: boolean;
}

export interface Run extends RunBrief {
  requested_by_name?: string | null;
  approved_by_name?: string | null;
  approved_at?: string | null;
  queued_at?: string | null;
  last_heartbeat_at?: string | null;
  trigger_rule_id?: string | null;
  trigger_event_id?: string | null;
  parent_run_id?: string | null;
  retry_of_run_id?: string | null;
  parameters: Record<string, unknown>;
  exit_code?: number | null;
  timeout_seconds: number;
  cancel_requested: boolean;
  result_summary: Record<string, unknown>;
  flow_version?: number | null;
  permissions?: { cancel: boolean; approve: boolean; retry: boolean };
  trigger_rule?: { id: string; name: string; type: string } | null;
  trigger_event?: { id: string; dedup_key: string; received_at: string; details: Record<string, unknown> } | null;
}

export interface ParameterDef {
  name: string;
  type: "string" | "integer" | "date" | "boolean" | "enum";
  description: string;
  required: boolean;
  default?: unknown;
  choices: string[];
  sensitive: boolean;
}

export interface Rule {
  id: string;
  bot_key: string;
  name: string;
  trigger_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
  requires_approval: boolean;
  has_secret: boolean;
  state: Record<string, unknown>;
  next_fire_at?: string | null;
  webhook_secret?: string;
  webhook_url?: string;
}

export interface Dependency {
  id: number;
  bot_key?: string;
  depends_on: string;
  condition: string;
  within_hours: number;
  enabled: boolean;
}

export interface Bot {
  key: string;
  name: string;
  description: string;
  category: string;
  risk_level: "low" | "medium" | "high";
  adapter: string;
  availability: "available" | "disabled" | "unvalidated" | "maintenance";
  enabled: boolean;
  in_registry: boolean;
  source?: "registry" | "ui";
  current_flow_version?: number | null;
  requires_approval: boolean;
  triggers_allowed: string[];
  permissions: string[];
  last_run?: RunBrief | null;
  // detalhe
  source_file?: string;
  project_ref?: string;
  execution_validated?: boolean;
  parameters?: ParameterDef[];
  prerequisites?: string[];
  external_effects?: string[];
  config_files?: string[];
  known_limitations?: string[];
  concurrency?: { policy: string; exclusive_resources: string[] };
  timeout_seconds?: number;
  success_detection?: Record<string, unknown>;
  retry?: { automatic: boolean; idempotent: boolean };
  role_permissions?: Record<string, string[]>;
  dependencies?: Dependency[];
  unmet_dependencies?: { depends_on: string; condition: string; within_hours: number }[];
  rules?: Rule[];
}

export interface Dashboard {
  bots_total: number;
  bots_available: number;
  running: number;
  queued: number;
  waiting_approval: number;
  succeeded_7d: number;
  failed_7d: number;
  needs_review: number;
  recent_failures: RunBrief[];
  recent_runs: RunBrief[];
  activity: { ts: string; actor: string; action: string; resource: string; outcome: string }[];
  workers: { name: string; last_seen_at: string | null; online: boolean }[];
}
