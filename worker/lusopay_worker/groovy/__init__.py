"""Runtime dos robôs Groovy: localiza o Java e as bibliotecas do Groovy e monta o comando do anfitrião
(BmHost.groovy) com limites de memória e isolamento.

    python -m lusopay_worker.groovy setup     # descarrega o Groovy (Maven Central, SHA-256 verificado)
    python -m lusopay_worker.groovy status    # mostra o que está instalado

Configuração (opcional): WORKER_JAVA / BM_JAVA (executável java), WORKER_GROOVY_LIB / BM_GROOVY_LIB (pasta dos .jar).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GROOVY_VERSION = "4.0.24"
# SHA-256 dos jars oficiais (confirmados contra o SHA-1 publicado no Maven Central)
JARS = {
    "groovy": "38db8aa6f48b96aa11dd75745b96ab2991ddc9a09f5f3840fae704b84a588867",
    "groovy-json": "e813df50d6544b90bbdc3552105be9a69758d9134e3b6990d882f35fca3c858f",
}
MAVEN = "https://repo1.maven.org/maven2/org/apache/groovy/{a}/{v}/{a}-{v}.jar"
HOST = Path(__file__).with_name("BmHost.groovy")
MIN_JAVA, MAX_JAVA = 17, 23  # o isolamento usa o SecurityManager, removido no Java 24
JVM_MEMORY = os.environ.get("WORKER_GROOVY_MEMORY", "512m")


class GroovyUnavailable(RuntimeError):
    pass


@dataclass
class Runtime:
    java: str
    classpath: list[str]

    def command(self, mode: str, work_dir: Path) -> list[str]:
        return [
            self.java, "-Djava.security.manager=allow", f"-Xmx{JVM_MEMORY}", "-Xss4m", "-XX:+UseSerialGC",
            "-XX:TieredStopAtLevel=1", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-Dgroovy.grape.enable=false",
            f"-Djava.io.tmpdir={work_dir}", f"-Duser.home={work_dir}", f"-Dbm.host.dir={HOST.parent}",
            "-cp", os.pathsep.join(self.classpath), "groovy.ui.GroovyMain", str(HOST), mode,
        ]

    @staticmethod
    def env(work_dir: Path) -> dict[str, str]:
        """Ambiente mínimo: nada do ambiente do worker (tokens, proxies, credenciais) passa para a JVM."""
        keep = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "LANG", "TZ")
        env = {k: v for k, v in os.environ.items() if k in keep}
        env.update({"TEMP": str(work_dir), "TMP": str(work_dir), "TMPDIR": str(work_dir), "HOME": str(work_dir)})
        return env


def lib_dir() -> Path:
    v = os.environ.get("WORKER_GROOVY_LIB") or os.environ.get("BM_GROOVY_LIB")
    return Path(v) if v else Path(__file__).resolve().parents[2] / "lib" / "groovy"


def java_executable() -> str | None:
    v = os.environ.get("WORKER_JAVA") or os.environ.get("BM_JAVA")
    if v:
        return v
    home = os.environ.get("JAVA_HOME")
    if home:
        exe = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.is_file():
            return str(exe)
    return shutil.which("java")


def java_major(java: str) -> int | None:
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30,
                             env={k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"})
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out.stderr + out.stdout)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


_cache: Runtime | None = None


def runtime() -> Runtime:
    """Runtime pronto a usar, ou GroovyUnavailable com a explicação do que falta."""
    global _cache
    if _cache is not None:
        return _cache
    java = java_executable()
    if not java:
        raise GroovyUnavailable("Java não encontrado: instale o Java 21 (ex.: winget install EclipseAdoptium.Temurin.21.JRE) "
                                "ou indique o caminho em WORKER_JAVA")
    major = java_major(java)
    if major is None or not MIN_JAVA <= major <= MAX_JAVA:
        raise GroovyUnavailable(f"Java {major or '?'} em {java}: os robôs Groovy precisam do Java {MIN_JAVA}–{MAX_JAVA} "
                                "(recomendado: 21)")
    jars = [lib_dir() / f"{a}-{GROOVY_VERSION}.jar" for a in JARS]
    missing = [j.name for j in jars if not j.is_file()]
    if missing:
        raise GroovyUnavailable(f"Groovy não instalado ({', '.join(missing)} em {lib_dir()}): "
                                "corra 'python -m lusopay_worker.groovy setup'")
    _cache = Runtime(java, [str(j) for j in jars])
    return _cache


def setup(dest: Path | None = None, retries: int = 5) -> list[Path]:
    """Descarrega os jars do Groovy e verifica o SHA-256. Idempotente."""
    dest = dest or lib_dir()
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for artifact, sha in JARS.items():
        target = dest / f"{artifact}-{GROOVY_VERSION}.jar"
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha:
            out.append(target)
            continue
        url = MAVEN.format(a=artifact, v=GROOVY_VERSION)
        delay = 3.0
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - URL fixo do Maven Central
                    data = r.read()
                break
            except OSError:
                if attempt == retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        digest = hashlib.sha256(data).hexdigest()
        if digest != sha:
            raise RuntimeError(f"{url}: SHA-256 inesperado ({digest}); ficheiro rejeitado")
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        out.append(target)
    return out


def run_tool(mode: str, code: str, timeout: float = 60) -> dict[str, Any]:
    """Compila sem executar: mode 'check' (erros de sintaxe/segurança) ou 'ast' (estrutura para conversão)."""
    import tempfile

    rt = runtime()
    with tempfile.TemporaryDirectory(prefix="bm-groovy-") as tmp:
        work = Path(tmp)
        try:
            proc = subprocess.run(rt.command(mode, work), input=json.dumps({"code": code, "out_dir": str(work)}) + "\n",
                                  capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                                  env=Runtime.env(work), cwd=work)
        except subprocess.TimeoutExpired as exc:
            raise GroovyUnavailable("a análise do código Groovy excedeu o tempo limite") from exc
    for line in proc.stdout.splitlines():
        if line.startswith("@@END "):
            return json.loads(line[6:])
    err = "\n".join(l for l in proc.stderr.splitlines() if not is_jvm_noise(l))[-2000:]
    raise GroovyUnavailable(f"o anfitrião Groovy terminou sem resultado: {err or proc.returncode}")


_NOISE = ("WARNING: A terminally deprecated method", "WARNING: System::setSecurityManager",
          "WARNING: Please consider reporting", "WARNING: java.lang.System::setSecurityManager",
          "WARNING: Security Manager is deprecated", "Picked up JAVA_TOOL_OPTIONS",
          "WARNING: A command line option has enabled the Security Manager",
          "WARNING: The Security Manager is deprecated")


def is_jvm_noise(line: str) -> bool:
    return not line.strip() or line.startswith(_NOISE)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "setup":
        for p in setup():
            print(f"OK  {p}")
    try:
        rt = runtime()
        print(f"Java: {rt.java}\nGroovy {GROOVY_VERSION}: {os.pathsep.join(rt.classpath)}\nRobôs Groovy: disponíveis")
        return 0
    except GroovyUnavailable as exc:
        print(f"Robôs Groovy indisponíveis: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
