# texMini

**LaTeX that just works, without managing a full TeX installation.**

Install [uv](https://docs.astral.sh/uv/), open a LaTeX project, and run:

```bash
uvx texmini paper.tex
```

texMini verifies a private TinyTeX runtime, discovers and installs missing TeX
Live packages, then builds with managed `latexmk`. It preserves ordinary LaTeX
projects and incremental state while avoiding a system TeX installation.

```bash
uvx texmini --watch paper.tex
uvx texmini --engine xelatex paper.tex
uvx texmini --shell-escape minted-paper.tex
```

pdfLaTeX, LuaLaTeX, XeLaTeX, BibTeX, Biber, indices, glossaries,
nomenclatures, minted, Beamer, multifile projects, `latexmkrc`, custom output
layouts, SyncTeX, cleanup, diagnostics, and watch mode remain supported. Use
`uv tool install texmini` for a persistent command.

Supported runtimes: macOS Apple Silicon/x86-64, Linux glibc x86-64/ARM64,
Linux musl x86-64, and Windows x86-64. macOS and Linux need Perl.

Official TinyTeX artifacts are release-pinned and SHA-256 verified. Shell
escape is never enabled implicitly.

See the [complete documentation and safety model](https://github.com/alexmill/texMini#readme).
