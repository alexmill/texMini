# texMini

texMini is a small LaTeX command wrapper with managed package autoinstall, bibliography detection, and auxiliary-file cleanup. It provides full LaTeX engines; the default only minimizes what is downloaded before a document proves it needs more.

## Requirements & Quickstart

Install one of these prerequisites:

- Node.js 20+ with npm and Perl (recommended for Node users)
- `uv` (recommended for Python users)
- Homebrew
- Nix
- Docker
- Zig and Python 3.10+

An existing TeX Live or BasicTeX installation with `latexmk` is optional. texMini reuses it without modifying it.

```bash
npm install --global git+https://github.com/alexmill/texMini.git#main
texmini test.tex
```

The npm launcher is Node-native and does not require Python or uv. See the install section for the uv alternative and one-off `npm exec` usage.

If the current directory contains exactly one `.tex` file, run `texmini` without a filename.

The default selection minimizes added footprint:

1. Reuse `latexmk` from `PATH` when present. This adds no TeX runtime and never runs `tlmgr install`.
2. Otherwise, download the 0.9 MiB TinyTeX-0 infrastructure archive, bootstrap the core engines, and batch-install only packages required by the document.

TinyTeX-1 is the faster cold-start option. Nix and Docker use pinned package closures and never install packages at runtime.

## Benchmarks

Measured on macOS 26.3.1 arm64 on 2026-07-14. Platform prerequisites were already installed. Wrapper installs used a local checkout so package-manager overhead is separate from source-transfer time. `test.tex` includes TikZ and a Biber bibliography; `simple.tex` is used only for the intentionally reduced `-basic` targets.

### Install And First PDF

| Path | Install / build | Execute | Wrapper install | First PDF | Added footprint | Measured network |
| --- | --- | --- | ---: | ---: | ---: | --- |
| npm, recommended for Node | `npm install --global git+https://github.com/alexmill/texMini.git#main` | `texmini test.tex` | 0.79s, 3.8 MiB from a local 14.6 kB package | 70.98s cold; 4.43s warm | 3.8 MiB wrapper plus 257.7 MiB TinyTeX after `test.tex` | npm dependency and Git transfer not measured; 0.9 MiB TinyTeX archive + 95.1 MiB package payload reported by `tlmgr` |
| uv tool, recommended | `uv tool install git+https://github.com/alexmill/texMini` | `texmini test.tex` | 1.16s, 216 KiB | 71.19s cold; 4.42s warm | 257.7 MiB TinyTeX after `test.tex` | 0.9 MiB archive + 95.1 MiB package payload reported by `tlmgr` |
| uv local checkout | `uv sync` | `uv run texmini test.tex` | 1.32s, 124 KiB | Same managed runtime | Same 257.7 MiB | Same managed-runtime downloads |
| Homebrew | `brew tap alexmill/texmini https://github.com/alexmill/texMini && brew install alexmill/texmini/texmini` | `texmini test.tex` | 8.44s, 136 KiB formula | Same managed runtime | 84.6 MiB Python dependency when not shared, plus TinyTeX | Managed-runtime downloads; Homebrew transfer not measured |
| Zig wrapper | `zig build install --prefix ~/.local` | `~/.local/bin/texmini test.tex` | 6.38s, 96 KiB | Same managed runtime | Uses Python from `PATH`, plus TinyTeX | No wrapper network from a local checkout; same managed-runtime downloads |
| Existing TeX Live | Install TeX Live separately, then install a wrapper above | `texmini --backend latexmk test.tex` | Depends on wrapper | Not measured; no host `latexmk` | No added TeX runtime | None from texMini; package autoinstall is disabled |
| TinyTeX-1 opt-in | Set `TEXMINI_TINYTEX_BUNDLE=TinyTeX-1` before the first run | `texmini test.tex` | Same wrapper | 24.00s cold; 4.35s warm | 338.0 MiB after `test.tex` | 63.3 MiB archive + 67.5 MiB package payload reported by `tlmgr` |
| Nix profile | `nix profile install github:alexmill/texMini` | `texmini test.tex` | Not measured on host | Same closure tested through Docker | 500.7 MiB unpacked closure | 113.6 MiB declared download; no runtime network |
| Nix one-shot | No persistent wrapper install | `nix run github:alexmill/texMini -- test.tex` | Not measured on host | Same closure tested through Docker | Same default closure | Same realization download; no runtime autoinstall |
| Docker default | `docker build --no-cache -t texmini .` | `docker run --rm --network none -v "$PWD:/work" texmini test.tex` | 73.80s build | 4.18s median | 474.3 MiB image | 113.6 MiB Nix download during build; runtime network disabled |
| Docker basic | `docker build --no-cache --build-arg NIX_TARGET=pdflatex-basic -t texmini-basic .` | `docker run --rm --network none -v "$PWD:/work" texmini-basic simple.tex` | 54.49s build | 0.252s median for `simple.tex` | 407.3 MiB image | 105.7 MiB Nix download during build; runtime network disabled |

