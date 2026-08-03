#!/usr/bin/env bash
set -euo pipefail

image="${1:?usage: tests/smoke_docker.sh IMAGE}"
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smoke_root="$(mktemp -d)"
runtime_volume="texmini-smoke-runtime-${GITHUB_RUN_ID:-$$}"

cleanup() {
  docker volume rm --force "$runtime_volume" >/dev/null 2>&1 || true
  rm -rf "$smoke_root"
}
trap cleanup EXIT

for fixture in simple bibliography bibtex index glossary glossary-xindy nomenclature minted multifile; do
  cp -R "$repository_root/tests/fixtures/$fixture" "$smoke_root/$fixture"
done

run_texmini() {
  docker run --rm -v "$runtime_volume:/opt/TinyTeX" "$@"
}

simple_output="$(run_texmini \
  -v "$smoke_root/simple:/work" \
  "$image" simple.tex)"
printf '%s\n' "$simple_output"
grep -q "Installing 1 package: geometry" <<< "$simple_output"

run_texmini -v "$smoke_root/bibliography:/work" "$image" bibliography.tex
run_texmini -v "$smoke_root/bibtex:/work" "$image" paper.tex
run_texmini -v "$smoke_root/index:/work" "$image" index.tex
run_texmini -v "$smoke_root/glossary:/work" "$image" glossary.tex
run_texmini -v "$smoke_root/glossary-xindy:/work" "$image" glossary.tex
run_texmini -v "$smoke_root/nomenclature:/work" "$image" nomenclature.tex
run_texmini -v "$smoke_root/minted:/work" "$image" --shell-escape minted.tex
run_texmini -v "$smoke_root/multifile:/work" "$image" main.tex

second_output="$(run_texmini \
  -v "$smoke_root/bibliography:/work" \
  "$image" bibliography.tex)"
printf '%s\n' "$second_output"
grep -q "bibliography.pdf is up to date" <<< "$second_output"
run_texmini -v "$smoke_root/bibliography:/work" "$image" --clean bibliography.tex

test -s "$smoke_root/simple/simple.pdf"
test -s "$smoke_root/bibliography/bibliography.pdf"
test -s "$smoke_root/bibtex/paper.bbl"
test -s "$smoke_root/index/people.ind"
test -s "$smoke_root/glossary/glossary.gls"
test -s "$smoke_root/glossary-xindy/glossary.gls"
test -s "$smoke_root/nomenclature/nomenclature.nls"
test -s "$smoke_root/minted/minted.pdf"
test -s "$smoke_root/multifile/build/publication.pdf"
test ! -e "$smoke_root/bibliography/bibliography.aux"
