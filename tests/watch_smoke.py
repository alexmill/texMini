from __future__ import annotations

import argparse
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("texmini")
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        for source in arguments.fixture.iterdir():
            shutil.copy2(source, project / source.name)

        process = subprocess.Popen(
            [arguments.texmini, "--watch", "-synctex=1", "bibliography.tex"],
            cwd=project,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        lines: queue.Queue[str] = queue.Queue()
        transcript: list[str] = []

        def read_output() -> None:
            for line in process.stdout:
                print(line, end="", flush=True)
                transcript.append(line)
                lines.put(line)

        threading.Thread(target=read_output, daemon=True).start()

        def wait_for(fragment: str, timeout: float = 120) -> None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if fragment in line:
                    return
            raise RuntimeError(
                f"Timed out waiting for {fragment!r}:\n{''.join(transcript)}"
            )

        try:
            wait_for("Watching bibliography.tex for changes")
            if not (project / "bibliography.synctex.gz").is_file():
                raise RuntimeError("Watch build did not create SyncTeX output.")

            bibliography = project / "refs.bib"
            bibliography.write_text(
                bibliography.read_text(encoding="utf-8").replace(
                    "A Bibliography Fixture for texMini",
                    "A Revised Bibliography Fixture for texMini",
                ),
                encoding="utf-8",
            )
            wait_for("Compiling bibliography.tex")
            wait_for("Built bibliography.pdf")
            time.sleep(1)

            document = project / "bibliography.tex"
            valid_source = document.read_text(encoding="utf-8")
            document.write_text(
                valid_source.replace(
                    "\\end{document}", "\\undefinedwatchcommand\n\\end{document}"
                ),
                encoding="utf-8",
            )
            wait_for("Build failed: TeX reported: Undefined control sequence")
            time.sleep(1)

            recovered_source = valid_source.replace(
                "\\usepackage{microtype}",
                "\\usepackage{microtype}\n\\usepackage{verse}",
            )
            document.write_text(recovered_source, encoding="utf-8")
            wait_for("Installing 1 package: verse")
            wait_for("Built bibliography.pdf")

            compiling_count = sum(
                "Compiling bibliography.tex" in line for line in transcript
            )
            time.sleep(2)
            if (
                sum("Compiling bibliography.tex" in line for line in transcript)
                != compiling_count
            ):
                raise RuntimeError(
                    f"Generated files caused a rebuild loop:\n{''.join(transcript)}"
                )
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            process.wait(timeout=10)

        if process.returncode != 130:
            raise RuntimeError(
                f"Watch process returned {process.returncode}:\n{''.join(transcript)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
