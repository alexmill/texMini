{
  description = "Ultra-lean TeX Live (<100 MB) flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";  # pick a revision for reproducibility
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
        texlive = pkgs.texlive;

        # --- core: smallest usable LaTeX stack ---
        minimalSet = [
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
          "pgf"          # TikZ graphics
          "pdftexcmds"   # hyperref dependency
          "infwarerr"
          "kvoptions"
          "etoolbox"
          "refcount"
          "collection-latexrecommended"
          "cm-super"     # Complete Computer Modern font collection including the missing tcrm1095
          "lm"           # Latin Modern fonts (better quality replacement for CM)
          "fontenc"      # Font encoding support
          "textcomp" 
        ];

        # helper to turn list of strings into attrset expected by texlive.combine
        asAttr = names: builtins.listToAttrs (map (n: { name = n; value = texlive.${n}; }) names);

        texMini = texlive.combine (asAttr minimalSet);

        # Smart wrapper that can handle --extra packages
        texMiniSmart = pkgs.writeShellScriptBin "latexmk" ''
          # Parse --extra packages
          EXTRA_PACKAGES=()
          LATEXMK_ARGS=()
          
          while [[ $# -gt 0 ]]; do
            case $1 in
              --extra)
                shift
                # Collect packages until we hit another flag or end
                while [[ $# -gt 0 && $1 != -* ]]; do
                  EXTRA_PACKAGES+=("$1")
                  shift
                done
                ;;
              *)
                LATEXMK_ARGS+=("$1")
                shift
                ;;
            esac
          done
          
          if [ ''${#EXTRA_PACKAGES[@]} -eq 0 ]; then
            # No extra packages, use basic texMini
            exec ${texMini}/bin/latexmk "''${LATEXMK_ARGS[@]}"
          else
            # Build nix expression with extra packages
            EXTRA_LIST=$(printf '"%s" ' "''${EXTRA_PACKAGES[@]}")
            EXTRA_LIST="[ $EXTRA_LIST]"
            
            echo "Building with extra packages: ''${EXTRA_PACKAGES[*]}"
            
            # Use nix shell with the extended texlive - find flake.nix in current dir
            FLAKE_DIR="$PWD"
            while [[ "$FLAKE_DIR" != "/" && ! -f "$FLAKE_DIR/flake.nix" ]]; do
              FLAKE_DIR=$(dirname "$FLAKE_DIR")
            done
            
            if [[ -f "$FLAKE_DIR/flake.nix" ]]; then
              cd "$FLAKE_DIR"
              exec nix shell --impure --expr "
                let
                  flake = builtins.getFlake (toString ./.);
                  system = builtins.currentSystem;
                in
                  flake.lib.\''${system}.texMiniWith { extra = $EXTRA_LIST; }
              " -c latexmk "''${LATEXMK_ARGS[@]}"
            else
              echo "Error: Could not find flake.nix in current directory or parent directories"
              echo "Please run from within the texMini repository"
              exit 1
            fi
          fi
        '';

      in {
        # nix build .#texMini       → < 80 MB store path with smart --extra support
        packages.texMini = pkgs.symlinkJoin {
          name = "texmini-smart";
          paths = [ texMiniSmart texMini ];  # Our wrapper first, then texMini
        };
        
        # Basic texMini without smart wrapper (for reference)
        packages.texMiniBasic = texMini;
        
        # Pre-configured variants for common needs
        packages.texMiniBiblio = texlive.combine (asAttr (minimalSet ++ [ "biblatex" "biber" "csquotes" ]));
        packages.texMiniTypo = texlive.combine (asAttr (minimalSet ++ [ "microtype" "fontspec" "unicode-math" ]));
        packages.texMiniGraphics = texlive.combine (asAttr (minimalSet ++ [ "tikz-cd" "pgfplots" "circuitikz" ]));

        # dev shell for quick tests: pdflatex + tlmgr exposed
        devShells.default = pkgs.mkShell {
          buildInputs = [ texMini pkgs.perl ];
          shellHook = "export PATH=${texMini}/bin:$PATH";
        };

        lib.texMiniWith = { extra ? [] }:
          texlive.combine (asAttr (minimalSet ++ extra));
      }) // {
        # expose a helper so others can extend this baseline (system-independent)
        overlays.default = final: prev: {
          texMini = prev.texlive.combine (
            builtins.listToAttrs (map (n: { name = n; value = prev.texlive.${n}; }) [
              "scheme-infraonly" "latex-bin" "amsmath" "amsfonts" "amscls" "geometry"
              "hyperref" "xcolor" "graphics" "babel" "latexmk" "framed" "ucs" "ec"
              "pgf" "pdftexcmds" "infwarerr" "kvoptions" "etoolbox" "refcount"
              "collection-latexrecommended"
            ])
          );
          texMiniWith = { extra ? [] }: 
            let
              minimalSet = [
                "scheme-infraonly" "latex-bin" "amsmath" "amsfonts" "amscls" "geometry"
                "hyperref" "xcolor" "graphics" "babel" "latexmk" "framed" "ucs" "ec"
                "pgf" "pdftexcmds" "infwarerr" "kvoptions" "etoolbox" "refcount"
                "collection-latexrecommended"
              ];
              asAttr = names: builtins.listToAttrs (map (n: { name = n; value = prev.texlive.${n}; }) names);
            in
              prev.texlive.combine (asAttr (minimalSet ++ extra));
        };
      };
}
