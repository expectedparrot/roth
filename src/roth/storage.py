"""Locked append-only state history with content hashes and atomic event writes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile

from .common import digest, read_json, require


def empty_state():
    return {
        "market": None,
        "preferences": {},
        "preference_history": [],
        "snapshots": {},
        "runs": {},
        "fields": {},
        "screening": {},
        "score_plans": {},
        "scores": {},
        "benchmarks": {},
        "registrations": {},
    }


class Store:
    def __init__(self, project):
        self.root = Path(project).resolve() / ".roth"

    @contextmanager
    def lock(self, create=False):
        require(
            create or self.root.exists(),
            "No Roth project; run roth init or roth example create",
            "NOT_INITIALIZED",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "write.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield self
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self):
        state, previous = empty_state(), None
        paths = sorted((self.root / "events").glob("*.json"))
        for seq, path in enumerate(paths, 1):
            event = read_json(path)
            checksum = event.pop("hash")
            require(
                checksum == digest(event),
                f"Corrupt event {path.name}",
                "INTEGRITY_ERROR",
            )
            require(
                event["sequence"] == seq
                and path.name == f"{seq:08d}.json"
                and event["previous"] == previous,
                "Broken history chain",
                "INTEGRITY_ERROR",
            )
            state = read_json(self.root / "objects" / f"{event['state_hash']}.json")
            require(
                digest(state) == event["state_hash"],
                "Corrupt state object",
                "INTEGRITY_ERROR",
            )
            previous = checksum
        self.sequence, self.previous = len(paths), previous
        return state

    def commit(self, state, action, details=None):
        state_hash = digest(state)
        objects = self.root / "objects"
        objects.mkdir(exist_ok=True)
        target = objects / f"{state_hash}.json"
        if not target.exists():
            self._atomic(target, state)
        events = self.root / "events"
        events.mkdir(exist_ok=True)
        event = {
            "sequence": self.sequence + 1,
            "previous": self.previous,
            "state_hash": state_hash,
            "action": action,
            "details": details or {},
            "time": datetime.now(timezone.utc).isoformat(),
        }
        event["hash"] = digest(event)
        self._atomic(events / f"{event['sequence']:08d}.json", event)
        self.sequence += 1
        self.previous = event["hash"]
        return event["hash"]

    @staticmethod
    def _atomic(target, value):
        require(not target.exists(), f"Refusing to overwrite {target}")
        fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".pending-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temp, target)
        finally:
            os.unlink(temp)