`tlmgr` payload is the sum of package sizes printed by TeX Live. It excludes HTTP and repository-index overhead. The Homebrew measurement used a temporary local tap and upgraded existing dependencies, so its elapsed time is reported but is less isolated than the uv and Zig wrapper measurements.

### Managed Bundle Comparison

Each bundle ran the same simple, common-package, seeded random-package, and overdispersed bibliography fixtures against an initially empty managed directory.

| Bundle | Release archive | Simple cold | Simple warm median | Final allocated runtime | Default use |
| --- | ---: | ---: | ---: | ---: | --- |
| TinyTeX-0 | 0.9 MiB | 40.40s | 0.339s | 254.5 MiB | Default: lowest measured footprint |
| TinyTeX-1 | 63.3 MiB | 9.86s | 0.334s | 340.5 MiB | Faster first build |
| TinyTeX | 198.7 MiB | 17.01s | 0.351s | 555.2 MiB | Preinstalled community bundle |

TinyTeX-0 saves 86.0 MiB versus TinyTeX-1 after the full fixture corpus. It pays for that with package-manager work on the first document. Full engines remain available: from the hydrated TinyTeX-0 `test.tex` runtime, first XeLaTeX provisioning took 12.75s and 64.6 MiB, while LuaLaTeX took 6.45s and 1.5 MiB.

Raw results and methodology are in [`benchmarks/results`](benchmarks/results) and [`benchmarks/README.md`](benchmarks/README.md). Nix was unavailable on the host, so fresh Nix closures were measured through Docker. The npm benchmark used the packed artifact with a failing `python3` shadow first on `PATH` to verify that the Node path is independent of Python.

## Backend Selection

Most users should leave backend selection on `auto`.

| Invocation | Install / build | Execute | Selected backend | Runtime package install |
| --- | --- | --- | --- | --- |
| npm | Install from GitHub as above | `texmini document.tex` | existing `latexmk`, otherwise TinyTeX-0 | Managed TinyTeX only |
| uv tool | `uv tool install git+https://github.com/alexmill/texMini` | `texmini document.tex` | existing `latexmk`, otherwise TinyTeX-0 | Managed TinyTeX only |
| uv checkout | `uv sync` | `uv run texmini document.tex` | existing `latexmk`, otherwise TinyTeX-0 | Managed TinyTeX only |
| Homebrew | Tap and install as above | `texmini document.tex` | existing `latexmk`, otherwise TinyTeX-0 | Managed TinyTeX only |
| Zig | `zig build install --prefix ~/.local` | `~/.local/bin/texmini document.tex` | existing `latexmk`, otherwise TinyTeX-0 | Managed TinyTeX only |
| Existing TeX Live | Install TeX Live separately | `texmini --backend latexmk document.tex` | `latexmk` from `PATH` | Never |
| Managed TinyTeX | Optional: `texmini install-tinytex` | `texmini --backend tinytex document.tex` | TinyTeX-0 owned by texMini | Enabled by default |
| Nix profile | `nix profile install github:alexmill/texMini` | `texmini document.tex` | pinned Nix `latexmk` closure | Never |
| Nix one-shot | None | `nix run github:alexmill/texMini -- document.tex` | pinned Nix `latexmk` closure | Never |
| Nix basic | None | `nix run github:alexmill/texMini#pdflatex-basic -- simple.tex` | pinned direct `pdflatex` closure | Never |
| Docker default | `docker build -t texmini .` | `docker run --rm -v "$PWD:/work" texmini document.tex` | pinned Nix `latexmk` closure | Never |
| Docker basic | Build with `NIX_TARGET=pdflatex-basic` | Run `texmini-basic simple.tex` in the image | pinned direct `pdflatex` closure | Never |

