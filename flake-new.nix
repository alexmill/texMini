{
  description = "Ultra-lean TeX Live (~41MB) with smart package loading";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
        texlive = pkgs.texlive;

        # --- Basic LaTeX (no bibliography) ---
        basicPackages = [
          "scheme-infraonly"   # engines + tlmgr
          "latex-bin"          # LaTeX formats + required macros (article.cls, etc.)
          "amsmath"            # math support used in >90% of docs
          "amsfonts"
          "amscls"
          "geometry"           # page margins; small footprint
          "hyperref"           # PDF metadata / links; pulls url & hycolor
          "xcolor"             # needed by hyperref & geometry for colors
          "graphics"           # includegraphics & small set of friends
          "babel"              # basic multilingual support
          "latexmk"
          "framed"
          "ucs"
          "ec"
          "pgf"                # TikZ graphics
          "pdftexcmds"         # hyperref dependency
          "infwarerr"
          "kvoptions"
          "etoolbox"
          "refcount"
          "collection-latexrecommended"
          "cm-super"           # Complete Computer Modern font collection
          "lm"                 # Latin Modern fonts
          "fontenc"            # Font encoding support
          "textcomp" 
        ];

        # --- LaTeX + Bibliography ---
        biblioPackages = basicPackages ++ [
          "biblatex"
          "biber"
          "csquotes"
        ];

        # Helper functions
        asAttr = names: builtins.listToAttrs (map (n: { name = n; value = texlive.${n}; }) names);
        makeTexLive = packages: texlive.combine (asAttr packages);

        # Base distributions
        texMiniBasic = makeTexLive basicPackages;
        texMiniBiblio = makeTexLive biblioPackages;

        # Cleanup script
        cleanupScript = pkgs.writeShellScript "texmini-cleanup" ''
          set -euo pipefail
          
          # Parse arguments to determine if cleanup should be disabled and filter out custom flags
          AUTO_CLEAN=''${TEXMINI_AUTO_CLEAN:-true}
          LATEXMK_ARGS=()
          
          for arg in "$@"; do
            case "$arg" in
              -pvc) 
                AUTO_CLEAN=false
                LATEXMK_ARGS+=("$arg")
                ;;
              --no-clean) 
                AUTO_CLEAN=false
                # Don't pass this custom flag to latexmk
                ;;
              *)
                LATEXMK_ARGS+=("$arg")
                ;;
            esac
          done
          
          # Run latexmk with filtered arguments
          latexmk "''${LATEXMK_ARGS[@]}"
          exit_code=$?
          
          # Clean up auxiliary files if compilation was successful and auto-clean is enabled
          if [[ $exit_code -eq 0 && "$AUTO_CLEAN" == "true" ]]; then
            latexmk -c 2>/dev/null || true  # Don't fail if cleanup fails
            echo "✓ Build successful, auxiliary files cleaned"
          elif [[ $exit_code -ne 0 ]]; then
            echo "✗ Build failed, keeping auxiliary files for debugging"
          fi
          
          exit $exit_code
        '';

        # Create individual command wrappers
        makeLatexCommand = name: engine: texlivePackage: pkgs.writeShellScriptBin name ''
          set -euo pipefail
          export PATH="${texlivePackage}/bin:$PATH"
          exec ${cleanupScript} ${engine} "$@"
        '';

        makePdfLatexCommand = name: texlivePackage: makeLatexCommand name "-pdf" texlivePackage;
        makeLuaLatexCommand = name: texlivePackage: makeLatexCommand name "-lualatex" texlivePackage;
        makeXeLatexCommand = name: texlivePackage: makeLatexCommand name "-xelatex" texlivePackage;

      in {
        packages = {
          # Basic LaTeX commands (no bibliography)
          pdflatex = makePdfLatexCommand "pdflatex" texMiniBasic;
          lualatex = makeLuaLatexCommand "lualatex" texMiniBasic;
          xelatex = makeXeLatexCommand "xelatex" texMiniBasic;
          latexmk = makePdfLatexCommand "latexmk" texMiniBasic;
          
          # Bibliography-enabled LaTeX commands
          pdflatex-biblio = makePdfLatexCommand "pdflatex-biblio" texMiniBiblio;
          lualatex-biblio = makeLuaLatexCommand "lualatex-biblio" texMiniBiblio;
          xelatex-biblio = makeXeLatexCommand "xelatex-biblio" texMiniBiblio;
          latexmk-biblio = makePdfLatexCommand "latexmk-biblio" texMiniBiblio;

          # Raw TeX Live packages (for nix shell usage)
          texMiniBasic = texMiniBasic;
          texMiniBiblio = texMiniBiblio;

          # Default (basic)
          default = makePdfLatexCommand "texmini" texMiniBasic;
        };

        # For nix shell usage
        devShells = {
          default = pkgs.mkShell {
            buildInputs = [ texMiniBasic ];
          };
          biblio = pkgs.mkShell {
            buildInputs = [ texMiniBiblio ];
          };
        };

        apps = {
          default = {
            type = "app";
            program = "${self.packages.${system}.default}/bin/texmini";
          };
        };
      });
}
