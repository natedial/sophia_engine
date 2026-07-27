# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security** tab using a
private vulnerability report. Do not open a public issue containing credentials,
personal data, exploit details, or other sensitive information.

Include the affected component, reproduction steps, likely impact, and any
suggested mitigation. Please allow time for assessment and remediation before
public disclosure.

## Secrets and runtime data

Never commit `.env` files, API keys, database exports, chat transcripts, runtime
state under `.sophia/`, or licensed market-data archives. Use deployment secret
storage for production credentials and synthetic data for tests.
