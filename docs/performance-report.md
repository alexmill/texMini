# Performance Report: Optimized Python Orchestrator

Date: 2026-08-16  
Baseline commit: `1cb7a53798fbc39f9cb224005203db48aeae5461`  
Decision: retain one small, pure-Python, universal uv application.

## Outcome

The optimized Python design is the measured winner. The frozen comparator passed
all 49 deterministic scenario checks, four independent footprint checks, and the
watch check. Of the 49 scenario checks, 43 improved by more than the larger of
5% or three baseline MADs; the other six were also faster, but by less than that
practical/noise threshold. There were no failed semantic samples in either
400-sample full run, and every one of the seven watch trials per candidate
produced a changed PDF and exited through the handled Ctrl-C status 130.

The most important local medians improved as follows: source startup 48.040 ms
to 12.470 ms, installed startup 47.582 ms to 11.965 ms, simple no-op build
197.130 ms to 123.128 ms, and simple one-line rebuild 289.749 ms to 215.520 ms.
The raw `latexmk` no-op lower bound stayed effectively flat at about 73 ms,
showing that the gains came from texMini-owned orchestration rather than a
fortuitously faster TeX installation.

The wheel grew by 4,419 bytes, within the frozen 5,120-byte allowance, while
the complete uv tool directory shrank by 75,525 logical bytes. The TinyTeX base
runtime was byte-for-byte unchanged. These results support the architecture
decision in [ADR 0001](architecture/0001-optimize-python-orchestrator.md): a
Rust, Go, clean-rewrite, or hybrid implementation would add packaging and
maintenance cost without removing the dominant TeX Live, `latexmk`, network,
XZ, or Pygments work.

## Provenance and validity

| Evidence | Baseline | Final |
| --- | --- | --- |
| Candidate | `baseline-1cb7a537-final-harness` | `optimized-python-final` |
| Target commit | `1cb7a53798fbc39f9cb224005203db48aeae5461` (clean) | same commit plus the measured working tree |
| Target tree SHA-256 | `2ce58b16061b56af6cf1b5dd39701c413715542c898b0aedaa617c9804e36e53` | `65f0cd516c2c64fcdf5b5bcb905201d369d1559e6c30c7b08e9ec3bc6dc1feb4` |
| Harness tree SHA-256 | `65f0cd516c2c64fcdf5b5bcb905201d369d1559e6c30c7b08e9ec3bc6dc1feb4` | same |
| UTC start | `20260816T045928Z` | `20260816T050824Z` |
| Full result | [JSON](../benchmarks/results/20260816-python-baseline-full-v2-macos-arm64.json) · [raw JSONL](../benchmarks/results/20260816-python-baseline-full-v2-macos-arm64.20260816T045928Z.37206.raw.jsonl) | [JSON](../benchmarks/results/20260816-python-final-full-macos-arm64.json) · [raw JSONL](../benchmarks/results/20260816-python-final-full-macos-arm64.20260816T050824Z.52919.raw.jsonl) |
| Raw bytes / SHA-256 | 635,775 / `aa52bb8a16af778d498bd2989e8c3e0841f687f0e7269c406d7a781f64f30f2e` | 639,561 / `d3a298d37f517a6baf4e10588ce1da25dcd9ca9af1f71ec80f1972f1ee30f602` |

Both target and harness fingerprints were stable from the start to the end of
each run. The comparator re-read the raw JSONL, verified byte counts and SHA-256
digests, required exact equality with the embedded samples, recomputed the
summaries from those samples, and matched the frozen baseline filename, commit,
candidate, and tree identity. The machine-readable [comparison](../benchmarks/results/20260816-python-before-after-macos-arm64.json)
records `environment_matches: true`, 54 passing checks, and no failures.

The reference host was macOS 15.6.1 (`Darwin 24.6.0`) on an Apple M2 Ultra with
24 logical CPUs, 128 GiB RAM, and APFS. Both runs used uv 0.9.17, uv-managed
Python 3.12.12, Pygments 2.20.0, and psutil 7.2.2. CI and release automation are
separately pinned to uv 0.11.20. The runtime was TinyTeX 2026.08 for `darwin`,
asset `TinyTeX-1-darwin-v2026.08.tar.xz`, with manifest SHA-256
`48779c4af05fb4f70891ead6d599c826e16c8f15c1f3b9937bff5294f40b08dc`
and asset SHA-256
`dd22ffdf1063eff79cadcff45de1f24e8546edf508ab402dc9f87ec2f3367344`.
The same APFS-cloned base tree was used outside every full timing: content
identity `a1ee814d2b359ab69cc36630c94093056e6912483b668f7ab1263386c30a3e3c`,
123 packages. The final provisioned inventory was also identical at 159
packages with inventory SHA-256
`f7fae6d98c8efdb9bf856582d6dff626a3a5a9212bc5a20313c6e8ce8e80a2ab`.

