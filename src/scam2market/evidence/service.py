import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from scam2market.evidence.schemas import (
    DeterministicExplanation,
    EvidenceInput,
    EvidenceReference,
    EvidenceSnapshot,
)

SNAPSHOT_SCHEMA_VERSION = "evidence-snapshot-v1"
EXPLANATION_TEMPLATE_VERSION = "deterministic-explanation-v1"


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class EvidenceBuilder:
    def build(
        self,
        source: EvidenceInput,
        *,
        previous_chain_hash: str | None,
        created_at: datetime,
    ) -> tuple[EvidenceSnapshot, DeterministicExplanation]:
        content = source.model_dump(mode="json")
        content_hash = canonical_hash(content)
        chain_hash = canonical_hash(
            {
                "previous_chain_hash": previous_chain_hash,
                "content_hash": content_hash,
                "alert_version": source.alert_version,
            }
        )
        snapshot_id = uuid5(
            NAMESPACE_URL,
            f"evidence:{source.alert_id}:{source.alert_version}:{content_hash}",
        )
        completeness = self._completeness(source)
        references = self._references(source)
        snapshot = EvidenceSnapshot(
            snapshot_id=snapshot_id,
            alert_id=source.alert_id,
            campaign_id=source.campaign_id,
            scope_id=source.scope_id,
            asset_id=source.asset_id,
            alert_version=source.alert_version,
            evidence_cutoff=source.evidence_cutoff,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            content=content,
            content_hash=content_hash,
            previous_chain_hash=previous_chain_hash,
            chain_hash=chain_hash,
            completeness_score=float(completeness["score"]),
            completeness=completeness,
            references=references,
            created_at=created_at,
        )
        return snapshot, self._explain(snapshot, source, created_at)

    @staticmethod
    def _completeness(source: EvidenceInput) -> dict[str, Any]:
        fusion = source.fusion
        checks = {
            "market": fusion.get("market_score") is not None,
            "social": fusion.get("social_score") is not None,
            "coordination": fusion.get("coordination_score") is not None,
            "feature_lineage": source.feature is not None and source.feature_lineage is not None,
            "narrative": source.narrative is not None,
            "graph": source.graph is not None,
            "verification": bool(source.verifications),
        }
        present = sum(checks.values())
        return {
            "score": round(present / len(checks), 4),
            "present": sorted(name for name, available in checks.items() if available),
            "missing": sorted(name for name, available in checks.items() if not available),
        }

    @staticmethod
    def _references(source: EvidenceInput) -> list[EvidenceReference]:
        refs = [
            EvidenceReference(
                evidence_type="CAMPAIGN_EVIDENCE",
                evidence_id=source.campaign_evidence_event_id,
                event_time=source.evidence_cutoff,
                digest=canonical_hash(source.fusion),
                metadata={"model_version": source.fusion.get("model_version")},
            )
        ]
        for evidence_type, value, identity_key in (
            ("FEATURE", source.feature, "feature_window_id"),
            ("NARRATIVE", source.narrative, "narrative_id"),
            ("GRAPH", source.graph, "graph_snapshot_id"),
        ):
            if value is not None:
                refs.append(
                    EvidenceReference(
                        evidence_type=evidence_type,
                        evidence_id=str(value.get(identity_key, canonical_hash(value))),
                        event_time=source.evidence_cutoff,
                        digest=canonical_hash(value),
                    )
                )
        refs.extend(
            EvidenceReference(
                evidence_type="CLAIM_VERIFICATION",
                evidence_id=str(item["verification_id"]),
                event_time=source.evidence_cutoff,
                digest=canonical_hash(item),
                metadata={"result": item.get("result")},
            )
            for item in source.verifications
        )
        return refs

    @staticmethod
    def _explain(
        snapshot: EvidenceSnapshot,
        source: EvidenceInput,
        generated_at: datetime,
    ) -> DeterministicExplanation:
        fusion = source.fusion
        score_names = (
            "market_score",
            "social_score",
            "coordination_score",
            "temporal_score",
            "graph_score",
            "claim_risk",
            "legitimate_event_score",
        )
        contributors = sorted(
            (
                {"feature": name, "value": float(fusion[name])}
                for name in score_names
                if fusion.get(name) is not None
            ),
            key=lambda item: abs(float(str(item["value"]))),
            reverse=True,
        )
        rules = [
            {
                "rule": "ALERT_THRESHOLD",
                "outcome": source.severity,
                "fusion_score": fusion.get("fusion_score"),
            },
            {
                "rule": "MARKET_CORROBORATION",
                "outcome": (fusion.get("market_score") or 0) >= 0.35,
            },
        ]
        if source.verifications:
            rules.append(
                {
                    "rule": "CLAIM_VERIFICATION",
                    "outcome": sorted({item.get("result") for item in source.verifications}),
                }
            )
        top = contributors[0]["feature"] if contributors else "available evidence"
        summary = (
            f"{source.severity} {source.alert_type} for {source.asset_id}; "
            f"the strongest recorded contributor was {top}."
        )
        return DeterministicExplanation(
            explanation_id=uuid5(NAMESPACE_URL, f"explanation:{snapshot.snapshot_id}"),
            snapshot_id=snapshot.snapshot_id,
            template_version=EXPLANATION_TEMPLATE_VERSION,
            summary=summary,
            triggered_rules=rules,
            contributors=contributors,
            context={
                "stage": source.stage,
                "scope_id": source.scope_id,
                "evidence_cutoff": source.evidence_cutoff.isoformat(),
                "data_freshness": (source.feature or {}).get("data_freshness"),
                "lead_lag": (source.feature or {}).get("temporal_lead_lag"),
                "narrative_post_count": (source.narrative or {}).get("post_count"),
                "graph_features": (source.graph or {}).get("features"),
                "verification_results": [item.get("result") for item in source.verifications],
                "model_version": fusion.get("model_version"),
                "fusion_policy_version": fusion.get("fusion_policy_version"),
                "threshold_version": fusion.get("threshold_version", "fusion-thresholds-v1"),
                "evidence_completeness": snapshot.completeness_score,
            },
            generated_at=generated_at,
        )
