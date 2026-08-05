# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

FROM ghcr.io/astral-sh/uv:0.11.20@sha256:eaa5f1a3305307aaf9e67fe2bbba1d85ebbb2d8a63bce23af21797bfafbe0f8b AS uv

FROM ${PYTHON_IMAGE} AS python-build

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv build --wheel --out-dir /dist \
  && uv venv /opt/texmini \
  && uv pip install --python /opt/texmini/bin/python --no-cache /dist/texmini-*.whl

FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818 AS tinytex

ARG TARGETARCH
ARG TINYTEX_VERSION=2026.08
ARG TINYTEX_AMD64_SHA256=6bcde65cbbc147d6e492fa105a7210a06792d609358ef74a14a95228e3e36656
ARG TINYTEX_ARM64_SHA256=7f4a52d8cb85a6d7056a12eb132b989180cd883d408741181a0fe4e8775fb9d4

RUN apt-get update \
  && apt-get install --yes --no-install-recommends ca-certificates curl perl xz-utils \
  && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
  case "$TARGETARCH" in \
    amd64) platform="linux-x86_64"; checksum="$TINYTEX_AMD64_SHA256" ;; \
    arm64) platform="linux-arm64"; checksum="$TINYTEX_ARM64_SHA256" ;; \
    *) echo "Unsupported Docker architecture: $TARGETARCH" >&2; exit 1 ;; \
  esac; \
  archive="TinyTeX-1-${platform}-v${TINYTEX_VERSION}.tar.xz"; \
  curl --fail --location --retry 3 \
    "https://github.com/rstudio/tinytex-releases/releases/download/v${TINYTEX_VERSION}/${archive}" \
    --output "/tmp/${archive}"; \
  echo "${checksum}  /tmp/${archive}" | sha256sum --check -; \
  mkdir -p /opt; \
  tar -xJf "/tmp/${archive}" -C /opt; \
  if [ -d /opt/.TinyTeX ]; then mv /opt/.TinyTeX /opt/TinyTeX; fi; \
  tex_bin="$(find /opt/TinyTeX/bin -mindepth 1 -maxdepth 1 -type d -print -quit)"; \
  PATH="${tex_bin}:$PATH" tlmgr update --self; \
  test -x "${tex_bin}/latexmk"; \
  chmod -R a+rwX /opt/TinyTeX; \
  rm "/tmp/${archive}"

FROM ${PYTHON_IMAGE} AS runtime

RUN apt-get update \
  && apt-get install --yes --no-install-recommends ca-certificates curl fontconfig ghostscript libncurses6 perl util-linux xz-utils \
  && rm -rf /var/lib/apt/lists/*
COPY --from=python-build /opt/texmini /opt/texmini
COPY --from=tinytex /opt/TinyTeX /opt/TinyTeX
RUN chmod -R a+rwX /opt/TinyTeX
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/texmini-entrypoint

ENV HOME=/tmp \
  PATH="/opt/texmini/bin:${PATH}" \
  TEXMINI_PACKAGE_MAP=/opt/TinyTeX/.texmini-package-map.json \
  TEXMINI_TINYTEX_ROOT=/opt/TinyTeX

WORKDIR /work
ENTRYPOINT ["texmini-entrypoint"]