The full suite used 15 source-startup repeats, 10 installed/cached-uvx repeats,
seven ordinary workload repeats, three package-recovery repeats, and seven
five-second watch trials. Each authoritative command ran in a fresh worker.
Tables report median ± median absolute deviation (MAD); negative percentages
are improvements. OS page cache was uncontrolled and is part of the recorded
noise. Instrumented attribution samples were excluded from timing summaries.
With seven or fewer observations, p95 is merely the observed maximum, so it is
not used below.

## Repeatable local performance

| Scenario | Baseline ms | Final ms | Change | Repeats |
| --- | ---: | ---: | ---: | ---: |
| Source-tree `--version` | 48.040 ± 1.181 | 12.470 ± 0.131 | -74.0% | 15 / 15 |
| Source-tree `--help` | 47.652 ± 0.789 | 12.516 ± 0.266 | -73.7% | 15 / 15 |
| Cached `uvx … --version` | 78.251 ± 0.643 | 49.150 ± 0.498 | -37.2% | 10 / 10 |
| Installed command, warm | 47.582 ± 1.340 | 11.965 ± 0.084 | -74.9% | 10 / 10 |
| Simple clean build | 382.784 ± 0.560 | 308.552 ± 0.782 | -19.4% | 7 / 7 |
| Simple no-op build | 197.130 ± 1.673 | 123.128 ± 2.044 | -37.5% | 7 / 7 |
| Simple one-line rebuild | 289.749 ± 0.573 | 215.520 ± 1.651 | -25.6% | 7 / 7 |
| Ordinary failure | 255.340 ± 2.497 | 182.651 ± 0.366 | -28.5% | 7 / 7 |
| Incomplete-PDF failure | 255.592 ± 0.926 | 182.612 ± 0.509 | -28.6% | 7 / 7 |
| Raw `latexmk` no-op lower bound | 73.889 ± 1.026 | 73.360 ± 0.747 | -0.7% | 7 / 7 |

Raw `latexmk` is intentionally labeled a lower bound, not an equivalent tool:
it omits runtime provisioning, source analysis, package recovery, safety policy,
diagnostics, and the uv interface. The optimized no-op still spends roughly
73 ms of its 123 ms in that unavoidable lower-bound process.

Representative specialty clean builds follow. The full machine result also
gates no-op and visible one-line incremental states for every fixture.

| Specialty clean build | Baseline ms | Final ms | Change | Repeats |
| --- | ---: | ---: | ---: | ---: |
| LuaLaTeX | 527.028 ± 0.792 | 454.642 ± 1.087 | -13.7% | 7 / 7 |
| XeLaTeX | 308.160 ± 0.763 | 236.020 ± 1.542 | -23.4% | 7 / 7 |
| BibTeX | 465.497 ± 0.823 | 393.116 ± 1.418 | -15.5% | 7 / 7 |
| Biber | 4,312.210 ± 9.234 | 4,240.922 ± 5.829 | -1.7% | 7 / 7 |
| Index | 396.465 ± 1.319 | 323.337 ± 1.763 | -18.4% | 7 / 7 |
| Glossary | 727.947 ± 1.377 | 650.345 ± 0.846 | -10.7% | 7 / 7 |
| Glossary with Xindy | 817.442 ± 0.631 | 744.182 ± 0.510 | -9.0% | 7 / 7 |
| Nomenclature | 444.521 ± 0.614 | 365.749 ± 1.173 | -17.7% | 7 / 7 |
| Minted/Pygments | 1,652.032 ± 2.072 | 1,575.218 ± 2.411 | -4.6% | 7 / 7 |
| Beamer | 1,198.933 ± 3.274 | 1,120.993 ± 2.413 | -6.5% | 7 / 7 |
| Multifile/custom layout | 510.731 ± 1.187 | 444.827 ± 0.685 | -12.9% | 7 / 7 |
| Custom layout with SyncTeX | 386.112 ± 0.969 | 382.679 ± 2.093 | -0.9% | 7 / 7 |

