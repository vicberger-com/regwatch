# Production proxy (M10.3; ADR-0001): the web app built once, served as static files by Caddy,
# which also terminates TLS and passes /api/* to the API. Build context: web/.
# Behind a TLS-intercepting proxy, pass its CA as the optional build secret `build_ca`.
FROM node:22-trixie-slim@sha256:68c76cfad89921b927eae28ba21407475e29d0ce450afcdbe70c1532db042b64 AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml .npmrc ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    corepack enable && corepack install && pnpm install --frozen-lockfile
COPY . .
RUN ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build

FROM caddy:2@sha256:36c24ad91a7ff7bc4c87fe22bfa8df3c4b18da0773d73fc12ee2c52b98c0bb7e
COPY --from=build /app/dist /srv
COPY THIRD_PARTY_NOTICES.md /srv/THIRD_PARTY_NOTICES.md
