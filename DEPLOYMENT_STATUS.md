# Deployment Status

Last verified: 2026-08-02

texMini `0.3.0` is publicly available from PyPI and GHCR. The release was built from the tested `main` commit, published through OIDC Trusted Publishing, and verified from clean, anonymous environments.

## Release

- Version: `0.3.0`
- Tested `main` commit: [`ad054c6b`](https://github.com/alexmill/texMini/commit/ad054c6b00cf4f22761d2cd9fffd762bc469f962)
- Annotated tag: [`v0.3.0`](https://github.com/alexmill/texMini/tree/v0.3.0)
- Passing `main` CI: [run 30771914364](https://github.com/alexmill/texMini/actions/runs/30771914364)
- Passing release workflow: [run 30772000914](https://github.com/alexmill/texMini/actions/runs/30772000914)
- PyPI: <https://pypi.org/project/texmini/0.3.0/>
- GitHub Release: <https://github.com/alexmill/texMini/releases/tag/v0.3.0>
- GHCR: `ghcr.io/alexmill/texmini:0.3.0`
- GHCR rolling tag: `ghcr.io/alexmill/texmini:latest`

The release workflow published GHCR tags `0.3.0`, `0.3`, `0`, and `latest`. The `0.3.0` and `latest` tags resolve to the same public multi-architecture image:

```text
sha256:2e68850248b63b322988ff066a7e5ddb43eff2b242f339740e4308f462b47077
```

The image index contains `linux/amd64` and `linux/arm64` manifests. GitHub provenance attestation verification succeeds for the versioned image.

## Package Integrity

The artifacts attached to the GitHub Release match the files served by PyPI:

| Artifact | SHA-256 |
| --- | --- |
| `texmini-0.3.0-py3-none-any.whl` | `fad6871c59c52b68d87b0ab6c995e8706cceac2c6ee37020582607e8be0efd3b` |
| `texmini-0.3.0.tar.gz` | `bbdf2de1faeffd642e27352308717b830d6e22cc01fe2048683a7e756fe7c81d` |

PyPI converted the pending publisher into an active publisher for `texmini`. Publication uses GitHub Actions OIDC with repository `alexmill/texMini`, workflow `release.yml`, and environment `pypi`; no PyPI token is stored in GitHub.

## Verification Results

- A clean `uvx --from texmini==0.3.0 texmini --version` invocation returned `0.3.0`.
- PyPI reports the corrected summary: “Approachable LaTeX compiler with automatic TeX Live package installation.”
- Anonymous pulls and manifest requests succeeded for both `:0.3.0` and `:latest`.
- The exact README Docker command anonymously pulled `:latest` and produced `paper.pdf`.
- The Docker Desktop output owner matched the host user.
- A public PyPI install compiled `docs/paper.tex` with its sibling bibliography into `docs/paper.pdf`, reported the unchanged second build as up to date, and removed source-relative auxiliary files with `--clean`.
- A public PyPI install rejected a nonexistent source before runtime initialization with the source filename in the diagnostic.
- Tests confirm commented-out package and bibliography directives are excluded from dependency discovery while escaped percent signs remain valid source text.
- The Linux release smoke test compiled common fixtures offline without `--user` and verified host ownership.
- Explicit arbitrary UID behavior passed on Linux.
- Fresh managed runtimes compiled pdfLaTeX, LuaLaTeX, and XeLaTeX documents on macOS and Linux.
- `gh attestation verify oci://ghcr.io/alexmill/texmini:0.3.0 --repo alexmill/texMini` succeeded.
- The PyPI and GitHub Release wheel and source archive hashes match exactly.

## Release Configuration

- The `pypi` GitHub environment requires review and allows self-approval.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow validates annotated stable SemVer tags and package-version equality.
- Release actions are pinned to immutable commit SHAs and use job-scoped permissions.

Future releases should increment the package version, merge and test `main`, register any necessary release notes, and create a new annotated version tag. Published version tags and artifacts must remain immutable.