Biber clean, minted clean, the three custom-layout/SyncTeX states, and raw
`latexmk` were the six deterministic scenarios whose reductions did not exceed
the frozen practical/noise threshold. None regressed. SyncTeX deliberately uses
the conservative layout fallback, while Biber and minted are dominated by
their required external tools.

## Watch behavior

| Five-second watch trial metric | Baseline | Final | Change |
| --- | ---: | ---: | ---: |
| Startup to ready, ms | 190.204 ± 0.283 | 119.045 ± 1.289 | -37.4% |
| Change to detection, ms | 489.414 ± 3.916 | 335.197 ± 7.048 | -31.5% |
| Detection to completed rebuild, ms | 161.127 ± 0.651 | 183.399 ± 2.253 | +13.8% |
| Change to completed rebuild, ms | 649.924 ± 3.343 | 506.623 ± 16.499 | -22.0% |
| Idle CPU, % of one core | 0.81683 ± 0.01127 | 0.04973 ± 0.00750 | -93.9% |
| Idle sampled tree RSS, MiB | 22.750 ± 0.078 | 20.703 ± 0.109 | -9.0% |

The tradeoff is explicit: once a change was detected, the rebuild sub-phase was
22.272 ms slower. Faster detection more than offset it, reducing user-visible
change-to-completion latency by 143.300 ms, while idle CPU fell below 0.05% of
one core. The frozen gate is the complete change-to-PDF interval plus an
independent 2% idle-CPU ceiling; both passed.

## CPU and memory

| Scenario | CPU baseline ms | CPU final ms | CPU change | RSS baseline MiB | RSS final MiB | RSS change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Source-tree `--version` | 42.445 | 11.181 | -73.7% | 21.08 | 9.80 | -53.5% |
| Cached uvx | 70.313 | 39.138 | -44.3% | 52.89 | 30.91 | -41.6% |
| Simple clean | 372.911 | 301.797 | -19.1% | 61.95 | 60.64 | -2.1% |
| Simple no-op | 189.650 | 118.254 | -37.6% | 38.03 | 36.05 | -5.2% |
| Simple incremental | 280.275 | 210.228 | -25.0% | 62.28 | 60.77 | -2.4% |
| Raw `latexmk` no-op | 69.370 | 69.465 | +0.1% | 15.03 | 15.58 | +3.6% |

CPU is POSIX `RUSAGE_CHILDREN` user plus system time for the completed command.
RSS above is the descendant process tree sampled every 5 ms. A tree median is
accepted only when every valid repeat has a positive observation; otherwise the
comparator falls back to the maximum waited-child RSS and labels that lower-
fidelity backend. Every row shown here used the sampled-tree backend. The
sampling-based unique-process count is useful diagnostic evidence but is not an
exact process census; exact direct subprocess counts come only from trace
events.

## Footprint

| Footprint | Baseline | Final | Absolute change | Relative change |
| --- | ---: | ---: | ---: | ---: |
| Universal wheel | 33,153 B | 37,572 B | +4,419 B | +13.33% |
| uv tool directory, logical | 4,817,631 B | 4,742,106 B | -75,525 B | -1.57% |
| uv tool directory, allocated | 5,619,712 B | 5,537,792 B | -81,920 B | -1.46% |
| uvx cache, logical | 9,511,933 B | 9,463,304 B | -48,629 B | -0.51% |
| Base TinyTeX runtime, logical | 402,707,475 B | 402,707,475 B | 0 B | 0% |
| Fully provisioned runtime, logical | 529,860,130 B | 529,860,133 B | +3 B | effectively 0% |

The final wheel is `texmini-0.6.0-py3-none-any.whl` and retains 701 bytes of
headroom under the frozen wheel-growth limit. The three-byte provisioned-runtime
difference is generated TeX metadata; package names and revisions are identical.
The managed Python installation itself is pre-existing and excluded from tool
directory totals on both sides. Pygments remains an installed dependency so
minted works immediately; removing Python therefore would not remove the full
uv/Pygments environment.

## Network-dependent and cold observations

Package installation uses the live TeX Live repository, so DNS, TLS, mirrors,
CDN state, and repository state were uncontrolled. The comparator records these
results but never uses them as deterministic gates.

