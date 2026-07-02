# Security Policy

## Reporting a vulnerability

Open a **private security advisory**:
https://github.com/patchwright/wildlint/security/advisories/new — do **not**
open a public issue. Reporters get acknowledgment within 72h and a fix/CVE
timeline; coordinated disclosure on merge.

## Scope

wildlint is a static-analysis tool: no network surface, and its only untrusted
input is the source files it scans, parsed with the stdlib `ast` / `tokenize`
(which do not execute code). The two realistic risk surfaces are:

- **Analysis logic** — a crafted input file aiming to trip a parse-path bug.
- **Release / CI supply chain** — PyPI publishing uses Trusted Publishing (OIDC,
  no stored tokens); the build runs from a pinned-tag checkout. Reports against
  either are welcomed.

`py.typed` ships in the wheel (PEP 561) so downstream type-checkers get the same
guarantees CI enforces.
