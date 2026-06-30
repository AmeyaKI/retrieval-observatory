from __future__ import annotations

from typing import Any, Dict, List

import httpx

from retrieval_observatory.tracing.model_v2 import RetrievalTraceV2


class RemoteResultsClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def create_run(self, experiment_name: str, config_json: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/experiments/{experiment_name}/runs",
                json={"config_json": config_json},
            )
            response.raise_for_status()
            return response.json()

    async def push_traces(self, run_id: str, traces: List[RetrievalTraceV2]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/runs/{run_id}/results",
                json={"traces": [trace.to_dict() for trace in traces]},
            )
            response.raise_for_status()
            return response.json()

    async def push_metrics(self, run_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/runs/{run_id}/metrics",
                json={"rows": rows},
            )
            response.raise_for_status()
            return response.json()

    async def finish(self, run_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/runs/{run_id}/finish")
            response.raise_for_status()
            return response.json()
