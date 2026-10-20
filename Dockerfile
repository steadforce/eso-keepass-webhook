# syntax=docker/dockerfile:1

# uv for the build host. A plain `COPY --from=<image>` would take the target platform's
# binary, which the build host cannot run without emulation.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b AS uv

# Runs on the build host for every target platform: uv downloads the target's wheels
# directly, so multi-arch builds need no emulation. Keep the Python minor version in
# sync with the runtime image.
FROM --platform=$BUILDPLATFORM python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS build
COPY --from=uv /uv /usr/local/bin/uv

ARG TARGETARCH
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN case "$TARGETARCH" in \
      amd64) platform=x86_64-manylinux_2_28 ;; \
      arm64) platform=aarch64-manylinux_2_28 ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && uv export --frozen --no-dev --no-emit-project --output-file requirements.txt \
 && uv pip install --target /app --no-deps --require-hashes --only-binary :all: \
      --python-version 3.13 --python-platform "$platform" -r requirements.txt

COPY src/eso_keepass_webhook /app/eso_keepass_webhook
RUN python -m compileall -q --invalidation-mode unchecked-hash /app

FROM gcr.io/distroless/python3-debian13:nonroot@sha256:83aa8d4f74a4d7f7cf2d472054139bef71a927b76c680c0f2e1021d6b1d6d732
COPY --from=build /app /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["python3", "-m", "eso_keepass_webhook"]
