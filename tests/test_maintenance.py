from __future__ import annotations

import os
import time

from webfetch_service.maintenance import remove_stale_temporary_files


def test_remove_only_stale_temporary_files(tmp_path) -> None:
    old = tmp_path / "old.tmp"
    fresh = tmp_path / "fresh.tmp"
    keep = tmp_path / "keep.bin"
    old.write_text("old")
    fresh.write_text("fresh")
    keep.write_text("keep")
    old_time = time.time() - 7200
    os.utime(old, (old_time, old_time))
    assert remove_stale_temporary_files(tmp_path, 3600) == 1
    assert not old.exists()
    assert fresh.exists()
    assert keep.exists()
