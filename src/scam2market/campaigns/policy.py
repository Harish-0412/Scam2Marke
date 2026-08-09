from scam2market.campaigns.schemas import (
    AlertTrigger,
    AlertType,
    CampaignAssessment,
    CampaignStage,
)
from scam2market.intelligence.fusion import FusionResult, RiskLevel

_RISK_RANK = {
    RiskLevel.normal: 0,
    RiskLevel.watch: 1,
    RiskLevel.high: 2,
    RiskLevel.critical: 3,
}


class InvalidCampaignTransition(ValueError):
    pass


class CampaignStateMachine:
    _transitions: dict[CampaignStage, set[CampaignStage]] = {
        CampaignStage.normal: {CampaignStage.normal, CampaignStage.early_social_seeding},
        CampaignStage.early_social_seeding: {
            CampaignStage.normal,
            CampaignStage.early_social_seeding,
            CampaignStage.coordinated_amplification,
            CampaignStage.post_event,
        },
        CampaignStage.coordinated_amplification: {
            CampaignStage.coordinated_amplification,
            CampaignStage.market_pump,
            CampaignStage.post_event,
        },
        CampaignStage.market_pump: {
            CampaignStage.market_pump,
            CampaignStage.distribution,
            CampaignStage.dump,
        },
        CampaignStage.distribution: {
            CampaignStage.distribution,
            CampaignStage.dump,
            CampaignStage.post_event,
        },
        CampaignStage.dump: {CampaignStage.dump, CampaignStage.post_event},
        CampaignStage.post_event: {CampaignStage.post_event},
    }

    def validate(self, current: CampaignStage, target: CampaignStage) -> None:
        if target not in self._transitions[current]:
            raise InvalidCampaignTransition(f"invalid campaign transition: {current} -> {target}")

    def assess(self, current: CampaignStage, score: FusionResult) -> CampaignAssessment:
        target, reason = self._next_stage(current, score)
        self.validate(current, target)
        return CampaignAssessment(
            next_stage=target,
            transition_reason=reason,
            alerts=self._alerts(score),
        )

    def _next_stage(self, current: CampaignStage, score: FusionResult) -> tuple[CampaignStage, str]:
        price_return = score.stage_signals.get("price_return") or 0.0
        pressure = score.stage_signals.get("buy_sell_pressure") or 0.0
        social = score.social_coordination_risk or score.social_score or 0.0
        coordination = score.coordination_score or 0.0
        market = score.market_anomaly_risk or 0.0

        if current == CampaignStage.normal:
            if social >= 0.35:
                return CampaignStage.early_social_seeding, "social activity crossed watch threshold"
            return current, "no campaign signal"
        if current == CampaignStage.early_social_seeding:
            if coordination >= 0.55:
                return (
                    CampaignStage.coordinated_amplification,
                    "coordination corroborated social seeding",
                )
            if score.severity == RiskLevel.normal and social < 0.20:
                return CampaignStage.normal, "social signal decayed before corroboration"
            return current, "social seeding persists"
        if current == CampaignStage.coordinated_amplification:
            if market >= 0.60 and _RISK_RANK[score.severity] >= _RISK_RANK[RiskLevel.high]:
                return CampaignStage.market_pump, "market anomaly corroborated coordination"
            if score.severity == RiskLevel.normal and social < 0.20:
                return CampaignStage.post_event, "coordinated activity ended without a pump"
            return current, "coordinated amplification persists"
        if current == CampaignStage.market_pump:
            if price_return <= -0.08:
                return CampaignStage.dump, "price reversal crossed dump threshold"
            if pressure <= -0.25 or price_return < -0.02:
                return CampaignStage.distribution, "sell pressure followed pump activity"
            return current, "pump conditions persist"
        if current == CampaignStage.distribution:
            if price_return <= -0.08 or pressure <= -0.50:
                return CampaignStage.dump, "distribution progressed to a sharp selloff"
            if score.severity == RiskLevel.normal:
                return CampaignStage.post_event, "distribution signal decayed"
            return current, "distribution conditions persist"
        if current == CampaignStage.dump and score.severity == RiskLevel.normal:
            return CampaignStage.post_event, "dump activity returned to baseline"
        return current, "campaign remains in terminal monitoring"

    def _alerts(self, score: FusionResult) -> list[AlertTrigger]:
        alerts: list[AlertTrigger] = []
        signals = score.stage_signals
        market = score.market_anomaly_risk or 0.0
        social = score.social_coordination_risk or 0.0
        coordination = score.coordination_score or 0.0
        price_return = signals.get("price_return") or 0.0
        relative_volume = signals.get("relative_volume") or 0.0
        spread = signals.get("spread") or 0.0
        imbalance = signals.get("orderbook_imbalance") or 0.0
        pressure = signals.get("buy_sell_pressure") or 0.0

        if social >= 0.35:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.social_hype_surge,
                    severity=score.social_coordination_severity,
                    reason="social hype or author concentration crossed threshold",
                )
            )
        if coordination >= 0.55:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.coordinated_promotion,
                    severity=score.social_coordination_severity,
                    reason="coordination heuristics crossed threshold",
                )
            )
        if (score.claim_risk or 0.0) >= 0.60:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.unverified_narrative,
                    severity=max_risk(RiskLevel.watch, score.severity),
                    reason="narrative lacked time-valid official support",
                )
            )
        if market >= 0.35 and relative_volume >= 2.5:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.market_volume_anomaly,
                    severity=score.market_anomaly_severity,
                    reason="relative market volume crossed threshold",
                )
            )
        if abs(price_return) >= 0.08:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.market_price_anomaly,
                    severity=score.market_anomaly_severity,
                    reason="absolute price return crossed threshold",
                )
            )
        if spread >= 0.02 or abs(imbalance) >= 0.70:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.market_microstructure_anomaly,
                    severity=score.market_anomaly_severity,
                    reason="spread or order-book imbalance crossed threshold",
                )
            )
        if score.fusion_score >= 0.35 and market >= 0.35 and social >= 0.35:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.cross_domain_manipulation_risk,
                    severity=score.severity,
                    reason="market and social evidence corroborated each other",
                )
            )
        if price_return <= -0.05 or pressure <= -0.35:
            alerts.append(
                AlertTrigger(
                    alert_type=AlertType.possible_dump_phase,
                    severity=max_risk(RiskLevel.watch, score.market_anomaly_severity),
                    reason="negative return or sell pressure indicates a possible dump",
                )
            )
        return alerts


def max_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    return left if _RISK_RANK[left] >= _RISK_RANK[right] else right
