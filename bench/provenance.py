"""Append-only acquisition and artifact history, separate from native exports."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import time

from .config import file_digest

_ledger = ContextVar("provenance_ledger", default=None)
_scope = ContextVar("provenance_scope", default={})


def timestamp():
    ns = time.time_ns()
    seconds, fraction = divmod(ns, 1_000_000_000)
    utc = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return {"timestamp_ns": ns, "timestamp_utc": f"{utc}.{fraction:09d}Z"}


def record(operation, **fields):
    root = _ledger.get()
    if root is not None:
        row = {"schema_version": 1, "operation": operation, **_scope.get(), **fields, "recorded": timestamp()}
        with (root / "provenance.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


@contextmanager
def recording(root):
    token = _ledger.set(Path(root))
    try:
        yield
    finally:
        _ledger.reset(token)


@contextmanager
def operation(name, **fields):
    span = {"started": timestamp(), **fields}
    clock = time.monotonic_ns()
    token = _scope.set({**_scope.get(), **fields})
    try:
        yield span
    except BaseException as exc:
        span.update(status="failed", error_type=type(exc).__name__)
        raise
    else:
        span.setdefault("status", "completed")
    finally:
        span.update(finished=timestamp(), duration_ns=time.monotonic_ns() - clock)
        try:
            record(name, **span)
        finally:
            _scope.reset(token)


def observed(name, source=None):
    """Record a read window; check lists also carry that window on stdout."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            fields = {"source": source(*args, **kwargs)} if source else {}
            with operation(name, **fields) as span:
                result = function(*args, **kwargs)
            if isinstance(result, list):
                for check in result:
                    check.setdefault("observation", dict(span))
            return result
        return wrapped
    return decorate


def artifact(path, **fields):
    root = _ledger.get()
    if root is not None:
        path = Path(path)
        record("artifact_saved", artifact=str(path.relative_to(root)),
               sha256=file_digest(path), bytes=path.stat().st_size, **fields)


def artifact_name(path):
    root = _ledger.get()
    return str(Path(path).relative_to(root)) if root is not None else Path(path).name
