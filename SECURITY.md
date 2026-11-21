# Security policy

## Reporting a vulnerability

Report vulnerabilities privately. **Never open a public issue for one.**

- **Preferred:** GitHub's private vulnerability reporting, under the repository's **Security** tab ("Report a vulnerability"). The owner has to enable it in the repository settings.
- **Otherwise:** the owner's security contact: _to be filled in by the owner_ (M10 question 4).

Please include:
- the version, or the commit;
- what is affected;
- the steps to reproduce;
- what an attacker gains.

Do not include real users' data.

## What to expect

- Acknowledgement within 3 business days.
- A first assessment, with a severity, within 7 days.
- Critical issues patched within 7 days, high ones within 30.
- You are credited in the release notes if you wish.

The fix ships in a release whose notes name the issue once users can upgrade.

## Supported versions

Only the latest release receives security fixes. Earlier releases do not; upgrade by following `docs/operations/release.md`.

## Scope

In scope:
- the application in this repository (API, worker, web app);
- its production configuration (`deploy/compose.prod.yaml`, `deploy/Caddyfile.prod`).

Out of scope:
- third-party services an operator connects, such as mail relays, printers and sources;
- the development and QA stacks;
- findings that need an administrator's own account to be misused, unless they cross a boundary the design draws.

Two examples of such boundaries: printers may only reach the configured printer networks, and report previews run sandboxed.

## Good faith

Testing in good faith against your own installation is welcome:
- do not access other people's data beyond what proves the issue;
- do not degrade a service others use, and no denial-of-service testing;
- no social engineering or phishing of users or staff;
- give us reasonable time to fix before disclosure.

There is no bug bounty.

We will not pursue such research.

The security design is in `docs/08-security-compliance.md`, and the operations runbooks are in `docs/operations/`.
