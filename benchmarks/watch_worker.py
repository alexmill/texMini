"""Measure watch readiness, idle resources, detection, and rebuild latency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil


POLL_SECONDS = 0.005


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_visible_edit(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    end_document = "\\end{document}"
    insertion_point = text.rfind(end_document)
    if insertion_point < 0:
        raise RuntimeError(f"Cannot insert a visible watch edit into {source}")
    marker = "texMini benchmark visible watch edit"
    source.write_text(
        f"{text[:insertion_point]}\\par\\noindent {marker}.\n"
        f"{text[insertion_point:]}",
        encoding="utf-8",
    )
    return marker


def _pdf_change_evidence(
    pdf: Path, expected_before_sha256: str, observed_before_sha256: str | None
) -> dict[str, object]:
    after_sha256 = _file_sha256(pdf)
    before_matches = observed_before_sha256 == expected_before_sha256
    return {
        "path": os.fspath(pdf),
        "expected_before_sha256": expected_before_sha256,
        "observed_before_sha256": observed_before_sha256,
        "after_sha256": after_sha256,
        "before_matches_request": before_matches,
        "changed": (
            before_matches
            and after_sha256 is not None
            and after_sha256 != observed_before_sha256
        ),
    }


def _tree(root: psutil.Process) -> list[psutil.Process]:
    try:
        return [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def _tree_cpu_seconds(root: psutil.Process) -> float:
    total = 0.0
    for process in _tree(root):
        try:
            times = process.cpu_times()
            total += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _tree_rss(root: psutil.Process) -> int:
    total = 0
    for process in _tree(root):
        try:
            total += process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _wait_for(
    lines: "queue.Queue[tuple[int, str]]", pattern: str, deadline: float
) -> tuple[int, list[str]]:
    observed: list[str] = []
    while time.monotonic() < deadline:
        try:
            timestamp, line = lines.get(timeout=min(0.1, deadline - time.monotonic()))
        except queue.Empty:
            continue
        observed.append(line)
        if pattern in line:
            return timestamp, observed
    raise TimeoutError(f"Timed out waiting for watch output containing {pattern!r}")


def run(request: dict[str, object]) -> dict[str, object]:
    command = [os.fspath(item) for item in request["command"]]  # type: ignore[index]
    cwd = Path(os.fspath(request["cwd"]))
    if "env" in request:  # schema-1 compatibility for direct callers
        env = {
            str(key): str(value)
            for key, value in request["env"].items()  # type: ignore[union-attr]
        }
    else:
        env = dict(os.environ)
        for key in request.get("env_unset", []):  # type: ignore[assignment]
            env.pop(str(key), None)
        env.update(
            {
                str(key): str(value)
                for key, value in request.get("env_overrides", {}).items()  # type: ignore[union-attr]
            }
        )
    source = cwd / os.fspath(request["source"])
    pdf = cwd / os.fspath(request["pdf"])
    expected_pdf_sha256 = str(request["expected_pdf_sha256"])
    log_path = Path(os.fspath(request["output_path"]))
    idle_seconds = float(request.get("idle_seconds", 5.0))
    timeout_seconds = float(request.get("timeout_seconds", 60.0))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

    started_ns = time.perf_counter_ns()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=creation_flags,
    )
    root = psutil.Process(process.pid)
    lines: "queue.Queue[tuple[int, str]]" = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        with log_path.open("w", encoding="utf-8") as log:
            for line in process.stdout:
                timestamp = time.perf_counter_ns()
                log.write(line)
                log.flush()
                lines.put((timestamp, line.rstrip("\r\n")))

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_seconds
    readiness_ns, _ = _wait_for(lines, "Watching ", deadline)

    idle_cpu_before = _tree_cpu_seconds(root)
    idle_peak_rss = 0
    idle_started = time.perf_counter_ns()
    while (time.perf_counter_ns() - idle_started) < idle_seconds * 1_000_000_000:
        idle_peak_rss = max(idle_peak_rss, _tree_rss(root))
        time.sleep(POLL_SECONDS)
    idle_elapsed_ns = time.perf_counter_ns() - idle_started
    idle_cpu_seconds = max(0.0, _tree_cpu_seconds(root) - idle_cpu_before)

    observed_pdf_sha256 = _file_sha256(pdf)
    changed_ns = time.perf_counter_ns()
    edit_marker = _apply_visible_edit(source)
    detected_ns, _ = _wait_for(lines, "Compiling ", deadline)
    completed_ns, _ = _wait_for(lines, "Built ", deadline)
    pdf_evidence = _pdf_change_evidence(
        pdf, expected_pdf_sha256, observed_pdf_sha256
    )
    pdf_evidence["path"] = os.fspath(request["pdf"])

    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    reader.join(timeout=2)
    return {
        "schema_version": 1,
        "returncode": process.returncode,
        "startup_to_ready_ns": readiness_ns - started_ns,
        "idle": {
            "wall_time_ns": idle_elapsed_ns,
            "tree_cpu_time_ns": round(idle_cpu_seconds * 1_000_000_000),
            "cpu_fraction_one_core": idle_cpu_seconds / (idle_elapsed_ns / 1_000_000_000),
            "peak_tree_rss_bytes": idle_peak_rss,
            "sample_interval_seconds": POLL_SECONDS,
        },
        "change_to_detection_ns": detected_ns - changed_ns,
        "detection_to_complete_ns": completed_ns - detected_ns,
        "change_to_complete_ns": completed_ns - changed_ns,
        "edit_marker": edit_marker,
        "pdf_change_evidence": pdf_evidence,
        "log": os.fspath(log_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    result = run(request)
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
