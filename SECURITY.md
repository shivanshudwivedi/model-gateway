# Security policy

Report vulnerabilities privately through GitHub private vulnerability reporting where
available. Do not include production credentials or sensitive prompts in a report.

- Store API and provider keys in a secret manager.
- Use TLS for public traffic and encrypted database/Redis connections.
- Replace static internal API keys with your identity platform for internet-facing use.
- Apply least-privilege network and database policies.
- Treat stored request and response payloads as sensitive data.
- Pin production images by digest and scan dependencies and containers.
