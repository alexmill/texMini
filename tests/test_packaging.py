from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def test_zig_installed_wrapper_uses_fast_python_startup(self) -> None:
        wrapper = (ROOT / "bin" / "texmini").read_text(encoding="utf-8")

        self.assertNotIn("TEXMINI_BACKEND", wrapper)
        self.assertIn('case "$1" in', wrapper)
        self.assertIn("--help|-h)", wrapper)
        self.assertIn("All other arguments are passed through to latexmk.", wrapper)
        self.assertIn('-S -m texmini.cli "$@"', wrapper)
        self.assertIn('site_packages=( "$root"/lib/python*/site-packages )', wrapper)

    def test_uv_tool_install_uses_fast_script_file(self) -> None:
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

            installed_script = (bin_dir / "texmini").resolve().read_text(encoding="utf-8")
            self.assertIn("#!/usr/bin/env bash", installed_script)
            self.assertIn('case "$1" in', installed_script)
            self.assertIn("--help|-h)", installed_script)
            self.assertIn('-S -m texmini.cli "$@"', installed_script)

            version = subprocess.run(
                [str(bin_dir / "texmini"), "--version"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            self.assertIn("0.1.0", version.stdout)
            help_result = subprocess.run(
                [str(bin_dir / "texmini"), "--help"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            self.assertIn("Usage: texmini", help_result.stdout)
            self.assertIn("All other arguments are passed through to latexmk.", help_result.stdout)

    def test_pyproject_installs_script_file_for_uv_tools(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('[tool.setuptools]\nscript-files = ["bin/texmini"]', pyproject)
        self.assertNotIn("[project.scripts]", pyproject)

    def test_python_cli_import_avoids_heavy_startup_modules(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import sys, texmini.cli; print('__future__' in sys.modules, 'pathlib' in sys.modules, 're' in sys.modules, 'subprocess' in sys.modules)",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "False False False False")

    def test_zig_install_declares_only_runtime_python_files(self) -> None:
        build = (ROOT / "build.zig").read_text(encoding="utf-8")

        self.assertIn('b.installFile("src/texmini/__init__.py", "src/texmini/__init__.py");', build)
        self.assertIn('b.installFile("src/texmini/cli.py", "src/texmini/cli.py");', build)
        self.assertNotIn("installDirectory", build)

    def test_homebrew_formula_uses_fast_executable_wrapper(self) -> None:
        formula = (ROOT / "Formula" / "texmini.rb").read_text(encoding="utf-8")

        self.assertIn('url "https://github.com/alexmill/texMini.git"', formula)
        self.assertIn('using: :git, branch: "main"', formula)
        self.assertNotIn('TEXMINI_BACKEND="${TEXMINI_BACKEND:-auto}"', formula)
        self.assertIn('case "$1" in', formula)
        self.assertIn("--help|-h)", formula)
        self.assertIn("-S -m texmini.cli", formula)
        self.assertIn('chmod 0755, bin/"texmini"', formula)
        self.assertIn('assert_predicate bin/"texmini", :executable?', formula)

    def test_nix_docker_package_contains_only_default_package(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")

        self.assertIn("contents = [ package ];", flake)
        self.assertIn('docker = makeDockerImage "texmini" defaultPackage "texmini";', flake)
        self.assertIn('docker-basic = makeDockerImage "texmini-basic" basicPackage "texmini-basic";', flake)
        self.assertIn('basicPackage = makeDirectTexCommand "texmini-basic" "pdflatex" texMiniBasic;', flake)
        self.assertIn("ln -s ${pkgs.bash}/bin/bash bin/sh", flake)
        self.assertNotIn("writeShellApplication", flake)
        self.assertNotIn("pkgs.bashInteractive", flake)

    def test_nix_default_latexmk_wrapper_avoids_python_cli_runtime(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        latexmk_wrapper = flake.split("makeLatexmkCommand = ", 1)[1].split("makeDirectTexCommand =", 1)[0]

        self.assertIn('latexmk "\'\'${latexmk_engine_args[@]}" "\'\'${latexmk_args[@]}"', latexmk_wrapper)
        self.assertIn("pkgs.coreutils", latexmk_wrapper)
        self.assertNotIn("pkgs.gnugrep", latexmk_wrapper)
        self.assertIn('tex_source="$(< "$tex_file")"', latexmk_wrapper)
        self.assertNotIn("grep -", latexmk_wrapper)
        self.assertIn("--engine pdflatex|lualatex|xelatex|latexmk", latexmk_wrapper)
        self.assertIn("report_missing_files()", latexmk_wrapper)
        self.assertIn('echo "Missing TeX files found: \'\'${missing_files[*]}"', latexmk_wrapper)
        self.assertNotIn("python3", latexmk_wrapper)
        self.assertIn('makeDefaultCommand = name: makeLatexmkCommand name "pdflatex" texMiniDefault;', flake)
        self.assertIn('pdflatex = makeLatexmkCommand "pdflatex" "pdflatex" texMiniDefault;', flake)
        self.assertIn('latexmk-basic = makeLatexmkCommand "latexmk-basic" "latexmk" texMiniBasicLatexmk;', flake)

    def test_nix_direct_basic_avoids_python_cli_runtime(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        direct_wrapper = flake.split("makeDirectTexCommand = ", 1)[1].split("makeDefaultCommand =", 1)[0]

        self.assertIn('"${engine}" -interaction=nonstopmode -file-line-error', direct_wrapper)
        self.assertIn('echo "${version}"', direct_wrapper)
        self.assertIn('echo "Usage: ${name} [--no-clean] [document.tex]"', direct_wrapper)
        self.assertIn("accept_backend()", direct_wrapper)
        self.assertIn("auto|direct)", direct_wrapper)
        self.assertIn("--engine|--engine=*)", direct_wrapper)
        self.assertIn('echo "Error: ${name} is already bound to ${engine}; choose a different Nix target for another engine."', direct_wrapper)
        self.assertIn("--no-install)", direct_wrapper)
        self.assertIn("report_missing_files()", direct_wrapper)
        self.assertIn('echo "Missing TeX files found: \'\'${missing_files[*]}"', direct_wrapper)
        self.assertIn("pkgs.coreutils", direct_wrapper)
        self.assertNotIn("python3", direct_wrapper)
        self.assertIn('pdflatex-basic = makeDirectTexCommand "pdflatex-basic" "pdflatex" texMiniBasic;', flake)
        self.assertIn('lualatex-basic = makeDirectTexCommand "lualatex-basic" "lualatex" texMiniBasic;', flake)
        self.assertIn('xelatex-basic = makeDirectTexCommand "xelatex-basic" "xelatex" texMiniBasic;', flake)
        self.assertNotIn("texMiniTinytex", flake)
        self.assertNotIn("TEXMINI_BACKEND=tinytex", flake)

    def test_nix_package_set_avoids_broad_recommended_collection(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")

        self.assertNotIn('"collection-latexrecommended"', flake)
        self.assertNotIn('"cm-super"', flake)
        self.assertNotIn('"tikz-bayesnet"', flake)

    def test_nix_default_package_set_includes_biblatex_dependencies(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        common_section = flake.split("commonPackages = [", 1)[1].split("];", 1)[0]

        self.assertIn('"pgf"', common_section)
        self.assertIn('"l3packages"', common_section)
        self.assertIn('"epstopdf-pkg"', common_section)
        self.assertIn('"ec"', common_section)
        self.assertIn('"metafont"', common_section)
        self.assertIn('"mfware"', common_section)

    def test_nix_basic_package_set_is_minimal(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        basic_section = flake.split("basicPackages = [", 1)[1].split("];", 1)[0]

        self.assertIn('"latex-bin"', basic_section)
        self.assertNotIn('"latexmk"', basic_section)
        self.assertNotIn('"pgf"', basic_section)
        self.assertNotIn('"biblatex"', basic_section)
        self.assertNotIn('"biber"', basic_section)

    def test_nix_latexmk_basic_keeps_latexmk_out_of_direct_basic(self) -> None:
        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        latexmk_basic_section = flake.split("basicLatexmkPackages = basicPackages ++ [", 1)[1].split("];", 1)[0]

        self.assertIn('"latexmk"', latexmk_basic_section)
        self.assertIn(
            'latexmk-basic = makeLatexmkCommand "latexmk-basic" "latexmk" texMiniBasicLatexmk;',
            flake,
        )

    def test_dockerfile_provides_shell_for_latexmk(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("ARG NIX_TARGET=default", dockerfile)
        self.assertIn("COPY flake.nix flake.lock ./", dockerfile)
        self.assertNotIn("COPY src", dockerfile)
        self.assertNotIn("COPY . .", dockerfile)
        self.assertIn('nix build ".#${NIX_TARGET}"', dockerfile)
        self.assertIn("find /image/nix/store -maxdepth 1 -name '*-texdoc' -exec rm -rf {} +", dockerfile)
        self.assertIn("-name doc -o -name man -o -name info", dockerfile)
        self.assertIn('/image/bin/sh', dockerfile)

    def test_docker_context_contains_only_nix_inputs(self) -> None:
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        self.assertEqual(dockerignore, ["*", "!Dockerfile", "!flake.lock", "!flake.nix"])


if __name__ == "__main__":
    unittest.main()
