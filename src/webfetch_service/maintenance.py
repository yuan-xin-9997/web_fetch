from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from webfetch_service.core.config import get_settings


def remove_stale_temporary_files(root: Path, older_than_seconds: int = 3600) -> int:
    if not root.exists():
        return 0
    threshold = time.time() - older_than_seconds
    count = 0
    for path in root.rglob("*.tmp"):
        if path.is_file() and path.stat().st_mtime < threshold:
            path.unlink()
            count += 1
    return count


async def run() -> int:
    settings = get_settings()
    age = int(os.getenv("WEBFETCH_MAINTENANCE_TMP_MAX_AGE_SECONDS", "3600"))
    return await asyncio.to_thread(remove_stale_temporary_files, settings.storage.artifact_root, age)


def main() -> None:
    count = asyncio.run(run())
    print(f"removed_temporary_files={count}")


if __name__ == "__main__":
    main()
