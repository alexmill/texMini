# texMini

**LaTeX that just works, without managing a full TeX installation.**

## Try it now

### On macOS or Linux with [uv](https://docs.astral.sh/uv/):
You can compile a `.tex` document with texMini in seconds with the following command:

```bash
uvx texmini paper.tex
```

or 

```bash
uv tool install texmini
texmini paper.tex
```

### On Windows (or any platform) with Docker Engine:

```bash
docker run --rm -v texmini-runtime:/opt/TinyTeX -v "${PWD}:/work" ghcr.io/alexmill/texmini:latest paper.tex
```

## How it works

```text
paper.tex  ──▶  texmini  ──▶  auto-detect + install what is missing  ──▶  paper.pdf
```

texMini provides a self-contained, zero-install installation LaTeX utility that grows with your documents instead of arriving as a multi-gigabyte desktop distribution. It builds upon [TinyTeX](https://yihui.org/tinytex/) and provides additional packaging/helpers to make the experience of building TeX documents more universal and seamless across platforms. The native runtime lives in `~/.texmini`; the Docker pathway uses the `texmini-runtime` volume. texMini neither requires nor modifies a pre-existing system TeX installation.

The utility uses `latekmk` by default as its native runtime, while also supporting pdfLaTeX, LuaLaTeX, XeLaTeX, as well as common document complications such as bibliographies (BibTeX, Biber), indices, glossaries, and nomenclatures out of the box. The wider TeX Live package ecosystem also remains available. Existing projects do not need to adopt a new document language or a different TeX engine.

## Why texMini

A conventional TeX installation offers broad compatibility, but asks you to install and maintain an entire distribution. [Tectonic](https://tectonic-typesetting.github.io/en-US/) offers an excellent self-contained build experience, but uses its own XeTeX-derived engine and cannot replace every traditional TeX engine and utility. TinyTeX provides the small, portable TeX Live foundation used here, while its most automatic missing-package workflow is normally accessed through R.

texMini combines conventional TeX compatibility with a disposable and maximally portable command-line experience:

- **Use the project you already have.** Build ordinary `.tex` files with TeX Live and `latexmk`.
- **Install only what the document needs.** Missing classes, packages, fonts, bibliography styles, and Biber are resolved and installed automatically.
- **Keep TeX contained.** The managed runtime stays under `~/.texmini` or in a named Docker volume.
- **Remove it cleanly.** Delete the native directory or Docker volume; there is no system-wide installation to unwind.
- **Choose native or containerized execution.** The published Docker image runs the same adaptive compiler through a cross-platform compatibility layer.

## Comparison

| System | Existing LaTeX projects | Package handling | Installation and removal | Main compromise |
| --- | --- | --- | --- | --- |
| **texMini** | Builds conventional projects with pdfLaTeX, LuaLaTeX, or XeLaTeX | Automatically detects and installs needed TeX Live packages and common build tools into a private runtime | Run with `uvx` or Docker; remove the native directory or Docker volume to uninstall | Arbitrary project-specific executables can require additional setup |
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

The first compile downloads the latest monthly TinyTeX-1 release into `~/.texmini/TinyTeX` and installs any additional packages required by `paper.tex`. Later builds reuse that runtime.

texMini does not replace an existing managed runtime because replacement would remove packages that the user has installed. Remove `~/.texmini/TinyTeX` before the next compile if an existing installation should be recreated from TinyTeX-1.

Install the command for repeated authoring:

```bash
uv tool install texmini
texmini paper.tex
```

texMini retains LaTeX's auxiliary build state so unchanged builds and partial rebuilds are substantially faster. For a one-shot or CI build that should remove supported auxiliary files after success, use:

```bash
texmini --clean paper.tex
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

1. Select `paper.tex`, or find the unique top-level `.tex` file that declares a document class.
2. Recursively check local inputs, classes, and packages for required TeX files and build tools.
3. Install the private TinyTeX runtime if it does not exist.
4. Compile with managed `latexmk` and pdfLaTeX.
5. Read a failed build for missing TeX files, resolve their TeX Live packages, and install them together.
6. Continue installing and retrying while each round discovers a new package, with a 20-round safety ceiling.
7. Write the PDF to the effective `latexmk` output location and retain incremental build state by default.

For a path such as `docs/paper.tex`, texMini uses `latexmk -cd`, so sibling bibliographies, included files, logs, auxiliary state, and `paper.pdf` remain with the source. A root-level `latexmkrc` still loads and can configure the project.

Package mappings are cached in `~/.texmini/package-map.json`. Package installation modifies only texMini's private TinyTeX tree.

TeX Live reports a warning when GnuPG is unavailable because package repository signatures cannot be verified. TeX Live continues the installation. Run `brew install gnupg` on macOS, or install your system's `gnupg` package, then rerun texMini to restore signature verification.

## Engines and options

```text
texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex] [OPTIONS] [document.tex] [refs.bib ...]
```

Examples:

```bash
texmini paper.tex
texmini docs/paper.tex
texmini --engine lualatex paper.tex
texmini --engine xelatex paper.tex
texmini --watch paper.tex
texmini --shell-escape minted-paper.tex
texmini -synctex=1 paper.tex
texmini --clean paper.tex
texmini --verbose paper.tex
texmini paper.tex references.bib
```

Options:

- `--engine ENGINE`: select `pdflatex`, `lualatex`, or `xelatex`.
- `--clean`: remove supported auxiliary files after a successful build.
- `--watch`: rebuild when project files change without launching a PDF viewer. `-pvc` is an alias.
- `--shell-escape`: permit the document to run external commands. `-shell-escape` is an alias.
- `--verbose`: show complete TeX, `latexmk`, Biber, and package-manager output.
- `--no-install`: do not install missing TeX Live packages.
- `--version`: print the texMini version.

Arguments not handled by texMini are passed to managed `latexmk`. `-view=none` is accepted with watch mode, but texMini rejects options that would launch or control a viewer.

Prepare the managed runtime without compiling a document:

```bash
texmini install-tinytex
```

## Bibliographies

texMini distinguishes the usual bibliography workflows and installs the required backend automatically:

- `\bibliography`, `\bibliographystyle`, and `natbib` use BibTeX.
- BibLaTeX uses Biber by default.
- BibLaTeX with `backend=bibtex` uses BibTeX.
- Missing local or TeX Live bibliography styles are resolved before a retry.

A traditional BibTeX document needs no special texMini option:

```tex
\usepackage{natbib}
\bibliographystyle{plainnat}
\bibliography{refs}
```

```bash
texmini paper.tex
```

Explicit bibliography files are checked before compilation:

```bash
texmini paper.tex references.bib
```

## Indices, glossaries, and nomenclatures

The standard package workflows are integrated with `latexmk`: `makeidx`, `imakeidx`, `glossaries`, `glossaries-extra`, and `nomencl`. texMini installs MakeIndex, `makeglossaries`, or Xindy when the source selects them and reruns the document until the generated material is current.

```bash
texmini indexed-paper.tex
texmini glossary.tex
texmini nomenclature.tex
```

Project `latexmkrc` rules remain authoritative. This lets publisher templates replace texMini's built-in glossary and nomenclature rules when needed.

## Minted and external commands

texMini includes Pygments and can install the `minted` TeX package, but it never grants external command execution implicitly. A document using `minted` must opt in:

```bash
texmini --shell-escape paper.tex
```

Shell escape lets TeX execute commands with the permissions of the current user or container. Use it only for documents and project files you trust. Without the option, texMini stops with a focused instruction instead of silently enabling execution.

## Continuous rebuilding

Use watch mode while editing with a PDF viewer that already refreshes changed files:

```bash
texmini --watch paper.tex
```

The familiar `texmini -pvc paper.tex` spelling is equivalent. texMini performs its normal package analysis, recovery, diagnostics, and incremental `latexmk` build after project source, bibliography, class, style, configuration, script, or image dependencies change. It keeps watching after ordinary LaTeX errors so saving a fix rebuilds the PDF.

Watch mode does not open or manage a viewer. It cannot be combined with `--clean`; incremental state is part of the continuous workflow. Press Ctrl-C to stop.

## Engines and editor directives

The default engine is pdfLaTeX. Projects can select LuaLaTeX or XeLaTeX through either common magic-comment form:

```tex
% !TeX program = lualatex
```

```tex
% !TEX TS-program = xelatex
```

Precedence is explicit `--engine`, then `TEXMINI_ENGINE`, then the source directive, then pdfLaTeX. Unsupported directives produce a warning and use the configured or default engine.

## Custom build layouts

texMini honors project `latexmkrc` settings and the short or long `latexmk` forms for output directories, auxiliary directories, and job names:

```bash
texmini -outdir=build -auxdir=aux -jobname=final paper.tex
```

The corresponding long names are `-output-directory`, `-aux-directory`, and `-jobname`. Status messages, diagnostics, change detection, and cleanup use the effective layout reported by `latexmk`, including layouts configured in Perl rather than guessed from command-line text.

## SyncTeX

SyncTeX is available as an opt-in `latexmk` argument, including in watch mode:

```bash
texmini --watch -synctex=1 paper.tex
```

texMini does not enable it by default. `--clean -synctex=1` removes the generated `.synctex.gz` file while preserving the PDF and sources.

## Build cleanup

By default, successful builds retain `.aux`, `.bbl`, `.bcf`, `.fdb_latexmk`, and related state so `latexmk` can avoid unnecessary work on the next invocation.

With `--clean`, texMini removes supported bibliography, index, glossary, acronym, nomenclature, minted-cache, SyncTeX, and ordinary LaTeX auxiliary files after a successful build. It preserves sources, bibliography files, local classes and styles, images, scripts, PDFs, and unrelated files. Failed builds always retain their logs and auxiliary files for diagnosis.

## Output and diagnostics

Normal builds show short, stable progress messages and suppress successful `tlmgr`, TeX, Metafont, Biber, and `latexmk` transcripts. Warnings that affect the finished document, including unresolved references and missing characters, remain visible.

texMini provisions its managed toolchain and runs the document's declared build. It does not repair the document or attempt to diagnose the full range of LaTeX errors. The [diagnostic responsibility principle](docs/diagnostic-responsibility.md) defines this boundary and how texMini surfaces ordinary TeX failures.

Use `--verbose` to stream complete subprocess output. On failure, the default output shows the primary LaTeX error and source line when available, points to the retained log, and warns when the failed invocation created or changed the PDF.

A PDF with missing characters or unresolved citations or references is an incomplete build. texMini retains the PDF and diagnostic files, prints the content-loss warnings beside the final result, and exits with a nonzero status.

## Docker

Docker is the cross-platform, isolated pathway for Docker Desktop and Docker Engine users, including Windows. Compile a document in the current directory with:

```bash
docker run --rm -v texmini-runtime:/opt/TinyTeX -v "${PWD}:/work" ghcr.io/alexmill/texmini:latest paper.tex
```

Use the versioned image for a reproducible invocation:

```bash
docker run --rm -v texmini-runtime:/opt/TinyTeX -v "${PWD}:/work" ghcr.io/alexmill/texmini:0.5.0 paper.tex
```

The image pins a tested monthly TinyTeX-1 archive and provides Pygments. texMini analyzes the document and installs other TeX Live packages on demand, using the same package-recovery logic as the native path. A network connection is therefore required when a project introduces a package that is not already in the runtime volume.

The named `texmini-runtime` volume preserves those adaptive additions across disposable `--rm` containers. Omit that volume for a fully disposable one-shot build; any packages downloaded during that invocation will then be discarded with the container.

Remove the persistent Docker runtime at any time with `docker volume rm texmini-runtime`.

An existing named volume retains the runtime that first populated it. Remove and recreate the volume if the volume should start from the TinyTeX-1 baseline in texMini 0.5.0.

On native Linux, the entrypoint writes outputs as the owner of the mounted directory. Explicit Docker `--user` settings remain supported. Docker Desktop handles bind-mount ownership through its virtual machine.

## Automation and AI agents

texMini is noninteractive and uses stable status lines without spinners or terminal-only formatting. A successful build exits with zero; a failed build returns the underlying nonzero status, retains its log and diagnostic files, and prints the primary error near the end. Use `--verbose` for complete tool transcripts and `--clean` when an automation should remove supported auxiliary files after success.

This makes texMini friendly to scripts, CI, and AI coding agents without adding an agent-specific protocol: the same small CLI is used by people and automation.

## Compatibility and limitations

texMini targets ordinary projects that build with real TeX Live, `latexmk`, and pdfLaTeX, LuaLaTeX, or XeLaTeX. It can plausibly replace the compilation part of an Overleaf workflow, but it is not a collaborative editor or document-hosting service.

- Native runtime installation supports macOS and Linux; Windows uses Docker Desktop.
- DVI/PostScript output, plain TeX, pLaTeX/upLaTeX, and ConTeXt are outside texMini's supported build model.
- System-font projects depend on fonts installed on the host or in the container; texMini does not provision arbitrary operating-system fonts.
- Arbitrary project-specific executables and scripts may require additional setup. Shell escape is always opt-in.
- The managed native runtime grows as packages are installed. It is shared across builds and is not locked independently per project.

## Environment

- `TEXMINI_ENGINE`: default engine; defaults to `pdflatex`.
- `TEXMINI_CLEAN=true`: remove supported auxiliary files after successful builds.
- `TEXMINI_AUTO_INSTALL=false`: disable document-driven package installation.
- `TEXMINI_TINYTEX_ROOT`: managed TinyTeX directory; defaults to `~/.texmini/TinyTeX`.
- `TEXMINI_PACKAGE_MAP`: package mapping cache; defaults to `~/.texmini/package-map.json`.

## Development

Changes to automatic recovery and error reporting must follow the [diagnostic responsibility principle](docs/diagnostic-responsibility.md).

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
docker run --rm \
  -v texmini-development-runtime:/opt/TinyTeX \
  -v "${PWD}/tests/fixtures/bibliography:/work" \
  texmini bibliography.tex
```

TinyTeX bundle benchmark methodology and raw results are in [`benchmarks`](benchmarks).
