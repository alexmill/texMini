from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def test_uv_tool_install_exposes_standard_console_script(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required to verify uv tool installation")

        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory) / "tools"
            bin_dir = Path(directory) / "bin"
            env = {
                **os.environ,
                "UV_TOOL_DIR": str(tool_dir),
                "UV_TOOL_BIN_DIR": str(bin_dir),
                "UV_NO_PROGRESS": "1",
                "UV_NO_CACHE": "1",
            }
            subprocess.run(
                ["uv", "tool", "install", "--force", str(ROOT)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )

            version = subprocess.run(
                [str(bin_dir / "texmini"), "--version"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            self.assertEqual(version.stdout.strip(), "0.4.1")

            help_result = subprocess.run(
                [str(bin_dir / "texmini"), "--help"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            self.assertIn("--engine pdflatex|lualatex|xelatex", help_result.stdout)
            self.assertNotIn("--backend", help_result.stdout)

    def test_pyproject_declares_one_dynamic_versioned_entry_point(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('[project.scripts]\ntexmini = "texmini.cli:main"', pyproject)
        self.assertIn('version = { attr = "texmini.__version__" }', pyproject)
        self.assertNotIn("script-files", pyproject)

    def test_pyproject_exposes_public_package_metadata(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]

        self.assertEqual(project["name"], "texmini")
        self.assertEqual(
            project["urls"]["Repository"], "https://github.com/alexmill/texMini"
        )
        self.assertIn("Operating System :: MacOS", project["classifiers"])
        self.assertIn("Operating System :: POSIX :: Linux", project["classifiers"])

    def test_sdist_contains_benchmarks_and_compile_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["uv", "build", "--sdist", "--out-dir", directory],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            archive = next(Path(directory).glob("texmini-*.tar.gz"))
            with tarfile.open(archive, "r:gz") as distribution:
                names = distribution.getnames()

        self.assertTrue(
            any(name.endswith("/benchmarks/benchmark.py") for name in names)
        )
        self.assertTrue(
            any(name.endswith("/tests/fixtures/simple/simple.tex") for name in names)
        )
        self.assertTrue(
            any(
                name.endswith("/tests/fixtures/bibliography/refs.bib") for name in names
            )
        )
        self.assertTrue(
            any(
                name.endswith("/tests/fixtures/multifile/tex/publisher.cls")
                for name in names
            )
        )
        self.assertTrue(
            any(name.endswith("/src/texmini/texmini_latexmkrc") for name in names)
        )

    def test_dockerfile_pins_supported_tinytex_archives(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("TINYTEX_VERSION=2026.07", dockerfile)
        self.assertIn(
            "7b107b20dcb7d35069fde8199b70cdc4603298ad77de4706f760dd0e8a432938",
            dockerfile,
        )
        self.assertIn(
            "7eec4fa1f85794a0e254290f45d73c55d84f7d790996aea94eddde4cf7e9d5b7",
            dockerfile,
        )
        self.assertIn("python:3.12-slim-bookworm@sha256:", dockerfile)
        self.assertIn("debian:bookworm-slim@sha256:", dockerfile)
        self.assertIn("ghcr.io/astral-sh/uv:0.11.20@sha256:", dockerfile)
        self.assertIn("uv build --wheel", dockerfile)
        self.assertIn('archive="TinyTeX-0-${platform}', dockerfile)
        self.assertIn("latex-bin latexmk metafont mfware", dockerfile)
        self.assertIn("biblatex biber bibtex natbib csquotes", dockerfile)
        self.assertNotIn("makeindex imakeidx glossaries", dockerfile)
        self.assertNotIn("enumitem microtype", dockerfile)
        self.assertIn("curl fontconfig", dockerfile)
        self.assertIn("libncurses6", dockerfile)
        self.assertIn("util-linux", dockerfile)
        self.assertIn("xz-utils", dockerfile)
        self.assertIn("TEXMINI_PACKAGE_MAP=/opt/TinyTeX/", dockerfile)
        self.assertIn("TEXMINI_TINYTEX_BUNDLE=TinyTeX-0", dockerfile)
        self.assertIn("RUN chmod -R a+rwX /opt/TinyTeX", dockerfile)
        self.assertIn("COPY --chmod=755 docker-entrypoint.sh", dockerfile)
        self.assertIn('ENTRYPOINT ["texmini-entrypoint"]', dockerfile)
        self.assertNotIn("nix", dockerfile.lower())

    def test_docker_entrypoint_matches_work_directory_ownership(self) -> None:
        entrypoint = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("stat -c %u /work", entrypoint)
        self.assertIn("stat -c %g /work", entrypoint)
        self.assertIn("setpriv --reuid", entrypoint)
        self.assertIn('exec texmini "$@"', entrypoint)

    def test_release_workflow_uses_tag_gates_and_trusted_publishing(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("group: release-${{ github.ref }}", workflow)
        self.assertIn("Release tags must be annotated.", workflow)
        self.assertIn("pypa/gh-action-pypi-publish@", workflow)
        self.assertIn("ghcr.io/alexmill/texmini", workflow)
        self.assertIn("platforms: linux/amd64,linux/arm64", workflow)
        self.assertIn("push-to-registry: true", workflow)

    def test_docker_context_contains_only_python_package_inputs(self) -> None:
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            dockerignore,
            [
                "*",
                "!Dockerfile",
                "!docker-entrypoint.sh",
                "!LICENSE",
                "!README.md",
                "!pyproject.toml",
                "!src/",
                "!src/**",
            ],
        )


if __name__ == "__main__":
    unittest.main()
