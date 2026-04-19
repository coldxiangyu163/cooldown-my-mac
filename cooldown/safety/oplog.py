"""Append-only operations log (mirrors Mole's ~/Library/Logs/mole/operations.log)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_PATH = Path.home() / "Library" / "Logs" / "cooldown" / "operations.log"


def _enabled() -> bool:
    return os.environ.get("COOL_NO_OPLOG", "").strip() not in {"1", "true", "yes"}


def record(action: str, **fields: Any) -> None:
    if not _enabled():
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            **fields,
        }
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # Never let logging kill the action.
        pass
