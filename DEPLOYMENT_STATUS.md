# Deployment Status

Last verified: 2026-08-02

texMini `0.2.0` is publicly available from PyPI and GHCR. The release was built from the tested `main` commit, published through OIDC Trusted Publishing, and verified from clean, anonymous environments.

## Release

- Version: `0.2.0`
- Tested `main` commit: [`2cafa447`](https://github.com/alexmill/texMini/commit/2cafa447f368481b900e3703935681058216cd67)
- Annotated tag: [`v0.2.0`](https://github.com/alexmill/texMini/tree/v0.2.0)
- Passing `main` CI: [run 30768001232](https://github.com/alexmill/texMini/actions/runs/30768001232)
- Passing release workflow: [run 30768455946](https://github.com/alexmill/texMini/actions/runs/30768455946)
- PyPI: <https://pypi.org/project/texmini/0.2.0/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.2.0>
- GHCR: `ghcr.io/alexmill/texmini:0.2.0`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The release workflow published GHCR tags `0.2.0`, `0.2`, `0`, and `latest`. The `0.2.0` and `latest` tags resolve to the same public multi-architecture image:

```text
sha256:15495dc0ec04e2427dcd746f23fb43fd98b43fff8a156292a082923e77150bfa
```

The image index contains `linux/amd64` and `linux/arm64` manifests. GitHub provenance attestation verification succeeds for the versioned image.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.2.0-py3-none-any.whl` | `5fd2340306fd6296d65c7156a4dc1a87417940bff7b15f1ebbb8bfba192cdae3` |
| `texmini-0.2.0.tar.gz` | `d787e8980b4c17b77adce64225663e2d5af021bebc18b3e6e9e209305a7c5661` |

PyPI converted the pending publisher into an active publisher for `texmini`. Publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`; no PyPI token is stored in GitHub.

## Verification Results

- A clean `uvx --from texmini==0.2.0 texmini --version` invocation returned `0.2.0`.
- Anonymous manifest requests succeeded for both `:0.2.0` and `:latest`.
- The exact README Docker command anonymously pulled `:latest` and produced `paper.pdf`.
- The Docker Desktop output owner matched the host user.
- The Linux release smoke test compiled common fixtures offline without `--user` and verified host ownership.
- Explicit arbitrary UID behavior passed on Linux.
- Fresh managed runtimes compiled pdfLaTeX, LuaLaTeX, and XeLaTeX documents on macOS and Linux.
- `gh attestation verify oci://ghcr.io/alexmill/texmini:0.2.0 --repo alexmill/texMini` succeeded.
- The PyPI and GitHub Release wheel and source archive hashes match exactly.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, merge and test `main`, register any necessary release notes, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
