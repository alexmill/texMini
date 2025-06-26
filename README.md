# texMini: Ultra-lean LaTeX with Smart Package Loading

A minimal TeX Live distribution (~41MB) with intelligent on-demand package loading.

## Quick Start

```bash
# Basic compilation (minimal LaTeX) - auto-cleans auxiliary files on success
nix run github:alexmill/texMini#texMini -- -pdf document.tex

# Keep auxiliary files for debugging
nix run github:alexmill/texMini#texMini -- -pdf document.tex --no-clean

# Add packages on-the-fly with --extra
nix run github:alexmill/texMini#texMini -- -pdf document.tex --extra biber microtype fontspec

# Continuous compilation with preview (auto-disables cleanup)
nix run github:alexmill/texMini#texMini -- -pdf -pvc document.tex --extra tikz-cd biblatex

# Works with any latexmk options  
nix run github:alexmill/texMini#texMini -- -lualatex document.tex --extra fontspec unicode-math

# For local development, use the shell variant
nix shell github:alexmill/texMini#texMini -c latexmk -pdf document.tex
```

### VS Code LaTeX Workshop Integration

For seamless VS Code integration, use the environment-variable variant:

```bash
# Set extra packages via environment variable
TEXMINI_EXTRA_PACKAGES="microtype fontspec" nix shell github:alexmill/texMini#texMiniEnv -c latexmk -pdf document.tex

# Disable auto-cleanup if needed
TEXMINI_AUTO_CLEAN=false nix shell github:alexmill/texMini#texMiniEnv -c latexmk -pdf document.tex
```

## Usage Patterns

### One-off Compilation
Use `nix run` for quick compilation without entering a shell:
```bash
nix run github:alexmill/texMini#texMini -- -pdf document.tex
```

### Development Shell
Use `nix shell` for interactive development where you'll run multiple commands:
```bash
nix shell github:alexmill/texMini#texMini
# Now you have latexmk and texMini wrapper available in your PATH
latexmk -pdf document.tex
texmini -pdf document.tex --extra tikz-cd
```

### Environment Integration
Use the environment-variable variant for tool integration (VS Code, editors, CI/CD):
```bash
TEXMINI_EXTRA_PACKAGES="biblatex biber" nix shell github:alexmill/texMini#texMiniEnv -c latexmk -pdf paper.tex
```

### VS Code LaTeX Workshop Configuration

For VS Code with LaTeX Workshop extension, use this configuration in your `settings.json`:

```json
{
  "latex-workshop.latex.tools": [
    {
      "name": "texmini-latexmk",
      "command": "nix",
      "args": [
        "shell",
        "github:alexmill/texMini#texMiniEnv",
        "-c",
        "latexmk",
        "-pdf",
        "-interaction=nonstopmode",
        "-file-line-error",
        "%DOC%"
      ],
      "env": {
        "TEXMINI_EXTRA_PACKAGES": "microtype fontspec"
      }
    },
    {
      "name": "texmini-biblio",
      "command": "nix",
      "args": [
        "shell",
        "github:alexmill/texMini#texMiniBiblio",
        "-c",
        "latexmk",
        "-pdf",
        "-interaction=nonstopmode",
        "-file-line-error",
        "%DOC%"
      ],
      "env": {}
    }
  ],
  "latex-workshop.latex.recipes": [
    {
      "name": "texMini",
      "tools": ["texmini-latexmk"]
    },
    {
      "name": "texMini + Bibliography",
      "tools": ["texmini-biblio"]
    }
  ]
}
```

## Features

- **🚀 Ultra-lean**: ~41MB base installation with essential packages
- **🧠 Smart loading**: Add packages dynamically with `--extra package1 package2`
- **🧹 Auto-cleanup**: Removes auxiliary files after successful builds (disable with `--no-clean` or `TEXMINI_AUTO_CLEAN=false`)
- **📁 Filename-agnostic**: Works with any document name and cleans corresponding auxiliary files
- **⚡ Fast**: Pre-built variants for common use cases (biblio, typography, graphics)
- **🔄 Compatible**: Works with all latexmk options and compilation modes (pdflatex, lualatex, xelatex)
- **📦 Reproducible**: Pinned nixpkgs for consistent builds across machines
- **🎛️ Tool-friendly**: Environment variable interface for VS Code and other editors
- **🌐 Zero-install**: Run directly from GitHub without local installation

## Automatic Cleanup

texMini automatically cleans auxiliary files (`.aux`, `.log`, `.fls`, `.fdb_latexmk`) after successful compilation to keep your workspace tidy. This works with any filename:

- **✅ Successful build**: Auxiliary files are cleaned automatically
- **❌ Failed build**: Auxiliary files are preserved for debugging
- **🔄 Continuous mode (`-pvc`)**: Cleanup is disabled automatically
- **🛑 Manual override**: Use `--no-clean` flag or `TEXMINI_AUTO_CLEAN=false`

