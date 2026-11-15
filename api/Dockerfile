# One image, three process types (ADR-0001): regwatch-api, regwatch-worker, regwatch-beat.
# Behind a TLS-intercepting proxy, pass its CA as the optional build secret `build_ca`
# (see deploy/README.md); without it the build uses the public trust store.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
RUN groupadd --system regwatch && useradd --system --gid regwatch --home /app regwatch \
    && mkdir -p /data/objectstore && chown regwatch:regwatch /data/objectstore
WORKDIR /app

FROM base AS dev
# Development: dependencies baked in, source bind-mounted by deploy/compose.yaml for hot reload.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen --no-install-project
COPY src ./src
# Migrations and seed data (#28): `make migrate` and `make seed` run them in this image.
COPY alembic.ini ./
COPY alembic ./alembic
COPY seed ./seed
COPY THIRD_PARTY_NOTICES.md ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen && chown -R regwatch:regwatch /app
USER regwatch
EXPOSE 8000
CMD ["regwatch-api", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS runtime
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen --no-dev --no-editable && rm -rf src
COPY alembic.ini ./
COPY alembic ./alembic
COPY seed ./seed
COPY THIRD_PARTY_NOTICES.md ./
USER regwatch
EXPOSE 8000
CMD ["regwatch-api", "--host", "0.0.0.0", "--port", "8000"]