Use the default Nix/Docker target for bibliography-capable documents. The `-basic` targets deliberately omit bibliography, TikZ, hyperlinks, and multi-pass orchestration.

## Install

### npm

Install directly from GitHub over HTTPS:

```bash
npm install --global git+https://github.com/alexmill/texMini.git#main
texmini document.tex
```

Run without a permanent installation:

```bash
npm exec --yes \
  --package=git+https://github.com/alexmill/texMini.git#main \
  -- texmini document.tex
```

The npm package has no lifecycle scripts. npm installs its JavaScript archive-extraction dependencies normally; TinyTeX is downloaded only when the first document needs a managed runtime. Managed installation currently supports macOS and Linux and requires Perl for TeX Live's tools. On Windows, npm can use an existing `latexmk` backend.

### uv

```bash
uv tool install git+https://github.com/alexmill/texMini
texmini document.tex
```

The uv tool install uses texMini's shell wrapper directly, so it runs Python with `-S` instead of a generated console-script entry point.

For local development from this checkout:

```bash
uv run texmini document.tex
```

### Nix

```bash
nix profile install github:alexmill/texMini
texmini document.tex
```

The default Nix command uses the pinned TeX Live distribution from the flake instead of the TinyTeX downloader.

Available Nix commands:

```bash
nix run github:alexmill/texMini#pdflatex -- document.tex
nix run github:alexmill/texMini#lualatex -- document.tex
nix run github:alexmill/texMini#xelatex -- document.tex
nix run github:alexmill/texMini#latexmk -- document.tex
```

The `-basic` variants use a smaller package set. The direct engine variants omit `latexmk`; `latexmk-basic` keeps `latexmk` when build orchestration matters more than minimum runtime size. Nix latexmk wrappers are shell-only, so the reproducible paths do not carry texMini's Python CLI runtime.

```bash
nix run github:alexmill/texMini#pdflatex-basic -- simple.tex
```

`pdflatex-basic` is intended for simple documents that do not need bibliography processing, hyperlinks, color, TikZ, or multiple compile passes.

### Docker

```bash
docker build -t texmini .
docker run --rm -v "$PWD:/work" texmini document.tex
```

The Docker image is built from the Nix package closure. For documents that do not need bibliography packages, build the smaller basic image:

```bash
docker build --build-arg NIX_TARGET=pdflatex-basic -t texmini-basic .
docker run --rm -v "$PWD:/work" texmini-basic simple.tex
```

If you build images through Nix, use `.#docker` for the default image and `.#docker-basic` for the smaller image:

```bash
nix build .#docker
nix build .#docker-basic
```

### Zig

```bash
zig build install --prefix ~/.local
~/.local/bin/texmini document.tex
```

### Homebrew

```bash
brew tap alexmill/texmini https://github.com/alexmill/texMini
brew install alexmill/texmini/texmini
texmini document.tex
```

The Homebrew formula depends on Python and lets texMini download TinyTeX on demand.

## Usage

```bash
texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex|latexmk] [OPTIONS] [document.tex] [refs.bib ...]
```

Examples:

```bash
# Compile an explicit document.
texmini paper.tex

# Compile with an explicit bibliography file.
texmini paper.tex refs.bib

# Use LuaLaTeX.
texmini --engine lualatex paper.tex

# Keep auxiliary files.
texmini --no-clean paper.tex

# Continuous preview with latexmk.
texmini --backend latexmk -pvc paper.tex
```

Options:

- `--engine pdflatex|lualatex|xelatex|latexmk`: choose the LaTeX engine.
- `--no-clean`: keep auxiliary files after a successful build.
- `--no-install`: disable TinyTeX package autoinstall.
- `-pvc`: pass continuous-preview mode to `latexmk` and disable cleanup.
- `--version`: print the texMini version.

Optional setup command:

- `install-tinytex`: download and extract TinyTeX into `~/.texmini/TinyTeX` before the first compile. This is useful for prefetching, but normal builds do it automatically when needed.

Advanced backend override:

- `--backend auto`: use existing `latexmk` when available, otherwise use managed TinyTeX. This is the default.
- `--backend direct`: run the selected TeX engine once. The smallest Nix and Docker wrappers implement the same direct behavior in shell to avoid a Python runtime closure.
- `--backend latexmk`: force `latexmk` from `PATH`.
- `--backend tinytex`: force managed TinyTeX.

