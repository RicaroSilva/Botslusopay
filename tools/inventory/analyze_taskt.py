"""Static analyser for taskt / OpenBots-style XML scripts.

Reads every *.xml in a folder and produces an inventory (JSON) describing each
script: purpose (first comments), sub-scripts called (RunTaskCommand), external
endpoints, files read/written, interactive/UI requirements and *counts* of
secret-like values. Secret values are never printed or written.

Usage:
    python analyze_taskt.py <scripts_folder> [-o inventory.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
UI_COMMANDS = {
    "SendMouseMoveCommand", "SendKeysCommand", "SendAdvancedKeyStrokesCommand",
    "ActivateWindowCommand", "SetWindowStateCommand", "CloseWindowCommand",
}
SELENIUM_PREFIX = "SeleniumBrowser"
SECRET_ATTRS = {
    "v_SMTPPassword": "smtp_password",
    "v_ConnectionStringPassword": "db_password",
    "v_WebRequestCredentials": None,  # flag only
}
SECRET_HEADER_NAMES = {"authorization", "x-api-key", "api-key", "password", "token"}


def decode_zip_name(name: str) -> str:
    """Zip archives created without the UTF-8 flag encode chars as #Uxxxx."""
    return re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), name)


def status_from_name(name: str) -> str:
    low = name.lower()
    if low.startswith(("old_", "old ")):
        return "obsolete"
    if low.startswith("rever"):
        return "to_review"
    if low.startswith("substitu"):
        return "replaced"
    if low.startswith("teste") or low.startswith("ok teste"):
        return "test"
    if low.startswith("ok "):
        return "ok"
    return "unlabelled"


def url_summary(base: str, endpoint: str = "") -> str:
    full = (base or "") + (endpoint or "")
    full = full.split("?")[0]
    try:
        parts = urlsplit(full)
        if parts.netloc:
            return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except ValueError:
        pass
    return full


def analyse(path: Path) -> dict:
    tree = ET.parse(path)
    root = tree.getroot()
    info: dict = {
        "file": path.name,
        "status_label": status_from_name(path.name),
        "size_bytes": path.stat().st_size,
        "commands_total": 0,
        "commands_commented": 0,
        "command_types": {},
        "description": [],
        "run_task": [],
        "start_process": [],
        "rest_endpoints": set(),
        "http_requests": set(),
        "files_read": set(),
        "files_written": set(),
        "smtp_hosts": set(),
        "database_connections": 0,
        "selenium": 0,
        "ui_automation": 0,
        "message_boxes": 0,
        "message_boxes_without_autoclose": 0,
        "user_input": 0,
        "error_handling": set(),
        "stop_task": 0,
        "variables": [],
        "secrets_found": {},
    }

    def add_secret(kind: str) -> None:
        info["secrets_found"][kind] = info["secrets_found"].get(kind, 0) + 1

    for cmd in root.iter("ScriptCommand"):
        ctype = cmd.get(XSI_TYPE, "?")
        commented = cmd.get("IsCommented") == "true" or cmd.get("CommandEnabled") == "false"
        info["commands_total"] += 1
        if commented:
            info["commands_commented"] += 1
            continue
        info["command_types"][ctype] = info["command_types"].get(ctype, 0) + 1
        a = cmd.attrib
        if ctype == "CommentCommand" and len(info["description"]) < 3 and a.get("v_Comment"):
            info["description"].append(a["v_Comment"].strip()[:300])
        elif ctype == "RunTaskCommand":
            info["run_task"].append(a.get("v_taskPath", ""))
        elif ctype == "StartProcessCommand":
            info["start_process"].append(a.get("v_ProgramName", ""))
        elif ctype == "RESTCommand":
            info["rest_endpoints"].add(f'{a.get("v_APIMethodType", "?")} ' + url_summary(a.get("v_BaseURL", ""), a.get("v_APIEndPoint", "")))
            for row in cmd.iter():
                name_el = row.find("Parameter_x0020_Name")
                if name_el is None or (name_el.text or "").strip().lower() not in SECRET_HEADER_NAMES:
                    continue
                value = (row.findtext("Parameter_x0020_Value") or "").strip()
                if value.startswith("{") and value.endswith("}"):
                    add_secret("http_auth_header_from_variable")
                elif value:
                    add_secret("http_auth_header_literal")
        elif ctype == "HTTPRequestCommand":
            info["http_requests"].add(url_summary(a.get("v_WebRequestURL", "")))
        elif ctype == "ReadTextFileCommand":
            info["files_read"].add(a.get("v_FilePath", ""))
        elif ctype in ("WriteTextFileCommand",):
            info["files_written"].add(a.get("v_FilePath", ""))
        elif ctype == "SMTPSendEmailCommand":
            info["smtp_hosts"].add(a.get("v_SMTPHost", ""))
        elif ctype == "DatabaseDefineConnectionCommand":
            info["database_connections"] += 1
            if re.search(r"password\s*=\s*[^;#]", a.get("v_ConnectionString", ""), re.I):
                add_secret("db_password_in_connection_string")
            if re.search(r"(user id|uid)\s*=", a.get("v_ConnectionString", ""), re.I):
                add_secret("db_username_in_connection_string")
        elif ctype.startswith(SELENIUM_PREFIX):
            info["selenium"] += 1
            if (cmd.findtext("v_SeleniumElementAction") or "") == "Set Text" and re.search(
                r"senha|pass", a.get("v_Comment", ""), re.I
            ):
                for row in cmd.iter():
                    if row.findtext("Parameter_x0020_Name") == "Text To Set":
                        value = (row.findtext("Parameter_x0020_Value") or "").strip()
                        if value and not value.startswith("{"):
                            add_secret("password_typed_literal_in_browser")
        elif ctype in UI_COMMANDS:
            info["ui_automation"] += 1
        elif ctype == "MessageBoxCommand":
            info["message_boxes"] += 1
            if a.get("v_AutoCloseAfter", "0") in ("", "0"):
                info["message_boxes_without_autoclose"] += 1
        elif ctype == "UserInputCommand":
            info["user_input"] += 1
        elif ctype == "ErrorHandlingCommand":
            info["error_handling"].add(a.get("v_ErrorHandlingAction", ""))
        elif ctype == "StopTaskCommand":
            info["stop_task"] += 1
        for attr, kind in SECRET_ATTRS.items():
            val = a.get(attr)
            if kind and val and not val.startswith("{"):
                add_secret(kind if attr != "v_SMTPPassword" else "smtp_password_plaintext")
        for attr, val in a.items():
            if attr in SECRET_ATTRS or not val:
                continue
            if re.search(r"(bearer|basic)\s+[A-Za-z0-9+/=._-]{12,}", val, re.I):
                add_secret("inline_bearer_or_basic_token")

    for var in root.iter("ScriptVariable"):
        name = var.findtext("VariableName") or ""
        value = var.findtext("VariableValue") or ""
        info["variables"].append(name)
        if value and re.search(r"senha|pass|pwd|token|secret|key", name, re.I):
            add_secret("variable_default_value_for_secret_like_name")

    for k, v in list(info.items()):
        if isinstance(v, set):
            info[k] = sorted(x for x in v if x)
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()
    results = []
    for p in sorted(Path(args.folder).glob("*.xml")):
        try:
            results.append(analyse(p))
        except ET.ParseError as exc:
            results.append({"file": p.name, "parse_error": str(exc)})
    out = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
