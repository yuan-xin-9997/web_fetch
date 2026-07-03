#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a running WebFetch service")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    results: dict[str, object] = {}
    with httpx.Client(timeout=args.timeout) as client:
        for endpoint in ("/health/live", "/health/ready"):
            response = client.get(base_url + endpoint)
            results[endpoint] = {"status": response.status_code, "body": response.json()}
            response.raise_for_status()
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
