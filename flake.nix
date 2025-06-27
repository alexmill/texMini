{
  description = "Ultra-lean TeX Live (~41MB) with smart package loading and bibliography support by default";

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
        
        # Default is now bibliography-enabled for better compatibility
        texMiniDefault = texMiniBiblio;

        # Cleanup script
        cleanupScript = pkgs.writeShellScript "texmini-cleanup" ''
          set -euo pipefail
          
          # Parse arguments to determine if cleanup should be disabled and separate file arguments
          AUTO_CLEAN=''${TEXMINI_AUTO_CLEAN:-true}
          LATEXMK_ARGS=()
          TEX_FILE=""
          BIB_FILES=()
          
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
              *.tex)
                if [[ -z "$TEX_FILE" ]]; then
                  TEX_FILE="$arg"
                  LATEXMK_ARGS+=("$arg")
                else
                  echo "Error: Multiple .tex files specified: $TEX_FILE and $arg"
                  echo "Please specify only one .tex file to compile."
                  exit 1
                fi
                ;;
              *.bib)
                BIB_FILES+=("$arg")
                # Don't add .bib files to latexmk args - they're handled automatically
                ;;
              *)
                LATEXMK_ARGS+=("$arg")
                ;;
            esac
          done
          
          # If TEX_FILE is set, we have an explicit .tex file
          has_tex_file=false
          detected_tex_file=""
          if [[ -n "$TEX_FILE" ]]; then
            has_tex_file=true
            detected_tex_file="$TEX_FILE"
          fi
          
          # If no .tex file specified, try to auto-detect
          if [[ "$has_tex_file" == "false" ]]; then
            # Check if there's exactly one .tex file in the current directory
            tex_files=(*.tex)
            if [ ''${#tex_files[@]} -eq 1 ] && [ -f "''${tex_files[0]}" ]; then
              echo "Auto-detected LaTeX file: ''${tex_files[0]}"
              LATEXMK_ARGS+=("''${tex_files[0]}")
              detected_tex_file="''${tex_files[0]}"
            else
              echo "Error: No .tex file specified and unable to auto-detect."
              if [ ''${#tex_files[@]} -eq 0 ]; then
                echo "No .tex files found in current directory."
              elif [ ''${#tex_files[@]} -gt 1 ]; then
                echo "Multiple .tex files found: ''${tex_files[*]}"
                echo "Please specify which file to compile."
              fi
              exit 1
            fi
          fi
          
          # Auto-detect bibliography setup if the .tex file uses biblatex/biber
          if [[ -n "$detected_tex_file" && -f "$detected_tex_file" ]]; then
            # Check if the .tex file uses biblatex or bibliography commands
            if grep -q -E '\\(usepackage.*biblatex|bibliography\{|addbibresource\{)' "$detected_tex_file"; then
              echo "Detected bibliography usage in $detected_tex_file"
              
              # Use explicitly specified .bib files if provided
              if [ ''${#BIB_FILES[@]} -gt 0 ]; then
                echo "Using explicitly specified bibliography files: ''${BIB_FILES[*]}"
                
                # Validate that all specified .bib files exist
                for bib_file in "''${BIB_FILES[@]}"; do
                  if [[ ! -f "$bib_file" ]]; then
                    echo "Error: Specified bibliography file '$bib_file' not found"
                    exit 1
                  fi
                done
                
                # Check if the .tex file references the specified .bib files
                for bib_file in "''${BIB_FILES[@]}"; do
                  if ! grep -q "$bib_file" "$detected_tex_file"; then
                    echo "Warning: Bibliography file $bib_file specified but not referenced in $detected_tex_file"
                    echo "You may need to add \\addbibresource{$bib_file} to your document"
                  fi
                done
              else
                # Auto-detect .bib files as before
                bib_files=(*.bib)
                if [ ''${#bib_files[@]} -eq 1 ] && [ -f "''${bib_files[0]}" ]; then
                  echo "Auto-detected bibliography file: ''${bib_files[0]}"
                  
                  # Check if the .tex file already references this .bib file
                  if ! grep -q "''${bib_files[0]}" "$detected_tex_file"; then
                    echo "Warning: Bibliography file ''${bib_files[0]} found but not referenced in $detected_tex_file"
                    echo "You may need to add \\addbibresource{''${bib_files[0]}} to your document"
                  fi
                elif [ ''${#bib_files[@]} -eq 0 ]; then
                  echo "Warning: Bibliography commands found in $detected_tex_file but no .bib files found"
                elif [ ''${#bib_files[@]} -gt 1 ]; then
                  echo "Info: Multiple .bib files found: ''${bib_files[*]}"
                  echo "Make sure the correct ones are referenced in your document"
                  echo "Or specify explicitly: nix run . -- $detected_tex_file file1.bib file2.bib"
                fi
              fi
            fi
          fi
          
          # Run latexmk with filtered arguments
          latexmk "''${LATEXMK_ARGS[@]}"
          exit_code=$?
          
          # Clean up auxiliary files if compilation was successful and auto-clean is enabled
          if [[ $exit_code -eq 0 && "$AUTO_CLEAN" == "true" ]]; then
            # After successful compilation, clean up ALL auxiliary files
            # Keep only: .tex (source), .bib (bibliography database), .pdf (output)
            
            # Get the base name from the first argument (assuming it's the .tex file)
            basename=""
            for arg in "''${LATEXMK_ARGS[@]}"; do
              if [[ "$arg" == *.tex ]]; then
                basename="''${arg%.tex}"
                break
              fi
            done
            
            if [[ -n "$basename" ]]; then
              # Remove all auxiliary files for this document
              for ext in aux bbl bcf blg fls fdb_latexmk log nav out snm toc vrb run.xml; do
                rm -f "$basename.$ext" 2>/dev/null || true
              done
              echo "✓ Build successful, all auxiliary files cleaned (kept: .tex, .bib, .pdf)"
            else
              # Fallback: remove common auxiliary file extensions
              for ext in aux bbl bcf blg fls fdb_latexmk log nav out snm toc vrb; do
                find . -maxdepth 1 -name "*.$ext" -delete 2>/dev/null || true
              done
              find . -maxdepth 1 -name "*.run.xml" -delete 2>/dev/null || true
              echo "✓ Build successful, auxiliary files cleaned"
            fi
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
          # Default LaTeX commands (now with bibliography support)
          pdflatex = makePdfLatexCommand "pdflatex" texMiniDefault;
          lualatex = makeLuaLatexCommand "lualatex" texMiniDefault;
          xelatex = makeXeLatexCommand "xelatex" texMiniDefault;
          latexmk = makePdfLatexCommand "latexmk" texMiniDefault;
          
          # Basic LaTeX commands (lightweight, no bibliography)
          pdflatex-basic = makePdfLatexCommand "pdflatex-basic" texMiniBasic;
          lualatex-basic = makeLuaLatexCommand "lualatex-basic" texMiniBasic;
          xelatex-basic = makeXeLatexCommand "xelatex-basic" texMiniBasic;
          latexmk-basic = makePdfLatexCommand "latexmk-basic" texMiniBasic;
          
          # Explicit bibliography-enabled LaTeX commands (same as default now)
          pdflatex-biblio = makePdfLatexCommand "pdflatex-biblio" texMiniBiblio;
          lualatex-biblio = makeLuaLatexCommand "lualatex-biblio" texMiniBiblio;
          xelatex-biblio = makeXeLatexCommand "xelatex-biblio" texMiniBiblio;
          latexmk-biblio = makePdfLatexCommand "latexmk-biblio" texMiniBiblio;

          # Raw TeX Live packages (for nix shell usage)
          texMiniBasic = texMiniBasic;
          texMiniBiblio = texMiniBiblio;

          # Default (now bibliography-enabled)
          default = makePdfLatexCommand "texmini" texMiniDefault;
        };

        # For nix shell usage
        devShells = {
          default = pkgs.mkShell {
            buildInputs = [ texMiniDefault ];
          };
          basic = pkgs.mkShell {
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