| Package-recovery state | Baseline ms | Final ms | Change | Repeats |
| --- | ---: | ---: | ---: | ---: |
| One package, empty map | 6,529.316 ± 5.976 | 6,537.034 ± 68.593 | +0.1% | 3 / 3 |
| One package, warm map | 3,955.477 ± 35.959 | 3,923.867 ± 14.955 | -0.8% | 3 / 3 |
| Many packages, empty map | 18,464.012 ± 60.597 | 8,328.645 ± 71.812 | -54.9% | 3 / 3 |
| Many packages, warm map | 5,768.057 ± 88.042 | 5,683.120 ± 35.368 | -1.5% | 3 / 3 |

The large many-package/empty-map observation is consistent with replacing five
serial authoritative `tlmgr search` calls with one bounded batched search, but
the percentage is not claimed as a reproducible network-independent gain.
Single observations of uncached uvx acquisition (2,181.740 ms to 824.601 ms),
`uv tool install` (598.674 ms to 456.223 ms), and first launch after install
(189.231 ms to 161.452 ms) are reported for completeness and are likewise not
performance gates.

The separate empty-runtime pair began with no runtime template and no package
map. Its raw-linked results are [baseline JSON](../benchmarks/results/20260816-python-baseline-cold-macos-arm64.json),
[baseline JSONL](../benchmarks/results/20260816-python-baseline-cold-macos-arm64.20260816T051607Z.65859.raw.jsonl),
[final JSON](../benchmarks/results/20260816-python-final-cold-macos-arm64.json),
and [final JSONL](../benchmarks/results/20260816-python-final-cold-macos-arm64.20260816T051703Z.66772.raw.jsonl).
Raw linkage and summaries verify for all 35 samples in each result. The one
authoritative first-build observation was 12,302.676 ms baseline versus
9,104.921 ms final (-26.0%), but this is explicitly observational because it
includes an uncontrolled archive download.

The final attribution-only first build took 9,151.099 ms and recorded these
owned phases:

| Final cold phase | Duration |
| --- | ---: |
| Download plus SHA-256 | 4,718.089 ms |
| Safe runtime extraction | 3,710.103 ms |
| `latexmk` compilation | 517.747 ms |
| Manifest load | 1.196 ms |
| Source analysis | 0.784 ms |
| Project source discovery | 0.509 ms |
| Runtime validation | 0.299 ms |
| Runtime prerequisite check | 0.064 ms |

The downloader observed exactly 67,051,368 response-body bytes for the runtime
archive. The trace recorded two direct subprocesses: one `kpsewhich` and one
`latexmk`. Parent phases such as `cli`, `document_build`, and `subprocess`
overlap the leaf phases and must not be summed with them. The baseline code did
not emit trace events, so only end-to-end cold timing is compared across
candidates; phase attribution is final-only.

## Product-contract gates

The current uv-managed Python 3.12 run passed all 212 unit/contract tests. The
full benchmark added real TinyTeX compile evidence with zero semantic failures.
The table maps every non-negotiable invariant to an explicit verification path.

