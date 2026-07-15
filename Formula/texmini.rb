class Texmini < Formula
  desc "Ultra-lean LaTeX command wrapper with bibliography detection and cleanup"
  homepage "https://github.com/alexmill/texMini"
  url "https://github.com/alexmill/texMini.git", using: :git, branch: "main"
  version "0.1.0"
  license "MIT"

  depends_on "python@3.14"

  def install
    libexec.install "src"

    (bin/"texmini").write <<~EOS
      #!/usr/bin/env bash
      set -euo pipefail
      print_help() {
        cat <<'EOF'
      Usage: texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex|latexmk] [OPTIONS] [document.tex] [refs.bib ...]

      Compile a LaTeX document, detect bibliography files, and clean auxiliary files after successful builds.

      Options:
        --engine ENGINE   Select pdflatex, lualatex, xelatex, or latexmk.
        --no-clean        Keep auxiliary files after a successful build.
        --no-install      Disable TinyTeX package autoinstall.
        --version         Print the texMini version.
        -pvc              Pass latexmk continuous-preview mode and disable cleanup.

      Advanced:
        --backend BACKEND Select auto, direct, latexmk, or tinytex.

      All other arguments are passed through to latexmk.
      EOF
      }

      if [ "$#" -eq 1 ]; then
        case "$1" in
          --version)
            echo "#{version}"
            exit 0
            ;;
          --help|-h)
            print_help
            exit 0
            ;;
        esac
      fi
      export PYTHONPATH="#{libexec}/src${PYTHONPATH:+:$PYTHONPATH}"
      exec "#{Formula["python@3.14"].opt_bin}/python3" -S -m texmini.cli "$@"
    EOS
    chmod 0755, bin/"texmini"
  end

  test do
    assert_predicate bin/"texmini", :executable?
    assert_match "0.1.0", shell_output("#{bin}/texmini --version")
  end
end
