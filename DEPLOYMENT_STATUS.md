# Deployment Status

Last verified: 2026-08-13

texMini `0.6.0` is publicly available from PyPI, GHCR, and GitHub Releases. The release adds native Windows x86-64 provisioning through the official TinyTeX self-extracting bundle and its bundled Perl, while retaining the pinned TinyTeX-1 baseline on every supported platform.

## Release

- Release commit: [`86667ec`](https://github.com/alexmill/texMini/commit/86667ecfbba85ae4ee4ff9100563abb965caf13e)
- Annotated tag: [`v0.6.0`](https://github.com/alexmill/texMini/tree/v0.6.0)
- Passing main-branch CI: [run 31767131789](https://github.com/alexmill/texMini/actions/runs/31767131789)
- Passing release workflow: [run 31767397353](https://github.com/alexmill/texMini/actions/runs/31767397353)
- PyPI: <https://pypi.org/project/texmini/0.6.0/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.6.0>
- GHCR: `ghcr.io/alexmill/texmini:0.6.0`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The `0.6.0`, `0.6`, `0`, and `latest` GHCR tags resolve to the same public image index:

```text
sha256:236d60a476677eb6121a6a7c3f6e4acf32b97d2e9cbd7ab15b47d0f9a2b13a75
```

The image index contains these platform manifests:

| Platform | Manifest digest |
| --- | --- |
| `linux/amd64` | `sha256:597eaca41e27f391483439dffad9882ec208a502533f06fc12580df4beb9ad6b` |
| `linux/arm64` | `sha256:b7b183446857f4b92aed227d9b4a765b8fd78489dd4a940cfeaf430c042849bc` |

`gh attestation verify oci://ghcr.io/alexmill/texmini:0.6.0 --repo alexmill/texMini` completed successfully.

## Package Integrity

The artifacts attached to the GitHub Release match the SHA-256 digests reported by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.6.0-py3-none-any.whl` | `5ef6039a2436f49b457dbccfdcf2eb931ea767da2382420415f6336da530f2bd` |
| `texmini-0.6.0.tar.gz` | `ff2aedc2c1b77bbdb98cbd2bfaf219b3e8111f9f7e14527158b10ea43e6c97b2` |

PyPI publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`. The protected environment received approval from the `alexmill` account after both release smoke architectures passed.

## Verification Results

- All 104 unit and packaging tests passed locally and on Ubuntu, macOS, and Windows in CI.
- The wheel and source distribution passed Twine validation, and a clean installation from public PyPI reported texMini `0.6.0`.
- Native Windows CI installed the wheel, provisioned TinyTeX through the Windows self-extracting bundle without host Perl, and compiled pdfLaTeX, LuaLaTeX, XeLaTeX, Beamer, and Biber fixtures from paths containing spaces.
- Native macOS and Linux smoke tests provisioned fresh managed runtimes and exercised adaptive package installation, all supported engines, bibliographies, indices, glossaries, nomenclature, minted, custom layouts, and continuous rebuilding.
- The release workflow ran the full Docker fixture suite on amd64 and representative pdfLaTeX and Biber builds on arm64.
- PyPI and the GitHub Release report identical wheel and source archive hashes.
- The versioned, major-minor, major, and rolling GHCR tags report the same image index digest.
- The published image index contains amd64 and arm64 manifests, and GitHub provenance verification succeeded for the versioned image.

## User-Facing Release Changes

- Windows x86-64 uses the official TinyTeX Windows bundle, its bundled Perl, and platform-native executable discovery.
- The GPG advisory now makes clear that the current build continues and that installing GnuPG protects future package installations.
- First-run output and the README disclose the managed runtime's approximate 300–350 MB initial disk use.
- Absolute input paths now produce absolute PDF and diagnostic paths in status output.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, test `main`, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
