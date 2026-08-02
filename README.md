# texMini

**LaTeX that just works, without managing a full TeX installation.**

## Try it now

Choose either path. Both run texMini without a separate texMini installation.

On macOS or Linux with [uv](https://docs.astral.sh/uv/):

```bash
uvx texmini paper.tex
```

With Docker Desktop or Docker Engine:

```bash
docker run --rm -v "${PWD}:/work" ghcr.io/alexmill/texmini:latest paper.tex
```

The Docker command works in Bash, zsh, and PowerShell. The image downloads on its first use. Pin `ghcr.io/alexmill/texmini:0.2.0` instead of `:latest` when reproducibility matters.

texMini builds existing LaTeX projects with real TeX Live and `latexmk`. On the first run, it downloads a minimal private TinyTeX runtime. When a document needs a package that is not installed, texMini finds the corresponding TeX Live package, installs it, and retries the build.

The result is a TeX installation that grows with your documents instead of arriving as a multi-gigabyte desktop distribution. It lives in `~/.texmini`, does not modify the system TeX installation, and can be removed by deleting that directory.

```text
paper.tex  ──▶  texmini  ──▶  install what is missing  ──▶  paper.pdf
```

pdfLaTeX, LuaLaTeX, XeLaTeX, Biber, and the wider TeX Live package ecosystem remain available. Existing projects do not need to adopt a new document language or a different TeX engine.

## Why texMini

A conventional TeX installation offers broad compatibility, but asks you to install and maintain an entire distribution. Tectonic offers an excellent self-contained build experience, but uses its own XeTeX-derived engine and cannot replace every traditional TeX engine and utility. TinyTeX provides the small, portable TeX Live foundation used here, while its most automatic missing-package workflow is normally accessed through R.

texMini combines conventional TeX compatibility with a disposable command-line experience:

- **Use the project you already have.** Build ordinary `.tex` files with TeX Live and `latexmk`.
- **Install only what the document needs.** Missing classes, packages, fonts, bibliography styles, and Biber are resolved and installed automatically.
- **Keep TeX contained.** The managed runtime and its packages stay under `~/.texmini`.
- **Remove it like ordinary files.** There is no system-wide uninstaller or package database to unwind.
- **Choose native or containerized execution.** The published Docker image is a ready-to-run, cross-platform option for common documents.

## Comparison

| System | Existing LaTeX projects | Package handling | Installation and removal | Main compromise |
| --- | --- | --- | --- | --- |
| **texMini** | Builds conventional projects with pdfLaTeX, LuaLaTeX, or XeLaTeX | Automatically detects and installs needed TeX Live packages into a private runtime | Run with `uvx` or Docker; delete `~/.texmini` to remove the native runtime | Specialized external tools can require additional setup |
| [Tectonic](https://tectonic-typesetting.github.io/) | Builds many projects, subject to its XeTeX-derived engine and build model | Downloads support files from a configured bundle | A single executable and a removable cache | It does not provide every engine and utility in conventional TeX Live |
| [TinyTeX with R](https://yihui.org/tinytex/) | Broad TeX Live compatibility | The R package can detect and install missing packages during compilation | A small, portable TeX Live directory | The automated workflow is coupled to R |
| **TinyTeX from the shell** | Broad TeX Live compatibility | Packages are managed directly with `tlmgr` | A small, portable TeX Live directory | Compilation and missing-package repair are manual |
| **TeX Live, MacTeX, or MiKTeX** | Broadest conventional compatibility | Large package sets or distribution-specific package management | A conventional desktop or system installation | More disk usage and distribution administration |
| [Overleaf](https://www.overleaf.com/) | Builds projects supported by its hosted TeX environment | A large package set is supplied by the service | No local TeX installation | The build environment is remote and controlled by the service |
| [Typst](https://typst.app/) | LaTeX projects must be rewritten | Uses Typst packages rather than TeX Live packages | A simple executable and package cache | It is a different document language, not a LaTeX compiler |

## Native workflow

The native managed runtime supports macOS and Linux and requires uv and Perl. TinyTeX uses Perl for `tlmgr` and `latexmk`. Windows users should use the Docker pathway above.

Run texMini directly from PyPI:

```bash
uvx texmini paper.tex
```

The first compile downloads TinyTeX-0 into `~/.texmini/TinyTeX`, bootstraps the compiler, and installs the packages required by `paper.tex`. Later builds reuse that runtime.

For repeated authoring, use the default incremental workflow:

```bash
texmini paper.tex
```

texMini retains LaTeX's auxiliary build state so unchanged builds and partial rebuilds are substantially faster. For a one-shot or CI build that should remove supported auxiliary files after success, use:

```bash
texmini --clean paper.tex
```

Install the command for repeated use:

```bash
uv tool install texmini
texmini paper.tex
```

If a directory contains exactly one `.tex` file, the filename is optional:

```bash
texmini
```

## What happens during a build

Running:

```bash
texmini paper.tex
```

causes texMini to:

1. Select `paper.tex`, or find the only `.tex` file in the current directory.
2. Check the source for required classes, packages, and bibliography tooling.
3. Install the private TinyTeX runtime if it does not exist.
4. Compile with managed `latexmk` and pdfLaTeX.
5. Read a failed build for missing TeX files, resolve their TeX Live packages, and install them together.
6. Continue installing and retrying while each round discovers a new package, with a 20-round safety ceiling.
7. Write `paper.pdf` beside the source and retain incremental build state by default.

Package mappings are cached in `~/.texmini/package-map.json`. Package installation modifies only texMini's private TinyTeX tree.

## Engines and options

```text
texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex] [OPTIONS] [document.tex] [refs.bib ...]
```

Examples:

```bash
texmini paper.tex
texmini --engine lualatex paper.tex
texmini --engine xelatex paper.tex
texmini --clean paper.tex
texmini --verbose paper.tex
texmini paper.tex references.bib
```

Options:

- `--engine ENGINE`: select `pdflatex`, `lualatex`, or `xelatex`.
- `--clean`: remove supported auxiliary files after a successful build.
- `--verbose`: show complete TeX, `latexmk`, Biber, and package-manager output.
- `--no-install`: do not install missing TeX Live packages.
- `--version`: print the texMini version.

Arguments not handled by texMini are passed to managed `latexmk`. Continuous preview mode (`-pvc`) is not supported.

Prepare the managed runtime without compiling a document:

```bash
texmini install-tinytex
```

## Bibliographies

texMini detects `\bibliography{...}`, `\addbibresource{...}`, and `biblatex`. Biber is installed automatically when a managed document uses `biblatex`.

Explicit bibliography files are checked before compilation:

```bash
texmini paper.tex references.bib
```

## Build cleanup

By default, successful builds retain `.aux`, `.bbl`, `.bcf`, `.fdb_latexmk`, and related state so `latexmk` can avoid unnecessary work on the next invocation.

With `--clean`, texMini removes supported auxiliary files after a successful build while preserving `.tex`, `.bib`, `.pdf`, and unrelated files. Failed builds always retain their logs and auxiliary files for diagnosis.

## Output and diagnostics

Normal builds show short, stable progress messages and suppress successful `tlmgr`, TeX, Metafont, Biber, and `latexmk` transcripts. Warnings that affect the finished document, including unresolved references and missing characters, remain visible.

Use `--verbose` to stream complete subprocess output. On failure, the default output shows the primary LaTeX error and source line when available, points to the retained log, and warns when the failed invocation created or changed the PDF.

## Docker

Docker is the cross-platform, isolated pathway for Docker Desktop and Docker Engine users, including Windows. Compile a document in the current directory with:

```bash
docker run --rm -v "${PWD}:/work" ghcr.io/alexmill/texmini:latest paper.tex
```

Use the versioned image for a reproducible invocation:

```bash
docker run --rm -v "${PWD}:/work" ghcr.io/alexmill/texmini:0.2.0 paper.tex
```

The image bundles TinyTeX plus packages used by many math, layout, bibliography, hyperlink, color, and TikZ documents. Common documents can therefore build from the downloaded image alone. When networking is available, texMini downloads uncommon TeX Live packages as needed. Those additions are discarded with `--rm`; this is an isolated ready-to-run workflow, not a promise that every possible project compiles offline.

On native Linux, the entrypoint writes outputs as the owner of the mounted directory. Explicit Docker `--user` settings remain supported. Docker Desktop handles bind-mount ownership through its virtual machine.

## Automation and AI agents

texMini is noninteractive and uses stable status lines without spinners or terminal-only formatting. A successful build exits with zero; a failed build returns the underlying nonzero status, retains its log and diagnostic files, and prints the primary error near the end. Use `--verbose` for complete tool transcripts and `--clean` when an automation should remove supported auxiliary files after success.

This makes texMini friendly to scripts, CI, and AI coding agents without adding an agent-specific protocol: the same small CLI is used by people and automation.

## Compatibility and limitations

texMini targets ordinary projects that build with real TeX Live, `latexmk`, and pdfLaTeX, LuaLaTeX, or XeLaTeX. It can plausibly replace the compilation part of an Overleaf workflow, but it is not a collaborative editor or document-hosting service.

- Native runtime installation supports macOS and Linux; Windows uses Docker Desktop.
- Specialized external tools such as glossary generators, Pygments-based syntax highlighting, or project-specific scripts may require additional setup.
- The managed native runtime grows as packages are installed. It is shared across builds and is not locked independently per project.
- TeX projects can depend on system fonts, executables, or shell-escape behavior that texMini does not automatically provision.

## Environment

- `TEXMINI_ENGINE`: default engine; defaults to `pdflatex`.
- `TEXMINI_CLEAN=true`: remove supported auxiliary files after successful builds.
- `TEXMINI_AUTO_INSTALL=false`: disable document-driven package installation.
- `TEXMINI_TINYTEX_ROOT`: managed TinyTeX directory; defaults to `~/.texmini/TinyTeX`.
- `TEXMINI_TINYTEX_BUNDLE`: release bundle; defaults to `TinyTeX-0`.
- `TEXMINI_PACKAGE_MAP`: package mapping cache; defaults to `~/.texmini/package-map.json`.

## Development

Run texMini from the source tree:

```bash
uv run texmini paper.tex
```

Run the test suite and validate the distributions:

```bash
uv run python -m unittest discover -s tests -v
uv build --sdist --wheel
uvx --from twine==6.2.0 twine check dist/*
```

Build and smoke-test Docker:

```bash
docker build -t texmini .
docker run --rm --network none \
  -v "${PWD}:/work" \
  texmini test.tex
```

TinyTeX bundle benchmark methodology and raw results are in [`benchmarks`](benchmarks).
