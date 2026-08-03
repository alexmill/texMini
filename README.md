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

The Docker command works in Bash, zsh, and PowerShell. The image downloads on its first use. Pin `ghcr.io/alexmill/texmini:0.4.0` instead of `:latest` when reproducibility matters.

texMini builds existing LaTeX projects with real TeX Live and `latexmk`. On the first run, it downloads a minimal private TinyTeX runtime. When a document needs a package that is not installed, texMini finds the corresponding TeX Live package, installs it, and retries the build.

The result is a TeX installation that grows with your documents instead of arriving as a multi-gigabyte desktop distribution. It lives in `~/.texmini`, does not modify the system TeX installation, and can be removed by deleting that directory.

```text
paper.tex  ──▶  texmini  ──▶  install what is missing  ──▶  paper.pdf
```

pdfLaTeX, LuaLaTeX, XeLaTeX, BibTeX, Biber, indices, glossaries, nomenclatures, and the wider TeX Live package ecosystem remain available. Existing projects do not need to adopt a new document language or a different TeX engine.

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
| **texMini** | Builds conventional projects with pdfLaTeX, LuaLaTeX, or XeLaTeX | Automatically detects and installs needed TeX Live packages and common build tools into a private runtime | Run with `uvx` or Docker; delete `~/.texmini` to remove the native runtime | Arbitrary project-specific executables can require additional setup |
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

1. Select `paper.tex`, or find the unique top-level `.tex` file that declares a document class.
2. Recursively check local inputs, classes, and packages for required TeX files and build tools.
3. Install the private TinyTeX runtime if it does not exist.
4. Compile with managed `latexmk` and pdfLaTeX.
5. Read a failed build for missing TeX files, resolve their TeX Live packages, and install them together.
6. Continue installing and retrying while each round discovers a new package, with a 20-round safety ceiling.
7. Write the PDF to the effective `latexmk` output location and retain incremental build state by default.

For a path such as `docs/paper.tex`, texMini uses `latexmk -cd`, so sibling bibliographies, included files, logs, auxiliary state, and `paper.pdf` remain with the source. A root-level `latexmkrc` still loads and can configure the project.

Package mappings are cached in `~/.texmini/package-map.json`. Package installation modifies only texMini's private TinyTeX tree.

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

Use `--verbose` to stream complete subprocess output. On failure, the default output shows the primary LaTeX error and source line when available, points to the retained log, and warns when the failed invocation created or changed the PDF.

## Docker

Docker is the cross-platform, isolated pathway for Docker Desktop and Docker Engine users, including Windows. Compile a document in the current directory with:

```bash
docker run --rm -v "${PWD}:/work" ghcr.io/alexmill/texmini:latest paper.tex
```

Use the versioned image for a reproducible invocation:

```bash
docker run --rm -v "${PWD}:/work" ghcr.io/alexmill/texmini:0.4.0 paper.tex
```

The image bundles TinyTeX, Pygments, and packages used by common math, layout, BibTeX, Biber, index, glossary, nomenclature, minted, hyperlink, color, and TikZ documents. These workflows can therefore build from the downloaded image alone. When networking is available, texMini downloads uncommon TeX Live packages as needed. Those additions are discarded with `--rm`; this is an isolated ready-to-run workflow, not a promise that every possible project compiles offline.

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
  -v "${PWD}/tests/fixtures/bibliography:/work" \
  texmini bibliography.tex
```

TinyTeX bundle benchmark methodology and raw results are in [`benchmarks`](benchmarks).
