# texMini: Ultra-lean LaTeX with Bibliography Support by Default

A minimal TeX Live distribution (~41MB) with intelligent file auto-detection, automatic bibliography support, and smart cleanup.

## Quick Start

```bash
# Auto-detect and compile with bibliography support included
nix run github:alexmill/texMini

# Specify files explicitly (recommended for scripts and automation)
nix run github:alexmill/texMini -- document.tex bibliography.bib

# Just specify .tex file (auto-detects .bib if present and unambiguous)
nix run github:alexmill/texMini -- document.tex
```

## Full Details
```bash
# Auto-detect .tex file in current directory (bibliography support included)
nix run github:alexmill/texMini#pdflatex

# Or specify explicitly  
nix run github:alexmill/texMini#pdflatex -- document.tex

# Different engines - with bibliography support by default
nix run github:alexmill/texMini#lualatex -- document.tex
nix run github:alexmill/texMini#xelatex -- document.tex

# Lightweight versions without bibliography packages
nix run github:alexmill/texMini#pdflatex-basic -- document.tex
nix run github:alexmill/texMini#lualatex-basic -- document.tex  
nix run github:alexmill/texMini#xelatex-basic -- document.tex

# Use latexmk (most common, bibliography support included)
nix run github:alexmill/texMini#latexmk -- -pdf document.tex

# Keep auxiliary files for debugging
nix run github:alexmill/texMini#pdflatex -- document.tex --no-clean

# For local development, use nix shell
nix shell github:alexmill/texMini          # bibliography support included
# or for lightweight shell:
nix shell github:alexmill/texMini#texMiniBasic
```

## Smart Features

### 🎯 Auto-Detection
- **Single .tex file**: Automatically detected and compiled if no file specified
- **Bibliography files**: Auto-detects `.bib` files and checks for proper references
- **Smart warnings**: Alerts for missing or ambiguous files with helpful suggestions

### 🧹 Intelligent Cleanup  
- **Default behavior**: Keeps only `.tex`, `.bib`, and `.pdf` files after successful builds
- **Failure preservation**: Auxiliary files retained on build errors for debugging
- **Flexible control**: Use `--no-clean` flag or continuous mode (`-pvc`) to disable cleanup

### Two Simple Levels

texMini provides exactly two levels to cover 99% of LaTeX use cases:

1. **Default** (`texMiniDefault`): Core LaTeX with math, graphics, hyperlinks, TikZ, **and bibliography support** (biblatex, biber, csquotes)
2. **Basic** (`texMiniBasic`): Lightweight core LaTeX with math, graphics, hyperlinks, and TikZ only

The default now includes bibliography support because most academic and professional documents need citations. Use the `-basic` variants only when you specifically need a lighter distribution.

### VS Code LaTeX Workshop Integration

For VS Code integration, choose the appropriate level and configure LaTeX Workshop:

```json
{
  "latex-workshop.latex.tools": [
    {
      "name": "texmini",
      "command": "nix",
      "args": [
        "run",
        "github:alexmill/texMini#latexmk",
        "--",
        "-pdf",
        "-interaction=nonstopmode",
        "-file-line-error",
        "%DOC%"
      ]
    },
    {
      "name": "texmini-basic",
      "command": "nix",
      "args": [
        "run",
        "github:alexmill/texMini#latexmk-basic",
        "--",
        "-pdf", 
        "-interaction=nonstopmode",
        "-file-line-error",
        "%DOC%"
      ]
    }
  ],
  "latex-workshop.latex.recipes": [
    {
      "name": "texMini (with Bibliography)",
      "tools": ["texmini"]
    },
    {
      "name": "texMini Basic (Lightweight)", 
      "tools": ["texmini-basic"]
    }
  ]
}
```

## Auto-Detection Examples

### Single File Projects
```bash
# If directory contains only "thesis.tex":
nix run github:alexmill/texMini#pdflatex
# → Auto-detects and compiles thesis.tex (with bibliography support)

# If directory contains "paper.tex" and "refs.bib":
nix run github:alexmill/texMini#pdflatex
# → Auto-detects paper.tex, detects bibliography usage,
#   automatically processes refs.bib if referenced in the document
```

### Multiple File Scenarios
```bash
# Directory with "intro.tex", "main.tex", "conclusion.tex":
nix run github:alexmill/texMini#pdflatex
# → Error: Multiple .tex files found, please specify which to compile

nix run github:alexmill/texMini#pdflatex -- main.tex
# → Compiles main.tex explicitly
```

### Bibliography Auto-Detection
```bash
# Document with \usepackage{biblatex} or \bibliography{} commands:
nix run github:alexmill/texMini#pdflatex -- paper.tex
# → Automatically detects and processes bibliography
# → If single .bib file found, checks if it's referenced
# → Warns about missing references or multiple .bib files
```

### Command-Line File Specification

texMini supports both explicit file specification and smart auto-detection:

