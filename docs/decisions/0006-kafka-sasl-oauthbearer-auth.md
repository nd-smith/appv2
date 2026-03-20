# 0006: Kafka Authentication via SASL_SSL + OAUTHBEARER (Azure AD)

**Date:** 2026-03-20
**Status:** Accepted

## Context

The pipeline connects to an enterprise Confluent Kafka broker that requires authentication. We need to configure all Kafka producers and consumers (bridge workers, transform workers, logging, dead-letter) to authenticate using OAuth2 via the organization's Azure AD identity provider.

Key constraints gathered:
- **IDP:** Azure AD (internal), using OIDC client credentials flow.
- **Credential delivery:** Environment variables injected from Jenkins-managed secrets.
- **CA certificate:** Standard public CA — no custom `ssl.ca.location` needed.
- **Credential scope:** Single set of credentials shared across all workers.

## Decision

Use `SASL_SSL` security protocol with `OAUTHBEARER` SASL mechanism, leveraging librdkafka's built-in OIDC support (`sasl.oauthbearer.method=oidc`). Credentials are supplied via environment variables. Authentication config is defined once in `config.yaml` under `pipeline.kafka` and applied uniformly to all producers and consumers.

### Configuration Properties

The following librdkafka properties will be set on every Kafka client (producer and consumer):

| Property | Value | Source |
|----------|-------|--------|
| `security.protocol` | `SASL_SSL` | config.yaml (static) |
| `sasl.mechanism` | `OAUTHBEARER` | config.yaml (static) |
| `sasl.oauthbearer.method` | `oidc` | config.yaml (static) |
| `sasl.oauthbearer.client.id` | Azure AD app registration client ID | `${KAFKA_OAUTH_CLIENT_ID}` env var |
| `sasl.oauthbearer.client.secret` | Azure AD app registration client secret | `${KAFKA_OAUTH_CLIENT_SECRET}` env var |
| `sasl.oauthbearer.token.endpoint.url` | Azure AD token endpoint | `${KAFKA_OAUTH_TOKEN_URL}` env var |
| `sasl.oauthbearer.scope` | Confluent-required scope (if any) | `${KAFKA_OAUTH_SCOPE}` env var (optional) |

### Design Choices

1. **librdkafka-native OIDC** — No custom Python token callback. librdkafka >= 1.9.0 supports `sasl.oauthbearer.method=oidc` natively, handling token acquisition, caching, and refresh. This is simpler and more reliable than a custom `oauth_cb`. The `confluent-kafka >= 2.6.0` dependency (decision 0002) bundles a sufficiently recent librdkafka.

2. **Config-driven, not code-driven** — Auth properties are defined in `config.yaml` under `pipeline.kafka.auth` and resolved via existing `${ENV_VAR}` substitution. No auth logic in producer/consumer Python code beyond passing config through.

3. **Single credential set** — One Azure AD app registration, one client ID/secret pair, used by all workers. No per-source credential separation needed at current scale (<50 sources).

4. **Standard CA** — The enterprise Confluent broker uses a publicly-trusted CA. No `ssl.ca.location` override needed. If this changes in the future, it can be added as an optional config field.

5. **Dev environment unchanged** — Local development continues to use Redpanda with no auth. Auth config is only populated when env vars are present. When `auth` section is absent or all values are empty, clients connect without authentication (plaintext), preserving the local dev experience.

## PRD Alignment

The PRD specifies Kafka as the internal and output transport but does not prescribe an authentication mechanism. This decision fills that gap. Aligns with:
- Dual-transport architecture (Kafka side now authenticated).
- Observability — failed auth attempts will surface via librdkafka error callbacks already wired into structured logging.
- Simplicity — uses library-native OIDC, no custom token management code.

## Consequences

- **Easier:** Single config block applies auth to all Kafka clients. No custom OAuth code to maintain. Token refresh handled automatically by librdkafka. Dev environment unaffected.
- **Harder:** Debugging token issues requires understanding librdkafka's OIDC flow (mitigated by enabling `debug=security` in non-prod). Requires Jenkins secrets to be configured before deployment.
- **Trade-off:** If per-source credentials are ever needed, the `pipeline.kafka.auth` block would need to support overrides at the source level. Not needed now, easy to add later.
