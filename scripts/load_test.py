"""Dependency-free concurrent API load probe; prints measured results as JSON."""

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="hr_dev_local_change_me")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    statuses: dict[int, int] = {}

    async with httpx.AsyncClient(base_url=args.url, timeout=15) as client:

        async def send(index: int) -> None:
            async with semaphore:
                started = time.perf_counter()
                response = await client.post(
                    "/api/v1/events",
                    headers={
                        "X-API-Key": args.api_key,
                        "Idempotency-Key": f"load-{time.time_ns()}-{index}",
                    },
                    json={"event_type": "load.test", "payload": {"index": index}},
                )
                latencies.append((time.perf_counter() - started) * 1000)
                statuses[response.status_code] = statuses.get(response.status_code, 0) + 1

        started = time.perf_counter()
        await asyncio.gather(*(send(index) for index in range(args.requests)))
        elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    print(
        json.dumps(
            {
                "requests": args.requests,
                "concurrency": args.concurrency,
                "elapsed_seconds": round(elapsed, 3),
                "requests_per_second": round(args.requests / elapsed, 2),
                "latency_ms_p50": round(statistics.median(ordered), 2),
                "latency_ms_p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2),
                "statuses": statuses,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