#### Explicit File Specification (Recommended)
```bash
# Specify .tex file and single .bib file
nix run github:alexmill/texMini -- paper.tex refs.bib

# Multiple bibliography files
nix run github:alexmill/texMini -- thesis.tex refs.bib methods.bib

# Only .tex file (auto-detects .bib if unambiguous)  
nix run github:alexmill/texMini -- paper.tex

# Mix with latexmk options
nix run github:alexmill/texMini -- paper.tex refs.bib -pvc    # continuous preview
nix run github:alexmill/texMini -- paper.tex --no-clean      # keep aux files
```

#### Auto-Detection (Convenience)
```bash
# Full auto-detection (works when single .tex file present)
nix run github:alexmill/texMini
```

#### Error Handling
The system provides helpful feedback:
- **Missing .bib files**: Error if explicitly specified file doesn't exist
- **Unreferenced .bib files**: Warning if .bib file isn't cited in the document
- **Multiple candidates**: Clear guidance when auto-detection is ambiguous

## Usage Patterns

### One-off Compilation
Use `nix run` for quick compilation without entering a shell:
```bash
# Auto-detect single .tex file in current directory
nix run github:alexmill/texMini#latexmk

# Or specify explicitly
nix run github:alexmill/texMini#latexmk -- -pdf document.tex
```

### Development Shell
Use `nix shell` for interactive development where you'll run multiple commands:
```bash
# Default shell with bibliography support
nix shell github:alexmill/texMini
# Now you have latexmk available in your PATH
latexmk -pdf document.tex

# For lightweight shell without bibliography
nix shell github:alexmill/texMini#texMiniBasic
latexmk -pdf simple-document.tex
```

## Cleanup Behavior

texMini features intelligent cleanup that adapts to your workflow:

### Default Cleanup (Recommended)
After successful compilation, only essential files remain:
- **✅ Kept**: `.tex` (source), `.bib` (bibliography), `.pdf` (output)  
- **🗑️ Removed**: `.aux`, `.log`, `.bbl`, `.bcf`, `.blg`, `.fls`, `.fdb_latexmk`, `.nav`, `.out`, `.snm`, `.toc`, `.vrb`, `.run.xml`

```bash
# These all clean up automatically after successful builds:
nix run github:alexmill/texMini#pdflatex -- thesis.tex
nix run github:alexmill/texMini#pdflatex-biblio -- paper.tex
```

### When Cleanup is Disabled
- **Build failures**: Auxiliary files preserved for debugging
- **Continuous mode**: `latexmk -pvc` automatically disables cleanup
- **Manual override**: `--no-clean` flag or `TEXMINI_AUTO_CLEAN=false`

```bash
# Keep all files for debugging
nix run github:alexmill/texMini#pdflatex -- document.tex --no-clean

# Continuous preview mode (cleanup auto-disabled)
nix run github:alexmill/texMini#latexmk -- -pdf -pvc document.tex
```

## Features

- **🚀 Ultra-lean**: ~41MB base installation with essential packages
- **🎯 Auto-detection**: Automatically finds single `.tex` and `.bib` files when not specified
- **📝 Explicit specification**: Support for multiple `.tex` and `.bib` files via command line
- **🧠 Smart warnings**: Clear error messages for ambiguous, missing, or unreferenced files  
- **🧹 Intelligent cleanup**: Keeps only `.tex`, `.bib`, and `.pdf` files after successful builds
- **📁 Filename-agnostic**: Works with any document name and cleans corresponding auxiliary files
- **⚡ Fast**: Pre-built variants for common use cases (basic, bibliography)
- **🔄 Compatible**: Works with all latexmk options and compilation modes (pdflatex, lualatex, xelatex)
- **📦 Reproducible**: Pinned nixpkgs for consistent builds across machines
- **🛑 Debug-friendly**: Preserves auxiliary files on build failures or when explicitly requested
- **🌐 Zero-install**: Run directly from GitHub without local installation

## Smart Cleanup Details

texMini's cleanup system is designed to be helpful without getting in your way:

### What Gets Cleaned
After **successful** compilation, these auxiliary files are automatically removed:
- `.aux` (cross-references)
- `.log` (compilation log) 
- `.bbl` (bibliography)
- `.bcf` (biblatex control)
- `.blg` (bibliography log)
- `.fls` (file list)
- `.fdb_latexmk` (latexmk database)
- `.nav`, `.out`, `.snm`, `.toc`, `.vrb` (beamer/navigation)
- `.run.xml` (biblatex metadata)

### What's Always Kept
- `.tex` (your source files)
- `.bib` (bibliography databases)
- `.pdf` (compiled output)
- Any files not recognized as auxiliary

