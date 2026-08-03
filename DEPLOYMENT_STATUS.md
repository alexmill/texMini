# Deployment Status

Last verified: 2026-08-02

texMini `0.4.0` is publicly available from PyPI and GHCR. The release was built from the tested `main` commit, published through OIDC Trusted Publishing, and verified from clean, anonymous environments.

## Release

- Version: `0.4.0`
- Release PR: [#8](https://github.com/alexmill/texMini/pull/8)
- Tested `main` commit: [`bb439d7`](https://github.com/alexmill/texMini/commit/bb439d72196f7e7c16714b74b15cba1c9c49c7b7)
- Annotated tag: [`v0.4.0`](https://github.com/alexmill/texMini/tree/v0.4.0)
- Passing `main` CI: [run 30774923259](https://github.com/alexmill/texMini/actions/runs/30774923259)
- Passing release workflow: [run 30775069381](https://github.com/alexmill/texMini/actions/runs/30775069381)
- PyPI: <https://pypi.org/project/texmini/0.4.0/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.4.0>
- GHCR: `ghcr.io/alexmill/texmini:0.4.0`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The release workflow published GHCR tags `0.4.0`, `0.4`, `0`, and `latest`. The `0.4.0` and `latest` tags resolve to the same public multi-architecture image:

```text
sha256:7dfa7432ac268823fc63b99012041f716e31d5741d435810eb9e0c6845b4b628
```

The image index contains these platform manifests:

| Platform | Manifest digest |
| --- | --- |
| `linux/amd64` | `sha256:d61b0da48d1e42db799c43cbb7a69076824dcee6feaf605f91d716d1a3094a2c` |
| `linux/arm64` | `sha256:cdadcec4fe6e75f08a3cd430de1d89a65e6e4e240313e7a910bb7b599b802ebd` |

GitHub provenance attestation verification succeeds for the versioned image.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.4.0-py3-none-any.whl` | `27a31f86a60c70b0fb8f003dba95498b6db47b94fd5910d80c0be69cd340ca19` |
| `texmini-0.4.0.tar.gz` | `b4a9b69d8f521a259a5abca4c6fda22b38255535b12f9e828bdd3f6efef3f3c0` |

PyPI converted the pending publisher into an active publisher for `texmini`. Publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`; no PyPI token is stored in GitHub.

## Verification Results

- A clean `uvx --refresh --from texmini==0.4.0 texmini --version` invocation returned `0.4.0`.
- PyPI reports the corrected summary: “Approachable LaTeX compiler with automatic TeX Live package installation.”
- Anonymous pulls and manifest requests succeeded for both `:0.4.0` and `:latest`; both resolved to the same image digest.
- The published image compiled traditional BibTeX, Biber-backed and BibTeX-backed BibLaTeX, multiple indexes, MakeIndex and Xindy glossaries, acronyms, nomenclature, minted, multi-file local templates, and engine-directive fixtures with networking disabled.
- The published image required `--shell-escape` for minted and returned a focused error without permission.
- The published image honored CLI and `latexmkrc` output directories, auxiliary directories, job names, and opt-in SyncTeX.
- Published-image watch mode performed the initial build, rebuilt after a bibliography change without looping on generated files, retained SyncTeX output, and returned 130 after SIGINT.
- Published-image cleanup removed custom-layout auxiliary and SyncTeX artifacts while preserving the source and PDF.
- Regression tests retain source-relative subdirectory builds, missing-source diagnostics, and comment-aware package discovery.
- The Linux release smoke test compiled the complete common-workflow fixture set offline without `--user` and verified host ownership.
- Explicit arbitrary UID behavior passed on Linux.
- Fresh managed runtimes compiled pdfLaTeX, LuaLaTeX, XeLaTeX, bibliography, index, glossary, nomenclature, minted, multi-file, custom-layout, and watch workflows on macOS and Linux as applicable.
- `gh attestation verify oci://ghcr.io/alexmill/texmini:0.4.0 --repo alexmill/texMini` succeeded.
- The PyPI and GitHub Release wheel and source archive hashes match exactly.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, merge and test `main`, register any necessary release notes, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
