from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS = ROOT / "benchmarks" / "thresholds.json"


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def _load_result_pair(path: Path) -> dict[str, Any]:
    result = _load(path)
    raw_name = result.get("raw_samples")
    if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
        raise ValueError(f"{path} has an unsafe or missing raw_samples basename")
    raw_path = path.parent / raw_name
    raw_bytes = raw_path.read_bytes()
    if result.get("raw_samples_bytes") != len(raw_bytes):
        raise ValueError(f"{raw_path} byte count does not match {path.name}")
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if result.get("raw_samples_sha256") != raw_sha256:
        raise ValueError(f"{raw_path} digest does not match {path.name}")
    try:
        raw_samples = [
            json.loads(line)
            for line in raw_bytes.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{raw_path} is not valid UTF-8 JSONL: {error}") from error
    if raw_samples != result.get("samples"):
        raise ValueError(f"{raw_path} samples do not match embedded result samples")
    from benchmarks.benchmark import _scenario_summary

    if result.get("summary") != _scenario_summary(raw_samples):
        raise ValueError(f"{path} summary does not match its raw samples")
    return result


def _environment_identity(result: dict[str, Any]) -> tuple[object, ...]:
    host = result.get("host", {})
    runtime = result.get("runtime_manifest", {})
    harness = result.get("harness_git", {})
    configuration = result.get("configuration", {})
    base_runtime = result.get("footprints", {}).get("base_runtime", {})
    fully_provisioned_runtime = result.get("footprints", {}).get(
        "fully_provisioned_runtime", {}
    )
    return (
        host.get("system"),
        host.get("release"),
        host.get("machine"),
        host.get("processor"),
        host.get("cpu"),
        host.get("logical_cpu_count"),
        host.get("memory_bytes"),
        host.get("filesystem"),
        host.get("filesystem_type"),
        host.get("filesystem_mount"),
        host.get("python"),
        host.get("uv"),
        json.dumps(host.get("dependency_versions", {}), sort_keys=True),
        runtime.get("schema_version"),
        runtime.get("tinytex_version"),
        runtime.get("repository"),
        runtime.get("platform_key"),
        runtime.get("asset"),
        runtime.get("asset_sha256"),
        runtime.get("manifest_sha256"),
        harness.get("commit"),
        harness.get("tree_content_sha256"),
        configuration.get("suite"),
        configuration.get("repeats"),
        configuration.get("startup_repeats"),
        configuration.get("package_repeats"),
        configuration.get("watch_repeats"),
        configuration.get("watch_idle_seconds"),
        configuration.get("skip_packaging"),
        configuration.get("skip_package_recovery"),
        configuration.get("runtime_template"),
        base_runtime.get("logical_bytes"),
        base_runtime.get("regular_files"),
        base_runtime.get("content_identity", {}).get("sha256"),
        fully_provisioned_runtime.get("package_inventory", {}).get(
            "package_count"
        ),
        fully_provisioned_runtime.get("package_inventory", {}).get("sha256"),
    )


def _validate_environment_evidence(label: str, result: dict[str, Any]) -> None:
    host = result.get("host", {})
    runtime = result.get("runtime_manifest", {})
    footprints = result.get("footprints", {})
    missing = []
    if not (host.get("cpu") or host.get("processor")):
        missing.append("host CPU identity")
    if host.get("logical_cpu_count") is None:
        missing.append("logical CPU count")
    if not isinstance(host.get("dependency_versions"), dict):
        missing.append("dependency versions")
    if not runtime.get("manifest_sha256"):
        missing.append("target runtime-manifest content identity")
    if not result.get("harness_git", {}).get("tree_content_sha256"):
        missing.append("harness tree content identity")
    if not footprints.get("base_runtime", {}).get("content_identity", {}).get(
        "sha256"
    ):
        missing.append("base runtime content identity")
    if not footprints.get("fully_provisioned_runtime", {}).get(
        "package_inventory", {}
    ).get("sha256"):
        missing.append("fully provisioned installed-package inventory")
    if missing:
        raise ValueError(
            f"{label} lacks required environment evidence: {', '.join(missing)}"
        )


def _percent_change(before: int | float, after: int | float) -> float:
    if before == 0:
        return 0.0 if after == 0 else float("inf")
    return (after / before - 1.0) * 100.0


def _network_dependent_scenarios(result: dict[str, Any]) -> set[str]:
    dependent = set()
    for sample in result.get("samples", []):
        if sample.get("network", {}).get("dependent"):
            dependent.add(f"{sample.get('scenario')}/{sample.get('state')}")
    return dependent


def _validate_baseline_identity(
    baseline: dict[str, Any],
    thresholds: dict[str, Any],
    baseline_name: str | None,
) -> dict[str, object]:
    expected_name = thresholds.get("baseline")
    if expected_name is not None:
        if baseline_name is None:
            raise ValueError(
                "thresholds name a frozen baseline; baseline_name is required"
            )
        if baseline_name != expected_name:
            raise ValueError(
                f"thresholds require baseline {expected_name!r}, got {baseline_name!r}"
            )
    expected_commit = thresholds.get("baseline_git_commit")
    actual_commit = baseline.get("git", {}).get("commit")
    if expected_commit is not None and actual_commit != expected_commit:
        raise ValueError(
            f"thresholds require baseline commit {expected_commit!r}, "
            f"got {actual_commit!r}"
        )
    expected_candidate = thresholds.get("baseline_candidate_id")
    actual_candidate = baseline.get("candidate_id")
    if expected_candidate is not None and actual_candidate != expected_candidate:
        raise ValueError(
            f"thresholds require baseline candidate {expected_candidate!r}, "
            f"got {actual_candidate!r}"
        )
    expected_tree = thresholds.get("baseline_tree_content_sha256")
    actual_tree = baseline.get("git", {}).get("tree_content_sha256")
    if expected_tree is not None and actual_tree != expected_tree:
        raise ValueError(
            f"thresholds require baseline tree {expected_tree!r}, got {actual_tree!r}"
        )
    return {
        "basename": baseline_name,
        "git_commit": actual_commit,
        "candidate_id": actual_candidate,
        "tree_content_sha256": actual_tree,
    }


def _raw_valid_sample_counts(result: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in result.get("samples", []):
        if sample.get("instrumented") or not sample.get("semantic_success", False):
            continue
        name = f"{sample.get('scenario')}/{sample.get('state')}"
        counts[name] = counts.get(name, 0) + 1
    return counts


def _watch_integrity_failures(label: str, result: dict[str, Any]) -> list[str]:
    watch = result.get("watch")
    if not isinstance(watch, dict):
        return [f"missing {label} watch result"]
    samples = watch.get("samples")
    if not isinstance(samples, list):
        return [f"{label} watch samples are missing"]
    failures: list[str] = []
    expected = result.get("configuration", {}).get("watch_repeats")
    valid_samples = int(watch.get("valid_samples", 0))
    if expected is not None and len(samples) != int(expected):
        failures.append(
            f"{label} watch sample count mismatch: {len(samples)} != {expected}"
        )
    if valid_samples != len(samples):
        failures.append(
            f"{label} watch valid sample count mismatch: "
            f"{valid_samples} != {len(samples)}"
        )
    bad_returncodes = [
        sample.get("returncode")
        for sample in samples
        if sample.get("returncode") != 130
    ]
    if bad_returncodes:
        failures.append(
            f"{label} watch did not use handled Ctrl-C return code 130: "
            f"{bad_returncodes}"
        )
    semantic_failures = sum(
        not sample.get("semantic_success", False) for sample in samples
    )
    if semantic_failures:
        failures.append(
            f"{label} watch contains {semantic_failures} failed samples"
        )
    stale_outputs = sum(
        sample.get("pdf_change_evidence", {}).get("changed") is not True
        for sample in samples
    )
    if stale_outputs:
        failures.append(
            f"{label} watch lacks changed-PDF evidence for "
            f"{stale_outputs} samples"
        )
    return failures


def compare_results(
    baseline: dict[str, Any],
    final: dict[str, Any],
    thresholds: dict[str, Any],
    *,
    allow_environment_mismatch: bool = False,
    baseline_name: str | None = None,
) -> dict[str, Any]:
    if baseline.get("schema_version") != 3 or final.get("schema_version") != 3:
        raise ValueError("comparison requires schema-version-3 benchmark results")
    _validate_environment_evidence("baseline", baseline)
    _validate_environment_evidence("final", final)
    baseline_identity = _validate_baseline_identity(
        baseline, thresholds, baseline_name
    )
    environment_matches = _environment_identity(baseline) == _environment_identity(
        final
    )
    if not environment_matches and not allow_environment_mismatch:
        raise ValueError("baseline and final benchmark environments do not match")

    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    for label, result in (("baseline", baseline), ("final", final)):
        failed_samples = [
            sample
            for sample in result.get("samples", [])
            if not sample.get("semantic_success", False)
        ]
        if failed_samples:
            failures.append(f"{label} contains {len(failed_samples)} failed samples")
        watch = result.get("watch")
        if watch and not watch.get("semantic_success", False):
            failures.append(f"{label} watch semantics failed")
        failures.extend(_watch_integrity_failures(label, result))
    baseline_summary = baseline.get("summary", {})
    final_summary = final.get("summary", {})
    baseline_raw_counts = _raw_valid_sample_counts(baseline)
    final_raw_counts = _raw_valid_sample_counts(final)
    scenario_policies = dict(thresholds.get("scenarios", {}))
    default_policy = thresholds.get("default_scenario")
    observations_not_gated: list[dict[str, str]] = []
    all_scenarios = sorted(set(baseline_summary) | set(final_summary))
    for name in all_scenarios:
        if name not in baseline_summary or name not in final_summary:
            failures.append(f"missing scenario: {name}")
            continue
        before_count = int(baseline_summary[name].get("valid_samples", 0))
        after_count = int(final_summary[name].get("valid_samples", 0))
        if before_count != after_count:
            failures.append(
                f"valid sample count mismatch: {name} "
                f"({before_count} != {after_count})"
            )
        for label, summary_count, raw_count in (
            ("baseline", before_count, baseline_raw_counts.get(name, 0)),
            ("final", after_count, final_raw_counts.get(name, 0)),
        ):
            if summary_count != raw_count:
                failures.append(
                    f"{label} summary/raw sample count mismatch: {name} "
                    f"({summary_count} != {raw_count})"
                )
    if default_policy:
        baseline_network = _network_dependent_scenarios(baseline)
        final_network = _network_dependent_scenarios(final)
        for name in all_scenarios:
            if name not in baseline_summary or name not in final_summary:
                continue
            if name in scenario_policies:
                continue
            before_count = int(baseline_summary[name].get("valid_samples", 0))
            after_count = int(final_summary[name].get("valid_samples", 0))
            if name in baseline_network or name in final_network:
                observations_not_gated.append(
                    {"name": name, "reason": "network-dependent"}
                )
            elif min(before_count, after_count) < 3:
                observations_not_gated.append(
                    {"name": name, "reason": "fewer than three valid repeats"}
                )
            else:
                scenario_policies[name] = default_policy

    for name, policy in scenario_policies.items():
        if name not in baseline_summary or name not in final_summary:
            failures.append(f"missing scenario: {name}")
            continue
        before = baseline_summary[name]
        after = final_summary[name]
        before_wall_metric = before.get("wall_time_ns")
        after_wall_metric = after.get("wall_time_ns")
        if not isinstance(before_wall_metric, dict) or not isinstance(
            after_wall_metric, dict
        ):
            failures.append(f"missing valid wall-time summary: {name}")
            continue
        before_wall = int(before_wall_metric["median"])
        after_wall = int(after_wall_metric["median"])
        baseline_mad = int(before_wall_metric["mad"])
        allowed_wall = max(
            before_wall * float(policy["max_wall_regression_percent"]) / 100.0,
            baseline_mad * 3,
        )
        wall_passed = after_wall - before_wall <= allowed_wall
        before_rss_value = before.get("peak_tree_rss_bytes_median")
        after_rss_value = after.get("peak_tree_rss_bytes_median")
        rss_backend = "sampled process tree"
        if before_rss_value is None or after_rss_value is None:
            before_rss_value = before.get("peak_child_rss_bytes_median")
            after_rss_value = after.get("peak_child_rss_bytes_median")
            rss_backend = "waited child maximum"
        if before_rss_value is None or after_rss_value is None:
            failures.append(f"missing RSS metric: {name}")
            before_rss = before_rss_value
            after_rss = after_rss_value
            rss_passed = False
        else:
            before_rss = int(before_rss_value)
            after_rss = int(after_rss_value)
            allowed_rss = (
                before_rss
                * float(policy["max_peak_rss_regression_percent"])
                / 100.0
            )
            rss_passed = after_rss - before_rss <= allowed_rss
        significance = max(before_wall * 0.05, baseline_mad * 3)
        check = {
            "kind": "scenario",
            "name": name,
            "baseline_wall_time_ns": before_wall,
            "final_wall_time_ns": after_wall,
            "wall_change_percent": _percent_change(before_wall, after_wall),
            "baseline_mad_ns": baseline_mad,
            "wall_regression_allowance_ns": round(allowed_wall),
            "wall_passed": wall_passed,
            "improvement_exceeds_noise": before_wall - after_wall > significance,
            "baseline_peak_rss_bytes": before_rss,
            "final_peak_rss_bytes": after_rss,
            "rss_backend": rss_backend,
            "rss_change_percent": (
                _percent_change(before_rss, after_rss)
                if before_rss is not None and after_rss is not None
                else None
            ),
            "rss_passed": rss_passed,
            "passed": wall_passed and rss_passed,
        }
        checks.append(check)
        if not check["passed"]:
            failures.append(f"performance regression: {name}")

    footprint_policy = thresholds.get("footprints", {})
    before_footprints = baseline.get("footprints", {})
    after_footprints = final.get("footprints", {})
    footprint_metrics = (
        (
            "wheel_bytes",
            before_footprints.get("packaging", {}).get("wheel", {}).get("bytes"),
            after_footprints.get("packaging", {}).get("wheel", {}).get("bytes"),
            int(footprint_policy.get("wheel_max_growth_bytes", 0)),
            "bytes",
        ),
        (
            "uv_tool_directory_logical_bytes",
            before_footprints.get("packaging", {})
            .get("uv_tool_directory", {})
            .get("logical_bytes"),
            after_footprints.get("packaging", {})
            .get("uv_tool_directory", {})
            .get("logical_bytes"),
            float(footprint_policy.get("uv_tool_directory_max_growth_percent", 0)),
            "percent",
        ),
        (
            "base_runtime_logical_bytes",
            before_footprints.get("base_runtime", {}).get("logical_bytes"),
            after_footprints.get("base_runtime", {}).get("logical_bytes"),
            int(footprint_policy.get("base_runtime_max_growth_bytes", 0)),
            "bytes",
        ),
        (
            "fully_provisioned_runtime_logical_bytes",
            before_footprints.get("fully_provisioned_runtime", {}).get(
                "logical_bytes"
            ),
            after_footprints.get("fully_provisioned_runtime", {}).get(
                "logical_bytes"
            ),
            int(
                footprint_policy.get(
                    "fully_provisioned_runtime_max_growth_bytes", 0
                )
            ),
            "bytes",
        ),
    )
    for name, before_value, after_value, allowance, allowance_kind in footprint_metrics:
        if before_value is None or after_value is None:
            failures.append(f"missing footprint: {name}")
            continue
        growth = int(after_value) - int(before_value)
        allowed_growth = (
            float(allowance)
            if allowance_kind == "bytes"
            else int(before_value) * float(allowance) / 100.0
        )
        passed = growth <= allowed_growth
        checks.append(
            {
                "kind": "footprint",
                "name": name,
                "baseline": before_value,
                "final": after_value,
                "change_percent": _percent_change(before_value, after_value),
                "allowed_growth": round(allowed_growth),
                "passed": passed,
            }
        )
        if not passed:
            failures.append(f"footprint regression: {name}")

    watch_policy = thresholds.get("watch", {})
    before_watch = baseline.get("watch", {})
    after_watch = final.get("watch", {})
    if before_watch and after_watch:
        idle_fraction = float(after_watch["idle"]["cpu_fraction_one_core"])
        idle_passed = idle_fraction <= float(
            watch_policy["idle_cpu_fraction_one_core_max"]
        )
        before_complete = int(before_watch["change_to_complete_ns"])
        after_complete = int(after_watch["change_to_complete_ns"])
        baseline_mad_value = (
            before_watch.get("dispersion", {})
            .get("change_to_complete_ns", {})
            .get("mad")
        )
        if baseline_mad_value is None:
            failures.append("missing baseline watch change-to-complete MAD")
            baseline_mad = 0
            watch_noise_available = False
        else:
            baseline_mad = int(baseline_mad_value)
            watch_noise_available = True
        latency_allowance = max(
            before_complete
            * float(watch_policy["max_change_to_complete_regression_percent"])
            / 100.0,
            baseline_mad * 3,
        )
        latency_passed = (
            watch_noise_available
            and after_complete - before_complete <= latency_allowance
        )
        checks.append(
            {
                "kind": "watch",
                "name": "idle_and_rebuild",
                "idle_cpu_fraction_one_core": idle_fraction,
                "baseline_change_to_complete_ns": before_complete,
                "final_change_to_complete_ns": after_complete,
                "change_to_complete_percent": _percent_change(
                    before_complete, after_complete
                ),
                "baseline_change_to_complete_mad_ns": baseline_mad,
                "change_to_complete_allowance_ns": round(latency_allowance),
                "idle_passed": idle_passed,
                "latency_passed": latency_passed,
                "passed": idle_passed and latency_passed,
            }
        )
        if not idle_passed or not latency_passed:
            failures.append("watch regression")
    else:
        failures.append("missing watch result")

    return {
        "schema_version": 1,
        "baseline_candidate": baseline.get("candidate_id"),
        "final_candidate": final.get("candidate_id"),
        "baseline_identity": baseline_identity,
        "environment_matches": environment_matches,
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "observations_not_gated": observations_not_gated,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare schema-3 texMini results against frozen thresholds."
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("final", type=Path)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-environment-mismatch", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = compare_results(
            _load_result_pair(args.baseline),
            _load_result_pair(args.final),
            _load(args.thresholds),
            allow_environment_mismatch=args.allow_environment_mismatch,
            baseline_name=args.baseline.name,
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
