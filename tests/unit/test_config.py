"""Unit tests for configuration loading."""


from pipeline.config import (
    KafkaAuthConfig,
    load_config,
)


class TestLoadConfig:
    def test_load_basic_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
pipeline:
  kafka:
    bootstrap_servers: "localhost:9092"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"

sources:
  claimx:
    source_id: "claimx"
    eventhub:
      connection_string: "Endpoint=sb://test"
      consumer_group: "propgateway-cx-bridge"
    kafka:
      internal_topic: "pipeline.claimx.internal"
      target_topic: "pipeline.claimx.target"
      consumer_group: "transform-claimx"
    schema_ref: "schemas/claimx/v1.json"
    retry:
      max_retries: 3
      initial_backoff_s: 1
      max_backoff_s: 30
      backoff_multiplier: 2
""")
        config = load_config(str(config_file))

        assert config.kafka.bootstrap_servers == "localhost:9092"
        assert config.kafka.logging_topic == "pipeline.logs"
        assert "claimx" in config.sources
        assert config.sources["claimx"].source_id == "claimx"
        assert config.sources["claimx"].kafka.internal_topic == "pipeline.claimx.internal"
        assert config.sources["claimx"].retry.max_retries == 3

    def test_env_var_substitution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_BOOTSTRAP", "kafka:9092")
        monkeypatch.setenv("TEST_EH_CONN", "Endpoint=sb://prod")

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
pipeline:
  kafka:
    bootstrap_servers: "${TEST_BOOTSTRAP}"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"

sources:
  claimx:
    source_id: "claimx"
    eventhub:
      connection_string: "${TEST_EH_CONN}"
      consumer_group: "propgateway-cx-bridge"
    kafka:
      internal_topic: "pipeline.claimx.internal"
      target_topic: "pipeline.claimx.target"
      consumer_group: "transform-claimx"
    schema_ref: "schemas/claimx/v1.json"
    retry:
      max_retries: 3
      initial_backoff_s: 1
      max_backoff_s: 30
      backoff_multiplier: 2
""")
        config = load_config(str(config_file))
        assert config.kafka.bootstrap_servers == "kafka:9092"
        assert config.sources["claimx"].eventhub.connection_string == "Endpoint=sb://prod"

    def test_unresolved_env_var_preserved(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
pipeline:
  kafka:
    bootstrap_servers: "${NONEXISTENT_VAR}"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"

sources: {}
""")
        config = load_config(str(config_file))
        assert config.kafka.bootstrap_servers == "${NONEXISTENT_VAR}"

    def test_multiple_sources(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
pipeline:
  kafka:
    bootstrap_servers: "localhost:9092"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"

sources:
  claimx:
    source_id: "claimx"
    eventhub:
      connection_string: "conn1"
      consumer_group: "propgateway-cx-bridge"
    kafka:
      internal_topic: "pipeline.claimx.internal"
      target_topic: "pipeline.claimx.target"
      consumer_group: "transform-claimx"
    schema_ref: "schemas/claimx/v1.json"
    retry:
      max_retries: 3
      initial_backoff_s: 1
      max_backoff_s: 30
      backoff_multiplier: 2
  validate:
    source_id: "validate"
    eventhub:
      connection_string: "conn2"
      consumer_group: "bridge-validate"
    kafka:
      internal_topic: "pipeline.validate.internal"
      target_topic: "pipeline.validate.target"
      consumer_group: "transform-validate"
    schema_ref: "schemas/validate/v1.json"
    retry:
      max_retries: 5
      initial_backoff_s: 2
      max_backoff_s: 60
      backoff_multiplier: 3
""")
        config = load_config(str(config_file))
        assert len(config.sources) == 2
        assert config.sources["validate"].retry.max_retries == 5


class TestKafkaAuthConfig:
    def test_empty_auth_returns_empty_dict(self):
        auth = KafkaAuthConfig()
        assert auth.to_librdkafka_config() == {}

    def test_unresolved_env_var_returns_empty_dict(self):
        auth = KafkaAuthConfig(security_protocol="${UNSET_VAR}")
        assert auth.to_librdkafka_config() == {}

    def test_full_auth_config(self):
        auth = KafkaAuthConfig(
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauthbearer_method="oidc",
            sasl_oauthbearer_client_id="my-client-id",
            sasl_oauthbearer_client_secret="my-secret",
            sasl_oauthbearer_token_endpoint_url="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            sasl_oauthbearer_scope="api://kafka/.default",
        )
        result = auth.to_librdkafka_config()
        assert result == {
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "OAUTHBEARER",
            "sasl.oauthbearer.method": "oidc",
            "sasl.oauthbearer.client.id": "my-client-id",
            "sasl.oauthbearer.client.secret": "my-secret",
            "sasl.oauthbearer.token.endpoint.url": "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            "sasl.oauthbearer.scope": "api://kafka/.default",
        }

    def test_skips_unresolved_optional_fields(self):
        auth = KafkaAuthConfig(
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauthbearer_method="oidc",
            sasl_oauthbearer_client_id="my-client-id",
            sasl_oauthbearer_client_secret="my-secret",
            sasl_oauthbearer_token_endpoint_url="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            sasl_oauthbearer_scope="${KAFKA_OAUTH_SCOPE}",
        )
        result = auth.to_librdkafka_config()
        assert "sasl.oauthbearer.scope" not in result
        assert result["sasl.oauthbearer.client.id"] == "my-client-id"

    def test_load_config_with_auth(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_CLIENT_ID", "loaded-client-id")
        monkeypatch.setenv("TEST_CLIENT_SECRET", "loaded-secret")
        monkeypatch.setenv("TEST_TOKEN_URL", "https://login.microsoftonline.com/t/oauth2/v2.0/token")

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
pipeline:
  kafka:
    bootstrap_servers: "localhost:9092"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"
    auth:
      security_protocol: "SASL_SSL"
      sasl_mechanism: "OAUTHBEARER"
      sasl_oauthbearer_method: "oidc"
      sasl_oauthbearer_client_id: "${TEST_CLIENT_ID}"
      sasl_oauthbearer_client_secret: "${TEST_CLIENT_SECRET}"
      sasl_oauthbearer_token_endpoint_url: "${TEST_TOKEN_URL}"
      sasl_oauthbearer_scope: "${UNSET_SCOPE}"

sources: {}
""")
        config = load_config(str(config_file))
        assert config.kafka.auth.security_protocol == "SASL_SSL"
        assert config.kafka.auth.sasl_oauthbearer_client_id == "loaded-client-id"
        assert config.kafka.auth.sasl_oauthbearer_scope == "${UNSET_SCOPE}"

        rdkafka = config.kafka.auth.to_librdkafka_config()
        assert rdkafka["sasl.oauthbearer.client.id"] == "loaded-client-id"
        assert "sasl.oauthbearer.scope" not in rdkafka

    def test_load_config_without_auth(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
pipeline:
  kafka:
    bootstrap_servers: "localhost:9092"
    logging_topic: "pipeline.logs"
    dead_letter_topic: "pipeline.dead-letter"

sources: {}
""")
        config = load_config(str(config_file))
        assert config.kafka.auth.to_librdkafka_config() == {}
