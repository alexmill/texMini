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

FROM ${PYTHON_IMAGE} AS runtime

RUN apt-get update \
  && apt-get install --yes --no-install-recommends ca-certificates fontconfig ghostscript libncurses6 perl util-linux xz-utils \
  && rm -rf /var/lib/apt/lists/*
COPY --from=python-build /opt/texmini /opt/texmini
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/texmini-entrypoint

ENV PATH="/opt/texmini/bin:${PATH}" \
  TEXMINI_PACKAGE_MAP=/opt/TinyTeX/.texmini-package-map.json \
  TEXMINI_TINYTEX_ROOT=/opt/TinyTeX

RUN texmini install-tinytex \
  && chmod -R a+rwX /opt/TinyTeX

ENV HOME=/tmp

WORKDIR /work
ENTRYPOINT ["texmini-entrypoint"]
