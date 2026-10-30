"""Divide um .zip com vários robôs (ex.: a pasta Robots do servidor de bots comprimida) em robôs individuais.

Cada ficheiro .xml/.obscript na raiz é um robô; cada pasta na raiz é um projeto (OpenBots com project.obconfig, ou
pasta com um .xml do taskt e os seus ficheiros de dados). O Config.txt nunca é lido.
"""
from __future__ import annotations

import io
import zipfile

from .readers import MAX_BYTES, RobotFormatError, zip_name

SCRIPT_EXT = (".xml", ".obscript", ".json")


def split_robots(data: bytes) -> list[tuple[str, bytes]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise RobotFormatError("ficheiro .zip inválido") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > MAX_BYTES * 40:
        raise RobotFormatError("arquivo demasiado grande")
    paths = {zip_name(i).strip("/"): i for i in infos}
    # pasta raiz única (ex.: Robots/...) é retirada
    while paths and all("/" in p for p in paths) and len({p.split("/", 1)[0] for p in paths}) == 1:
        paths = {p.split("/", 1)[1]: i for p, i in paths.items()}
    if any(p.lower() == "project.obconfig" for p in paths):  # o .zip é um único projeto OpenBots
        return [("projeto.zip", data)]
    robots: list[tuple[str, bytes]] = []
    folders: dict[str, list[str]] = {}
    for p in sorted(paths):
        if "/" in p:
            folders.setdefault(p.split("/", 1)[0], []).append(p)
        elif p.lower().endswith(SCRIPT_EXT):
            robots.append((p, zf.read(paths[p])))
    for folder, members in sorted(folders.items()):
        if not any(m.lower().endswith(SCRIPT_EXT) for m in members):
            continue
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
            for m in members:
                if m.rsplit("/", 1)[-1].lower() == "config.txt":
                    continue
                out.writestr(m, zf.read(paths[m]))
        robots.append((folder + ".zip", buf.getvalue()))
    if not robots:
        raise RobotFormatError("o .zip não contém robôs (.xml, .obscript ou pastas de projeto)")
    return robots
