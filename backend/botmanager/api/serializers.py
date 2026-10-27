from __future__ import annotations

from typing import Any

from ..models import Bot, Run, TriggerRule, User
from ..registry.loader import bot_definition


def user_out(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "role": u.role.value,
        "is_active": u.is_active,
        "auth_source": u.auth_source,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def bot_out(bot: Bot, permissions: list[str] | None = None, last_run: Run | None = None, full: bool = False) -> dict[str, Any]:
    defn = bot_definition(bot)
    out: dict[str, Any] = {
        "key": bot.key,
        "name": bot.name,
        "description": bot.description,
        "category": bot.category,
        "risk_level": bot.risk_level,
        "adapter": bot.adapter,
        "availability": bot.availability.value,
        "enabled": bot.enabled,
        "in_registry": bot.in_registry,
        "source": bot.source,
        "current_flow_version": bot.current_flow_version,
        "requires_approval": defn.requires_approval,
        "triggers_allowed": defn.triggers_allowed,
        "permissions": permissions or [],
        "last_run": run_brief(last_run) if last_run else None,
    }
    if full:
        out.update(
            {
                "source_file": defn.source_file,
                "project_ref": defn.execution.script,
                "execution_validated": defn.execution.validated,
                "parameters": [p.model_dump(mode="json") for p in defn.parameters],
                "prerequisites": defn.prerequisites,
                "external_effects": defn.external_effects,
                "config_files": defn.config_files,
                "known_limitations": defn.known_limitations,
                "concurrency": defn.concurrency.model_dump(mode="json"),
                "timeout_seconds": defn.timeout_seconds,
                "success_detection": defn.success_detection.model_dump(mode="json"),
                "retry": defn.retry.model_dump(mode="json"),
                "role_permissions": defn.permissions,
            }
        )
    return out


def _iso(d):
    return d.isoformat() if d else None


def run_brief(r: Run) -> dict[str, Any]:
    return {
        "id": r.id,
        "bot_key": r.bot.key if r.bot else None,
        "bot_name": r.bot.name if r.bot else None,
        "status": r.status.value,
        "trigger_source": r.trigger_source,
        "requested_by": r.requested_by,
        "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at),
        "failure_reason": r.failure_reason,
        "needs_review": r.needs_review,
    }


def run_out(r: Run, usernames: dict[str, str]) -> dict[str, Any]:
    out = run_brief(r)
    out.update(
        {
            "requested_by_name": usernames.get(r.requested_by or "", None),
            "approved_by_name": usernames.get(r.approved_by or "", None),
            "approved_at": _iso(r.approved_at),
            "queued_at": _iso(r.queued_at),
            "last_heartbeat_at": _iso(r.last_heartbeat_at),
            "trigger_rule_id": r.trigger_rule_id,
            "trigger_event_id": r.trigger_event_id,
            "parent_run_id": r.parent_run_id,
            "retry_of_run_id": r.retry_of_run_id,
            "parameters": r.parameters,
            "exit_code": r.exit_code,
            "timeout_seconds": r.timeout_seconds,
            "cancel_requested": r.cancel_requested,
            "result_summary": r.result_summary,
            "worker_id": r.worker_id,
            "flow_version": r.flow_version,
        }
    )
    return out


def rule_out(rule: TriggerRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "bot_key": rule.bot.key,
        "name": rule.name,
        "trigger_type": rule.trigger_type,
        "config": rule.config,
        "enabled": rule.enabled,
        "requires_approval": rule.requires_approval,
        "has_secret": bool(rule.secret),
        "state": rule.state,
        "next_fire_at": _iso(rule.next_fire_at),
        "created_at": _iso(rule.created_at),
    }
