# Security policy

## Supported versions

Security fixes are applied to the latest released minor version. This alpha project does not promise backports to older minors.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private vulnerability reporting for this repository. Include affected version, impact, reproduction, and any suggested mitigation. The maintainer will acknowledge a complete report within seven days and coordinate disclosure after a fix or mitigation is available.

## Deployment boundary

The bundled dashboard is local-first, single-tenant, and unauthenticated. Bind to loopback or place it behind trusted authentication/network controls. Treat query text, candidate metadata, traces, reports, and Test Sets as potentially sensitive; see [Data and privacy](docs/PRIVACY.md).
