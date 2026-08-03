# Deployment Status

Last verified: 2026-08-02

texMini `0.4.2` is publicly available from PyPI and GHCR. The release contains the post-`0.4.1` architecture refactor, was built from the tested `main` commit, published through OIDC Trusted Publishing, and verified through public package and anonymous registry requests.

## Release

- Architecture PR: [#12](https://github.com/alexmill/texMini/pull/12)
- Release PR: [#13](https://github.com/alexmill/texMini/pull/13)
- Version: `0.4.2`
- Tested `main` commit: [`a3dfcd7`](https://github.com/alexmill/texMini/commit/a3dfcd7c5aedb99c938c9fe9b369b24bc727f9e4)
- Annotated tag: [`v0.4.2`](https://github.com/alexmill/texMini/tree/v0.4.2)
- Passing `main` CI: [run 30781688198](https://github.com/alexmill/texMini/actions/runs/30781688198)
- Passing release workflow: [run 30781803141](https://github.com/alexmill/texMini/actions/runs/30781803141)
- PyPI: <https://pypi.org/project/texmini/0.4.2/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.4.2>
- GHCR: `ghcr.io/alexmill/texmini:0.4.2`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The release workflow published GHCR tags `0.4.2`, `0.4`, `0`, and `latest`. Anonymous registry requests confirm that the `0.4.2` and `latest` tags resolve to the same public multi-architecture image:

```text
sha256:ecb3dea4f3ac27166dd41c2f48da6c998f65e40e782b442a673843ab55a5910a
```

The image index contains these platform manifests:

| Platform | Manifest digest |
| --- | --- |
| `linux/amd64` | `sha256:02955c4d7e43298b9887aad52cb1787573f9cba2675337d99f45a9508d60f8e3` |
| `linux/arm64` | `sha256:6ae6ddc72fd0d9b3313d9c37255ed3e09de5fcb36df448b60652872b190468b8` |

GitHub provenance attestation verification succeeds for the versioned image.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.4.2-py3-none-any.whl` | `c66fdfbebfb66098416e8e21583363f329d834950900eea99429abc063f5c42d` |
| `texmini-0.4.2.tar.gz` | `f3ba59d10ebc3a8f6e002ec922dc53076667d035a3e9b86390a98ba40d454dc7` |

PyPI converted the pending publisher into an active publisher for `texmini`. Publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`; no PyPI token is stored in GitHub.

## Verification Results

- A refreshed `uvx --from texmini==0.4.2 texmini --version` invocation returned `0.4.2`.
- PyPI reports the corrected summary: “Approachable LaTeX compiler with automatic TeX Live package installation.”
- Anonymous registry requests succeeded for both `:0.4.2` and `:latest`; both resolved to the same image digest.
- The Docker image contains the compiler and bibliography baseline. Geometry, indexing, glossary, nomenclature, minted, and other document-specific packages are installed by texMini only when a source requires them.
- The exact versioned README command reused the `texmini-runtime` volume, adaptively installed `geometry` and its additional dependency, and built a fresh document in 7.24 seconds.
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
- `gh attestation verify oci://ghcr.io/alexmill/texmini:0.4.2 --repo alexmill/texMini` succeeded and bound the image digest to commit `a3dfcd7c5aedb99c938c9fe9b369b24bc727f9e4` and tag `v0.4.2`.
- The PyPI and GitHub Release wheel and source archive hashes match exactly.

## Architecture Refactor

- Native `uvx` and Docker continue to execute the same installed Python package and compilation pipeline.
- The Python implementation is split by CLI, model, project analysis, runtime management, build orchestration, reporting, and watch responsibilities while preserving `texmini.cli:main`.
- Docker remains a provisioning and compatibility layer; it does not contain separate compilation, recovery, cleanup, or diagnostic logic.
- CI and release use the same checked-in `tests/smoke_docker.sh` compatibility matrix.
- The Docker TeX Live baseline is declared once in `docker-packages.txt` and consumed directly by the Docker build.
- All 78 unit tests, macOS/Linux fresh-runtime builds, amd64/arm64 Docker builds, adaptive workflow tests, packaging checks, and workflow lint passed before the release tag was created.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, merge and test `main`, register any necessary release notes, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
