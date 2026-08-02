# Deployment Status

Last verified: 2026-08-02

texMini `0.2.1` is publicly available from PyPI and GHCR. The release was built from the tested `main` commit, published through OIDC Trusted Publishing, and verified from clean, anonymous environments.

## Release

- Version: `0.2.1`
- Tested `main` commit: [`775ac5d6`](https://github.com/alexmill/texMini/commit/775ac5d6ca2a11258c297a061cb6b0b35c7dc964)
- Annotated tag: [`v0.2.1`](https://github.com/alexmill/texMini/tree/v0.2.1)
- Passing `main` CI: [run 30769205619](https://github.com/alexmill/texMini/actions/runs/30769205619)
- Passing release workflow: [run 30769285732](https://github.com/alexmill/texMini/actions/runs/30769285732)
- PyPI: <https://pypi.org/project/texmini/0.2.1/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.2.1>
- GHCR: `ghcr.io/alexmill/texmini:0.2.1`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The release workflow published GHCR tags `0.2.1`, `0.2`, `0`, and `latest`. The `0.2.1` and `latest` tags resolve to the same public multi-architecture image:

```text
sha256:5e0b0596df47426e39ad8beecca25c938ecdeb961f6f4ce72449cfc8e777a191
```

The image index contains `linux/amd64` and `linux/arm64` manifests. GitHub provenance attestation verification succeeds for the versioned image.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.2.1-py3-none-any.whl` | `6cd3dc5cf5ee38d5b9094d27bb135ea4168097d13bb47bbef183b68972418e48` |
| `texmini-0.2.1.tar.gz` | `7294957af804f8f14eb27b6548a36afcf18c0ca4048a208b00ec21c439ca7251` |

PyPI converted the pending publisher into an active publisher for `texmini`. Publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`; no PyPI token is stored in GitHub.

## Verification Results

- A clean `uvx --from texmini==0.2.1 texmini --version` invocation returned `0.2.1`.
- PyPI reports the corrected summary: “Approachable LaTeX compiler with automatic TeX Live package installation.”
- Anonymous pulls and manifest requests succeeded for both `:0.2.1` and `:latest`.
- The exact README Docker command anonymously pulled `:latest` and produced `paper.pdf`.
- The Docker Desktop output owner matched the host user.
- The Linux release smoke test compiled common fixtures offline without `--user` and verified host ownership.
- Explicit arbitrary UID behavior passed on Linux.
- Fresh managed runtimes compiled pdfLaTeX, LuaLaTeX, and XeLaTeX documents on macOS and Linux.
- `gh attestation verify oci://ghcr.io/alexmill/texmini:0.2.1 --repo alexmill/texMini` succeeded.
- The PyPI and GitHub Release wheel and source archive hashes match exactly.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, merge and test `main`, register any necessary release notes, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
