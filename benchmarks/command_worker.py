"""One-shot command measurement worker used by the benchmark supervisor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Prime the observer before a timed child starts; importing it in the sampler
# can take as long as the shortest commands and miss their entire lifetime.
try:
    import psutil as _psutil
except ImportError:
    _psutil = None


SAMPLE_INTERVAL_SECONDS = 0.005


def _usage() -> Any | None:
    try:
        import resource
    except ImportError:
        return None
    return resource.getrusage(resource.RUSAGE_CHILDREN)


def _usage_delta(before: Any | None, after: Any | None) -> dict[str, object]:
    if before is None or after is None:
        return {
            "backend": "unavailable",
            "user_cpu_ns": None,
            "system_cpu_ns": None,
            "peak_child_rss_bytes": None,
            "peak_rss_fidelity": "unavailable",
        }
    max_rss = int(after.ru_maxrss)
    if sys.platform != "darwin":
        max_rss *= 1024
    return {
        "backend": "resource.RUSAGE_CHILDREN",
        "user_cpu_ns": round((after.ru_utime - before.ru_utime) * 1_000_000_000),
        "system_cpu_ns": round((after.ru_stime - before.ru_stime) * 1_000_000_000),
        "peak_child_rss_bytes": max_rss,
        "peak_rss_fidelity": "maximum waited child; not aggregate concurrent tree RSS",
        "minor_page_faults": after.ru_minflt - before.ru_minflt,
        "major_page_faults": after.ru_majflt - before.ru_majflt,
        "block_inputs": after.ru_inblock - before.ru_inblock,
        "block_outputs": after.ru_oublock - before.ru_oublock,
        "voluntary_context_switches": after.ru_nvcsw - before.ru_nvcsw,
        "involuntary_context_switches": after.ru_nivcsw - before.ru_nivcsw,
    }


def _output_metadata(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    tail = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            tail = (tail + chunk)[-8192:]
    return {
        "output_bytes": path.stat().st_size,
        "output_sha256": digest.hexdigest(),
        "failure_tail": tail.decode("utf-8", errors="replace").splitlines()[-20:],
    }


def _sample_process_tree(
    process: subprocess.Popen[bytes], stop: threading.Event
) -> dict[str, object]:
    if _psutil is None:
        return {
            "backend": "unavailable (install the benchmark dependency group)",
            "sample_interval_seconds": None,
            "peak_tree_rss_bytes": None,
            "unique_process_count": None,
        }

    try:
        root = _psutil.Process(process.pid)
    except _psutil.NoSuchProcess:
        return {
            "backend": "psutil sampled descendant tree",
            "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
            "peak_tree_rss_bytes": 0,
            "unique_process_count": 0,
        }
    peak_rss = 0
    seen: set[tuple[int, float]] = set()
    while not stop.is_set():
        try:
            processes = [root, *root.children(recursive=True)]
        except (_psutil.NoSuchProcess, _psutil.AccessDenied):
            processes = []
        rss = 0
        for child in processes:
            try:
                seen.add((child.pid, child.create_time()))
                rss += child.memory_info().rss
            except (_psutil.NoSuchProcess, _psutil.AccessDenied):
                continue
        peak_rss = max(peak_rss, rss)
        stop.wait(SAMPLE_INTERVAL_SECONDS)
    return {
        "backend": "psutil sampled descendant tree",
        "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "peak_tree_rss_bytes": peak_rss,
        "unique_process_count": len(seen),
    }


def run(request: dict[str, object]) -> dict[str, object]:
    command = [os.fspath(item) for item in request["command"]]  # type: ignore[index]
    cwd = os.fspath(request["cwd"])
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
    output_path = Path(os.fspath(request["output_path"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    usage_before = _usage()
    started_ns = time.perf_counter_ns()
    with output_path.open("wb") as output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        stop_sampling = threading.Event()
        process_tree: dict[str, object] = {}

        def sample_resources() -> None:
            try:
                process_tree.update(_sample_process_tree(process, stop_sampling))
            except Exception as error:
                process_tree.update(
                    {
                        "backend": f"unavailable ({type(error).__name__})",
                        "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
                        "peak_tree_rss_bytes": None,
                        "unique_process_count": None,
                    }
                )

        sampler = threading.Thread(target=sample_resources, daemon=True)
        sampler.start()
        process.wait()
        elapsed_ns = time.perf_counter_ns() - started_ns
        stop_sampling.set()
        sampler.join()
    usage_after = _usage()
    output = _output_metadata(output_path)
    if process.returncode == 0:
        output["failure_tail"] = []
    return {
        "schema_version": 1,
        "command": command,
        "cwd": cwd,
        "returncode": process.returncode,
        "wall_time_ns": elapsed_ns,
        "resources": _usage_delta(usage_before, usage_after),
        "process_tree": process_tree,
        **output,
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
