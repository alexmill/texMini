from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


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
            self.assertEqual(version.stdout.strip(), "0.2.0")

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
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

        self.assertEqual(project["name"], "texmini")
        self.assertEqual(project["urls"]["Repository"], "https://github.com/alexmill/texMini")
        self.assertIn("Operating System :: MacOS", project["classifiers"])
        self.assertIn("Operating System :: POSIX :: Linux", project["classifiers"])

    def test_dockerfile_pins_supported_tinytex_archives(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("TINYTEX_VERSION=2026.07", dockerfile)
        self.assertIn("b814b0370ea3f633fa5ce640ad74c3d1cdfa80cc4aa0d33893baf1467c4b35fe", dockerfile)
        self.assertIn("befcf452ed2fe07edea92c8b23e9e6977a6bfbffc15d7ce8bae2fd96a3d8eee5", dockerfile)
        self.assertIn("python:3.12-slim-bookworm@sha256:", dockerfile)
        self.assertIn("debian:bookworm-slim@sha256:", dockerfile)
        self.assertIn("ghcr.io/astral-sh/uv:0.11.20@sha256:", dockerfile)
        self.assertIn("uv build --wheel", dockerfile)
        self.assertIn("biblatex biber csquotes", dockerfile)
        self.assertIn('ENTRYPOINT ["texmini"]', dockerfile)
        self.assertNotIn("nix", dockerfile.lower())

    def test_release_workflow_uses_tag_gates_and_trusted_publishing(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

        self.assertIn('group: release-${{ github.ref }}', workflow)
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
                "!LICENSE",
                "!README.md",
                "!pyproject.toml",
                "!src/",
                "!src/**",
            ],
        )


if __name__ == "__main__":
    unittest.main()
