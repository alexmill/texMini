from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from texmini import __version__, _download, model


class _BinaryStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


class DownloaderTest(unittest.TestCase):
    def test_download_streams_to_an_atomic_destination(self) -> None:
        content = b"runtime payload"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.tar.xz"
            with patch(
                "urllib.request.urlopen", return_value=io.BytesIO(content)
            ) as urlopen:
                _download.download(
                    "https://example.test/asset.tar.xz",
                    destination,
                    hashlib.sha256(content).hexdigest(),
                )

            request = urlopen.call_args.args[0]
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(request.get_header("User-agent"), f"texmini/{__version__}")
            self.assertEqual(
                urlopen.call_args.kwargs["timeout"], _download.DOWNLOAD_TIMEOUT
            )

    def test_download_to_stdout_uses_binary_output(self) -> None:
        output = _BinaryStdout()
        with (
            patch("urllib.request.urlopen", return_value=io.BytesIO(b"database")),
            patch("sys.stdout", output),
        ):
            _download.download("https://example.test/database", "-")

        self.assertEqual(output.buffer.getvalue(), b"database")

    def test_checksum_failure_removes_temporary_and_final_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.tar.xz"
            with (
                patch("urllib.request.urlopen", return_value=io.BytesIO(b"invalid")),
                self.assertRaisesRegex(model.TexMiniError, "integrity check failed"),
            ):
                _download.download(
                    "https://example.test/asset.tar.xz", destination, "0" * 64
                )

            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_transient_http_failure_is_retried(self) -> None:
        temporary_error = urllib.error.HTTPError(
            "https://example.test/asset", 503, "Unavailable", {}, None
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset"
            with (
                patch(
                    "urllib.request.urlopen",
                    side_effect=[temporary_error, io.BytesIO(b"redirected payload")],
                ) as urlopen,
                patch("time.sleep"),
            ):
                _download.download("https://example.test/asset", destination)

            self.assertEqual(destination.read_bytes(), b"redirected payload")

        self.assertEqual(urlopen.call_count, 2)

    def test_permanent_http_failure_is_not_retried(self) -> None:
        permanent_error = urllib.error.HTTPError(
            "https://example.test/missing", 404, "Not Found", {}, None
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("urllib.request.urlopen", side_effect=permanent_error) as urlopen,
            self.assertRaisesRegex(model.TexMiniError, "404"),
        ):
            _download.download(
                "https://example.test/missing", Path(directory) / "missing"
            )

        urlopen.assert_called_once()

    def test_non_https_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(model.TexMiniError, "non-HTTPS"):
            _download.download("http://example.test/asset", Path("asset"))


if __name__ == "__main__":
    unittest.main()
