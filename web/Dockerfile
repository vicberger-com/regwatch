# Development image for the Vite dev server (deploy/compose.yaml service `web`).
# Behind a TLS-intercepting proxy, pass its CA as the optional build secret `build_ca`.
FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS dev
WORKDIR /app
COPY package.json pnpm-lock.yaml .npmrc ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    corepack enable && corepack install && pnpm install --frozen-lockfile \
    && chown -R node:node /app
COPY --chown=node:node . .
USER node
EXPOSE 5173
# Run Vite directly: the internal network has no egress, so corepack cannot fetch pnpm here.
CMD ["./node_modules/.bin/vite"]
