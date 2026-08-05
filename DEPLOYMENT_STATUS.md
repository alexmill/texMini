# Deployment Status

Last verified: 2026-08-05

texMini `0.5.0` is publicly available from PyPI, GHCR, and GitHub Releases. The release adopts TinyTeX-1 as the shared baseline for new native runtimes and Docker runtime volumes. GitHub Actions published the Python distributions through PyPI Trusted Publishing and published the multi-architecture container with provenance.

## Release

- Release commit: [`fa4920c`](https://github.com/alexmill/texMini/commit/fa4920ccdf15fb166d0e92edcf1c9a2e2d230415)
- Annotated tag: [`v0.5.0`](https://github.com/alexmill/texMini/tree/v0.5.0)
- Passing main-branch CI: [run 31054416537](https://github.com/alexmill/texMini/actions/runs/31054416537)
- Passing release workflow: [run 31054846778](https://github.com/alexmill/texMini/actions/runs/31054846778)
- PyPI: <https://pypi.org/project/texmini/0.5.0/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.5.0>
- GHCR: `ghcr.io/alexmill/texmini:0.5.0`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The `0.5.0`, `0.5`, `0`, and `latest` GHCR tags resolve to the same public image index:

```text
sha256:7bd209eabdb69a884da44e680d32abe0d4bed745fd3e991ecd359a4fb7d8cf62
```

The image index contains these platform manifests:

| Platform | Manifest digest |
| --- | --- |
| `linux/amd64` | `sha256:db198e0e3a7206e97ec808e551e1e03156c81e2c179b85c9a5ac400eea8acd5b` |
| `linux/arm64` | `sha256:f36b92bbf06a13789e46350a58a923afc6e0368550aabd09faa2c4e18e3e7bf5` |

`gh attestation verify oci://ghcr.io/alexmill/texmini:0.5.0 --repo alexmill/texMini` completed successfully.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.5.0-py3-none-any.whl` | `0f925ee31519bbb743a823f83b3d36cdff76aa96e4b2681745574aaa217ef51a` |
| `texmini-0.5.0.tar.gz` | `f4b7ea9f1e0761908a879353bc6da32a6fdaa163eeb09d0c2f0d333c8ee242ac` |

PyPI publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`. The protected environment required and received approval from the `alexmill` account.

## Verification Results

- All 95 unit and packaging tests passed locally and in CI.
- The wheel and source distribution passed Twine validation, and the release workflow installed and tested the wheel.
- Main-branch CI passed on macOS and Ubuntu, including fresh native TinyTeX-1 runtimes, amd64 and arm64 Docker builds, adaptive package installation, ownership behavior, package validation, and workflow validation.
- The release workflow ran the full Docker fixture suite on amd64 and representative pdfLaTeX and Biber builds on arm64.
- A clean `texmini==0.5.0` installation from public PyPI provisioned TinyTeX-1 and compiled the simple fixture.
- A clean Docker runtime volume compiled the simple fixture with the published `0.5.0` image. A second container reused the volume and reported that the PDF was up to date.
- PyPI and the GitHub Release report identical wheel and source archive hashes.
- The versioned, major-minor, major, and rolling GHCR tags report the same image index digest.
- The published image index contains amd64 and arm64 manifests.
- GitHub provenance verification succeeded for the versioned GHCR image.

## TinyTeX-1 Observations

The native benchmark used the August 2026 TinyTeX-1 archive for macOS arm64. The archive contained 67,051,368 bytes. The installed runtime used 342,211,981 logical bytes and 360,333,312 allocated bytes after the benchmark builds. All cold benchmark builds completed, and texMini installed additional TeX Live packages as each fixture required them. These measurements describe one run; they are not release gates.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, test `main`, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
