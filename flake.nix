{
  description = "Ultra-lean TeX Live with smart file detection and bibliography support by default";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
        texlive = pkgs.texlive;

        basicPackages = [
          "scheme-infraonly"
          "latex-bin"
          "amsmath"
          "amsfonts"
          "amscls"
          "geometry"
        ];

        basicLatexmkPackages = basicPackages ++ [
          "latexmk"
        ];

        commonPackages = [
          "hyperref"
          "xcolor"
          "graphics"
          "babel"
          "ec"
          "epstopdf-pkg"
          "framed"
          "metafont"
          "mfware"
          "pgf"
          "l3packages"
          "lm"
        ];

        biblioPackages = basicPackages ++ commonPackages ++ [
          "latexmk"
          "biblatex"
          "biber"
          "csquotes"
        ];

        asAttr = names: builtins.listToAttrs (map (n: { name = n; value = texlive.${n}; }) names);
        makeTexLive = packages: texlive.combine (asAttr packages);

        texMiniBasic = makeTexLive basicPackages;
        texMiniBasicLatexmk = makeTexLive basicLatexmkPackages;
        texMiniBiblio = makeTexLive biblioPackages;
        texMiniDefault = texMiniBiblio;

        version = "0.1.0";

        makeLatexmkCommand = name: defaultEngine: texlivePackage: pkgs.writeTextFile {
          inherit name;
          executable = true;
          destination = "/bin/${name}";
          text = ''
            #!${pkgs.bash}/bin/bash
            set -uo pipefail

            auto_clean="''${TEXMINI_AUTO_CLEAN:-true}"
            tex_file=""
            latexmk_args=()
            bib_files=()
            latexmk_engine_args=()

            set_engine() {
              case "$1" in
                texmini|latexmk|pdflatex)
                  latexmk_engine_args=("-pdf")
                  ;;
                lualatex)
                  latexmk_engine_args=("-lualatex")
                  ;;
                xelatex)
                  latexmk_engine_args=("-xelatex")
                  ;;
                *)
                  echo "Error: --engine must be pdflatex, lualatex, xelatex, or latexmk." >&2
                  exit 1
                  ;;
              esac
            }

            accept_backend() {
              case "$1" in
                auto|latexmk)
                  ;;
                *)
                  echo "Error: ${name} uses the pinned Nix latexmk backend; use the uv/TinyTeX path for runtime package autoinstall." >&2
                  exit 1
                  ;;
              esac
            }

            report_missing_files() {
              log_file="''${tex_file%.tex}.log"
              [ -f "$log_file" ] || return 0
              missing_files=()
              seen=" "

              while IFS= read -r line || [ -n "$line" ]; do
                missing_file=""
                if [[ "$line" == *"not found"* && "$line" =~ ([A-Za-z0-9_.+-]+\.(sty|cls|bst|bbx|cbx|def|fd|map|tfm|pfb|otf|ttf|enc|cfg)) ]]; then
                  missing_file="''${BASH_REMATCH[1]}"
                elif [[ "$line" =~ mktextfm[[:space:]]+([A-Za-z0-9_.-]+) ]]; then
                  missing_file="''${BASH_REMATCH[1]}.tfm"
                elif [[ "$line" =~ Metric[[:space:]]+\(TFM\)[[:space:]]+file[[:space:]]+not[[:space:]]+found && "$line" =~ =([A-Za-z0-9_.-]+) ]]; then
                  missing_file="''${BASH_REMATCH[1]}.tfm"
                fi

                if [ -n "$missing_file" ] && [[ "$seen" != *" $missing_file "* ]]; then
                  seen="$seen$missing_file "
                  missing_files+=("$missing_file")
                fi
              done < "$log_file"

              if [ "''${#missing_files[@]}" -gt 0 ]; then
                echo "Missing TeX files found: ''${missing_files[*]}"
              fi
            }

            set_engine "${defaultEngine}"

            while [ "$#" -gt 0 ]; do
              case "$1" in
                --version)
                  echo "${version}"
                  exit 0
                  ;;
                --help|-h)
                  echo "Usage: ${name} [--engine pdflatex|lualatex|xelatex|latexmk] [--no-clean] [document.tex] [refs.bib ...]"
                  exit 0
                  ;;
                --engine)
                  if [ "$#" -lt 2 ]; then
                    echo "Error: --engine requires pdflatex, lualatex, xelatex, or latexmk." >&2
                    exit 1
                  fi
                  set_engine "$2"
                  shift 2
                  ;;
                --engine=*)
                  set_engine "''${1#--engine=}"
                  shift
                  ;;
                --backend)
                  if [ "$#" -lt 2 ]; then
                    echo "Error: --backend requires auto or latexmk for this Nix wrapper." >&2
                    exit 1
                  fi
                  accept_backend "$2"
                  shift 2
                  ;;
                --backend=*)
                  accept_backend "''${1#--backend=}"
                  shift
                  ;;
                --no-clean)
                  auto_clean=false
                  shift
                  ;;
                --no-install)
                  shift
                  ;;
                -pvc)
                  auto_clean=false
                  latexmk_args+=("$1")
                  shift
                  ;;
                *.tex)
                  if [ -n "$tex_file" ]; then
                    echo "Error: Multiple .tex files specified: $tex_file and $1" >&2
                    exit 1
                  fi
                  tex_file="$1"
                  latexmk_args+=("$1")
                  shift
                  ;;
                *.bib)
                  bib_files+=("$1")
                  shift
                  ;;
                *)
                  latexmk_args+=("$1")
                  shift
                  ;;
              esac
            done

            if [ -z "$tex_file" ]; then
              shopt -s nullglob
              tex_files=(*.tex)
              shopt -u nullglob
              if [ "''${#tex_files[@]}" -ne 1 ]; then
                echo "Error: No .tex file specified and unable to auto-detect." >&2
                exit 1
              fi
              tex_file="''${tex_files[0]}"
              latexmk_args+=("$tex_file")
              echo "Auto-detected LaTeX file: $tex_file"
            fi

            export PATH="${pkgs.lib.makeBinPath [ texlivePackage pkgs.coreutils ]}:$PATH"

            if [ -f "$tex_file" ]; then
              tex_source="$(< "$tex_file")"
              if [[ "$tex_source" =~ \\(usepackage.*biblatex|bibliography\{|addbibresource\{) ]]; then
                echo "Detected bibliography usage in $tex_file"
                if [ "''${#bib_files[@]}" -gt 0 ]; then
                  echo "Using explicitly specified bibliography files: ''${bib_files[*]}"
                  for bib_file in "''${bib_files[@]}"; do
                    if [ ! -f "$bib_file" ]; then
                      echo "Error: Specified bibliography file '$bib_file' not found" >&2
                      exit 1
                    fi
                    if [[ "$tex_source" != *"$bib_file"* ]]; then
                      echo "Warning: Bibliography file $bib_file specified but not referenced in $tex_file"
                      echo "You may need to add \\addbibresource{$bib_file} to your document"
                    fi
                  done
                else
                  shopt -s nullglob
                  detected_bib_files=(*.bib)
                  shopt -u nullglob
                  if [ "''${#detected_bib_files[@]}" -eq 1 ]; then
                    echo "Auto-detected bibliography file: ''${detected_bib_files[0]}"
                    if [[ "$tex_source" != *"''${detected_bib_files[0]}"* ]]; then
                      echo "Warning: Bibliography file ''${detected_bib_files[0]} found but not referenced in $tex_file"
                      echo "You may need to add \\addbibresource{''${detected_bib_files[0]}} to your document"
                    fi
                  elif [ "''${#detected_bib_files[@]}" -eq 0 ]; then
                    echo "Warning: Bibliography commands found in $tex_file but no .bib files found"
                  else
                    echo "Info: Multiple .bib files found: ''${detected_bib_files[*]}"
                    echo "Make sure the correct ones are referenced in your document"
                    echo "Or specify explicitly: ${name} $tex_file file1.bib file2.bib"
                  fi
                fi
              fi
            fi

            latexmk "''${latexmk_engine_args[@]}" "''${latexmk_args[@]}"
            status=$?

            if [ "$status" -eq 0 ] && [ "$auto_clean" = "true" ]; then
              base="''${tex_file%.tex}"
              for ext in aux bbl bcf blg fls fdb_latexmk log nav out snm toc vrb run.xml; do
                rm -f "$base.$ext"
              done
              echo "Build successful, all auxiliary files cleaned (kept: .tex, .bib, .pdf)"
            elif [ "$status" -ne 0 ]; then
              report_missing_files
              echo "Build failed, keeping auxiliary files for debugging"
            fi

            exit "$status"
          '';
        };

        makeDirectTexCommand = name: engine: texlivePackage: pkgs.writeTextFile {
          inherit name;
          executable = true;
          destination = "/bin/${name}";
          text = ''
            #!${pkgs.bash}/bin/bash
            auto_clean="''${TEXMINI_AUTO_CLEAN:-true}"
            tex_file=""
            args=()

            accept_backend() {
              case "$1" in
                auto|direct)
                  ;;
                *)
                  echo "Error: ${name} runs the pinned Nix direct ${engine} backend; use a latexmk wrapper or the uv/TinyTeX path for other backends." >&2
                  exit 1
                  ;;
              esac
            }

            report_missing_files() {
              log_file="''${tex_file%.tex}.log"
              [ -f "$log_file" ] || return 0
              missing_files=()
              seen=" "

              while IFS= read -r line || [ -n "$line" ]; do
                missing_file=""
                if [[ "$line" == *"not found"* && "$line" =~ ([A-Za-z0-9_.+-]+\.(sty|cls|bst|bbx|cbx|def|fd|map|tfm|pfb|otf|ttf|enc|cfg)) ]]; then
                  missing_file="''${BASH_REMATCH[1]}"
                elif [[ "$line" =~ mktextfm[[:space:]]+([A-Za-z0-9_.-]+) ]]; then
                  missing_file="''${BASH_REMATCH[1]}.tfm"
                elif [[ "$line" =~ Metric[[:space:]]+\(TFM\)[[:space:]]+file[[:space:]]+not[[:space:]]+found && "$line" =~ =([A-Za-z0-9_.-]+) ]]; then
                  missing_file="''${BASH_REMATCH[1]}.tfm"
                fi

                if [ -n "$missing_file" ] && [[ "$seen" != *" $missing_file "* ]]; then
                  seen="$seen$missing_file "
                  missing_files+=("$missing_file")
                fi
              done < "$log_file"

              if [ "''${#missing_files[@]}" -gt 0 ]; then
                echo "Missing TeX files found: ''${missing_files[*]}"
              fi
            }

            while [ "$#" -gt 0 ]; do
              case "$1" in
                --version)
                  echo "${version}"
                  exit 0
                  ;;
                --help|-h)
                  echo "Usage: ${name} [--no-clean] [document.tex]"
                  exit 0
                  ;;
                --no-clean)
                  auto_clean=false
                  shift
                  ;;
                --no-install)
                  shift
                  ;;
                --backend)
                  if [ "$#" -lt 2 ]; then
                    echo "Error: --backend requires auto or direct for this Nix wrapper." >&2
                    exit 1
                  fi
                  accept_backend "$2"
                  shift 2
                  ;;
                --backend=*)
                  accept_backend "''${1#--backend=}"
                  shift
                  ;;
                --engine|--engine=*)
                  echo "Error: ${name} is already bound to ${engine}; choose a different Nix target for another engine." >&2
                  exit 1
                  ;;
                -pvc)
                  echo "Error: ${name} runs ${engine} directly and does not support continuous-preview mode." >&2
                  exit 1
                  ;;
                *.tex)
                  if [ -n "$tex_file" ]; then
                    echo "Error: Multiple .tex files specified: $tex_file and $1" >&2
                    exit 1
                  fi
                  tex_file="$1"
                  args+=("$1")
                  shift
                  ;;
                *)
                  args+=("$1")
                  shift
                  ;;
              esac
            done

            if [ -z "$tex_file" ]; then
              shopt -s nullglob
              tex_files=(*.tex)
              shopt -u nullglob
              if [ "''${#tex_files[@]}" -ne 1 ]; then
                echo "Error: Specify exactly one .tex file." >&2
                exit 1
              fi
              tex_file="''${tex_files[0]}"
              args+=("$tex_file")
              echo "Auto-detected LaTeX file: $tex_file"
            fi

            export PATH="${pkgs.lib.makeBinPath [ texlivePackage pkgs.coreutils ]}:$PATH"
            "${engine}" -interaction=nonstopmode -file-line-error "''${args[@]}"
            status=$?

            if [ "$status" -eq 0 ] && [ "$auto_clean" = "true" ]; then
              base="''${tex_file%.tex}"
              for ext in aux bbl bcf blg fls fdb_latexmk log nav out snm toc vrb run.xml; do
                rm -f "$base.$ext"
              done
              echo "Build successful, all auxiliary files cleaned (kept: .tex, .bib, .pdf)"
            elif [ "$status" -ne 0 ]; then
              report_missing_files
              echo "Build failed, keeping auxiliary files for debugging"
            fi

            exit "$status"
          '';
        };

        makeDefaultCommand = name: makeLatexmkCommand name "pdflatex" texMiniDefault;
        defaultPackage = makeDefaultCommand "texmini";
        basicPackage = makeDirectTexCommand "texmini-basic" "pdflatex" texMiniBasic;

        makeDockerImage = name: package: binaryName: pkgs.dockerTools.buildLayeredImage {
          inherit name;
          tag = "latest";
          contents = [ package ];
          extraCommands = ''
            mkdir -p bin tmp work
            ln -s ${pkgs.bash}/bin/bash bin/sh
            chmod 1777 tmp
          '';
          config = {
            Entrypoint = [ "${package}/bin/${binaryName}" ];
            WorkingDir = "/work";
          };
        };
      in {
        packages = {
          pdflatex = makeLatexmkCommand "pdflatex" "pdflatex" texMiniDefault;
          lualatex = makeLatexmkCommand "lualatex" "lualatex" texMiniDefault;
          xelatex = makeLatexmkCommand "xelatex" "xelatex" texMiniDefault;
          latexmk = makeLatexmkCommand "latexmk" "latexmk" texMiniDefault;

          pdflatex-basic = makeDirectTexCommand "pdflatex-basic" "pdflatex" texMiniBasic;
          lualatex-basic = makeDirectTexCommand "lualatex-basic" "lualatex" texMiniBasic;
          xelatex-basic = makeDirectTexCommand "xelatex-basic" "xelatex" texMiniBasic;
          latexmk-basic = makeLatexmkCommand "latexmk-basic" "latexmk" texMiniBasicLatexmk;

          pdflatex-biblio = makeLatexmkCommand "pdflatex-biblio" "pdflatex" texMiniBiblio;
          lualatex-biblio = makeLatexmkCommand "lualatex-biblio" "lualatex" texMiniBiblio;
          xelatex-biblio = makeLatexmkCommand "xelatex-biblio" "xelatex" texMiniBiblio;
          latexmk-biblio = makeLatexmkCommand "latexmk-biblio" "latexmk" texMiniBiblio;

          texMiniBasic = texMiniBasic;
          texMiniBasicLatexmk = texMiniBasicLatexmk;
          texMiniBiblio = texMiniBiblio;
          texMiniCli = defaultPackage;

          docker = makeDockerImage "texmini" defaultPackage "texmini";
          docker-basic = makeDockerImage "texmini-basic" basicPackage "texmini-basic";

          default = defaultPackage;
        };

        devShells = {
          default = pkgs.mkShell {
            buildInputs = [ texMiniDefault pkgs.python3Minimal pkgs.uv pkgs.zig ];
          };
          basic = pkgs.mkShell {
            buildInputs = [ texMiniBasic pkgs.python3Minimal pkgs.uv pkgs.zig ];
          };
          biblio = pkgs.mkShell {
            buildInputs = [ texMiniBiblio pkgs.python3Minimal pkgs.uv pkgs.zig ];
          };
        };

        apps = {
          default = {
            type = "app";
            program = "${defaultPackage}/bin/texmini";
          };
        };
      });
}
