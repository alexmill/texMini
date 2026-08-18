# ADR 0001: Retain and Optimize the Python Orchestrator

- Status: Accepted
- Date: 2026-08-16
- Baseline: `1cb7a53798fbc39f9cb224005203db48aeae5461`
- Runtime evaluated: pinned TinyTeX 2026.08

## Decision

Keep texMini as one small, pure-Python uv application. Optimize orchestration by
removing duplicate processes and filesystem passes, batching TeX Live queries,
and streaming runtime extraction. Do not add a Rust or Go component and do not
rewrite the application.

`uvx texmini` remains the canonical zero-setup interface. The managed runtime,
real TeX Live and `latexmk`, Pygments support, package recovery, diagnostics, and
the existing platform contract remain unchanged.

## Context

The architecture question was deliberately open: optimize the current Python,
rewrite it, add a native component, or accept an upstream-imposed limit. The
decision had to account for complete user workflows rather than language
microbenchmarks, and every product invariant was a gate.

The benchmark separates Python/uv startup, texMini orchestration, TinyTeX
acquisition, package recovery, actual TeX work, watch behavior, and footprint.
Before implementation, focused probes isolated the important owned costs:

| Probe on the macOS ARM64 reference host | Baseline | Tested alternative |
| --- | ---: | ---: |
| Managed `latexmk` no-op | 75.5 ms | unavoidable semantic lower bound |
| `latexmk -dir-report-only` preflight | 72.1 ms | folded into the required compile |
| One-process compile plus layout hook | two processes | 70.9 ms total `latexmk` path |
| Five authoritative `tlmgr search` calls | 13.23 s | 2.66 s as one bounded regex search |
| 7,116-member TinyTeX extraction | 6.62 s | 3.88 s with validated one-pass iteration |
| Python import profile | about 33 ms | lazy command-specific imports |

The raw no-op result also establishes the scale of the remaining work: TeX and
`latexmk` already cost several times the optimized Python CLI startup, while
package installation and cold acquisition take seconds. The authoritative
baseline/final distributions are kept in `benchmarks/results/` and summarized
in `docs/performance-report.md`; network-dependent observations are not used as
deterministic performance gates.

## Options Considered

### Optimized existing Python

This option removes overhead at its source while retaining one portable wheel
and one implementation. Implemented changes include:

- lazy imports for commands that do not compile;
- one regex `tlmgr search` per bounded batch, with ambiguity left unresolved;
- one project traversal and reuse of already-read, comment-stripped sources;
- one-pass, member-validated `tar.xz` extraction into an atomic staging tree;
- one `latexmk` process for layout discovery and compilation on the exact
  verified runtime, using a pre-build hook/Python acknowledgement handshake;
- a persistent watch inventory that rescans directories only when their
  signatures change while still statting every relevant dependency;
- retained legacy preflight for SyncTeX, legacy runtimes, protocol failures, and
  an explicit diagnostic opt-out.

The focused probes showed a 41% extraction reduction and about an 80% search
reduction before the complete suite was run. End-to-end gains and their noise
floor remain in the performance report rather than being duplicated here.

### Clean Python rewrite

Rejected. Profiling identified a handful of localized process and traversal
costs, not structural complexity that required replacement. A rewrite would
recreate mature package-recovery, layout, diagnostics, security, and platform
behavior while using the same Python interpreter, TeX processes, and runtime.
It has no credible end-to-end advantage over the optimized implementation.

### Rust or Go executable

Rejected. Under the non-negotiable uv interface, a native core still requires
platform-specific wheels and a Python tool environment. Seamless minted support
still requires Pygments, which accounts for most of the non-TeX environment.
A native binary therefore adds its own bytes and release matrix without
removing the Python/Pygments environment. It cannot accelerate TeX, `latexmk`,
`tlmgr`, network transfer, or XZ decompression enough to recover that cost.

The maximum plausible startup gain after the Python changes is roughly the
remaining 20 ms process startup, while important builds spend 75 ms to seconds
in mandatory external tools. Native packaging would also require separate
wheels for macOS x86-64/ARM64, glibc x86-64/ARM64, musl x86-64, and Windows
x86-64, plus a source-build policy. The upstream TinyTeX assets do not currently
permit honest native Windows ARM64 or musl ARM64 support.

### Hybrid native extension

Rejected. The only CPU-heavy local operation was XZ extraction, where Python's
standard library already executes decompression in native code. Changing the
iteration strategy delivered a 41% improvement without an extension. Source
parsing and filesystem scans are millisecond-scale after simplification. No
remaining hotspot can repay an extension's wheel and maintenance surface.

## Consequences

Positive consequences:

- one `py3-none-any` wheel continues to serve every supported host;
- users need no compiler or language toolchain;
- uv acquisition and tool installation remain unchanged;
- the implementation stays close to the TeX/latexmk concepts it orchestrates;
- the fastest changes also simplify work by deleting processes and traversals.
- the release wheel remains universal and within the frozen 5 KiB growth budget;
  most managed non-TeX bytes still belong to Pygments, not the orchestrator.

Tradeoffs:

- Python process startup remains visible for `--help` and `--version`, although
  it is now around 20 ms on the reference host;
- Pygments remains an eager installed dependency so minted works on first use;
- watch mode keeps a polling fallback to preserve universal behavior;
- the combined layout path is deliberately gated to an exact tested TinyTeX
  release, so unknown or legacy runtimes pay the old preflight cost;
- network and TeX Live dominate cold provisioning and cannot be represented as
  deterministic performance gates on shared CI.

## Reconsideration Triggers

Reopen this decision only if measurements show a repeatable wrapper-owned
bottleneck that cannot be removed cleanly in Python, or if uv gains a native
application format that removes rather than duplicates the Python/Pygments
environment. Any candidate must beat the optimized Python result end to end,
fit within the current total installed footprint, ship without user toolchains
for every supported target, and pass the complete behavioral contract.

## Rejected Experiments

- Streaming tar mode (`r|xz`) was fast but increased RSS; seekable one-pass
  iteration retained the speedup without that memory tradeoff.
- Trusting Perl's PDF timestamp in the `latexmk` hook was rejected because the
  bundled Windows Perl may have only one-second timestamp resolution. The final
  protocol pauses `latexmk` while Python takes the existing nanosecond snapshot.
- A permanent package index was not adopted: it would add update and staleness
  policy. Bounded batched authoritative searches capture most of the benefit.
- Native filesystem notifications were not made mandatory because one backend
  does not cover the complete platform matrix; polling remains the semantic
  baseline and can be optimized without losing portability.
