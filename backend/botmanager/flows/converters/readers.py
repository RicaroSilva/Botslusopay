"""Leitura de ficheiros de robôs.

* taskt: XML (<Script><Commands><ScriptAction>…). Os blocos (If/Loop) estão
  aninhados em <AdditionalScriptCommands>, mas a ordem do documento é a
  sequência linear Begin…End, que é o que o tradutor espera.
* OpenBots Studio: JSON com a mesma estrutura (Commands → ScriptCommand +
  AdditionalScriptCommands), herdada do taskt. Formato deduzido; **por validar
  com um projeto real**. Projetos .zip: usa o ficheiro principal indicado em
  project.obconfig ("Main") ou o primeiro .obscript/.json.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET

from .model import Command, Robot

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
META_ATTRS = {"CommandID", "CommandName", "SelectionName", "DefaultPause", "PauseBeforeExeucution",
              "CommandEnabled", "IsCommented", "LineNumber", "v_Comment", "DisplayForeColor", "CustomRendering"}
MAX_BYTES = 10 * 1024 * 1024


class RobotFormatError(ValueError):
    pass


def _decode_tag(tag: str) -> str:
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), tag.split("}")[-1])


def _xml_tables(cmd: ET.Element) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    for child in cmd:
        name = child.tag.split("}")[-1]
        rows = []
        for de in child.iter():
            if de.tag.split("}")[-1] != "DocumentElement":
                continue
            for row in de:
                rows.append({_decode_tag(c.tag): (c.text or "") for c in row})
        if rows:
            tables[name] = rows
        elif name.startswith("v_") and len(child) == 0 and (child.text or "").strip():
            tables.setdefault("_text", []).append({"name": name, "value": child.text or ""})
    return tables


def read_taskt_xml(data: bytes, name: str) -> Robot:
    try:
        root = SafeET.fromstring(data)
    except ET.ParseError as exc:
        raise RobotFormatError(f"XML inválido: {exc}") from exc
    if root.tag != "Script" or root.find("Commands") is None:
        raise RobotFormatError("não parece um script taskt (falta <Script><Commands>)")
    commands = []
    for el in root.find("Commands").iter("ScriptCommand"):
        attrs = {k: v for k, v in el.attrib.items() if k not in META_ATTRS and k != XSI_TYPE and not k.startswith("{")}
        tables = _xml_tables(el)
        for t in tables.pop("_text", []):  # elementos de texto simples (ex.: v_SeleniumElementAction)
            attrs.setdefault(t["name"], t["value"])
        commands.append(Command(
            type=el.get(XSI_TYPE) or el.get("CommandName") or "?",
            attrs=attrs, tables=tables, comment=el.get("v_Comment") or "",
            line=int(el.get("LineNumber") or 0),
            enabled=el.get("IsCommented") != "true" and el.get("CommandEnabled") != "false",
        ))
    variables = {}
    for v in root.iter("ScriptVariable"):
        variables[v.findtext("VariableName") or ""] = v.findtext("VariableValue") or ""
    return Robot(name=name, source_format="taskt", commands=commands, variables=variables, files=[name])


def _json_command(obj: dict[str, Any]) -> Command:
    ctype = obj.get("CommandName") or str(obj.get("$type", "?")).split(",")[0].split(".")[-1]
    attrs, tables = {}, {}
    for k, v in obj.items():
        if k in META_ATTRS or k.startswith("$"):
            continue
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            tables[k] = [{str(a): ("" if b is None else str(b)) for a, b in x.items()} for x in v]
        elif isinstance(v, dict) and "Rows" in v:  # DataTable serializada como objeto
            tables[k] = [{str(a): ("" if b is None else str(b)) for a, b in x.items()} for x in v["Rows"]]
        elif isinstance(v, (str, int, float, bool)):
            attrs[k] = str(v).lower() if isinstance(v, bool) else str(v)
    return Command(type=ctype, attrs=attrs, tables=tables, comment=obj.get("v_Comment") or "",
                   line=int(obj.get("LineNumber") or 0),
                   enabled=not obj.get("IsCommented", False) and obj.get("CommandEnabled", True) is not False)


def _walk_json(actions: list[Any], out: list[Command]) -> None:
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        sc = a.get("ScriptCommand") or a.get("Command")
        if isinstance(sc, dict):
            out.append(_json_command(sc))
        _walk_json(a.get("AdditionalScriptCommands") or [], out)


def read_openbots_json(data: bytes, name: str) -> Robot:
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RobotFormatError(f"JSON inválido: {exc}") from exc
    if not isinstance(doc, dict) or "Commands" not in doc:
        raise RobotFormatError("não parece um script OpenBots (falta 'Commands')")
    commands: list[Command] = []
    _walk_json(doc["Commands"], commands)
    variables = {}
    for v in doc.get("Variables") or []:
        if isinstance(v, dict) and v.get("VariableName"):
            variables[v["VariableName"]] = "" if v.get("VariableValue") is None else str(v.get("VariableValue"))
    for v in doc.get("Arguments") or []:
        if isinstance(v, dict) and v.get("ArgumentName"):
            variables[v["ArgumentName"]] = "" if v.get("ArgumentValue") is None else str(v.get("ArgumentValue"))
    robot = Robot(name=name, source_format="openbots", commands=commands, variables=variables, files=[name])
    robot.notes.append("Formato OpenBots lido por dedução (derivado do taskt); confirme o resultado com cuidado.")
    return robot


def read_zip(data: bytes, name: str) -> Robot:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise RobotFormatError("ficheiro .zip inválido") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > MAX_BYTES * 5:
        raise RobotFormatError("projeto demasiado grande")
    names = {i.filename.replace("\\", "/"): i for i in infos}
    main = None
    for n in names:
        if n.lower().endswith("project.obconfig"):
            try:
                cfg = json.loads(zf.read(names[n]).decode("utf-8-sig"))
                m = cfg.get("Main") or cfg.get("main")
                if m:
                    base = n.rsplit("/", 1)[0] + "/" if "/" in n else ""
                    main = next((k for k in names if k.endswith(base + m) or k.endswith("/" + m) or k == m), None)
            except (ValueError, AttributeError):
                pass
    if main is None:
        main = next((k for k in names if k.lower().endswith((".obscript", ".json")) and not k.lower().endswith(".obconfig")), None)
    if main is None:
        main = next((k for k in names if k.lower().endswith(".xml")), None)
    if main is None:
        raise RobotFormatError("o .zip não contém nenhum script (.obscript, .json ou .xml)")
    robot = read_robot(zf.read(names[main]), main.rsplit("/", 1)[-1])
    others = sorted(k for k in names if k != main and k.lower().endswith((".obscript", ".xml")))
    if others:
        robot.notes.append("Outros scripts no projeto (importe-os em separado se forem chamados com Run Task): "
                           + ", ".join(o.rsplit("/", 1)[-1] for o in others[:20]))
    return robot


def read_robot(data: bytes, name: str) -> Robot:
    if len(data) > MAX_BYTES * 5:
        raise RobotFormatError("ficheiro demasiado grande")
    low = name.lower()
    if low.endswith(".zip") or data[:2] == b"PK":
        return read_zip(data, name)
    head = data.lstrip(b"\xef\xbb\xbf \r\n\t")[:1]
    if low.endswith(".xml") or head == b"<":
        return read_taskt_xml(data, name)
    if low.endswith((".obscript", ".json")) or head == b"{":
        return read_openbots_json(data, name)
    raise RobotFormatError("formato não reconhecido (use .xml do taskt, .obscript/.json do OpenBots ou .zip do projeto)")
