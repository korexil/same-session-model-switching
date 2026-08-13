"""Small atomic desired-route store for the reference controller."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from switch_controller import RouteEvidence


class JsonStateStore:
    """Atomically persists non-secret restart intent and its commit evidence."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_desired(self) -> Optional[str]:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("desired"), str):
            raise ValueError("invalid desired-state file")
        return data["desired"]

    def save_desired(self, alias: str, evidence: RouteEvidence) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "desired": alias,
            "committed_from": asdict(evidence),
        }
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(payload, temporary, ensure_ascii=False, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
