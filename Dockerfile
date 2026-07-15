FROM nixos/nix:latest AS build

ARG NIX_TARGET=default

WORKDIR /src
COPY flake.nix flake.lock ./
RUN nix build ".#${NIX_TARGET}" --extra-experimental-features "nix-command flakes"
RUN mkdir -p /image/bin /image/nix/store /image/tmp /image/work \
  && cp -a $(nix-store -qR result) /image/nix/store/ \
  && find /image/nix/store -maxdepth 1 -name '*-texdoc' -exec rm -rf {} + \
  && find /image/nix/store -type d \( -name doc -o -name man -o -name info \) -prune -exec rm -rf {} + \
  && command_path="$(find "$(readlink -f result)/bin" -maxdepth 1 -type f -perm -111 | sort | head -n 1)" \
  && ln -s "$command_path" /image/bin/texmini \
  && bash_bin="$(find /image/nix/store -path '*/bin/bash' -type f | head -n 1)" \
  && ln -s "${bash_bin#/image}" /image/bin/sh \
  && chmod 1777 /image/tmp

FROM scratch
COPY --from=build /image /
WORKDIR /work
ENTRYPOINT ["/bin/texmini"]
