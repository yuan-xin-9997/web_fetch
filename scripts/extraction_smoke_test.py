#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Run authenticated extraction requests")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-file", required=True)
    parser.add_argument("--url", action="append", required=True, dest="urls")
    parser.add_argument("--adapter", default="generic.article")
    parser.add_argument("--proxy-policy", choices=("auto", "direct", "proxy"), default="auto")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    with open(args.api_key_file, encoding="utf-8") as stream:
        api_key = stream.read().strip()

    results = []
    failed = False
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        for url in args.urls:
            response = client.post(
                "/v1/extract",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "url": url,
                    "adapter": args.adapter,
                    "fetch_options": {
                        "url": url,
                        "mode": "auto",
                        "proxy_policy": args.proxy_policy,
                        "force_refresh": True,
                    },
                },
            )
            payload = response.json()
            if response.is_error:
                failed = True
                results.append({"url": url, "http_status": response.status_code, "error": payload})
            else:
                results.append(payload)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
