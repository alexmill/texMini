# Papercuts

Small tooling and repository frictions observed during technical work.

- 2026-08-12 — **Astral image tag discovery:** The expected `0.11.20-python3.12-bookworm-slim` tag was not published, while the unversioned convenience tag resolved to an older UV release. Pinning the multi-platform digest required inspecting the moving tag, so published tag conventions or setup documentation should make versioned Python image names discoverable.
