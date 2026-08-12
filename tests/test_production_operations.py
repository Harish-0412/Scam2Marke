from scripts.validate_operations import validate

from scam2market.config.settings import Settings


def test_production_operations_contract() -> None:
    assert validate() == []


def test_managed_kafka_supports_tls_without_changing_local_default() -> None:
    assert Settings().kafka_security_protocol == "PLAINTEXT"
    assert (
        Settings.model_validate({"kafka_security_protocol": "SSL"}).kafka_security_protocol == "SSL"
    )