| # | Invariant | Verification evidence |
| ---: | --- | --- |
| 1 | `uvx texmini paper.tex` remains canonical | Quick start in [README](../README.md); uvx startup benchmarks; CI invokes `uvx --from . texmini`; packaging entry-point test. |
| 2 | `uv tool install texmini` remains supported | Installed-startup and tool-footprint benchmarks; `test_uv_tool_install_exposes_standard_console_script`; CI and release wheel install tests. |
| 3 | Development, testing, building, and Python use uv | Reproduction commands below, [README development commands](../README.md), and all Python/packaging workflow commands use `uv run`, `uv build`, or `uvx`. |
| 4 | No Rust, Go, C compiler, or other native build toolchain for users | Final artifact is one `py3-none-any` wheel; [pyproject](../pyproject.toml) has only Pygments at runtime; release validates the universal wheel. |
| 5 | Honest platform matrix is preserved | Pinned assets in [runtime manifest](../src/texmini/runtime_manifest.json), fail-closed platform tests, and the CI/release matrix summarized below. |
| 6 | Real TeX Live and `latexmk` compile conventional LaTeX | Every build benchmark used pinned TinyTeX and managed `latexmk`; raw `latexmk` lower bound and real fixture PDFs verify the path. |
| 7 | Engines, directives, `latexmkrc`, passthrough, subdirectories, layouts, job names, SyncTeX, incremental state, and watch remain | Engine-enforcing fixtures; all three engine and custom-layout/SyncTeX benchmarks; [build](../tests/test_build.py), [CLI](../tests/test_cli.py), [project](../tests/test_project.py), recovery, and watch contracts; native CI smoke. |
| 8 | Recursive analysis, mapping, batched install, recovery, retry, and wider TeX Live remain | [project](../tests/test_project.py), [runtime](../tests/test_runtime.py), and [recovery](../tests/test_recovery_contracts.py) contracts; one/many-package recovery workloads; 20-round ceiling tests. |
| 9 | BibTeX, Biber, indices, glossaries, nomenclature, local files, multifile, and minted work | Dedicated clean/no-op/incremental benchmark fixtures and the multi-platform managed-runtime smoke suite. |
| 10 | Shell escape is never implicit | Minted first fails with focused guidance and succeeds only with `--shell-escape` in tests and CI; dedicated build contract. |
| 11 | Isolated, reusable, atomic, pinned, HTTPS- and SHA-verified runtime with provenance | Downloader redirect/checksum/atomic tests; archive path/link safety tests; runtime validation, provenance, legacy reuse, managed-tool, and host-PATH isolation tests. |
| 12 | Quiet/noninteractive output, meaningful status, retained evidence, primary errors, and incomplete-PDF failure remain | [reporting](../tests/test_reporting.py) and CLI contracts; real ordinary-failure and incomplete-PDF benchmark scenarios; every semantic assertion passed. |
| 13 | Diagnostic responsibility principle remains authoritative | [Principle](diagnostic-responsibility.md); ownership, pass-through, no-speculation, no-progress, missing-local-file, and recovery tests. |
| 14 | Docker stays optional and shares provisioning | [Dockerfile](../Dockerfile) calls the packaged installer; packaging contracts forbid a provisioning fork; CI/release share amd64 and arm64 smoke matrices. |
| 15 | Default compatibility is not traded for a tiny fixed package set | Dynamic authoritative `tlmgr` resolution remains; package-many recovery and the 159-package specialty inventory prove on-demand growth; no compatibility whitelist was introduced. |

## Platform support

The package itself is universal Python. Native TinyTeX support is limited
honestly by pinned upstream assets and executable availability.

| Platform | Status | Repository verification path |
| --- | --- | --- |
| macOS Apple Silicon | Supported | `darwin` asset; native Python/platform job, full managed-runtime smoke, and exact-tag release bootstrap/compile. |
| macOS x86-64 | Supported | `darwin` asset; `macos-15-intel` unit/platform, managed-runtime smoke, and exact-tag release bootstrap/compile. |
| Linux glibc x86-64 | Supported | `linux-x86_64` asset; Ubuntu Python job, minimal-Linux uv install/bootstrap, managed-runtime smoke, and amd64 Docker smoke. |
| Linux glibc ARM64 | Supported | `linux-arm64` asset; native `ubuntu-24.04-arm` Python/platform job and linux/arm64 Docker bootstrap/compile in CI and release. |
| Linux musl x86-64 | Supported | `linuxmusl-x86_64` asset; Alpine native-musl `uvx` bootstrap and real simple compile. |
| Windows x86-64 | Supported | Pinned Windows SFX asset; Windows Python/platform job, native bootstrap/engines/bibliography/path-with-spaces smoke, and exact-tag release compile. |
| Windows ARM64 | Unsupported | No pinned upstream asset; not advertised. |
| Linux musl ARM64 | Unsupported | No pinned upstream asset; runtime selection fails closed and has a contract test. |

See [CI](../.github/workflows/ci.yml), [release](../.github/workflows/release.yml),
and [packaging contracts](../tests/test_packaging.py). These workflows enforce
the matrix; this macOS report is not presented as a substitute for executing
them on their native runners.

## Architecture decision and rejected alternatives

The retained implementation removes the measured owned costs directly:

- lazy command-specific imports reduce Python CLI startup;
- a verified `latexmk` hook combines layout observation with the necessary
  compile, deleting the duplicate preflight process while retaining guarded
  legacy and SyncTeX fallbacks;
- bounded batched `tlmgr search` replaces serial searches without guessing
  ambiguous ownership;
- source discovery and comment-stripped content are reused instead of walking
  the project repeatedly;
- safe one-pass tar iteration validates members and installs atomically;
- watch inventory reuse avoids repeated directory scans while still statting
  every relevant dependency.

Focused probes in the ADR measured the duplicate preflight at 72.1 ms, five
serial `tlmgr search` calls at 13.23 s versus 2.66 s batched, and 7,116-member
extraction at 6.62 s versus 3.88 s with safe one-pass iteration. The full result
then verified that these local wins survive end to end.

Rejected alternatives and experiments:

