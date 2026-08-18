# Reproducible Performance Benchmarks

The schema-3 benchmark measures explicit user-visible states and keeps
network-dependent observations separate from repeatable local measurements.
Run it from the repository root with uv:

```bash
uv run --frozen --group benchmark python -m benchmarks.benchmark --suite full
```

Useful smaller checkpoints are:

```bash
uv run --frozen --group benchmark python -m benchmarks.benchmark --suite startup
uv run --frozen --group benchmark python -m benchmarks.benchmark --suite core
```

Use `--target-root` to benchmark another checkout with the same harness and
`--runtime-template` to clone the same provisioned TinyTeX tree outside every
authoritative timing. An explicit `--workspace` must be empty so stale caches,
artifacts, or package maps cannot silently change the measured state.
`--keep-workspace` retains to that validated explicit path or to a unique
timestamped path; it never merges with an earlier retained run. `--help`
documents repeat counts, isolated workspaces, watch duration, and packaging
controls.

## States and Workloads

The suite names cache and runtime state rather than calling every repeat
"cold" or "warm". It covers:

- source, installed, cold-uvx, and cached-uvx startup;
- wheel, uv tool directory, uvx cache, and managed runtime footprints;
- an empty managed runtime, exact archive payload, verification, extraction,
  validation, and first build;
- missing-one and missing-many package recovery with empty and warm maps;
- clean, true no-op, and one-line incremental projects;
- pdfLaTeX, LuaLaTeX, XeLaTeX, BibTeX, Biber, index, glossary, xindy,
  nomenclature, minted, Beamer, custom-layout, and multifile fixtures;
- ordinary failure and incomplete-PDF diagnostic paths;
- watch startup, idle CPU/RSS, detection latency, and rebuild completion;
- raw `latexmk` on the same runtime as a pinned semantic-overlap lower bound.

Competitor results are labeled by semantic overlap. Raw `latexmk` omits
texMini's provisioning, source analysis, safety policy, diagnostics, and uv
experience, so it is a lower bound rather than an equivalent replacement.
Tectonic, MiKTeX, and full TeX Live should only be recorded when a pinned local
installation exists; they are not downloaded implicitly by this benchmark and
their differing package/runtime semantics must remain explicit.

## Measurement Policy

Each authoritative command trial runs in a fresh worker process and uses
`time.perf_counter_ns`. Results include median, median absolute deviation,
min/max, p95, and an alternating-sample A/A drift indicator. POSIX child CPU is
read from `resource`; process-tree RSS and process count are sampled through
`psutil`. The trace records phase duration, direct subprocess counts, and HTTP
response-body bytes where texMini owns the downloader.

Instrumented attribution runs are excluded from timing summaries, including a
separate empty-runtime download and a separate watch session. Watch readiness,
idle resources, detection, and completion report repeated uninstrumented
medians and MADs. Warm package-map trials clone the same package-absent runtime
and copy the same populated map outside every timing. Filesystem work is
represented by explicit trace counters because a portable syscall count is not
available. Logical and allocated sizes deduplicate hard links by device and
inode. The OS page cache is uncontrolled and recorded as such. With seven or
fewer samples, the reported p95 is necessarily the observed maximum; use the
MAD and raw samples rather than treating it as a tail-latency model.

Incremental trials insert a visible marker before `\end{document}` (and a
visible frame for Beamer), then require the expected PDF content digest to
change from the preceding no-op build. A successful process exit with a stale
PDF is therefore a semantic failure rather than a fast incremental sample.
Watch trials likewise send the worker the exact no-op PDF path and digest,
insert a visible marker, and require fresh PDF content before accepting the
reported build completion.

Network samples are observational. DNS, TLS, CDN caches, mirror state, and TeX
Live repository state are not reproducibly controlled on a developer host or
shared CI. An HTTP metadata probe, when present, is an expected artifact size;
only downloader telemetry is counted as observed response payload.

Every result records the exact argv and cache controls, Python/uv/dependency
versions, CPU/memory/filesystem identity, and the version and pinned runtime
manifest loaded from the `--target-root` checkout. Base and fully provisioned
runtime trees include exact content identities. Environment matching uses the
base content identity plus a stable fully provisioned inventory of installed
package names and TeX Live revisions; the latter avoids treating volatile TeX
metadata as a package mismatch. Candidate and harness checkouts each receive a
content hash over tracked plus untracked files, and publication is refused if
either role changes during a run. Machine results and their derived human report
are excluded from those input hashes. Per-command log and trace paths are emitted
only with `--keep-workspace`; otherwise their durable hashes, failure tails,
semantic assertions, and trace summaries remain embedded without dangling
temporary paths. The comparator verifies the referenced raw JSONL byte count,
digest, and exact agreement with embedded samples before evaluating any
threshold.

## Regression Policy

[`thresholds.json`](thresholds.json) was frozen against the checked-in baseline
before product optimizations. The comparator requires both its exact baseline
basename, candidate ID, Git commit, and candidate-tree content hash, preventing
an arbitrary result from being substituted for the frozen control. For wall
time, a claimed improvement must exceed the larger of 5% or three baseline
MADs. A regression fails when it exceeds the larger of the scenario-specific
percentage or three baseline MADs. Watch
rebuild latency uses the same larger-of percentage/three-MAD rule and requires
every trial to produce changed-PDF evidence and exit through texMini's handled
Ctrl-C status 130. Footprint and watch limits are evaluated independently; no
aggregate score may hide a material regression. The fully provisioned runtime
has a 4 KiB logical-size tolerance for generated TeX metadata; growth beyond it
fails independently.

Shared CI should enforce harness integrity and behavior, not tight latency
limits. Performance gates require a stable dedicated runner. Baseline and final
JSON plus raw JSONL observations belong in `benchmarks/results/`; do not edit
historical schema-1 or schema-2 records.

The comparator gates every repeated, local, non-network scenario independently;
the named core thresholds are stricter, while a default ceiling covers all
specialty workflows and the raw lower bound. Network-dependent and fewer-than-
three-repeat observations remain visible with a structured reason but cannot
fail a deterministic latency gate. Failed semantics, missing scenarios, and
summary/raw or baseline/final sample-count mismatches still fail the comparison;
they can never be reclassified as ungated performance observations.

## Interpreting Results

Compare absolute values as well as percentages. A wrapper optimization cannot
claim credit for a faster network mirror or warmer filesystem cache. Conversely,
raw `latexmk` cannot claim texMini-equivalent behavior while omitting automatic
runtime acquisition and package recovery. The architecture record in
[`docs/architecture/0001-optimize-python-orchestrator.md`](../docs/architecture/0001-optimize-python-orchestrator.md)
uses phase-level evidence and the same-runtime raw `latexmk` lower bound.
