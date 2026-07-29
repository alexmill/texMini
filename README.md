# texMini

texMini compiles LaTeX documents with a private, managed TinyTeX installation. It detects bibliography usage, installs missing TeX Live packages, retries the build, and removes auxiliary files after a successful compile.

texMini is distributed through PyPI for uv users and through GHCR as a multi-architecture Docker image.

## uv

Requirements:

- [uv](https://docs.astral.sh/uv/)
- Perl, which TinyTeX requires for `tlmgr` and `latexmk`

Install from PyPI:

```bash
uv tool install texmini
texmini document.tex
```

Run without keeping the tool installed:

```bash
uvx texmini document.tex
```

The first compile downloads TinyTeX-0 into `~/.texmini/TinyTeX`, bootstraps the core compiler, and installs packages required by the document. Later builds reuse that runtime.

Install the current development snapshot from GitHub:

```bash
uv tool install git+https://github.com/alexmill/texMini
```

## Docker

Pull the published image:

```bash
docker pull ghcr.io/alexmill/texmini:latest
```

Compile from the current directory:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" \
  ghcr.io/alexmill/texmini:latest document.tex
```

The image contains TinyTeX-1 plus common math, layout, bibliography, hyperlink, color, and TikZ packages. It can compile the repository fixtures without network access:

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" \
  ghcr.io/alexmill/texmini:latest test.tex
```

Uncommon packages are installed into the container at runtime when networking is available. Those additions are discarded with a `--rm` container.

## How the CLI works

The normal command is:

```bash
texmini paper.tex
```

texMini then:

1. Selects `paper.tex`, or auto-detects the source when the directory contains exactly one `.tex` file.
2. Scans the source for bibliography commands and checks explicitly supplied `.bib` files.
3. Installs the private TinyTeX runtime when it is not already present.
4. Runs managed `latexmk` with `pdflatex`.
5. If the build reports missing TeX files, resolves and installs their TeX Live packages, then retries.
6. Writes `paper.pdf` beside the source and removes auxiliary files after a successful build.

The same command is used after both uv and Docker installation. Docker already contains the TinyTeX runtime and common packages, so it normally begins at the compile step.

## CLI reference

```text
texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex] [OPTIONS] [document.tex] [refs.bib ...]
```

Options:

- `--engine ENGINE`: select `pdflatex`, `lualatex`, or `xelatex`.
- `--no-clean`: retain auxiliary files after a successful build.
- `--no-install`: disable document-driven TeX Live package installation.
- `--version`: print the texMini version.

Arguments not handled by texMini are passed to managed `latexmk`. Continuous preview mode is not supported.

Examples:

```bash
texmini paper.tex
texmini --engine lualatex paper.tex
texmini --no-clean paper.tex
texmini paper.tex references.bib
```

If the working directory contains exactly one `.tex` file, the filename may be omitted:

```bash
texmini
```

Use `install-tinytex` to prepare the managed runtime without compiling:

```bash
texmini install-tinytex
```

## Managed Packages

texMini starts with TinyTeX-0 for uv installations. A failed build is handled by:

1. Reading the LaTeX log and source for missing classes, packages, fonts, bibliography styles, and Biber.
2. Resolving files to TeX Live packages through a small built-in map, a local cache, or `tlmgr search`.
3. Installing all newly resolved packages in one `tlmgr install` call.
4. Retrying the build up to five times.

Package mappings are cached in `~/.texmini/package-map.json`. Package installation only modifies texMini's private TinyTeX tree.

## Bibliographies

texMini detects `\bibliography{...}`, `\addbibresource{...}`, and `biblatex`. Explicit `.bib` arguments are checked before compilation:

```bash
texmini paper.tex references.bib
```

Biber is installed automatically when a managed document uses `biblatex`.

## Cleanup

Successful builds keep `.tex`, `.bib`, and `.pdf` files. Common LaTeX auxiliaries such as `.aux`, `.bbl`, `.bcf`, `.blg`, `.log`, `.toc`, `.run.xml`, and Metafont's `missfont.log` are removed unless `--no-clean` is used. Failed builds retain their logs.

## Environment

- `TEXMINI_ENGINE`: default engine; defaults to `pdflatex`.
- `TEXMINI_AUTO_CLEAN=false`: disable successful-build cleanup.
- `TEXMINI_AUTO_INSTALL=false`: disable document-driven package installation.
- `TEXMINI_TINYTEX_ROOT`: managed TinyTeX directory; defaults to `~/.texmini/TinyTeX`.
- `TEXMINI_TINYTEX_BUNDLE`: release bundle; defaults to `TinyTeX-0`.
- `TEXMINI_PACKAGE_MAP`: package mapping cache; defaults to `~/.texmini/package-map.json`.

## Development

Run texMini from the source tree:

```bash
uv run texmini document.tex
```

Run the Python suite and validate the distributions:

```bash
uv run python -m unittest discover -s tests -v
uv build --sdist --wheel
uvx --from twine==6.2.0 twine check dist/*
```

Build and smoke-test Docker:

```bash
docker build -t texmini .
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" \
  texmini test.tex
```

## Releases

Production releases come from annotated stable-version tags. Update `texmini.__version__`, merge the change to `main`, wait for CI to pass, then create and push the matching tag:

```bash
git tag -a v0.2.0 -m "texMini 0.2.0"
git push origin v0.2.0
```

GitHub Actions validates the tag, builds and tests both distributions, publishes to PyPI and GHCR, and creates the GitHub Release. PyPI publication waits for approval in the `pypi` GitHub environment.

TinyTeX bundle benchmark methodology and raw results are in [`benchmarks`](benchmarks).
