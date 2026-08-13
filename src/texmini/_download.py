from __future__ import annotations

import hashlib
import http.client
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from texmini import __version__

from .model import TexMiniError

CHUNK_SIZE = 1024 * 1024
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_TIMEOUT = 60


def _safe_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))


def _download_once(
    url: str,
    destination: Path,
    expected_sha256: str | None,
    display_name: str,
) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"texmini/{__version__}"}
    )
    checksum = hashlib.sha256()
    with (
        urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response,
        destination.open("wb") as output,
    ):
        while chunk := response.read(CHUNK_SIZE):
            output.write(chunk)
            checksum.update(chunk)
    if expected_sha256 is not None and checksum.hexdigest() != expected_sha256:
        raise TexMiniError(f"Error: SHA-256 integrity check failed for {display_name}.")


def download(
    url: str, destination: Path | str, expected_sha256: str | None = None
) -> None:
    if not url.lower().startswith("https://"):
        raise TexMiniError(
            f"Error: texMini refuses a non-HTTPS download URL: {_safe_url(url)}"
        )

    output_path = None if os.fspath(destination) == "-" else Path(destination)
    display_name = (
        output_path.name if output_path is not None else url.rsplit("/", 1)[-1]
    )
    temporary_parent = output_path.parent if output_path is not None else None
    if temporary_parent is not None:
        temporary_parent.mkdir(parents=True, exist_ok=True)

    last_error: BaseException | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".texmini-download-",
                dir=temporary_parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
            temporary_path = Path(temporary_name)
            _download_once(url, temporary_path, expected_sha256, display_name)
            if output_path is None:
                with temporary_path.open("rb") as source:
                    shutil.copyfileobj(source, sys.stdout.buffer, CHUNK_SIZE)
                sys.stdout.buffer.flush()
                temporary_path.unlink()
            else:
                os.replace(temporary_path, output_path)
            return
        except TexMiniError:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as error:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            last_error = error
            if error.code < 500 or attempt == DOWNLOAD_ATTEMPTS:
                break
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as error:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
            last_error = error
            if attempt == DOWNLOAD_ATTEMPTS:
                break
        time.sleep(attempt)

    detail = (
        last_error
        if isinstance(last_error, urllib.error.HTTPError)
        else getattr(last_error, "reason", last_error)
    )
    raise TexMiniError(f"Error: Download failed for {_safe_url(url)}: {detail}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(
            "Usage: python -m texmini._download DESTINATION URL",
            file=sys.stderr,
        )
        return 2
    destination, url = argv
    try:
        download(url, destination)
    except TexMiniError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
