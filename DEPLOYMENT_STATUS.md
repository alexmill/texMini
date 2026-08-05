# Deployment Status

Last verified: 2026-08-05

texMini `0.4.3` is publicly available from PyPI, GHCR, and GitHub Releases. The release contains the fixes for [issue #15](https://github.com/alexmill/texMini/issues/15). GitHub Actions published the Python distributions through PyPI Trusted Publishing and published the multi-architecture container with provenance.

## Release

- Issue-fix commit: [`ef5f39d`](https://github.com/alexmill/texMini/commit/ef5f39d13348355464378b8802b81b107c0a4472)
- Release commit: [`da92681`](https://github.com/alexmill/texMini/commit/da92681516c4fe6a39558bf347e23482c41106cd)
- Annotated tag: [`v0.4.3`](https://github.com/alexmill/texMini/tree/v0.4.3)
- Passing release-preparation CI: [run 31040931927](https://github.com/alexmill/texMini/actions/runs/31040931927)
- Passing release workflow: [run 31041183374](https://github.com/alexmill/texMini/actions/runs/31041183374)
- PyPI: <https://pypi.org/project/texmini/0.4.3/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.4.3>
- GHCR: `ghcr.io/alexmill/texmini:0.4.3`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The `0.4.3` and `latest` GHCR tags resolve to the same public image index:

```text
sha256:5bc102dbeee3219b3e9e010af687678caa840854ba884ec8a933b7a06a7d8098
```

The image index contains these platform manifests:

| Platform | Manifest digest |
| --- | --- |
| `linux/amd64` | `sha256:225afc8cf2b1a6d2be0a8c78ee089659e6b16c4e498f4235e4c3c3e898b81016` |
| `linux/arm64` | `sha256:14d650b97a0caa3fc15cd0c9b20021a3e2b047b116cca0b0fe41078e625c8578` |

`gh attestation verify oci://ghcr.io/alexmill/texmini:0.4.3 --repo alexmill/texMini` completed successfully.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.4.3-py3-none-any.whl` | `20bd07f113abe50e1cfec00641bd172da99daa197e8da830687614853d0634a5` |
| `texmini-0.4.3.tar.gz` | `5cb24fdc7cc567f54279770767541a72fa934b926182f1fd1dd31e76b94a33ec` |

PyPI publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`. The protected environment required and received approval from the `alexmill` account.

## Verification Results

- All 90 unit tests passed locally and in the release package job.
- The wheel and source distribution passed Twine validation, and the release workflow installed and tested the wheel.
- Release-preparation CI passed on macOS and Ubuntu, including fresh managed runtimes, amd64 and arm64 Docker builds, adaptive package installation, ownership behavior, package validation, and workflow validation.
- The release Docker smoke job compiled the fixture set with adaptive package installation and verified image ownership behavior.
- A fresh `uvx --index-url https://pypi.org/simple --from texmini==0.4.3 texmini --version` invocation returned `0.4.3`.
- PyPI and the GitHub Release report identical wheel and source archive hashes.
- The versioned and rolling GHCR tags report the same image and platform manifest digests.
- GitHub provenance verification succeeded for the versioned GHCR image.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, test `main`, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
