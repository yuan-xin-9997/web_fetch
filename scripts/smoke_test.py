#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a running WebFetch service")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--api-key")
    parser.add_argument("--api-key-file")
    parser.add_argument("--target-url")
    parser.add_argument("--include-browser", action="store_true")
    parser.add_argument("--include-job", action="store_true")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    results: dict[str, object] = {}
    with httpx.Client(timeout=args.timeout) as client:
        for endpoint in ("/health/live", "/health/ready"):
            response = client.get(base_url + endpoint)
            results[endpoint] = {"status": response.status_code, "body": response.json()}
            response.raise_for_status()
        if args.target_url:
            api_key = args.api_key
            if args.api_key_file:
                with open(args.api_key_file, encoding="utf-8") as stream:
                    api_key = stream.read().strip()
            if not api_key:
                parser.error("--api-key or --api-key-file is required with --target-url")
            modes = ["http", "browser"] if args.include_browser else ["http"]
            for mode in modes:
                response = client.post(
                    base_url + "/v1/fetch",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "url": args.target_url,
                        "mode": mode,
                        "force_refresh": True,
                        "save_artifact": True,
                    },
                )
                payload = response.json()
                results[f"fetch:{mode}"] = {
                    "status": response.status_code,
                    "success": payload.get("success"),
                    "strategy": payload.get("strategy"),
                    "upstream_status": payload.get("status_code"),
                    "artifact_id": payload.get("artifact_id"),
                }
                response.raise_for_status()
                if not payload.get("success"):
                    raise RuntimeError(f"{mode} fetch did not succeed")
            if args.include_job:
                response = client.post(
                    base_url + "/v1/jobs",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"requests": [{"url": args.target_url, "mode": "http", "force_refresh": True}]},
                )
                response.raise_for_status()
                job_id = response.json()["job_id"]
                deadline = time.monotonic() + args.timeout
                job = response.json()
                while time.monotonic() < deadline:
                    response = client.get(
                        base_url + f"/v1/jobs/{job_id}",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    response.raise_for_status()
                    job = response.json()
                    if job["state"] in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.25)
                results["job"] = {
                    "job_id": job_id,
                    "state": job["state"],
                    "succeeded_count": job.get("succeeded_count"),
                    "failed_count": job.get("failed_count"),
                }
                if job["state"] != "succeeded":
                    raise RuntimeError(f"job did not succeed: {job['state']}")
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
