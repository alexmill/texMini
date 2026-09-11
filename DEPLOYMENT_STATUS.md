# Deployment Status

Last verified: 2026-09-11 (UTC)

texMini `0.6.2` is publicly available from PyPI, GHCR, and GitHub Releases.

## Release

- Release commit: [`91838c9`](https://github.com/alexmill/texMini/commit/91838c95ed9f9d48457815a3ff404e7dc5a4ccb9)
- Annotated tag: [`v0.6.2`](https://github.com/alexmill/texMini/tree/v0.6.2)
- Passing main-branch CI: [run 34568211197](https://github.com/alexmill/texMini/actions/runs/34568211197)
- Passing release workflow: [run 34568879579](https://github.com/alexmill/texMini/actions/runs/34568879579)
- PyPI: <https://pypi.org/project/texmini/0.6.2/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.6.2>
- GHCR: `ghcr.io/alexmill/texmini:0.6.2`

## Changes

- Recover from TeX Live's explicit requirement to update its package manager before installing packages.
- Detect Alpine's musl runtime when CPython's libc scan returns no library name.
- Pass Windows package-search expressions directly to bundled Perl, preserving the native launcher for self-updates.
- Refresh the Windows watch inventory to detect file renames reliably.
- Repair version assertions, Windows path comparisons, and benchmark test dependencies in CI and release validation.
- Keep generated benchmark measurements and local demo output out of future commits and source distributions. Existing local benchmark copies are preserved.

## Package Integrity

The public PyPI artifacts match the distributions produced by the release workflow:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.6.2-py3-none-any.whl` | `26b89c12ff3056da2b40c4cc29e91b02cf11d782b0b9776ae277221b6b36f289` |
| `texmini-0.6.2.tar.gz` | `b47a33a02d4aaa9df23dac641ba8d0961f6778a3d4c35802f61fa30d9cdc721f` |

The wheel contains only the runtime package and distribution metadata. The source archive retains reusable test sources and excludes benchmark results, personal test projects, and demo output.

## Verification

All main-branch CI jobs and release jobs passed, including Windows, both native macOS architectures, Linux glibc and musl checks, and both Docker architectures. The unit suite contains 216 tests, with platform-specific skips where applicable.

PyPI publication used the existing GitHub Actions trusted-publishing workflow and its protected `pypi` environment approval.
