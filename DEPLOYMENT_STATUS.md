# Deployment Status

Last verified: 2026-07-29

texMini's PyPI and GHCR release automation is implemented, pushed to `main`, and passing CI. No release has been published yet.

## Current State

- Release automation commit: [`cb2ac4e`](https://github.com/alexmill/texMini/commit/cb2ac4ea012e4fb6626ce44a27edff95032a48ad)
- Passing CI run: [GitHub Actions run 30433006632](https://github.com/alexmill/texMini/actions/runs/30433006632)
- Package version: `0.2.0`
- Release workflow: `.github/workflows/release.yml`
- Release trigger: annotated stable SemVer tags such as `v0.2.0`
- PyPI project: not created; `texmini` currently returns `404`
- GHCR package: not created
- GitHub tag `v0.2.0`: not created
- GitHub Releases: none

The passing CI run verified:

- Unit tests and wheel/source builds on macOS and Linux
- Wheel installation and fresh TinyTeX compilation on macOS and Linux
- Workflow validation with `actionlint`
- Docker builds for `linux/amd64` and `linux/arm64`
- Offline fixture compilation and arbitrary-UID output ownership on `linux/amd64`

Local verification also built both Docker architectures, compiled `simple.tex` and the Biber/TikZ fixture without networking, checked output ownership, and validated the wheel and source archive with `twine`.

## GitHub Configuration

The repository configuration is complete:

- A `pypi` environment exists.
- `alexmill` is the required reviewer.
- Self-approval is allowed.
- Only tags matching `v*` may deploy through the environment.
- Immutable GitHub Releases are enabled.
- The release workflow uses job-scoped permissions and immutable action SHAs.

No PyPI or registry credentials are stored in GitHub. PyPI publication uses OIDC Trusted Publishing, and GHCR publication uses the workflow's `GITHUB_TOKEN`.

## Release Outputs

Pushing `v0.2.0` will validate the tag and package version, rerun package and Docker smoke tests, and then:

1. Wait for approval of the `pypi` environment.
2. Publish the wheel and source archive to PyPI.
3. Publish a multi-architecture image to `ghcr.io/alexmill/texmini`.
4. Create GHCR tags `0.2.0`, `0.2`, `0`, and `latest`.
5. Attach a GitHub provenance attestation to the image.
6. Create an immutable GitHub Release containing the exact PyPI artifacts.

PyPI and GHCR publication jobs run independently after validation. If one succeeds and the other fails, rerun only the failed job. Never move or reuse a published version tag.

## Remaining Setup

Sign in to PyPI and register a pending Trusted Publisher at:

<https://pypi.org/manage/account/publishing/>

Use these exact values:

| Field | Value |
| --- | --- |
| PyPI project name | `texmini` |
| GitHub owner | `alexmill` |
| GitHub repository | `texMini` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

Do not push the release tag until this publisher exists.

## First Release

After the Trusted Publisher is registered, confirm that `main` still contains version `0.2.0` and has passing CI. Then create the annotated tag at the tested `main` commit:

```bash
git fetch https://github.com/alexmill/texMini.git main
git tag -a v0.2.0 FETCH_HEAD -m "texMini 0.2.0"
git push https://github.com/alexmill/texMini.git v0.2.0
```

When the release workflow reaches the PyPI deployment gate, approve the `pypi` environment in GitHub Actions.

The first GHCR publication creates a private package. After that job succeeds:

1. Open the `alexmill/texmini` package settings on GitHub.
2. Change package visibility to public.
3. Confirm that an unauthenticated pull succeeds.

## Release Verification

After the workflow completes, verify PyPI:

```bash
release_test="$(mktemp -d)"
UV_TOOL_DIR="$release_test/tools" \
UV_TOOL_BIN_DIR="$release_test/bin" \
uv tool install texmini==0.2.0
"$release_test/bin/texmini" --version
```

Verify the container manifest and tags:

```bash
docker buildx imagetools inspect ghcr.io/alexmill/texmini:0.2.0
docker buildx imagetools inspect ghcr.io/alexmill/texmini:latest
```

Verify offline compilation:

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" \
  ghcr.io/alexmill/texmini:0.2.0 test.tex
```

Verify provenance:

```bash
gh attestation verify \
  oci://ghcr.io/alexmill/texmini:0.2.0 \
  --repo alexmill/texMini
```

Finally, confirm that the PyPI wheel and source archive match the assets attached to the immutable GitHub Release.