## TinyTeX Autoinstall

The managed TinyTeX backend starts from TinyTeX-0. It bootstraps `latex-bin`, `latexmk`, `metafont`, and `mfware`, then installs missing TeX Live packages only when texMini owns the target tree.

When a TinyTeX build fails, texMini scans the document log for missing TeX files, supplements that list with source-level package files that `kpsewhich` reports missing from the managed TinyTeX tree, resolves common files from a built-in seed map before falling back to `tlmgr search --global --file`, caches mappings in `~/.texmini/package-map.json`, installs newly needed packages in one `tlmgr install ...` command, and retries the build.

Autoinstall does not run for `--backend latexmk`, Nix, or Docker. Those paths use their existing TeX closure and summarize missing files from the `.log` on failed builds without mutating the TeX installation.

Disable document-driven package autoinstall. A new TinyTeX-0 tree still needs its one-time core bootstrap:

```bash
texmini --backend tinytex --no-install document.tex
TEXMINI_AUTO_INSTALL=false texmini document.tex
```

## Bibliography Handling

texMini checks the selected `.tex` file for common bibliography commands:

- `\usepackage{biblatex}`
- `\bibliography{...}`
- `\addbibresource{...}`

If bibliography usage is detected, texMini reports what it found and warns when explicitly provided `.bib` files are missing or not referenced. When one `.bib` file is present in the working directory, texMini reports it as the detected bibliography file.

The default Nix package includes `biblatex`, `biber`, and `csquotes`. The managed backend installs them only when the document needs them.

## Cleanup

After a successful build, texMini keeps the source and output files and removes common LaTeX auxiliaries.

Kept:

- `.tex`
- `.bib`
- `.pdf`

Removed:

- `.aux`
- `.bbl`
- `.bcf`
- `.blg`
- `.fls`
- `.fdb_latexmk`
- `.log`
- `.nav`
- `.out`
- `.snm`
- `.toc`
- `.vrb`
- `.run.xml`

Cleanup is skipped when the build fails, when `--no-clean` is passed, or when continuous preview mode is used.

## Environment

- `TEXMINI_BACKEND`: default backend. Defaults to `auto`.
- `TEXMINI_ENGINE`: default engine.
- `TEXMINI_AUTO_CLEAN=false`: disable cleanup.
- `TEXMINI_AUTO_INSTALL=false`: disable TinyTeX package autoinstall.
- `TEXMINI_TINYTEX_ROOT`: TinyTeX installation directory. Defaults to `~/.texmini/TinyTeX`.
- `TEXMINI_TINYTEX_BUNDLE`: TinyTeX release bundle. Defaults to `TinyTeX-0`; use `TinyTeX-1` for a faster first build.
- `TEXMINI_PACKAGE_MAP`: package mapping cache path. Defaults to `~/.texmini/package-map.json`.

## Tests

Run both local test suites:

```bash
uv run python -m unittest discover -s tests -v
npm test
npm run pack:check
```

## Included TeX Live Packages

The Nix package has two package sets.

Default:

- Core LaTeX: `scheme-infraonly`, `latex-bin`, `latexmk`
- Math and fonts: `amsmath`, `amsfonts`, `amscls`, `l3packages`, `lm`, `metafont`, `mfware`
- Common document packages: `geometry`, `hyperref`, `xcolor`, `graphics`, `babel`, `ec`, `epstopdf-pkg`, `framed`
- Graphics: `pgf`
- Bibliography: `biblatex`, `biber`, `csquotes`

Basic direct:

- Core LaTeX: `scheme-infraonly`, `latex-bin`
- Math: `amsmath`, `amsfonts`, `amscls`
- Layout: `geometry`

Basic with latexmk adds `latexmk` to that package set.

## Troubleshooting

No `.tex` file found:

```bash
texmini document.tex
```

Multiple `.tex` files found:

```bash
texmini main.tex
```

Use a different TinyTeX location:

```bash
TEXMINI_TINYTEX_ROOT="$PWD/.tinytex" texmini install-tinytex
TEXMINI_TINYTEX_ROOT="$PWD/.tinytex" texmini document.tex
```

Use an existing TeX installation:

```bash
texmini --backend latexmk document.tex
```

Keep logs for debugging:

```bash
texmini --no-clean document.tex
```
