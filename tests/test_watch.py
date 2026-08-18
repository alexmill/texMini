from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from texmini import build, model, reporting, watch


class WatchTest(unittest.TestCase):
    def test_watch_snapshot_tracks_project_inputs_not_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            image = root / "figure.png"
            image.write_bytes(b"image")
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"pdf")
            (root / "paper.aux").write_text("generated", encoding="utf-8")
            layout = build.default_build_layout(str(source))

            snapshot = watch.watch_snapshot(root, layout)

        self.assertIn(source.resolve(), snapshot)
        self.assertIn(image.resolve(), snapshot)
        self.assertNotIn(pdf.resolve(), snapshot)
        self.assertFalse(any(path.suffix == ".aux" for path in snapshot))

    def test_watch_snapshot_reuses_inventory_until_directory_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            state = watch._WatchState()

            with patch(
                "texmini.watch._scan_project_paths",
                wraps=watch._scan_project_paths,
            ) as scan:
                first = watch.watch_snapshot(root, layout, state)
                second = watch.watch_snapshot(root, layout, state)

            self.assertEqual(first, second)
            self.assertEqual(scan.call_count, 1)

    def test_watch_snapshot_refreshes_for_creates_renames_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            state = watch._WatchState()
            baseline = watch.watch_snapshot(root, layout, state)

            bibliography = root / "references.bib"
            bibliography.write_text("entry", encoding="utf-8")
            created = watch.watch_snapshot(root, layout, state)
            style = root / "references.sty"
            bibliography.rename(style)
            renamed = watch.watch_snapshot(root, layout, state)
            style.unlink()
            deleted = watch.watch_snapshot(root, layout, state)
            nested = root / "chapters"
            nested.mkdir()
            chapter = nested / "introduction.tex"
            chapter.write_text("chapter", encoding="utf-8")
            nested_created = watch.watch_snapshot(root, layout, state)
            renamed_nested = root / "sections"
            nested.rename(renamed_nested)
            renamed_chapter = renamed_nested / chapter.name
            nested_renamed = watch.watch_snapshot(root, layout, state)

        self.assertNotEqual(created, baseline)
        self.assertIn(bibliography, created)
        self.assertNotIn(bibliography, renamed)
        self.assertIn(style, renamed)
        self.assertEqual(deleted, baseline)
        self.assertIn(chapter, nested_created)
        self.assertNotIn(chapter, nested_renamed)
        self.assertIn(renamed_chapter, nested_renamed)

    def test_watch_snapshot_detects_content_change_without_directory_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "paper.tex"
            source.write_text("first", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            state = watch._WatchState()
            baseline = watch.watch_snapshot(root, layout, state)

            source.write_text("second version", encoding="utf-8")
            with patch.object(state, "directories_changed", return_value=False):
                changed = watch.watch_snapshot(root, layout, state)

        self.assertNotEqual(changed, baseline)

    def test_watch_snapshot_refreshes_fls_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            first_input = root / "first.custom"
            second_input = root / "second.custom"
            first_input.write_text("first", encoding="utf-8")
            second_input.write_text("second", encoding="utf-8")
            fls = root / "paper.fls"
            fls.write_text(f"INPUT {first_input}\n", encoding="utf-8")
            state = watch._WatchState()

            first = watch.watch_snapshot(root, layout, state)
            fls.write_text(f"INPUT {second_input}\n", encoding="utf-8")
            second = watch.watch_snapshot(root, layout, state)

        self.assertIn(first_input, first)
        self.assertNotIn(second_input, first)
        self.assertNotIn(first_input, second)
        self.assertIn(second_input, second)

    def test_watch_snapshot_detects_fls_input_created_after_initial_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            generated = root / "generated.custom"
            fls = root / "paper.fls"
            fls.write_text(f"INPUT {generated}\n", encoding="utf-8")
            state = watch._WatchState()
            baseline = watch.watch_snapshot(root, layout, state)

            generated.write_text("generated", encoding="utf-8")
            changed = watch.watch_snapshot(root, layout, state)

        self.assertNotIn(generated, baseline)
        self.assertIn(generated, changed)

    def test_watch_snapshot_tracks_every_supported_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            expected = {source}
            for index, suffix in enumerate(sorted(watch.WATCH_SUFFIXES)):
                if suffix == ".tex":
                    continue
                path = root / f"dependency-{index}{suffix.upper()}"
                path.touch()
                expected.add(path)
            for name in ("latexmkrc", ".latexmkrc"):
                path = root / name
                path.touch()
                expected.add(path)
            layout = build.default_build_layout(str(source))

            snapshot = watch.watch_snapshot(root, layout)

        self.assertTrue(expected <= snapshot.keys())

    def test_watch_coalesces_one_detected_change_into_one_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            config = model.CliConfig(
                None, False, False, True, True, False, [str(source)], [], str(source)
            )
            outcome = model.BuildOutcome(0, 0.1, True, layout=layout)
            changed = {source.resolve(): (source.stat().st_mtime_ns, 6)}
            with (
                patch("texmini.watch.run_document_build", return_value=outcome) as run,
                patch(
                    "texmini.watch.watch_snapshot",
                    side_effect=[{}, changed, changed],
                ),
                patch(
                    "texmini.watch.sleep",
                    side_effect=[None, None, KeyboardInterrupt],
                ),
                redirect_stdout(io.StringIO()),
            ):
                result = watch.watch_document(
                    config, str(source), reporting.Reporter()
                )

        self.assertEqual(result, 130)
        self.assertEqual(run.call_count, 2)

    def test_watch_returns_130_on_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            config = model.CliConfig(
                None, False, False, True, True, False, [str(source)], [], str(source)
            )
            outcome = model.BuildOutcome(0, 0.1, True, layout=layout)
            output = io.StringIO()
            with (
                patch("texmini.watch.run_document_build", return_value=outcome),
                patch("texmini.watch.watch_snapshot", return_value={}),
                patch("texmini.watch.sleep", side_effect=KeyboardInterrupt),
                redirect_stdout(output),
            ):
                result = watch.watch_document(config, str(source), reporting.Reporter())

        self.assertEqual(result, 130)
        self.assertIn("Watching", output.getvalue())
        self.assertIn("Stopped watching", output.getvalue())

    def test_watch_stops_after_package_manager_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("source", encoding="utf-8")
            layout = build.default_build_layout(str(source))
            config = model.CliConfig(
                None, False, False, True, True, False, [str(source)], [], str(source)
            )
            outcome = model.BuildOutcome(
                7, 0.1, False, failure_kind="install_failed", layout=layout
            )
            with (
                patch("texmini.watch.run_document_build", return_value=outcome),
                patch("texmini.watch.watch_snapshot") as snapshot,
                redirect_stderr(io.StringIO()),
            ):
                result = watch.watch_document(config, str(source), reporting.Reporter())

        self.assertEqual(result, 7)
        snapshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
