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

        # Helper functions
        asAttr = names: builtins.listToAttrs (map (n: { name = n; value = texlive.${n}; }) names);
        
        # Validate and filter valid package names
        validatePackages = packages: 
          builtins.filter (pkg: texlive ? ${pkg}) packages;
        
        # Create texlive combination with validation
        makeTexLive = packages: 
          let validPackages = validatePackages packages;
          in texlive.combine (asAttr validPackages);

        texMini = makeTexLive minimalSet;

        # Shared cleanup logic
        cleanupScript = pkgs.writeShellScript "texmini-cleanup" ''
          set -euo pipefail
          
          # Run latexmk with provided arguments
          latexmk "$@"
          exit_code=$?
          
          # Parse arguments to determine if cleanup should be disabled
          AUTO_CLEAN=''${TEXMINI_AUTO_CLEAN:-true}
          for arg in "$@"; do
            case "$arg" in
              -pvc|--no-clean) AUTO_CLEAN=false ;;
            esac
          done
          
          # Clean up auxiliary files if compilation was successful and auto-clean is enabled
          if [[ $exit_code -eq 0 && "$AUTO_CLEAN" == "true" ]]; then
            latexmk -c 2>/dev/null || true  # Don't fail if cleanup fails
            echo "✓ Build successful, auxiliary files cleaned"
          elif [[ $exit_code -ne 0 ]]; then
            echo "✗ Build failed, keeping auxiliary files for debugging"
          fi
          
          exit $exit_code
        '';

        # Create texlive package with extra packages
        texMiniWith = extra: makeTexLive (minimalSet ++ extra);

        # Create a wrapper that handles extra packages
        makeSmartWrapper = useEnvVars: name: pkgs.writeShellScriptBin name (''
          set -euo pipefail
          
          # Parse packages based on mode
        '' + (if useEnvVars then ''
          # Environment variable mode (for VS Code integration)
          EXTRA_PACKAGES_STR="''${TEXMINI_EXTRA_PACKAGES:-}"
          if [[ -n "$EXTRA_PACKAGES_STR" ]]; then
            IFS=' ,' read -ra EXTRA_PACKAGES <<< "$EXTRA_PACKAGES_STR"
          else
            EXTRA_PACKAGES=()
          fi
          LATEXMK_ARGS=("$@")
        '' else ''
          # Command line flag mode
          EXTRA_PACKAGES=()
          LATEXMK_ARGS=()
          
          while [[ $# -gt 0 ]]; do
            case $1 in
              --extra)
                shift
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
        '') + ''
          
          if [ ''${#EXTRA_PACKAGES[@]} -eq 0 ]; then
            # No extra packages, use basic texMini
            export PATH="${texMini}/bin:$PATH"
            exec ${cleanupScript} "''${LATEXMK_ARGS[@]}"
          else
            # Validate packages exist
            VALID_PACKAGES=()
            INVALID_PACKAGES=()
            
            for pkg in "''${EXTRA_PACKAGES[@]}"; do
              # Simple validation - check if package looks reasonable
              if [[ "$pkg" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
                VALID_PACKAGES+=("$pkg")
              else
                INVALID_PACKAGES+=("$pkg")
              fi
            done
            
            if [ ''${#INVALID_PACKAGES[@]} -gt 0 ]; then
              echo "Warning: Skipping invalid package names: ''${INVALID_PACKAGES[*]}" >&2
            fi
            
            if [ ''${#VALID_PACKAGES[@]} -eq 0 ]; then
              echo "No valid extra packages specified, using basic texMini"
              export PATH="${texMini}/bin:$PATH"
              exec ${cleanupScript} "''${LATEXMK_ARGS[@]}"
            fi
            
            echo "Building with extra packages: ''${VALID_PACKAGES[*]}"
            
            # Create nix expression for extended texlive
            PACKAGES_NIX="[ "
            for pkg in "''${VALID_PACKAGES[@]}"; do
              PACKAGES_NIX+="\"$pkg\" "
            done
            PACKAGES_NIX+="]"
            
            exec ${pkgs.nix}/bin/nix shell \
              --expr "
                let
                  flake = builtins.getFlake (toString ${./.});
                  system = builtins.currentSystem;
                in
                  flake.lib.\''${system}.texMiniWith { extra = $PACKAGES_NIX; }
              " \
              --impure \
              -c ${cleanupScript} "''${LATEXMK_ARGS[@]}"
          fi
        '');

        # Smart wrapper for command-line use
        texMiniSmart = makeSmartWrapper false "texmini";
        
        # Environment-variable wrapper for VS Code integration  
        texMiniEnv = makeSmartWrapper true "latexmk";

        # Pre-configured variants for common needs
        texMiniBiblioBase = makeTexLive (minimalSet ++ [ "biblatex" "biber" "csquotes" ]);
        texMiniTypoBase = makeTexLive (minimalSet ++ [ "microtype" "fontspec" "unicode-math" ]);
        texMiniGraphicsBase = makeTexLive (minimalSet ++ [ "tikz-cd" "pgfplots" "circuitikz" ]);
        
        # Create auto-cleanup wrappers for the variants
        makeCleanupWrapper = texlivePkg: pkgs.writeShellScriptBin "latexmk" ''
          export PATH="${texlivePkg}/bin:$PATH"
          exec ${cleanupScript} "$@"
        '';

      in {
        # nix build .#texMini       → < 80 MB store path with smart --extra support and auto-cleanup
        packages.texMini = pkgs.symlinkJoin {
          name = "texmini-smart";
          paths = [ texMiniSmart texMini ];  # Our wrapper first, then texMini
          postBuild = ''
            # Create a latexmk symlink that points to our texmini wrapper for compatibility
            ln -sf $out/bin/texmini $out/bin/latexmk
          '';
        };
        
        # Environment-variable driven wrapper (ideal for VS Code integration)
        packages.texMiniEnv = pkgs.symlinkJoin {
          name = "texmini-env";
          paths = [ texMiniEnv texMini ];
        };
        
        # Basic texMini without smart wrapper (for reference)
        packages.texMiniBasic = texMini;
        
        packages.texMiniBiblio = pkgs.symlinkJoin {
          name = "texmini-biblio";
          paths = [ (makeCleanupWrapper texMiniBiblioBase) texMiniBiblioBase ];
        };
        
        packages.texMiniTypo = pkgs.symlinkJoin {
          name = "texmini-typo";
          paths = [ (makeCleanupWrapper texMiniTypoBase) texMiniTypoBase ];
        };
        
        packages.texMiniGraphics = pkgs.symlinkJoin {
          name = "texmini-graphics";
          paths = [ (makeCleanupWrapper texMiniGraphicsBase) texMiniGraphicsBase ];
        };

        # dev shell for quick tests: pdflatex + tlmgr exposed
        devShells.default = pkgs.mkShell {
          buildInputs = [ texMini pkgs.perl ];
          shellHook = "export PATH=${texMini}/bin:$PATH";
        };

        lib.texMiniWith = { extra ? [] }:
          makeTexLive (minimalSet ++ extra);
      }) // {
        # expose a helper so others can extend this baseline (system-independent)
        overlays.default = final: prev: 
          let
            # Define minimalSet in overlay scope for consistency
            overlayMinimalSet = [
              "scheme-infraonly" "latex-bin" "amsmath" "amsfonts" "amscls" "geometry"
              "hyperref" "xcolor" "graphics" "babel" "latexmk" "framed" "ucs" "ec"
              "pgf" "pdftexcmds" "infwarerr" "kvoptions" "etoolbox" "refcount"
              "collection-latexrecommended"
            ];
            asAttr = names: builtins.listToAttrs (map (n: { name = n; value = prev.texlive.${n}; }) names);
            validatePackages = packages: builtins.filter (pkg: prev.texlive ? ${pkg}) packages;
            makeTexLive = packages: 
              let validPackages = validatePackages packages;
              in prev.texlive.combine (asAttr validPackages);
          in {
            texMini = makeTexLive overlayMinimalSet;
            texMiniWith = { extra ? [] }: makeTexLive (overlayMinimalSet ++ extra);
          };
      };
}
