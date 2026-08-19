# Security Policy

## Scope

This repository is an educational portfolio. The Tripwise capstone is designed as a restricted demonstration for one owner and one automation service principal; it is not a multi-tenant production service.

Security-sensitive surfaces include Databricks App access, the Tripwise REST and MCP endpoints, OAuth credentials used by the pipeline, Lakebase connectivity, secret-scope references, public-source ingestion, and the software supply chain.

## Trust boundaries

- Databricks authenticates App requests and provides the `X-Forwarded-User` identity header. Tripwise treats this header as trustworthy only behind the Databricks Apps ingress; do not expose the process directly to untrusted networks in enforced mode.
- Tripwise performs application authorization after ingress authentication. Owner routes and automation routes use separate subject allowlists and fail closed when deployment configuration is incomplete.
- Lakebase is accessed with encrypted connections and short-lived credentials supplied at runtime. Database passwords are not application configuration.
- External weather and destination content is untrusted input. It is normalized, size-limited, provenance-checked, and stored as data rather than executed.
- Delta pipeline output crosses into Lakebase only through the authenticated, HTTPS-only pipeline API.

## Secure configuration

- Keep `TRIPWISE_AUTH_MODE=enforce` in every deployed environment. `disabled` is permitted only for local development and automated tests.
- Grant Databricks App `CAN_USE` only to the configured owner and automation service principal.
- Provide owner and automation subjects through deployment variables; do not hard-code real workspace identities in source.
- Store OAuth client secrets in a Databricks secret scope. Pass only the scope and key names through bundle variables.
- Require TLS for Lakebase and pipeline connections. Do not bypass certificate validation.
- Keep the App behind Databricks ingress so callers cannot forge `X-Forwarded-User`.
- Review the bundle plan and run `databricks bundle validate --strict` before deployment.

## Secret handling

Never commit `.env` files, access tokens, OAuth client secrets, database passwords, connection strings, private workspace URLs, or screenshots containing sensitive identifiers. Do not place secret values in command history, issue descriptions, test fixtures, logs, or evidence files.

If a secret is exposed, revoke or rotate it immediately, remove it from all active systems, and follow the hosting provider's history-remediation process. Deleting the latest file version is not sufficient because Git retains history.

## Dependency and change controls

Python runtime dependencies are declared in `requirements.in` and compiled to fully pinned, hashed `requirements.txt` files. Node dependencies are locked in `package-lock.json` and installed with `npm ci`. CI runs Ruff, automated tests, builds, `pip-audit`, and `npm audit`.

Changes to identity handling, SQL, MCP tools, pipeline validation, bundle permissions, or dependency overrides require focused tests and review of backward compatibility. The six public Tripwise MCP tool names and parameters are treated as a compatibility boundary.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed credential. Use the repository's private GitHub security advisory reporting flow. Include the affected path, impact, reproduction steps, and any safe remediation suggestion. Do not include live tokens, personal data, or production database contents.

Because this is a portfolio project, no formal response SLA is offered. Reports will be acknowledged and remediated on a best-effort basis, with credential exposure handled as the highest priority.
