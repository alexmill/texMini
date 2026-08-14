# Papercuts

Small tooling and repository frictions observed during technical work.

- 2026-08-12 — **Astral image tag discovery:** The expected `0.11.20-python3.12-bookworm-slim` tag was not published, while the unversioned convenience tag resolved to an older UV release. Pinning the multi-platform digest required inspecting the moving tag, so published tag conventions or setup documentation should make versioned Python image names discoverable.
- 2026-08-13 — **Stale package-index browse result:** The browsed PyPI JSON snapshot reported texMini 0.2.0 while the live PyPI API and GitHub release state reported 0.5.0. Release checks should prefer a direct package-index API request when freshness matters.
- 2026-08-13 — **Deployment-review form typing:** `gh api -f 'environment_ids[]=…'` encoded the environment ID as a string, but GitHub's pending-deployment review endpoint requires an integer array. This endpoint needs a typed JSON request body even though the CLI's form syntax appears to support arrays.
