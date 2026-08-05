# Benchmarks

Run the supported TinyTeX-1 managed-runtime benchmark from the repository root:

```bash
uv run python -m benchmarks.benchmark
```

TinyTeX-1 starts in an empty directory. Fixtures run in this order against the same growing runtime:

1. A simple article.
2. A fixed set of common packages.
3. Ten packages sampled from a fixed seed.
4. A Biber bibliography whose entry count follows a seeded gamma-Poisson model.

The schema-version-1 result records the original texMini 0.1.0 comparison among upstream bundles. It remains historical data and is not a supported configuration matrix. Schema-version-2 results measure only texMini's TinyTeX-1 baseline.

Generate a new timestamped result after a runtime implementation change. Benchmark measurements are observations. They are not release gates.

The JSON result records the release archive size, cold compile time, three warm runs, PDF size, package download payload reported by `tlmgr`, and runtime footprint before and after each fixture. The first fixture includes the archive download and package-manager preparation; later cold runs measure only packages newly needed by that fixture. Network payload excludes HTTP and repository-index overhead because those values are not exposed by `tlmgr`.

Logical and allocated runtime sizes deduplicate hard links by device and inode. Allocated size uses filesystem block counts, so it represents disk usage rather than summing the apparent size of every directory entry.

Use `--keep-workspaces` only for debugging; retained TeX trees are large and are ignored by Git.
