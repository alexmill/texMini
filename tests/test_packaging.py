from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from importlib.metadata import metadata
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

            executable = bin_dir / ("texmini.exe" if os.name == "nt" else "texmini")
            version = subprocess.run(
                [str(executable), "--version"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            self.assertEqual(version.stdout.strip(), "0.6.0")

            help_result = subprocess.run(
                [str(executable), "--help"],
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

        self.assertIn('requires = ["setuptools==84.0.0"]', pyproject)
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('"pygments==2.20.0"', pyproject)
        self.assertIn('"psutil==7.2.2"', pyproject)
        self.assertIn('[project.scripts]\ntexmini = "texmini.cli:main"', pyproject)
        self.assertIn('version = { attr = "texmini.__version__" }', pyproject)
        self.assertNotIn("script-files", pyproject)

    def test_pyproject_exposes_public_package_metadata(self) -> None:
        package_metadata = metadata("texmini")
        project_urls = dict(
            entry.split(", ", 1)
            for entry in package_metadata.get_all("Project-URL", failobj=[])
        )
        classifiers = package_metadata.get_all("Classifier", failobj=[])

        self.assertEqual(package_metadata["Name"], "texmini")
        self.assertEqual(
            project_urls["Repository"], "https://github.com/alexmill/texMini"
        )
        self.assertIn("Operating System :: MacOS", classifiers)
        self.assertIn(
            "Operating System :: Microsoft :: Windows", classifiers
        )
        self.assertIn("Operating System :: POSIX :: Linux", classifiers)

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
        self.assertTrue(any(name.endswith("/PYPI.md") for name in names))
        self.assertTrue(
            any(
                name.endswith(
                    "/docs/architecture/0001-optimize-python-orchestrator.md"
                )
                for name in names
            )
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
        self.assertTrue(
            any(name.endswith("/src/texmini/runtime_manifest.json") for name in names)
        )

    def test_dockerfile_uses_the_packaged_runtime_installer(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python:3.12-slim-bookworm@sha256:", dockerfile)
        self.assertIn("ghcr.io/astral-sh/uv:0.11.20@sha256:", dockerfile)
        self.assertIn("uv build --wheel", dockerfile)
        self.assertIn("RUN texmini install-tinytex", dockerfile)
        self.assertNotIn("tinytex-releases", dockerfile)
        self.assertNotIn("TINYTEX_VERSION", dockerfile)
        self.assertNotIn("SHA256", dockerfile)
        self.assertNotIn("tlmgr update --self", dockerfile)
        self.assertNotIn("docker-packages.txt", dockerfile)
        self.assertNotIn("tlmgr install", dockerfile)
        self.assertNotIn("makeindex imakeidx glossaries", dockerfile)
        self.assertNotIn("enumitem microtype", dockerfile)
        self.assertNotIn("curl", dockerfile)
        self.assertNotIn("wget", dockerfile)
        self.assertIn("fontconfig", dockerfile)
        self.assertIn("libncurses6", dockerfile)
        self.assertIn("util-linux", dockerfile)
        self.assertIn("xz-utils", dockerfile)
        self.assertIn("TEXMINI_PACKAGE_MAP=/opt/TinyTeX/", dockerfile)
        self.assertNotIn("TEXMINI_TINYTEX_BUNDLE", dockerfile)
        self.assertIn("chmod -R a+rwX /opt/TinyTeX", dockerfile)
        self.assertIn("COPY --chmod=755 docker-entrypoint.sh", dockerfile)
        self.assertIn('ENTRYPOINT ["texmini-entrypoint"]', dockerfile)
        self.assertNotIn("nix", dockerfile.lower())

    def test_docker_build_has_no_supplement_or_provisioning_fork(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertFalse((ROOT / "docker-packages.txt").exists())
        self.assertIn("texmini install-tinytex", dockerfile)
        self.assertNotIn("tar -x", dockerfile)
        self.assertNotIn("xargs env", dockerfile)

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

    def test_release_validates_the_exact_tag_on_native_desktop_platforms(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        native_job = workflow.split("  native-release-validation:\n", 1)[1].split(
            "\n  docker-smoke:\n", 1
        )[0]

        self.assertIn("needs: package", native_job)
        self.assertIn("fail-fast: false", native_job)
        self.assertIn(
            "os: [macos-latest, macos-15-intel, windows-latest]", native_job
        )
        self.assertIn("ref: ${{ github.sha }}", native_job)
        self.assertIn("version: ${{ env.UV_VERSION }}", native_job)
        self.assertIn(
            "uv run --frozen python -m unittest discover -s tests -v", native_job
        )
        self.assertIn("uv build --wheel --out-dir dist", native_job)
        self.assertIn("-py3-none-any.whl", native_job)
        self.assertIn("uvx --from twine==6.2.0 twine check", native_job)
        self.assertIn("uvx --from . texmini --version", native_job)
        self.assertEqual(
            workflow.count(
                "needs: [package, native-release-validation, docker-smoke]"
            ),
            2,
        )

    def test_ci_and_release_share_the_docker_smoke_matrix(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        smoke_script = ROOT / "tests" / "smoke_docker.sh"

        if os.name != "nt":
            self.assertTrue(smoke_script.stat().st_mode & 0o111)
        self.assertEqual(ci.count("tests/smoke_docker.sh"), 1)
        self.assertEqual(release.count("tests/smoke_docker.sh"), 1)

    def test_ci_pins_uv_and_names_native_platform_coverage_honestly(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('UV_VERSION: "0.11.20"', ci)
        self.assertIn('UV_VERSION: "0.11.20"', release)
        self.assertIn("macos-15-intel", ci)
        self.assertIn("ubuntu-24.04-arm", ci)
        self.assertIn("linuxmusl-x86_64", ci)
        self.assertIn("windows-x86_64", ci)
        self.assertIn("uvx --from . texmini --version", ci)
        self.assertIn(".github/workflows/*.yml", ci)
        self.assertIn("ghcr.io/astral-sh/uv:0.11.20-python3.12-trixie-slim@sha256:", ci)
        self.assertIn("ghcr.io/astral-sh/uv:0.11.20-python3.12-alpine@sha256:", ci)
        self.assertNotIn("windows-arm64", ci.lower())
        self.assertNotIn("windows-11-arm", ci.lower())

    def test_docker_context_contains_only_required_build_inputs(self) -> None:
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            dockerignore,
            [
                "*",
                "!Dockerfile",
                "!docker-entrypoint.sh",
                "!LICENSE",
                "!PYPI.md",
                "!pyproject.toml",
                "!src/",
                "!src/**",
            ],
        )


if __name__ == "__main__":
    unittest.main()
