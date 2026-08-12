from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate() -> list[str]:
    errors: list[str] = []
    terraform = _read("infra/terraform/aws/main.tf")
    _require(
        terraform, "endpoint_public_access  = false", "EKS public endpoint must be disabled", errors
    )
    _require(
        terraform, "enable_key_rotation     = true", "KMS key rotation must be enabled", errors
    )
    _require(
        terraform,
        "block_public_policy     = true",
        "backup bucket must block public policy",
        errors,
    )
    _require(terraform, 'client_broker = "TLS"', "managed Kafka must require TLS", errors)
    _require(terraform, "count  = 3", "production networking must span three AZs", errors)

    restore = _read("ops/backup/restore_drill.sh")
    _require(restore, "ALLOW_RESTORE_DRILL", "restore drill authorization guard is missing", errors)
    _require(restore, "*restore-drill*", "restore drill target-name guard is missing", errors)
    _require(restore, "sha256sum --check", "restore checksum verification is missing", errors)

    ingress = _read("deploy/helm/scam2market/templates/ingress.yaml")
    _require(ingress, "TLS13-1-2", "ingress must enforce TLS 1.2 or newer", errors)
    deployment = _read("deploy/helm/scam2market/templates/deployment.yaml")
    _require(deployment, "readOnlyRootFilesystem: true", "API filesystem must be read-only", errors)
    _require(
        deployment, 'include "scam2market.image"', "deployment image must be digest pinned", errors
    )
    backup_jobs = _read("deploy/helm/scam2market/templates/backup-cronjobs.yaml")
    _require(
        backup_jobs,
        'include "scam2market.operationsImage"',
        "backup image must be digest pinned",
        errors,
    )

    rules = yaml.safe_load(_read("ops/prometheus/rules/scam2market-slo.yml"))
    names = {
        rule.get("alert") or rule.get("record")
        for group in rules.get("groups", [])
        for rule in group.get("rules", [])
    }
    required = {
        "scam2market:sli_availability:ratio_rate5m",
        "Scam2MarketAvailabilityBudgetFastBurn",
        "Scam2MarketApiLatencyHigh",
        "Scam2MarketRequiredDependencyDown",
        "Scam2MarketNoApiTraffic",
    }
    missing = sorted(required - names)
    if missing:
        errors.append(f"missing SLO rules: {', '.join(missing)}")
    return errors


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(content: str, marker: str, message: str, errors: list[str]) -> None:
    if marker not in content:
        errors.append(message)


def main() -> None:
    errors = validate()
    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print("production operations contract passed")


if __name__ == "__main__":
    main()
