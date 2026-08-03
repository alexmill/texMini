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
