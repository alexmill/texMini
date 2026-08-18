"""Opt-in JSONL tracing for benchmark attribution."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from time import perf_counter_ns, process_time_ns
TRACE_ENV = "TEXMINI_TRACE"


def _append(event: dict[str, object]) -> None:
    destination = os.environ.get(TRACE_ENV)
    if not destination:
        return
    descriptor = os.open(
        destination,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(
            descriptor,
            (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
    finally:
        os.close(descriptor)


@contextmanager
def span(name: str, **fields: object):
    if not os.environ.get(TRACE_ENV):
        yield fields
        return

    started_ns = perf_counter_ns()
    started_cpu_ns = process_time_ns()
    try:
        yield fields
    except BaseException as error:
        fields["exception"] = type(error).__name__
        raise
    finally:
        ended_ns = perf_counter_ns()
        ended_cpu_ns = process_time_ns()
        _append(
            {
                "schema_version": 1,
                "name": name,
                "pid": os.getpid(),
                "started_ns": started_ns,
                "duration_ns": ended_ns - started_ns,
                "process_cpu_ns": ended_cpu_ns - started_cpu_ns,
                **fields,
            }
        )
