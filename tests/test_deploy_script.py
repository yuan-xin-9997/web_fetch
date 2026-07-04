from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "deploy" / "webfetch-jenkins-deploy"


def test_release_cleanup_runs_only_after_successful_health_check() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    health_failure = content.index('if [[ "$ready" != true ]]')
    failure_exit = content.index("exit 1", health_failure)
    cleanup_call = content.index("cleanup_old_releases\n", failure_exit)

    assert cleanup_call > failure_exit


def test_release_cleanup_is_configurable_and_protects_current() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert '${WEBFETCH_RELEASES_TO_KEEP:-5}' in content
    assert "(( keep < 2 ))" in content
    assert '[[ "$candidate" == "$current_release" ]]' in content
    assert '[[ "$(dirname "$candidate")" != "$(realpath "$releases_dir")" ]]' in content
