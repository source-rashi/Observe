import math
from typing import Dict, List, Tuple
import httpx

class PrometheusClientError(Exception):
    """Custom exception raised when Prometheus communication fails."""
    pass

class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.timeout = 5.0

    async def is_up(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/-/ready")
                return res.status_code == 200
        except Exception:
            return False

    async def query_range(
        self, promql: str, start: float, end: float, step: int
    ) -> Dict[str, List[Tuple[float, float]]]:
        params = {
            "query": promql,
            "start": str(start),
            "end": str(end),
            "step": str(step),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/api/v1/query_range", params=params)
                if res.status_code != 200:
                    raise PrometheusClientError(
                        f"Prometheus HTTP error {res.status_code}: {res.text}"
                    )
                data = res.json()
        except httpx.HTTPError as e:
            raise PrometheusClientError(f"HTTP connection error querying Prometheus: {e}") from e
        except Exception as e:
            if not isinstance(e, PrometheusClientError):
                raise PrometheusClientError(f"Unexpected error querying Prometheus: {e}") from e
            raise

        if data.get("status") != "success":
            raise PrometheusClientError(f"Prometheus query unsuccessful: {data.get('error', 'unknown error')}")

        result_series = data.get("data", {}).get("result", [])
        output: Dict[str, List[Tuple[float, float]]] = {}

        for item in result_series:
            metric = item.get("metric", {})
            if "endpoint" in metric:
                key = metric["endpoint"]
            elif metric:
                sorted_items = sorted(metric.items())
                key = str(tuple(sorted_items))
            else:
                key = ""

            points: List[Tuple[float, float]] = []
            for ts, val_str in item.get("values", []):
                try:
                    val = float(val_str)
                    if math.isnan(val) or math.isinf(val):
                        continue
                    points.append((float(ts), val))
                except (ValueError, TypeError):
                    continue

            output[key] = points

        return output
