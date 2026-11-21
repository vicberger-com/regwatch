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

FROM caddy:2@sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b
COPY --from=build /app/dist /srv
COPY THIRD_PARTY_NOTICES.md /srv/THIRD_PARTY_NOTICES.md
