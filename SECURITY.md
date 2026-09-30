# Security Policy

## Supported versions

Security fixes are applied to the latest release and current `main`. Older builds may not receive fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting at:

<https://github.com/shumybest/yet-another-downloader/security/advisories/new>

Do not open a public issue for an unpatched vulnerability. Include the affected version, impact, minimal reproduction, and suggested mitigation. Never include real cookies, authorization headers, signed media URLs, private videos, or unrelated personal data.

You should receive acknowledgement within seven days. The maintainer will coordinate validation, remediation, and disclosure timing. This is a best-effort open-source project and does not provide a guaranteed response SLA.

## Security boundaries

- The local API is intended to bind only to `127.0.0.1:8765`.
- Mutating API calls use a process-local bearer token.
- Captured credentials remain in memory and are removed with the task.
- The desktop deep link contains launch intent only.
- The application does not attempt to bypass DRM, paywalls, access controls, or service rate limits.

Reports about exposed public media URLs, unsupported websites, or content ownership disputes are support or legal-use questions rather than product vulnerabilities.
