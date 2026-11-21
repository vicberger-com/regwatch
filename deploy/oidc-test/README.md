# The `oidc-test` realm: for development and QA only

`regwatch-realm.json` is imported by the `oidc-test` profile's Keycloak (BL-147; `deploy/README.md`). It is a **test fixture**:
- plain http (`sslRequired: none`);
- test users;
- secrets substituted from `keycloak.env`.

Never import it into a Keycloak that real people use.
