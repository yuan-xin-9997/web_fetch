from __future__ import annotations

import hashlib

import pytest

from webfetch_service.services.artifacts import ArtifactStore


async def test_artifact_round_trip_and_header_redaction(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    await store.initialize()
    body = b"hello"
    artifact = await store.save(
        body,
        "text/plain",
        {
            "headers": {"Authorization": "secret", "Content-Type": "text/plain"},
            "content_type": "text/plain",
        },
    )
    loaded, content = await store.load(artifact.id)
    assert content == body
    assert loaded.sha256 == hashlib.sha256(body).hexdigest()
    metadata = (tmp_path / artifact.relative_path / "metadata.json").read_text(encoding="utf-8")
    assert "secret" not in metadata
    assert "[REDACTED]" in metadata


async def test_missing_artifact_is_404(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(Exception) as caught:
        await store.load("art_00000000000000000000000000000000")
    assert caught.value.code == "ARTIFACT_NOT_FOUND"