### Cleanup Examples
```bash
# Before compilation: thesis.tex, refs.bib
nix run github:alexmill/texMini#pdflatex-biblio -- thesis.tex
# After: thesis.tex, refs.bib, thesis.pdf (all .aux, .log, etc. removed)

# With multiple documents:
nix run github:alexmill/texMini#pdflatex -- chapter1.tex  
# Cleans chapter1.aux, chapter1.log, etc. (leaves other files untouched)

# Debug mode:
nix run github:alexmill/texMini#pdflatex -- thesis.tex --no-clean
# All auxiliary files preserved for inspection
```

## Available Commands

texMini provides focused command variants for different needs:

### Basic LaTeX (no bibliography)
```bash
# PDF output with pdflatex (most common)
nix run github:alexmill/texMini#pdflatex -- document.tex

# Alternative engines
nix run github:alexmill/texMini#lualatex -- document.tex  # Unicode & modern fonts
nix run github:alexmill/texMini#xelatex -- document.tex   # System fonts

# Full latexmk control (recommended for complex builds)
nix run github:alexmill/texMini#latexmk -- -pdf -pvc document.tex
```

### Bibliography Support
```bash
# Includes biblatex, biber, and csquotes
nix run github:alexmill/texMini#pdflatex-biblio -- paper.tex
nix run github:alexmill/texMini#lualatex-biblio -- paper.tex  
nix run github:alexmill/texMini#xelatex-biblio -- paper.tex
nix run github:alexmill/texMini#latexmk-biblio -- -pdf paper.tex
```

### Development Shells
```bash
# Enter a shell with basic LaTeX tools
nix shell github:alexmill/texMini#texMiniBasic

# Enter a shell with bibliography support  
nix shell github:alexmill/texMini#texMiniBiblio
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
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [ 
            texMini.packages.${system}.texMiniBasic
            # or texMini.packages.${system}.texMiniBiblio
          ];
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

## Common Use Cases

Here are some common packages you might need beyond the base installation:

- **Document classes**: `beamer`, `memoir`, `koma-script`, `moderncv`
- **Advanced math**: `mathtools`, `amsthm`, `thmtools`, `physics`
- **Tables**: `booktabs`, `longtable`, `array`, `tabularx`
- **Code listings**: `listings`, `minted`, `fvextra`
- **Advanced graphics**: `tikz-cd`, `pgfplots`, `circuitikz`, `forest`
- **Typography**: `microtype`, `fontspec`, `unicode-math`, `polyglossia`

To use packages beyond the base set, you can create your own flake that extends texMini with additional packages.

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

**Q: No .tex file found**
```bash
# Error: No .tex files found in current directory
# Solution: Create a .tex file or specify the path
nix run github:alexmill/texMini#pdflatex -- /path/to/document.tex
```

**Q: Multiple .tex files found**
```bash
# Error: Multiple .tex files found: main.tex intro.tex conclusion.tex
# Solution: Specify which file to compile
nix run github:alexmill/texMini#pdflatex -- main.tex
```

**Q: Bibliography not working**
```bash
# Warning: Bibliography commands found but no .bib files found
# Solution: Create a .bib file or use basic variant instead
nix run github:alexmill/texMini#pdflatex -- document.tex  # if no bibliography needed
```

**Q: Bibliography file not found**
```bash
# Error: Specified .bib file does not exist: missing.bib
# Solution: Check the filename and path
ls *.bib  # List available .bib files
nix run github:alexmill/texMini -- paper.tex refs.bib  # Use correct filename
```

**Q: Warning about unreferenced bibliography**
```bash
# Warning: refs.bib is not referenced in document.tex
# This means your .tex file doesn't cite anything from refs.bib
# Solution: Either remove the .bib file or add citations like \cite{key}
```

**Q: Multiple bibliography files not working**
```bash
# Make sure all .bib files exist and are referenced:
nix run github:alexmill/texMini -- thesis.tex refs.bib methods.bib
# Each .bib file should contain citations used in your document
```

**Q: Want to keep auxiliary files for debugging**
```bash
# Use --no-clean flag:
nix run github:alexmill/texMini#pdflatex -- document.tex --no-clean
```

**Q: VS Code integration not working**
- Ensure you're using the correct command variants in your LaTeX Workshop settings
- Check that the file paths in your VS Code config are correct
- Verify the LaTeX Workshop extension is installed and enabled

**Q: Slow first run**
- texMini downloads ~41MB on first use - subsequent runs are cached by Nix
- Use `nix shell` for development sessions to avoid repeated downloads

**Q: Missing packages**
- texMini focuses on core functionality to stay minimal
- For additional packages, create your own flake that extends texMini
- Most documents work with the provided basic or bibliography variants

## Why texMini?

- **Size**: Standard TeX Live is 5+ GB, texMini is just ~41MB
- **Speed**: Faster downloads and builds
- **Intelligence**: Auto-detects files and provides helpful error messages
- **Cleanliness**: Smart cleanup keeps your workspace organized  
- **Simplicity**: Two focused variants cover most use cases
- **Reproducible**: Pinned dependencies, consistent across machines
- **Zero-install**: Run directly from GitHub with `nix run`