"""Configuration loading from YAML with environment variable substitution.

Loads config.yaml and expands ${VAR_NAME} patterns from environment variables.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RetryConfig:
    max_retries: int = 3
    initial_backoff_s: float = 1.0
    max_backoff_s: float = 30.0
    backoff_multiplier: float = 2.0


@dataclass
class EventHubConfig:
    connection_string: str = ""
    consumer_group: str = ""
    eventhub_name: str = ""


@dataclass
class KafkaSourceConfig:
    internal_topic: str = ""
    target_topic: str = ""
    consumer_group: str = ""


@dataclass
class SourceConfig:
    source_id: str = ""
    eventhub: EventHubConfig = field(default_factory=EventHubConfig)
    kafka: KafkaSourceConfig = field(default_factory=KafkaSourceConfig)
    schema_ref: str = ""
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass
class KafkaAuthConfig:
    security_protocol: str = ""
    sasl_mechanism: str = ""
    sasl_oauthbearer_method: str = ""
    sasl_oauthbearer_client_id: str = ""
    sasl_oauthbearer_client_secret: str = ""
    sasl_oauthbearer_token_endpoint_url: str = ""
    sasl_oauthbearer_scope: str = ""

    _FIELD_MAP = {
        "sasl_oauthbearer_method": "sasl.oauthbearer.method",
        "sasl_oauthbearer_client_id": "sasl.oauthbearer.client.id",
        "sasl_oauthbearer_client_secret": "sasl.oauthbearer.client.secret",
        "sasl_oauthbearer_token_endpoint_url": "sasl.oauthbearer.token.endpoint.url",
        "sasl_oauthbearer_scope": "sasl.oauthbearer.scope",
    }

    def to_librdkafka_config(self) -> dict:
        """Convert to librdkafka property names. Returns empty dict if auth is not configured."""
        if not self.security_protocol or self.security_protocol.startswith("${"):
            return {}
        config = {
            "security.protocol": self.security_protocol,
            "sasl.mechanism": self.sasl_mechanism,
        }
        for attr, kafka_key in self._FIELD_MAP.items():
            val = getattr(self, attr)
            if val and not val.startswith("${"):
                config[kafka_key] = val
        return config


@dataclass
class PipelineKafkaConfig:
    bootstrap_servers: str = ""
    logging_topic: str = "pipeline.logs"
    dead_letter_topic: str = "pipeline.dead-letter"
    auth: KafkaAuthConfig = field(default_factory=KafkaAuthConfig)


@dataclass
class PipelineConfig:
    kafka: PipelineKafkaConfig = field(default_factory=PipelineKafkaConfig)
    sources: dict[str, SourceConfig] = field(default_factory=dict)


ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} patterns with environment variable values."""

    def replacer(match):
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            return match.group(0)  # Leave unresolved
        return env_value

    return ENV_VAR_PATTERN.sub(replacer, value)


def _substitute_recursive(obj):
    """Recursively substitute env vars in strings within dicts/lists."""
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: _substitute_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute_recursive(item) for item in obj]
    return obj


def _build_source_config(data: dict) -> SourceConfig:
    """Build a SourceConfig from a raw dict."""
    eh_data = data.get("eventhub", {})
    kafka_data = data.get("kafka", {})
    retry_data = data.get("retry", {})

    return SourceConfig(
        source_id=data.get("source_id", ""),
        eventhub=EventHubConfig(**eh_data),
        kafka=KafkaSourceConfig(**kafka_data),
        schema_ref=data.get("schema_ref", ""),
        retry=RetryConfig(**retry_data),
    )


def _find_project_root() -> Path:
    """Walk up from this file to find the project root (contains config.yaml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "config.yaml").exists():
            return current
        current = current.parent
    return Path.cwd()


def load_config(config_path: str | Path = "config.yaml") -> PipelineConfig:
    """Load and parse the pipeline configuration from YAML."""
    path = Path(config_path)
    if not path.is_absolute() and not path.exists():
        path = _find_project_root() / path
    with open(path) as f:
        raw = yaml.safe_load(f)

    raw = _substitute_recursive(raw)

    pipeline_data = raw.get("pipeline", {})
    kafka_data = pipeline_data.get("kafka", {})
    auth_data = kafka_data.pop("auth", {})

    sources = {}
    for name, source_data in raw.get("sources", {}).items():
        sources[name] = _build_source_config(source_data)

    return PipelineConfig(
        kafka=PipelineKafkaConfig(**kafka_data, auth=KafkaAuthConfig(**auth_data)),
        sources=sources,
    )
