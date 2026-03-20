# Kafka SASL_SSL + OAUTHBEARER — Implementation Plan

Reference: [Decision 0006](0006-kafka-sasl-oauthbearer-auth.md)

## Summary of Changes

Add OAuth2 authentication config to `config.yaml`, extend `PipelineKafkaConfig` to parse it, and thread auth properties through to all Kafka producer/consumer instances. No custom Python OAuth code — relies on librdkafka's native OIDC support.

---

## 1. Extend `config.yaml`

Add an `auth` block under `pipeline.kafka`:

```yaml
pipeline:
  kafka:
    bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS}"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"
    auth:
      security_protocol: "SASL_SSL"
      sasl_mechanism: "OAUTHBEARER"
      sasl_oauthbearer_method: "oidc"
      sasl_oauthbearer_client_id: "${KAFKA_OAUTH_CLIENT_ID}"
      sasl_oauthbearer_client_secret: "${KAFKA_OAUTH_CLIENT_SECRET}"
      sasl_oauthbearer_token_endpoint_url: "${KAFKA_OAUTH_TOKEN_URL}"
      sasl_oauthbearer_scope: "${KAFKA_OAUTH_SCOPE}"
```

When env vars are unset, `${VAR}` remains as the literal string. The auth builder (step 2) treats unresolved or empty values as "auth disabled."

---

## 2. Extend `src/pipeline/config.py`

Add a new `KafkaAuthConfig` dataclass and integrate it into `PipelineKafkaConfig`:

```python
@dataclass
class KafkaAuthConfig:
    security_protocol: str = ""
    sasl_mechanism: str = ""
    sasl_oauthbearer_method: str = ""
    sasl_oauthbearer_client_id: str = ""
    sasl_oauthbearer_client_secret: str = ""
    sasl_oauthbearer_token_endpoint_url: str = ""
    sasl_oauthbearer_scope: str = ""

    def to_librdkafka_config(self) -> dict:
        """Convert to librdkafka property names. Returns empty dict if auth is not configured."""
        if not self.security_protocol:
            return {}
        config = {
            "security.protocol": self.security_protocol,
            "sasl.mechanism": self.sasl_mechanism,
        }
        # Map remaining fields only if populated
        field_map = {
            "sasl_oauthbearer_method": "sasl.oauthbearer.method",
            "sasl_oauthbearer_client_id": "sasl.oauthbearer.client.id",
            "sasl_oauthbearer_client_secret": "sasl.oauthbearer.client.secret",
            "sasl_oauthbearer_token_endpoint_url": "sasl.oauthbearer.token.endpoint.url",
            "sasl_oauthbearer_scope": "sasl.oauthbearer.scope",
        }
        for attr, kafka_key in field_map.items():
            val = getattr(self, attr)
            if val and not val.startswith("${"):  # Skip unresolved env vars
                config[kafka_key] = val
        return config
```

Update `PipelineKafkaConfig`:

```python
@dataclass
class PipelineKafkaConfig:
    bootstrap_servers: str = ""
    logging_topic: str = "pipeline.logs"
    dead_letter_topic: str = "pipeline.dead-letter"
    auth: KafkaAuthConfig = field(default_factory=KafkaAuthConfig)
```

Update `load_config()` to parse the `auth` sub-dict:

```python
kafka_data = pipeline_data.get("kafka", {})
auth_data = kafka_data.pop("auth", {})
# ...
PipelineKafkaConfig(**kafka_data, auth=KafkaAuthConfig(**auth_data))
```

---

## 3. Thread auth config into producers and consumers

Wherever `KafkaProducer` or `KafkaConsumer` is instantiated, pass auth config:

```python
auth_config = pipeline_config.kafka.auth.to_librdkafka_config()
producer = KafkaProducer(bootstrap_servers=..., **auth_config)
consumer = KafkaConsumer(bootstrap_servers=..., group_id=..., topics=..., **auth_config)
```

This uses the existing `**extra_config` passthrough — **no changes to `kafka_producer.py` or `kafka_consumer.py` needed.**

Files to update (wherever Kafka clients are constructed):
- `src/pipeline/bridge_worker.py`
- `src/pipeline/transform_worker.py`
- `src/pipeline/kafka_logging.py` (logging producer)
- Any other call sites that create `KafkaProducer` or `KafkaConsumer`

---

## 4. Update `.env.example`

```
# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Kafka Auth (SASL_SSL + OAUTHBEARER via Azure AD)
# Leave unset for local dev (plaintext to Redpanda)
KAFKA_OAUTH_CLIENT_ID=
KAFKA_OAUTH_CLIENT_SECRET=
KAFKA_OAUTH_TOKEN_URL=https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token
KAFKA_OAUTH_SCOPE=
```

---

## 5. Tests

- **Unit test `KafkaAuthConfig.to_librdkafka_config()`** — verify correct key mapping, empty-when-unconfigured, and unresolved env var skipping.
- **Unit test `load_config()`** — verify auth block is parsed into `KafkaAuthConfig`.
- **Integration tests unchanged** — continue using local Redpanda without auth.

---

## 6. Files Changed (Summary)

| File | Change |
|------|--------|
| `config.yaml` | Add `auth` block under `pipeline.kafka` |
| `src/pipeline/config.py` | Add `KafkaAuthConfig` dataclass, update `PipelineKafkaConfig`, update `load_config()` |
| `src/pipeline/bridge_worker.py` | Pass `auth_config` when constructing Kafka clients |
| `src/pipeline/transform_worker.py` | Pass `auth_config` when constructing Kafka clients |
| `src/pipeline/kafka_logging.py` | Pass `auth_config` when constructing logging producer |
| `.env.example` | Add OAuth env var placeholders |
| `tests/` | Add unit tests for `KafkaAuthConfig` |
| `docs/decisions/0006-*` | Decision record (this PR) |

---

## What This Does NOT Include

- **Custom Python OAuth callback** — not needed; librdkafka handles OIDC natively.
- **Per-source credentials** — single credential set per decision 0006.
- **Custom CA configuration** — standard public CA, not needed.
- **Dev environment auth** — Redpanda stays unauthenticated. Auth activates only when env vars are populated.