```bash
# These all work the same regardless of filename:
nix run github:alexmill/texMini#texMini -- -pdf my-thesis.tex           # Cleans my-thesis.aux, etc.
nix run github:alexmill/texMini#texMini -- -pdf report_final_v3.tex     # Cleans report_final_v3.aux, etc.  
nix run github:alexmill/texMini#texMini -- -pdf document.tex --no-clean # Keeps all auxiliary files
```

## Pre-configured Variants

Skip the `--extra` flag for common document types:

```bash
# Bibliography documents (includes biblatex, biber, csquotes)
nix shell github:alexmill/texMini#texMiniBiblio -c latexmk -pdf paper.tex

# Typography-focused (includes microtype, fontspec, unicode-math)
nix shell github:alexmill/texMini#texMiniTypo -c latexmk -pdf article.tex

# Graphics/TikZ documents (includes tikz-cd, pgfplots, circuitikz)
nix shell github:alexmill/texMini#texMiniGraphics -c latexmk -pdf diagrams.tex
```

## Advanced Usage

### Using in Your Own Flake

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    texMini.url = "github:alexmill/texMini";
  };
  
  outputs = { self, nixpkgs, texMini }:
    nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-darwin" "x86_64-darwin" ] (system:
      let
        pkgs = import nixpkgs { 
          inherit system; 
          overlays = [ texMini.overlays.default ];
        };
        
        # Use texMini with custom packages
        myTexLive = pkgs.texMiniWith {
          extra = [ "beamer" "tikz-cd" "biblatex" "biber" ];
        };
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [ myTexLive ];
        };
      });
}
```

## What's Included

### Base Minimal Set
- **Core**: `scheme-infraonly`, `latex-bin`, `latexmk`
- **Math**: `amsmath`, `amsfonts`, `amscls`  
- **Essential**: `geometry`, `hyperref`, `xcolor`, `graphics`
- **Language**: `babel` (basic multilingual support)
- **Graphics**: `pgf` (TikZ), `framed`
- **Dependencies**: Common packages needed by the above

### Pre-configured Additions
- **texMiniBiblio**: `biblatex`, `biber`, `csquotes`
- **texMiniTypo**: `microtype`, `fontspec`, `unicode-math`  
- **texMiniGraphics**: `tikz-cd`, `pgfplots`, `circuitikz`

## Common Package Names

When using `--extra`, here are some frequently needed packages:

- **Bibliography**: `biblatex`, `biber`, `csquotes`, `natbib`
- **Advanced graphics**: `tikz-cd`, `pgfplots`, `circuitikz`, `forest`
- **Typography**: `microtype`, `fontspec`, `unicode-math`, `polyglossia`
- **Document classes**: `beamer`, `memoir`, `koma-script`, `moderncv`
- **Math**: `mathtools`, `amsthm`, `thmtools`, `physics`
- **Tables**: `booktabs`, `longtable`, `array`, `tabularx`
- **Code**: `listings`, `minted`, `fvextra`

## Package Discovery

To find TeX Live package names:
- Search [CTAN](https://www.ctan.org/pkg) 
- Use `tlmgr search --global <package>` in any TeX Live installation
- Check the [TeX Live package database](https://tug.org/texlive/pkgcontrib.html)

## Size Comparison

How does texMini compare to other LaTeX distributions?

| Distribution | Base Size | Notes |
|--------------|-----------|-------|
| **texMini** | **~41MB** | This project - ultra-minimal but complete |
| TinyTeX | ~200MB | R-focused minimal TeX Live |
| MiKTeX Basic | ~200MB | Windows-focused basic installation |
| BasicTeX (MacTeX) | ~100MB | macOS minimal TeX Live subset |
| TeX Live Scheme-Basic | ~300MB | Official TeX Live basic scheme |
| TeX Live Full | ~5-7GB | Complete TeX Live installation |

**texMini achieves 10x size reduction** compared to other minimal distributions while maintaining full LaTeX functionality through smart on-demand package loading.


## Troubleshooting

### Common Issues

**Q: Package not found error**
```bash
# If you get "Package X not found", add it with --extra:
nix run github:alexmill/texMini#texMini -- -pdf document.tex --extra X
```

**Q: Want to keep auxiliary files for debugging**
```bash
# Use --no-clean flag:
nix run github:alexmill/texMini#texMini -- -pdf document.tex --no-clean
```

**Q: VS Code integration not working**
- Ensure you're using the `texMiniEnv` variant in your settings
- Check that environment variables are set correctly
- Verify the LaTeX Workshop extension is installed

**Q: Slow first run**
- texMini downloads ~41MB on first use - subsequent runs are cached
- Use `nix shell` for development sessions to avoid repeated downloads

## Why texMini?

- **Size**: Standard TeX Live is 5+ GB, texMini is just ~41MB
- **Speed**: Faster downloads and builds
- **Flexibility**: Add exactly what you need, when you need it  
- **Reproducible**: Pinned dependencies, consistent across machines
- **Smart**: The `--extra` flag makes package management effortless