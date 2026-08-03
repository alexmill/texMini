# Deployment Status

Last verified: 2026-08-02

texMini `0.4.1` is publicly available from PyPI and GHCR. The release was built from the tested `main` commit, published through OIDC Trusted Publishing, and verified from clean, anonymous environments.

## Release

- Version: `0.4.1`
- Release PR: [#10](https://github.com/alexmill/texMini/pull/10)
- Tested `main` commit: [`ba1df42`](https://github.com/alexmill/texMini/commit/ba1df428a04e42909167fb843cdbb722a5369b40)
- Annotated tag: [`v0.4.1`](https://github.com/alexmill/texMini/tree/v0.4.1)
- Passing `main` CI: [run 30776636749](https://github.com/alexmill/texMini/actions/runs/30776636749)
- Passing release workflow: [run 30776950194](https://github.com/alexmill/texMini/actions/runs/30776950194)
- PyPI: <https://pypi.org/project/texmini/0.4.1/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.4.1>
- GHCR: `ghcr.io/alexmill/texmini:0.4.1`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The release workflow published GHCR tags `0.4.1`, `0.4`, `0`, and `latest`. The `0.4.1` and `latest` tags resolve to the same public multi-architecture image:

```text
sha256:11873c3b8aa29bd71be0f72fac7d5db05a1da05502caf1cd32a4c4f755ca3bbb
```

The image index contains these platform manifests:

| Platform | Manifest digest |
| --- | --- |
| `linux/amd64` | `sha256:8c03e6df1ad543c9f0e521203092e575a3cf3e320074330c6acb962cc4b8809f` |
| `linux/arm64` | `sha256:35cefedccf1745dd2f81460c116d47ec27c4c56b29f61a604266e3393919be54` |

GitHub provenance attestation verification succeeds for the versioned image.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.4.1-py3-none-any.whl` | `630eb6d0814ed12a8d316c1696b139654e06f3c2a6a2cc62f6382cb2146f6294` |
| `texmini-0.4.1.tar.gz` | `b7f5fe28e8c7726e035586ed06f142c6570f91f9d7e2adc0e16730dee831d400` |

PyPI converted the pending publisher into an active publisher for `texmini`. Publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`; no PyPI token is stored in GitHub.

## Verification Results

- A clean `uvx --refresh --from texmini==0.4.1 texmini --version` invocation returned `0.4.1`.
- PyPI reports the corrected summary: “Approachable LaTeX compiler with automatic TeX Live package installation.”
- Anonymous pulls and manifest requests succeeded for both `:0.4.1` and `:latest`; both resolved to the same image digest.
- The Docker image contains the compiler and bibliography baseline. Geometry, indexing, glossary, nomenclature, minted, and other document-specific packages are installed by texMini only when a source requires them.
- The exact README command created the `texmini-runtime` volume, installed `geometry` and its additional dependency, and built a fresh document in 7.79 seconds. A second disposable container reused the runtime and reported the PDF up to date in 0.22 seconds.
- The adaptive runtime volume occupied 181 MB after that first geometry document; a bibliography-rich fixture then installed its six additional document packages and compiled successfully.
- CI compiled traditional BibTeX, Biber-backed and BibTeX-backed BibLaTeX, multiple indexes, MakeIndex and Xindy glossaries, acronyms, nomenclature, minted, multi-file local templates, and engine-directive fixtures through the adaptive Docker path on amd64 and arm64.
- The published image required `--shell-escape` for minted and returned a focused error without permission.
- The published image honored CLI and `latexmkrc` output directories, auxiliary directories, job names, and opt-in SyncTeX.
- Published-image watch mode performed the initial build, rebuilt after a bibliography change without looping on generated files, retained SyncTeX output, and returned 130 after SIGINT.
- Published-image cleanup removed custom-layout auxiliary and SyncTeX artifacts while preserving the source and PDF.
- Regression tests retain source-relative subdirectory builds, missing-source diagnostics, and comment-aware package discovery.
- The Linux release smoke test installed required packages into a named volume without `--user` and verified host ownership.
- Explicit arbitrary UID behavior installed into a fresh runtime volume successfully on Linux.
- Fresh managed runtimes compiled pdfLaTeX, LuaLaTeX, XeLaTeX, bibliography, index, glossary, nomenclature, minted, multi-file, custom-layout, and watch workflows on macOS and Linux as applicable.
- `gh attestation verify oci://ghcr.io/alexmill/texmini:0.4.1 --repo alexmill/texMini` succeeded.
- The PyPI and GitHub Release wheel and source archive hashes match exactly.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, merge and test `main`, register any necessary release notes, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
