"""Gera o inventário detalhado em Markdown a partir do JSON de analyze_taskt.py.

Usage:
    python analyze_taskt.py "<pasta dos XML>" -o inventory.json
    python render_inventory.py inventory.json -o ../../docs/inventario-detalhado.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

STATUS = {
    "ok": "OK (produção)",
    "obsolete": "Obsoleto (old_/OLD)",
    "to_review": "REVER",
    "replaced": "Substituído por OpenBots",
    "test": "Teste",
    "unlabelled": "Sem prefixo",
}


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    out: list[str] = [
        "# Inventário detalhado dos scripts (gerado automaticamente)",
        "",
        "> Gerado por `tools/inventory/render_inventory.py`. Não editar à mão.",
        "> Os segredos encontrados são apenas **contados por tipo**; nenhum valor é reproduzido.",
        "",
    ]
    cnt = Counter(b.get("status_label") for b in data)
    out += ["| Estado | Nº |", "|---|---|"] + [f"| {STATUS.get(k, k)} | {v} |" for k, v in cnt.most_common()] + [""]
    out += [
        "| Ficheiro | Estado | Cmds ativos | Sub-scripts (Run Task) | APIs / HTTP | Email | BD | UI (Selenium/teclado) | Bloqueios interativos | Segredos (contagem) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in data:
        if "parse_error" in b:
            out.append(f"| {esc(b['file'])} | erro de parsing | | | | | | | | |")
            continue
        active = b["commands_total"] - b["commands_commented"]
        runs = sorted({Path(r.replace("\\", "/")).name for r in b["run_task"]})
        apis = b["rest_endpoints"] + [f"HTTP {u}" for u in b["http_requests"]]
        writes = [a for a in b["rest_endpoints"] if not a.startswith("GET")]
        api_txt = f"{len(apis)} ({len(writes)} escrita)" if apis else "—"
        ui = b["selenium"] + b["ui_automation"]
        blocking = []
        if b["message_boxes_without_autoclose"]:
            blocking.append(f"{b['message_boxes_without_autoclose']} MessageBox sem auto-fecho")
        if b["user_input"]:
            blocking.append(f"{b['user_input']} Prompt for Input")
        secrets = ", ".join(f"{k}: {v}" for k, v in sorted(b["secrets_found"].items())) or "—"
        out.append(
            f"| {esc(b['file'])} | {STATUS.get(b['status_label'], b['status_label'])} | {active} | "
            f"{esc(', '.join(runs)) or '—'} | {api_txt} | {'sim' if b['smtp_hosts'] else '—'} | "
            f"{b['database_connections'] or '—'} | {ui or '—'} | {'; '.join(blocking) or '—'} | {secrets} |"
        )
    out += ["", "## Endpoints por script", ""]
    for b in data:
        if b.get("rest_endpoints") or b.get("http_requests"):
            out.append(f"**{esc(b['file'])}**")
            out += [f"- `{e}`" for e in b["rest_endpoints"]]
            out += [f"- `HTTP {e}`" for e in b["http_requests"]]
            out.append("")
    out += ["## Primeiros comentários (descrição) por script", ""]
    for b in data:
        desc = [d for d in b.get("description", []) if not d.startswith("Items in this section")]
        if desc:
            out.append(f"- **{esc(b['file'])}**: {esc(' / '.join(desc))[:400]}")
    Path(args.output).write_text("\n".join(out) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
