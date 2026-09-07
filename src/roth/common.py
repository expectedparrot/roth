"""Validation and canonical serialization shared by Roth artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


class RothError(ValueError):
    def __init__(self, message, code="VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


def require(condition, message, code="VALIDATION_ERROR"):
    if not condition:
        raise RothError(message, code)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    return json.loads(
        Path(path).read_text(),
        parse_constant=lambda x: (_ for _ in ()).throw(
            RothError(f"Invalid JSON constant: {x}")
        ),
    )


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(
            json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )
    return str(path.resolve())


def identifier(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value),
        f"Invalid ID: {value!r}",
    )
    return value


def number(value, low=None, high=None):
    require(
        type(value) in (int, float) and math.isfinite(value), "Expected a finite number"
    )
    require(low is None or value >= low, f"Number must be >= {low}")
    require(high is None or value <= high, f"Number must be <= {high}")
    return value
