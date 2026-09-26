from __future__ import annotations

import json
import logging

from webfetch_service.core.logging import JsonFormatter


def test_json_log_includes_internal_exception_traceback() -> None:
    try:
        raise RuntimeError("chromium launch failed")
    except RuntimeError:
        import sys

        error_info = sys.exc_info()

    record = logging.LogRecord("browser", logging.ERROR, __file__, 1, "browser startup failed", (), error_info)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "browser startup failed"
    assert "RuntimeError: chromium launch failed" in entry["exception"]