- **Clean Python rewrite:** it would recreate mature recovery, layout,
  diagnostics, and security behavior while using the same interpreter and
  external tools; profiling found localized costs, not a structural limit.
- **Rust or Go rewrite:** it cannot accelerate TeX, `latexmk`, `tlmgr`, network
  transfer, or native XZ decompression. Minted still requires the Python/
  Pygments environment, while a native core would add platform-specific wheels
  and release work.
- **Hybrid extension:** XZ already runs in native library code and the remaining
  parsing/scanning work is millisecond-scale; no owned hotspot can repay the
  binary surface.
- **Streaming tar mode:** it was fast but increased RSS; seekable one-pass
  iteration retained the speed without that tradeoff.
- **Perl PDF timestamps for the layout handshake:** rejected because bundled
  Windows Perl may have one-second resolution; Python takes the nanosecond
  snapshot while `latexmk` waits.
- **Permanent package index:** rejected because it adds update/staleness policy;
  bounded authoritative batching captures most of the gain.
- **Mandatory native filesystem notifications:** rejected because no single
  backend covers the platform contract; optimized polling remains portable.

The reconsideration trigger is a new, repeatable wrapper-owned bottleneck that
cannot be removed cleanly in Python, or a uv native application format that
removes rather than duplicates the Python/Pygments environment. A future
candidate must beat this optimized result end to end, not merely win a language
microbenchmark.

## Reproduction

Run from the optimized checkout with a separate checkout of the frozen baseline
and a pinned TinyTeX template whose content identity matches the value above:

```bash
BASELINE_CHECKOUT=/absolute/path/to/texMini-baseline-1cb7a53
FINAL_CHECKOUT=/absolute/path/to/texMini-optimized
RUNTIME_TEMPLATE=/absolute/path/to/TinyTeX

cd "$FINAL_CHECKOUT"

uv run --python 3.12 --frozen --group benchmark python -m benchmarks.benchmark \
  --suite full \
  --candidate-id baseline-1cb7a537-final-harness \
  --target-root "$BASELINE_CHECKOUT" \
  --runtime-template "$RUNTIME_TEMPLATE" \
  --repeats 7 --startup-repeats 15 --package-repeats 3 \
  --watch-idle-seconds 5 \
  --output benchmarks/results/20260816-python-baseline-full-v2-macos-arm64.json

uv run --python 3.12 --frozen --group benchmark python -m benchmarks.benchmark \
  --suite full \
  --candidate-id optimized-python-final \
  --target-root "$FINAL_CHECKOUT" \
  --runtime-template "$RUNTIME_TEMPLATE" \
  --repeats 7 --startup-repeats 15 --package-repeats 3 \
  --watch-idle-seconds 5 \
  --output benchmarks/results/20260816-python-final-full-macos-arm64.json

uv run --python 3.12 --frozen --group benchmark python -m benchmarks.compare \
  benchmarks/results/20260816-python-baseline-full-v2-macos-arm64.json \
  benchmarks/results/20260816-python-final-full-macos-arm64.json \
  --output benchmarks/results/20260816-python-before-after-macos-arm64.json
```

Reproduce the observational empty-runtime pair without `--runtime-template`:

```bash
uv run --python 3.12 --frozen --group benchmark python -m benchmarks.benchmark \
  --suite core \
  --candidate-id baseline-1cb7a537-cold-final-harness \
  --target-root "$BASELINE_CHECKOUT" \
  --repeats 3 --startup-repeats 5 --package-repeats 1 \
  --watch-idle-seconds 2 --skip-packaging --skip-package-recovery \
  --output benchmarks/results/20260816-python-baseline-cold-macos-arm64.json

uv run --python 3.12 --frozen --group benchmark python -m benchmarks.benchmark \
  --suite core \
  --candidate-id optimized-python-cold-final \
  --target-root "$FINAL_CHECKOUT" \
  --repeats 3 --startup-repeats 5 --package-repeats 1 \
  --watch-idle-seconds 2 --skip-packaging --skip-package-recovery \
  --output benchmarks/results/20260816-python-final-cold-macos-arm64.json
```

The harness refuses a nonempty explicit workspace, fingerprints target and
harness trees before and after a run, writes raw/result pairs atomically, and
documents all cache controls and measurement semantics in the
[benchmark README](../benchmarks/README.md). Network observations should be
expected to vary; deterministic local comparisons require the same host,
runtime content, harness, repetition policy, and controlled project state.
