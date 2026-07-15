# Benchmarks

Run the managed-runtime benchmark from the repository root:

```bash
uv run python -m benchmarks.benchmark
```

Include the full community bundle for the published three-way comparison:

```bash
uv run python -m benchmarks.benchmark --bundles TinyTeX-0 TinyTeX-1 TinyTeX
```

Each TinyTeX bundle starts in a separate empty directory. Fixtures run in this order against the same growing runtime:

1. A simple article.
2. A fixed set of common packages.
3. Ten packages sampled from a fixed seed.
4. A Biber bibliography whose entry count follows a seeded gamma-Poisson model.

The JSON result records the release archive size, cold compile time, three warm runs, PDF size, package download payload reported by `tlmgr`, and runtime footprint before and after each fixture. The first fixture includes archive download and core bootstrap; later cold runs measure only packages newly needed by that fixture. Network payload excludes HTTP and repository-index overhead because those values are not exposed by `tlmgr`.

Logical and allocated runtime sizes deduplicate hard links by device and inode. Allocated size uses filesystem block counts, so it represents disk usage rather than summing the apparent size of every directory entry.

The repository README also reports separately measured wrapper installs, a clean `test.tex` first run, and fresh Docker builds. Those pathways use different prerequisites, so their acquisition, wrapper, TeX runtime, and execution measurements remain separate rather than being collapsed into one score.

Use `--keep-workspaces` only for debugging; retained TeX trees are large and are ignored by Git.
