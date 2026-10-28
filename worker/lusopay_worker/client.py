"""Cliente HTTP para a API /api/worker do backend."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import VERSION, WorkerConfig

log = logging.getLogger("lusopay_worker.client")


class BackendClient:
    def __init__(self, cfg: WorkerConfig, transport: httpx.BaseTransport | None = None,
                 http: httpx.Client | None = None):
        self.cfg = cfg
        self.http = http or httpx.Client(
            base_url=cfg.backend_url,
            headers={"Authorization": f"Bearer {cfg.token}", "User-Agent": f"lusopay-worker/{VERSION}"},
            timeout=httpx.Timeout(30.0),
            verify=cfg.ca_bundle or True,
            transport=transport,
        )

    def _post(self, path: str, json: dict | None = None, retries: int = 4) -> httpx.Response:
        """Todos os endpoints do worker são idempotentes do lado do backend, por isso
        é seguro repetir após erro de rede. Erros 4xx não são repetidos."""
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                resp = self.http.post(path, json=json or {})
                if resp.status_code >= 500 and attempt < retries:
                    raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt >= retries:
                    raise
                log.warning("erro a contactar o backend (%s); nova tentativa em %.0fs", type(exc).__name__, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise RuntimeError("unreachable")

    def claim(self, active_run_ids: list[str], capabilities: list[str]) -> dict[str, Any] | None:
        r = self._post("/api/worker/claim", {"active_run_ids": active_run_ids, "version": VERSION,
                                              "capabilities": capabilities})
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def heartbeat(self, run_id: str) -> dict[str, Any]:
        r = self._post(f"/api/worker/runs/{run_id}/heartbeat", retries=1)
        r.raise_for_status()
        return r.json()

    def logs(self, run_id: str, entries: list[dict[str, Any]]) -> None:
        for i in range(0, len(entries), 500):
            r = self._post(f"/api/worker/runs/{run_id}/logs", {"entries": entries[i:i + 500]})
            r.raise_for_status()

    def complete(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._post(f"/api/worker/runs/{run_id}/complete", payload, retries=6)
        r.raise_for_status()
        return r.json()

    def upload_artifact(self, run_id: str, name: str, data: bytes, content_type: str) -> None:
        import base64

        r = self._post(f"/api/worker/runs/{run_id}/artifacts",
                       {"name": name, "content_type": content_type, "data_b64": base64.b64encode(data).decode()})
        r.raise_for_status()

    def save_persistent(self, run_id: str, name: str, data: bytes) -> None:
        import base64

        r = self._post(f"/api/worker/runs/{run_id}/persistent-files",
                       {"name": name, "content_b64": base64.b64encode(data).decode()})
        r.raise_for_status()
