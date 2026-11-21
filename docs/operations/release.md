# Release process (M10.6; CP-36)

Versions follow semantic versioning: `vMAJOR.MINOR.PATCH`. A release is cut from `main` only; `release.yml` refuses a tag on any other commit.

## Before the first release (once, by the owner)
1. **Protect the tags.** In the repository's settings, add a tag ruleset for `v*` that allows only maintainers to create, move or delete them (BL-146).
2. **Turn on private vulnerability reporting** (`SECURITY.md`), and fill in the security contact there.

## Cutting a release
1. **Make sure everything is green.** All pull requests for the release are merged into `main`, and CI is green on the merge commit: lint, tests, `images` (critical and fixable high findings, the release-image import check, the alert rule tests), `security`, `licenses`, `contract`.
2. **Write the release notes.** Under `[Unreleased]` in `CHANGELOG.md`, add the section `## [X.Y.Z] - YYYY-MM-DD` above the entries it covers, and include any upgrade notes: migrations, new settings, new environment variables. Merge that change.
3. **Tag the merge commit and push the tag:**
   ```
   git checkout main && git pull
   git tag -a vX.Y.Z -m "regwatch X.Y.Z"
   git push origin vX.Y.Z
   ```
4. **`release.yml` runs.** It:
   - checks that the commit is on `main`;
   - builds the release images;
   - checks that every module imports;
   - fails on critical or fixable high findings;
   - attaches CycloneDX SBOMs of the API image, the proxy image and the source tree, with their SHA-256 sums, to the GitHub release.
5. **Paste the release notes** from the CHANGELOG section into the GitHub release.

## Upgrading an installation
1. **Back up first:**
   ```
   COMPOSE="docker compose -f deploy/compose.prod.yaml" make backup
   ```
   Copy the backup off the host, encrypted (`restore-drill.md`).
2. **Get the release and read its upgrade notes:**
   ```
   git fetch --tags && git checkout vX.Y.Z
   ```
3. **Build, then stop the application.** The database keeps running:
   ```
   docker compose -f deploy/compose.prod.yaml build
   docker compose -f deploy/compose.prod.yaml stop api worker beat
   ```
4. **Migrate and seed.** Seeding is idempotent and only adds:
   ```
   docker compose -f deploy/compose.prod.yaml --profile tools run --rm migrate
   docker compose -f deploy/compose.prod.yaml run --rm --no-deps api regwatch-seed
   ```
5. **Start:**
   ```
   docker compose -f deploy/compose.prod.yaml up -d
   ```
   Check that `GET /api/v1/ready` reports ready, sign in, and look at the dashboard.
6. **If something is wrong, roll back:**
   - check out the previous tag;
   - restore the backup taken in step 1 (`CONFIRM=yes make restore FILE=…`), because migrations are not always reversible;
   - then start the stack again.
