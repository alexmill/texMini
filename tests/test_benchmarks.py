from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from benchmarks import benchmark, command_worker, compare, watch_worker
from texmini import runtime


class BenchmarkFixtureTest(unittest.TestCase):
    def test_main_refuses_mixed_tree_and_preserves_previous_result_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            old_raw = root / "old.raw.jsonl"
            old_raw.write_text("old\n", encoding="utf-8")
            old_result = {"raw_samples": old_raw.name, "value": "old"}
            output.write_text(json.dumps(old_result), encoding="utf-8")
            arguments = argparse.Namespace(
                suite="startup",
                candidate_id="test",
                target_root=benchmark.ROOT,
                repeats=1,
                startup_repeats=1,
                package_repeats=1,
                watch_idle_seconds=0.1,
                output=output,
                workspace=None,
                runtime_template=None,
                skip_packaging=True,
                skip_package_recovery=True,
                keep_workspace=False,
            )
            git_states = [
                {"tree_content_sha256": "before"},
                {"tree_content_sha256": "after"},
            ]

            with (
                patch("benchmarks.benchmark.parse_args", return_value=arguments),
                patch("benchmarks.benchmark._git_metadata", side_effect=git_states),
                patch("benchmarks.benchmark._measure_startup"),
                self.assertRaisesRegex(RuntimeError, "changed during measurement"),
            ):
                benchmark.main()

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")), old_result
            )
            self.assertEqual(old_raw.read_text(encoding="utf-8"), "old\n")

    def test_main_refuses_harness_tree_change_for_separate_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "candidate"
            target.mkdir()
            arguments = argparse.Namespace(
                suite="startup",
                candidate_id="test",
                target_root=target,
                repeats=1,
                startup_repeats=1,
                package_repeats=1,
                watch_idle_seconds=0.1,
                output=root / "result.json",
                workspace=None,
                runtime_template=None,
                skip_packaging=True,
                skip_package_recovery=True,
                keep_workspace=False,
            )
            git_states = [
                {"tree_content_sha256": "candidate"},
                {"tree_content_sha256": "harness-before"},
                {"tree_content_sha256": "candidate"},
                {"tree_content_sha256": "harness-after"},
            ]
            manifest = {
                "asset": "TinyTeX-1-darwin-v2099.01.tar.xz",
                "bundle": "TinyTeX-1",
            }

            with (
                patch("benchmarks.benchmark.parse_args", return_value=arguments),
                patch("benchmarks.benchmark._git_metadata", side_effect=git_states),
                patch("benchmarks.benchmark._candidate_version", return_value="1"),
                patch(
                    "benchmarks.benchmark._candidate_runtime_manifest",
                    return_value=manifest,
                ),
                patch("benchmarks.benchmark._measure_startup"),
                self.assertRaisesRegex(RuntimeError, "harness inputs changed"),
            ):
                benchmark.main()

    def test_main_records_both_git_roles_without_refingerprinting_same_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            arguments = argparse.Namespace(
                suite="startup",
                candidate_id="test",
                target_root=benchmark.ROOT,
                repeats=1,
                startup_repeats=1,
                package_repeats=1,
                watch_idle_seconds=0.1,
                output=output,
                workspace=None,
                runtime_template=None,
                skip_packaging=True,
                skip_package_recovery=True,
                keep_workspace=False,
            )
            git_states = [
                {"commit": "same", "tree_content_sha256": "stable"},
                {"commit": "same", "tree_content_sha256": "stable"},
            ]
            manifest = {
                "asset": "TinyTeX-1-darwin-v2099.01.tar.xz",
                "bundle": "TinyTeX-1",
            }

            def create_raw(supervisor, *_args) -> None:
                supervisor.raw_path.touch()

            with (
                patch("benchmarks.benchmark.parse_args", return_value=arguments),
                patch(
                    "benchmarks.benchmark._git_metadata", side_effect=git_states
                ) as git_metadata,
                patch("benchmarks.benchmark._candidate_version", return_value="1"),
                patch(
                    "benchmarks.benchmark._candidate_runtime_manifest",
                    return_value=manifest,
                ),
                patch("benchmarks.benchmark._measure_startup", side_effect=create_raw),
            ):
                returncode = benchmark.main()

            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(returncode, 0)
        self.assertEqual(git_metadata.call_count, 2)
        self.assertEqual(result["git"]["tree_content_sha256"], "stable")
        self.assertEqual(result["harness_git"]["tree_content_sha256"], "stable")
        self.assertTrue(result["git"]["stable_during_run"])
        self.assertTrue(result["harness_git"]["stable_during_run"])

    def test_result_publication_preserves_previous_pair_until_atomic_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            old_raw = root / "old.raw.jsonl"
            old_raw.write_text("old\n", encoding="utf-8")
            output.write_text(
                json.dumps({"raw_samples": old_raw.name, "value": "old"}),
                encoding="utf-8",
            )
            abandoned_raw = root / "abandoned.raw.jsonl"
            abandoned_raw.write_text("partial\n", encoding="utf-8")

            # Merely starting another run cannot alter the published pair.
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["value"], "old"
            )
            self.assertEqual(old_raw.read_text(encoding="utf-8"), "old\n")

            new_raw = root / "new.raw.jsonl"
            new_raw.write_text("complete\n", encoding="utf-8")
            benchmark.publish_result_pair(
                output,
                new_raw,
                {"raw_samples": new_raw.name, "value": "new"},
            )

            published = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(published["value"], "new")
            self.assertEqual(published["raw_samples"], new_raw.name)
            self.assertFalse(old_raw.exists())
            self.assertEqual(abandoned_raw.read_text(encoding="utf-8"), "partial\n")

    def test_comparator_load_rejects_raw_pair_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "result.json"
            raw_path = root / "result.raw.jsonl"
            samples = [
                {
                    "scenario": "one",
                    "state": "warm",
                    "semantic_success": True,
                    "instrumented": False,
                    "returncode": 0,
                    "expected_returncode": 0,
                    "wall_time_ns": 123,
                    "resources": {
                        "user_cpu_ns": 10,
                        "system_cpu_ns": 5,
                        "peak_child_rss_bytes": 100,
                    },
                    "process_tree": {"peak_tree_rss_bytes": 120},
                }
            ]
            raw_bytes = (
                json.dumps(samples[0], sort_keys=True) + "\n"
            ).encode("utf-8")
            raw_path.write_bytes(raw_bytes)
            result_path.write_text(
                json.dumps(
                    {
                        "samples": samples,
                        "raw_samples": raw_path.name,
                        "raw_samples_bytes": len(raw_bytes),
                        "raw_samples_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                        "summary": benchmark._scenario_summary(samples),
                    }
                ),
                encoding="utf-8",
            )

            loaded = compare._load_result_pair(result_path)
            raw_path.write_text("corrupted\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "byte count does not match"):
                compare._load_result_pair(result_path)

        self.assertEqual(loaded["samples"], samples)

    def test_comparator_load_rejects_tampered_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "result.json"
            raw_path = root / "result.raw.jsonl"
            samples = [
                {
                    "scenario": "one",
                    "state": "warm",
                    "semantic_success": True,
                    "instrumented": False,
                    "returncode": 0,
                    "expected_returncode": 0,
                    "wall_time_ns": 123,
                    "resources": {},
                    "process_tree": {},
                }
            ]
            raw_bytes = (json.dumps(samples[0], sort_keys=True) + "\n").encode(
                "utf-8"
            )
            raw_path.write_bytes(raw_bytes)
            summary = benchmark._scenario_summary(samples)
            summary["one/warm"]["wall_time_ns"]["median"] = 1
            result_path.write_text(
                json.dumps(
                    {
                        "samples": samples,
                        "summary": summary,
                        "raw_samples": raw_path.name,
                        "raw_samples_bytes": len(raw_bytes),
                        "raw_samples_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "summary does not match"):
                compare._load_result_pair(result_path)

    def test_explicit_workspace_must_be_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "stale-package-map.json").write_text(
                "{}", encoding="utf-8"
            )

            with self.assertRaisesRegex(SystemExit, "--workspace must be empty"):
                benchmark._prepare_explicit_workspace(workspace)

    def test_candidate_version_and_manifest_come_from_target_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            package = target / "src" / "texmini"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                "__version__ = '99.1-target'\n", encoding="utf-8"
            )
            (package / "runtime.py").write_text(
                """from types import SimpleNamespace
def load_runtime_manifest():
    asset = SimpleNamespace(filename='TinyTeX-1-darwin-v2099.01.tar.xz', sha256='target-sha')
    return SimpleNamespace(schema_version=7, tinytex_version='2099.01', repository='https://target.invalid', assets={'target-platform': asset})
def tinytex_platform_key():
    return 'target-platform'
""",
                encoding="utf-8",
            )
            manifest_bytes = b'{"source":"target checkout"}\n'
            (package / "runtime_manifest.json").write_bytes(manifest_bytes)

            candidate_version = benchmark._candidate_version(target)
            manifest = benchmark._candidate_runtime_manifest(target)

        self.assertEqual(candidate_version, "99.1-target")
        self.assertEqual(manifest["tinytex_version"], "2099.01")
        self.assertEqual(manifest["asset_sha256"], "target-sha")
        self.assertEqual(
            manifest["manifest_sha256"],
            hashlib.sha256(manifest_bytes).hexdigest(),
        )

    def test_pinned_asset_lookup_uses_runtime_manifest_for_every_format(self) -> None:
        manifest = runtime.RuntimeManifest(
            1,
            "2099.01",
            "https://packages.example.test/tlnet",
            {
                "windows-x86_64": runtime.RuntimeAsset(
                    "TinyTeX-1-windows-v2099.01.exe", "a" * 64, "windows-sfx"
                )
            },
        )
        response = MagicMock()
        response.headers = {"Content-Length": "12345"}
        response.__enter__.return_value = response
        with (
            patch("benchmarks.benchmark.runtime.load_runtime_manifest", return_value=manifest),
            patch("benchmarks.benchmark.runtime.tinytex_platform_key", return_value="windows-x86_64"),
            patch("benchmarks.benchmark.urllib.request.urlopen", return_value=response) as urlopen,
        ):
            asset = benchmark.tinytex_asset()

        self.assertEqual(asset, ("TinyTeX-1-windows-v2099.01.exe", 12345))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "HEAD")
        self.assertEqual(
            request.full_url,
            "https://github.com/rstudio/tinytex-releases/releases/download/"
            "v2099.01/TinyTeX-1-windows-v2099.01.exe",
        )

    def test_bundle_name_is_derived_from_pinned_asset(self) -> None:
        self.assertEqual(
            benchmark.tinytex_bundle_name("TinyTeX-1-darwin-v2026.08.tar.xz"),
            "TinyTeX-1",
        )

    def test_directory_size_counts_hard_links_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"x" * 8192)
            os.link(source, root / "linked")

            self.assertEqual(benchmark.directory_size(root), 8192)
            source_stat = source.stat()
            allocated_size = (
                getattr(source_stat, "st_blocks", (source_stat.st_size + 511) // 512)
                * 512
            )
            self.assertEqual(
                benchmark.directory_size(root, allocated=True),
                allocated_size,
            )

    def test_runtime_content_identity_changes_with_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / "runtime-file"
            content.write_text("before", encoding="utf-8")
            before = benchmark.directory_content_identity(root)
            content.write_text("after", encoding="utf-8")
            after = benchmark.directory_content_identity(root)

        self.assertNotEqual(before["sha256"], after["sha256"])

    def test_runtime_package_inventory_hashes_names_and_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tlpkg = root / "tlpkg"
            tlpkg.mkdir()
            database = tlpkg / "texlive.tlpdb"
            database.write_text(
                "name package-b\nrevision 20\ncontainersize 99\n\n"
                "name package-a\nrevision 10\n\n",
                encoding="utf-8",
            )
            before = benchmark.runtime_package_inventory(root)
            database.write_text(
                "name package-a\nrevision 10\nvolatile-field changed\n\n"
                "name package-b\nrevision 20\n\n",
                encoding="utf-8",
            )
            reordered = benchmark.runtime_package_inventory(root)
            database.write_text(
                "name package-a\nrevision 11\n\n"
                "name package-b\nrevision 20\n\n",
                encoding="utf-8",
            )
            changed = benchmark.runtime_package_inventory(root)

        self.assertEqual(before["sha256"], reordered["sha256"])
        self.assertNotEqual(before["sha256"], changed["sha256"])
        self.assertEqual(before["package_count"], 2)

    def test_random_package_fixture_is_seeded_and_unique(self) -> None:
        first = benchmark.random_package_selection()
        second = benchmark.random_package_selection()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(set(first)), 10)

    def test_bibliography_fixture_has_seeded_overdispersed_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            benchmark.write_fixture("bibliography-generated", destination)
            bibliography = (destination / "references.bib").read_text(encoding="utf-8")
            source = (destination / "bibliography-generated.tex").read_text(
                encoding="utf-8"
            )
            count = benchmark.bibliography_entry_count()

        self.assertGreaterEqual(count, 8)
        self.assertEqual(bibliography.count("@article{"), count)
        self.assertEqual(source.count("\\cite{"), count)

    def test_common_and_random_package_fixtures_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            common = destination / "common"
            random_packages = destination / "random"
            benchmark.write_fixture("common", common)
            benchmark.write_fixture("random-packages", random_packages)

            common_source = (common / "common.tex").read_text(encoding="utf-8")
            random_source = (random_packages / "random-packages.tex").read_text(
                encoding="utf-8"
            )

        self.assertIn("Common packages", common_source)
        self.assertIn(",".join(benchmark.random_package_selection()), random_source)

    def test_full_fixture_matrix_names_specialty_artifacts_and_synctex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = benchmark.write_fixture(
                "custom-layout-synctex", Path(directory)
            )

        self.assertIn("-synctex=1", fixture.arguments)
        self.assertIn("build/publication.pdf", fixture.required_artifacts)
        self.assertTrue(
            any("synctex.gz" in artifact for artifact in fixture.required_artifacts)
        )
        for name in benchmark.DEFAULT_FUNCTIONAL_FIXTURES:
            with tempfile.TemporaryDirectory() as directory:
                generated = benchmark.write_fixture(name, Path(directory))
            self.assertTrue(generated.required_artifacts, name)

    def test_engine_fixtures_require_the_directed_engine(self) -> None:
        fixtures = benchmark.ROOT / "tests" / "fixtures" / "engine-directives"
        self.assertIn(
            "\\luatexversion",
            (fixtures / "lualatex.tex").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "\\XeTeXversion",
            (fixtures / "xelatex.tex").read_text(encoding="utf-8"),
        )

    def test_one_shot_worker_records_wall_cpu_rss_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "command.log"
            result = command_worker.run(
                {
                    "command": [sys.executable, "-c", "print('measured')"],
                    "cwd": directory,
                    "env": os.environ,
                    "output_path": os.fspath(output),
                }
            )

        self.assertEqual(result["returncode"], 0)
        self.assertGreater(result["wall_time_ns"], 0)
        self.assertEqual(result["failure_tail"], [])
        self.assertGreater(result["output_bytes"], 0)
        if os.name == "posix":
            self.assertGreater(result["resources"]["peak_child_rss_bytes"], 0)

    def test_worker_does_not_import_psutil_after_launching_timed_child(self) -> None:
        real_import = __import__
        late_psutil_imports: list[str] = []

        def track_import(name, *args, **kwargs):
            if name == "psutil":
                late_psutil_imports.append(name)
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "command.log"
            with patch("builtins.__import__", side_effect=track_import):
                result = command_worker.run(
                    {
                        "command": [sys.executable, "-c", "pass"],
                        "cwd": directory,
                        "env": os.environ,
                        "output_path": os.fspath(output),
                    }
                )

        self.assertIsNotNone(command_worker._psutil)
        self.assertEqual(late_psutil_imports, [])
        self.assertEqual(
            result["process_tree"]["backend"], "psutil sampled descendant tree"
        )

    def test_worker_wall_clock_excludes_resource_sampler_shutdown_lag(self) -> None:
        def delayed_sampler(process, stop):
            self.assertTrue(stop.wait(timeout=2))
            time.sleep(0.12)
            return {
                "backend": "test sampler",
                "sample_interval_seconds": 0.005,
                "peak_tree_rss_bytes": 1,
                "unique_process_count": 1,
            }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "command.log"
            started_ns = time.perf_counter_ns()
            with patch(
                "benchmarks.command_worker._sample_process_tree",
                side_effect=delayed_sampler,
            ):
                result = command_worker.run(
                    {
                        "command": [sys.executable, "-c", "pass"],
                        "cwd": directory,
                        "env": os.environ,
                        "output_path": os.fspath(output),
                    }
                )
            caller_elapsed_ns = time.perf_counter_ns() - started_ns

        self.assertEqual(result["returncode"], 0)
        self.assertGreaterEqual(
            caller_elapsed_ns - result["wall_time_ns"], 100_000_000
        )

    def test_environment_request_never_serializes_unchanged_inherited_secrets(self) -> None:
        secret = "sentinel-secret-value-that-must-not-reach-a-request-file"
        with patch.dict(
            os.environ,
            {"TEXMINI_BENCHMARK_SENTINEL_TOKEN": secret},
            clear=False,
        ):
            env = dict(os.environ)
            env["TEXMINI_TRACE"] = "/tmp/trace.jsonl"
            request = benchmark.environment_request(env)

        serialized = json.dumps(request)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("TEXMINI_BENCHMARK_SENTINEL_TOKEN", serialized)
        self.assertEqual(
            request["env_overrides"], {"TEXMINI_TRACE": "/tmp/trace.jsonl"}
        )

    def test_supervisor_fails_semantics_when_required_artifact_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = benchmark.Supervisor(
                benchmark.ROOT, root, root / "raw.jsonl", "test"
            )
            sample = supervisor.run(
                "artifact",
                "missing",
                1,
                [sys.executable, "-c", "print('command succeeded')"],
                root,
                dict(os.environ),
                required_artifacts=("required.pdf",),
            )

        self.assertFalse(sample["semantic_success"])
        self.assertFalse(
            sample["semantic_assertions"]["required_artifacts"]["required.pdf"]
        )

    def test_visible_incremental_edit_is_inside_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "document.tex"
            source.write_text(
                "\\documentclass{article}\n\\begin{document}\n"
                "Original.\n\\end{document}\n",
                encoding="utf-8",
            )

            marker = benchmark._apply_visible_incremental_edit(source, 4)
            updated = source.read_text(encoding="utf-8")

        self.assertIn(marker, updated)
        self.assertLess(updated.index(marker), updated.index("\\end{document}"))
        self.assertIn("\\par\\noindent", updated)

    def test_incremental_repeats_restore_the_same_noop_source(self) -> None:
        incremental_sources: list[str] = []

        class FakeSupervisor:
            def __init__(self, workspace: Path) -> None:
                self.workspace = workspace

            def environment(self, _runtime: Path, _package_map: Path) -> dict[str, str]:
                return {}

            def command(self, fixture: benchmark.Fixture) -> list[str]:
                return ["texmini", fixture.tex_file]

            def run(
                self,
                _scenario: str,
                state: str,
                iteration: int,
                _command: list[str],
                cwd: Path,
                _env: dict[str, str],
                **_options: object,
            ) -> dict[str, object]:
                pdf = cwd / "simple.pdf"
                pdf.write_bytes(f"sample-{state}-{iteration}".encode())
                if state == "project_incremental_one_line":
                    incremental_sources.append(
                        (cwd / "simple.tex").read_text(encoding="utf-8")
                    )
                return {}

        def prepare_noop(*_args: object, cwd: Path, **_kwargs: object) -> MagicMock:
            (cwd / "simple.pdf").write_bytes(b"baseline")
            return MagicMock(returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as directory:
            supervisor = FakeSupervisor(Path(directory))
            with patch(
                "benchmarks.benchmark.subprocess.run", side_effect=prepare_noop
            ) as setup:
                benchmark._measure_build_states(
                    supervisor, Path("runtime"), Path("map"), 2, ["simple"]
                )

        self.assertEqual(setup.call_count, 3)
        self.assertEqual(len(incremental_sources), 2)
        for iteration, source in enumerate(incremental_sources, 1):
            self.assertEqual(source.count("texMini benchmark visible edit"), 1)
            self.assertIn(f"texMini benchmark visible edit {iteration}", source)

    def test_watch_edit_and_pdf_evidence_require_visible_fresh_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "document.tex"
            pdf = root / "document.pdf"
            source.write_text(
                "\\documentclass{article}\n\\begin{document}\n"
                "Original.\n\\end{document}\n",
                encoding="utf-8",
            )
            pdf.write_bytes(b"before")
            before_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()

            marker = watch_worker._apply_visible_edit(source)
            observed_before = watch_worker._file_sha256(pdf)
            pdf.write_bytes(b"after")
            changed = watch_worker._pdf_change_evidence(
                pdf, before_sha256, observed_before
            )
            stale = watch_worker._pdf_change_evidence(
                pdf, changed["after_sha256"], changed["after_sha256"]
            )
            updated = source.read_text(encoding="utf-8")

        self.assertLess(updated.index(marker), updated.index("\\end{document}"))
        self.assertTrue(changed["before_matches_request"])
        self.assertTrue(changed["changed"])
        self.assertFalse(stale["changed"])

    def test_supervisor_requires_incremental_output_content_to_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "document.pdf"
            artifact.write_bytes(b"unchanged")
            before_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
            supervisor = benchmark.Supervisor(
                benchmark.ROOT, root, root / "raw.jsonl", "test"
            )

            stale = supervisor.run(
                "incremental",
                "stale",
                1,
                [sys.executable, "-c", "pass"],
                root,
                dict(os.environ),
                required_changed_artifacts={"document.pdf": before_sha256},
            )
            fresh = supervisor.run(
                "incremental",
                "fresh",
                1,
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('document.pdf').write_bytes(b'fresh')",
                ],
                root,
                dict(os.environ),
                required_changed_artifacts={"document.pdf": before_sha256},
            )

        self.assertFalse(stale["semantic_success"])
        stale_evidence = stale["semantic_assertions"]["required_changed_artifacts"]
        self.assertFalse(stale_evidence["document.pdf"]["changed"])
        self.assertTrue(fresh["semantic_success"])
        fresh_evidence = fresh["semantic_assertions"]["required_changed_artifacts"]
        self.assertTrue(fresh_evidence["document.pdf"]["changed"])

    def test_summary_excludes_instrumented_and_failed_samples(self) -> None:
        samples = [
            {
                "wall_time_ns": value,
                "returncode": 0,
                "expected_returncode": 0,
                "semantic_success": True,
                "instrumented": False,
                "resources": {},
            }
            for value in (100, 110, 120)
        ]
        samples.append(
            {
                "wall_time_ns": 1,
                "returncode": 0,
                "expected_returncode": 0,
                "semantic_success": True,
                "instrumented": True,
                "resources": {},
            }
        )

        summary = benchmark.summarize_samples(samples)

        self.assertEqual(summary["valid_samples"], 3)
        self.assertEqual(summary["wall_time_ns"]["median"], 110)

    def test_summary_rejects_incomplete_tree_rss_sampling(self) -> None:
        samples = [
            {
                "wall_time_ns": 100 + iteration,
                "returncode": 0,
                "expected_returncode": 0,
                "semantic_success": True,
                "instrumented": False,
                "resources": {"peak_child_rss_bytes": 1000 + iteration},
                "process_tree": {"peak_tree_rss_bytes": tree_rss},
            }
            for iteration, tree_rss in enumerate((900, 0, 1100))
        ]

        summary = benchmark.summarize_samples(samples)

        self.assertIsNone(summary["peak_tree_rss_bytes_median"])
        self.assertEqual(summary["peak_tree_rss_valid_samples"], 2)
        self.assertEqual(summary["peak_child_rss_bytes_median"], 1001)

    def test_watch_summary_uses_uninstrumented_medians_and_reports_noise(self) -> None:
        samples = []
        for iteration, ready, complete in ((1, 100, 500), (2, 110, 520), (3, 900, 540)):
            samples.append(
                {
                    "iteration": iteration,
                    "returncode": 130,
                    "semantic_success": True,
                    "startup_to_ready_ns": ready,
                    "idle": {
                        "wall_time_ns": 1_000,
                        "tree_cpu_time_ns": 2,
                        "cpu_fraction_one_core": 0.002,
                        "peak_tree_rss_bytes": 10,
                        "sample_interval_seconds": 0.005,
                    },
                    "change_to_detection_ns": complete - 100,
                    "detection_to_complete_ns": 100,
                    "change_to_complete_ns": complete,
                }
            )
        attribution = {
            "semantic_success": True,
            "trace_summary": {"events": 12},
            "startup_to_ready_ns": 1,
            "change_to_complete_ns": 1,
        }

        summary = benchmark.summarize_watch_results(samples, attribution)

        self.assertEqual(summary["valid_samples"], 3)
        self.assertEqual(summary["startup_to_ready_ns"], 110)
        self.assertEqual(summary["change_to_complete_ns"], 520)
        self.assertEqual(summary["dispersion"]["startup_to_ready_ns"]["mad"], 10)
        self.assertEqual(summary["trace_summary"], {"events": 12})
        self.assertTrue(summary["semantic_success"])

    @staticmethod
    def _comparison_result(
        wall: int,
        *,
        scenario: str = "scenario/state",
        rss: int = 1_000,
        tool_size: int = 1_000,
        fully_provisioned_size: int = 2_000,
        scenario_samples: int = 3,
        watch_complete: int = 1_000,
        watch_mad: int = 10,
        watch_samples: int = 3,
        watch_returncode: int = 130,
    ) -> dict[str, object]:
        scenario_name, state = scenario.split("/", 1)
        raw_samples = [
            {
                "scenario": scenario_name,
                "state": state,
                "iteration": iteration,
                "instrumented": False,
                "semantic_success": True,
                "returncode": 0,
                "expected_returncode": 0,
                "network": {"dependent": False},
            }
            for iteration in range(1, scenario_samples + 1)
        ]
        watch_raw = [
            {
                "iteration": iteration,
                "returncode": watch_returncode,
                "semantic_success": watch_returncode == 130,
                "pdf_change_evidence": {"changed": watch_returncode == 130},
            }
            for iteration in range(1, watch_samples + 1)
        ]
        return {
            "schema_version": 3,
            "candidate_id": str(wall),
            "git": {"commit": "frozen", "tree_content_sha256": "tree"},
            "harness_git": {
                "commit": "harness",
                "tree_content_sha256": "harness-tree",
            },
            "host": {
                "system": "test",
                "release": "test",
                "machine": "test",
                "processor": "test",
                "cpu": "test cpu",
                "logical_cpu_count": 4,
                "memory_bytes": 1_000_000,
                "filesystem": "test",
                "filesystem_type": "test",
                "python": "test",
                "uv": "test",
                "dependency_versions": {"psutil": "test"},
            },
            "runtime_manifest": {
                "schema_version": 1,
                "tinytex_version": "test",
                "repository": "test",
                "platform_key": "test",
                "asset": "test",
                "asset_sha256": "test",
                "manifest_sha256": "test",
            },
            "configuration": {
                "suite": "full",
                "repeats": 3,
                "startup_repeats": 3,
                "package_repeats": 1,
                "watch_repeats": 3,
                "watch_idle_seconds": 1,
                "skip_packaging": False,
                "skip_package_recovery": False,
                "runtime_template": "same",
            },
            "samples": raw_samples,
            "summary": {
                scenario: {
                    "valid_samples": scenario_samples,
                    "wall_time_ns": {"median": wall, "mad": 10},
                    "peak_child_rss_bytes_median": rss,
                }
            },
            "footprints": {
                "packaging": {
                    "wheel": {"bytes": 100},
                    "uv_tool_directory": {"logical_bytes": tool_size},
                },
                "base_runtime": {
                    "logical_bytes": 1_000,
                    "regular_files": 10,
                    "content_identity": {"sha256": "runtime"},
                },
                "fully_provisioned_runtime": {
                    "logical_bytes": fully_provisioned_size,
                    "package_inventory": {
                        "package_count": 2,
                        "sha256": "inventory",
                    },
                },
            },
            "watch": {
                "valid_samples": sum(
                    sample["semantic_success"] for sample in watch_raw
                ),
                "semantic_success": all(
                    sample["semantic_success"] for sample in watch_raw
                ),
                "samples": watch_raw,
                "idle": {"cpu_fraction_one_core": 0.01},
                "change_to_complete_ns": watch_complete,
                "dispersion": {
                    "change_to_complete_ns": {"mad": watch_mad}
                },
            },
        }

    @staticmethod
    def _comparison_thresholds() -> dict[str, object]:
        return {
            "scenarios": {
                "scenario/state": {
                    "max_wall_regression_percent": 7,
                    "max_peak_rss_regression_percent": 10,
                }
            },
            "default_scenario": {
                "max_wall_regression_percent": 10,
                "max_peak_rss_regression_percent": 10,
            },
            "footprints": {
                "wheel_max_growth_bytes": 5,
                "uv_tool_directory_max_growth_percent": 2,
                "base_runtime_max_growth_bytes": 0,
                "fully_provisioned_runtime_max_growth_bytes": 4_096,
            },
            "watch": {
                "idle_cpu_fraction_one_core_max": 0.02,
                "max_change_to_complete_regression_percent": 15,
            },
        }

    def test_comparison_applies_each_threshold_without_aggregate_score(self) -> None:
        thresholds = self._comparison_thresholds()
        passing = compare.compare_results(
            self._comparison_result(1_000),
            self._comparison_result(900, rss=1_050, tool_size=1_020),
            thresholds,
        )
        failing = compare.compare_results(
            self._comparison_result(1_000),
            self._comparison_result(1_200, rss=1_050, tool_size=1_020),
            thresholds,
        )

        self.assertTrue(passing["passed"])
        self.assertTrue(passing["checks"][0]["improvement_exceeds_noise"])
        self.assertFalse(failing["passed"])
        self.assertIn("performance regression: scenario/state", failing["failures"])

    def test_comparison_falls_back_when_either_tree_rss_sample_is_incomplete(self) -> None:
        baseline = self._comparison_result(100, rss=1000)
        final = self._comparison_result(90, rss=1050)
        baseline["summary"]["scenario/state"]["peak_tree_rss_bytes_median"] = 900
        final["summary"]["scenario/state"]["peak_tree_rss_bytes_median"] = None

        comparison = compare.compare_results(
            baseline, final, self._comparison_thresholds()
        )
        scenario = next(
            check for check in comparison["checks"] if check["kind"] == "scenario"
        )

        self.assertTrue(comparison["passed"])
        self.assertEqual(scenario["rss_backend"], "waited child maximum")
        self.assertEqual(scenario["baseline_peak_rss_bytes"], 1000)
        self.assertEqual(scenario["final_peak_rss_bytes"], 1050)

    def test_comparison_gates_all_repeated_local_scenarios_by_default(self) -> None:
        thresholds = self._comparison_thresholds()
        thresholds["scenarios"] = {}
        comparison = compare.compare_results(
            self._comparison_result(100, scenario="specialty/noop"),
            self._comparison_result(150, scenario="specialty/noop"),
            thresholds,
        )

        self.assertFalse(comparison["passed"])
        self.assertIn("performance regression: specialty/noop", comparison["failures"])

    def test_watch_latency_allows_larger_of_percent_and_three_mads(self) -> None:
        comparison = compare.compare_results(
            self._comparison_result(100, watch_complete=1_000, watch_mad=100),
            self._comparison_result(100, watch_complete=1_250, watch_mad=1),
            self._comparison_thresholds(),
        )
        watch_check = next(
            check for check in comparison["checks"] if check["kind"] == "watch"
        )

        self.assertTrue(comparison["passed"])
        self.assertEqual(watch_check["change_to_complete_allowance_ns"], 300)

    def test_comparison_rejects_bad_watch_returncode_and_count(self) -> None:
        bad_returncode = compare.compare_results(
            self._comparison_result(100),
            self._comparison_result(100, watch_returncode=-2),
            self._comparison_thresholds(),
        )
        bad_count = compare.compare_results(
            self._comparison_result(100),
            self._comparison_result(100, watch_samples=2),
            self._comparison_thresholds(),
        )

        self.assertFalse(bad_returncode["passed"])
        self.assertTrue(
            any("return code 130" in failure for failure in bad_returncode["failures"])
        )
        self.assertFalse(bad_count["passed"])
        self.assertTrue(
            any("watch sample count mismatch" in failure for failure in bad_count["failures"])
        )

    def test_comparison_requires_watch_pdf_change_evidence(self) -> None:
        final = self._comparison_result(100)
        final["watch"]["samples"][0]["pdf_change_evidence"] = {"changed": False}
        comparison = compare.compare_results(
            self._comparison_result(100), final, self._comparison_thresholds()
        )

        self.assertFalse(comparison["passed"])
        self.assertTrue(
            any("changed-PDF evidence" in failure for failure in comparison["failures"])
        )

    def test_comparison_rejects_scenario_count_and_semantic_failures(self) -> None:
        final = self._comparison_result(100, scenario_samples=2)
        final["samples"][0]["semantic_success"] = False
        final["summary"]["scenario/state"]["valid_samples"] = 1
        del final["summary"]["scenario/state"]["wall_time_ns"]
        comparison = compare.compare_results(
            self._comparison_result(100), final, self._comparison_thresholds()
        )

        self.assertFalse(comparison["passed"])
        self.assertTrue(
            any("failed samples" in failure for failure in comparison["failures"])
        )
        self.assertTrue(
            any("valid sample count mismatch" in failure for failure in comparison["failures"])
        )
        self.assertIn(
            "missing valid wall-time summary: scenario/state",
            comparison["failures"],
        )

    def test_comparison_gates_fully_provisioned_runtime_growth(self) -> None:
        comparison = compare.compare_results(
            self._comparison_result(100, fully_provisioned_size=10_000),
            self._comparison_result(100, fully_provisioned_size=14_097),
            self._comparison_thresholds(),
        )

        self.assertFalse(comparison["passed"])
        self.assertIn(
            "footprint regression: fully_provisioned_runtime_logical_bytes",
            comparison["failures"],
        )

    def test_comparison_enforces_frozen_baseline_name_and_commit(self) -> None:
        baseline = self._comparison_result(100)
        thresholds = self._comparison_thresholds()
        thresholds["baseline"] = "frozen.json"
        thresholds["baseline_git_commit"] = "frozen"
        thresholds["baseline_candidate_id"] = "100"
        thresholds["baseline_tree_content_sha256"] = "tree"

        report = compare.compare_results(
            baseline,
            self._comparison_result(100),
            thresholds,
            baseline_name="frozen.json",
        )
        with self.assertRaisesRegex(ValueError, "thresholds require baseline"):
            compare.compare_results(
                baseline,
                self._comparison_result(100),
                thresholds,
                baseline_name="substitute.json",
            )
        wrong_tree = self._comparison_result(100)
        wrong_tree["git"]["tree_content_sha256"] = "substitute"
        with self.assertRaisesRegex(ValueError, "thresholds require baseline tree"):
            compare.compare_results(
                wrong_tree,
                self._comparison_result(100),
                thresholds,
                baseline_name="frozen.json",
            )

        self.assertTrue(report["passed"])
        self.assertEqual(report["baseline_identity"]["git_commit"], "frozen")

    def test_environment_identity_includes_cpu_dependencies_and_runtime_content(self) -> None:
        baseline = self._comparison_result(100)
        for mutation in (
            lambda result: result["host"].update({"cpu": "different"}),
            lambda result: result["host"]["dependency_versions"].update(
                {"psutil": "different"}
            ),
            lambda result: result["footprints"]["base_runtime"][
                "content_identity"
            ].update({"sha256": "different"}),
            lambda result: result["footprints"]["fully_provisioned_runtime"][
                "package_inventory"
            ].update({"sha256": "different"}),
            lambda result: result["harness_git"].update(
                {"tree_content_sha256": "different"}
            ),
        ):
            final = self._comparison_result(100)
            mutation(final)
            with self.assertRaisesRegex(ValueError, "environments do not match"):
                compare.compare_results(
                    baseline, final, self._comparison_thresholds()
                )

        incomplete = self._comparison_result(100)
        del incomplete["footprints"]["fully_provisioned_runtime"][
            "package_inventory"
        ]
        with self.assertRaisesRegex(
            ValueError, "fully provisioned installed-package inventory"
        ):
            compare.compare_results(
                baseline, incomplete, self._comparison_thresholds()
            )


if __name__ == "__main__":
    unittest.main()
