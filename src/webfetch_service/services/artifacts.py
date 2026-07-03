from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.ids import new_id
from webfetch_service.core.logging import redact_headers


@dataclass(slots=True)
class Artifact:
    id: str
    relative_path: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: str


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._index: dict[str, Artifact] = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)

    async def is_ready(self) -> bool:
        try:
            await self.initialize()
            probe = self.root / ".ready"
            await asyncio.to_thread(probe.write_text, "ok", encoding="utf-8")
            await asyncio.to_thread(probe.unlink, missing_ok=True)
            return True
        except OSError:
            return False

    async def save(
        self,
        body: bytes,
        content_type: str,
        metadata: dict[str, object],
    ) -> Artifact:
        now = datetime.now(UTC)
        artifact_id = new_id("art")
        digest = hashlib.sha256(body).hexdigest()
        relative = Path(now.strftime("%Y/%m/%d")) / digest[:2] / artifact_id
        target_dir = self._safe_path(relative)
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=False)
        body_path = target_dir / "body.bin"
        metadata_path = target_dir / "metadata.json"
        await asyncio.to_thread(self._atomic_write, body_path, body)

        safe_metadata = dict(metadata)
        headers = safe_metadata.get("headers")
        if isinstance(headers, dict):
            safe_metadata["headers"] = redact_headers({str(k): str(v) for k, v in headers.items()})
        await asyncio.to_thread(
            self._atomic_write,
            metadata_path,
            json.dumps(safe_metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        artifact = Artifact(
            id=artifact_id,
            relative_path=relative.as_posix(),
            content_type=content_type,
            size_bytes=len(body),
            sha256=digest,
            created_at=now.isoformat(),
        )
        self._index[artifact_id] = artifact
        return artifact

    async def load(self, artifact_id: str) -> tuple[Artifact, bytes]:
        artifact = self._index.get(artifact_id)
        if artifact is None:
            artifact = await asyncio.to_thread(self._scan_for, artifact_id)
        if artifact is None:
            raise WebFetchError("ARTIFACT_NOT_FOUND", "原始文件不存在", 404)
        body_path = self._safe_path(Path(artifact.relative_path)) / "body.bin"
        return artifact, await asyncio.to_thread(body_path.read_bytes)

    def _scan_for(self, artifact_id: str) -> Artifact | None:
        if not artifact_id.startswith("art_") or any(ch not in "0123456789abcdef_" for ch in artifact_id):
            return None
        matches = list(self.root.glob(f"*/*/*/*/{artifact_id}/metadata.json"))
        if not matches:
            return None
        metadata_path = matches[0]
        body_path = metadata_path.parent / "body.bin"
        body = body_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        artifact = Artifact(
            id=artifact_id,
            relative_path=metadata_path.parent.relative_to(self.root).as_posix(),
            content_type=str(metadata.get("content_type", "application/octet-stream")),
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            created_at=str(metadata.get("fetched_at", datetime.now(UTC).isoformat())),
        )
        self._index[artifact_id] = artifact
        return artifact

    def _safe_path(self, relative: Path) -> Path:
        root = self.root.resolve()
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise WebFetchError("INVALID_REQUEST", "非法文件路径", 400)
        return path

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
