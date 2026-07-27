"""Structured gateway skills built on top of the existing tool stack."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pylon import Pylon

from sophia.gateway.run_store import GatewayRunStore


@dataclass
class GatewaySkillService:
    """Gateway-level structured workflow service."""

    pylon: Pylon
    run_store: GatewayRunStore

    async def run_catalyst_radar(
        self,
        *,
        window_hours: int,
        portfolio_profile: dict[str, Any],
        include: dict[str, bool],
        max_events: int,
        as_of: str | None,
        session_id: str | None,
        agent_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, math.ceil(max(1, window_hours) / 24))
        release_rows = []
        if include.get("economic_releases", True):
            release_rows = await self._load_json_rows(
                "get_releases_upcoming",
                {"days": days, "key_only": True},
            )

        top_events = []
        for row in release_rows[:max_events]:
            name = str(row.get("name") or row.get("title") or "Unnamed release")
            scheduled_at = (
                row.get("release_date")
                or row.get("scheduled_at")
                or row.get("date")
                or as_of
                or _iso_now()
            )
            importance = 85.0 if bool(row.get("key_release", True)) else 60.0
            surprise_risk = 65.0
            positioning_risk = 55.0
            cross_asset = 50.0
            proximity = max(20.0, 100.0 - (days - 1) * 12.5)
            impact_score = round(
                0.35 * importance
                + 0.25 * surprise_risk
                + 0.20 * positioning_risk
                + 0.10 * cross_asset
                + 0.10 * proximity,
                1,
            )
            top_events.append(
                {
                    "event_id": f"release:{row.get('release_id') or name.lower().replace(' ', '_')}:{scheduled_at[:10]}",
                    "event_type": "economic_release",
                    "name": name,
                    "scheduled_at": scheduled_at,
                    "impact_score": impact_score,
                    "impact_bucket": _bucketize(impact_score),
                    "surprise_risk_score": surprise_risk,
                    "positioning_risk_score": positioning_risk,
                    "affected_assets": list(portfolio_profile.get("focus_assets") or ["rates", "usd"]),
                    "watch_levels": [],
                    "base_case": "Consensus outcome with limited cross-asset follow-through.",
                    "upside_case": "A positive surprise increases repricing pressure.",
                    "downside_case": "A softer outcome relaxes immediate pressure.",
                }
            )

        response = {
            "as_of": as_of or _iso_now(),
            "window_hours": window_hours,
            "events": top_events,
            "top_three_summary": [
                f"{event['name']} is a {event['impact_bucket']}-impact catalyst for the next window."
                for event in top_events[:3]
            ] or ["No qualifying catalysts were returned by the current tool set."],
        }
        artifact_id = self.run_store.save_skill_artifact(
            skill_name="catalyst-radar",
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            payload=response,
        )
        response["artifact_id"] = artifact_id
        return response

    async def generate_trade_ideas(
        self,
        *,
        horizon: str,
        risk_budget_bps: float,
        max_ideas: int,
        catalyst_ids: list[str],
        portfolio_constraints: dict[str, Any],
        style: str,
        session_id: str | None,
        agent_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        ideas = []
        base_confidence = max(35.0, min(85.0, 45.0 + risk_budget_bps * 0.6))
        for index, catalyst_id in enumerate(catalyst_ids[:max_ideas], start=1):
            confidence = round(max(30.0, min(90.0, base_confidence - index * 2.5)), 1)
            ideas.append(
                {
                    "idea_id": f"idea_{datetime.now(UTC).strftime('%Y%m%d')}_{index:03d}",
                    "title": f"{style.replace('_', ' ').title()} around {catalyst_id}",
                    "thesis": "Express the catalyst through the cleanest liquid relative-value setup.",
                    "expression": _default_expression(style=style),
                    "entry_zone": "Enter only if price action confirms the catalyst direction.",
                    "invalidation": "Exit if the catalyst narrative breaks or volatility regime shifts.",
                    "target": f"Seek approximately {round(risk_budget_bps * 1.8, 1)} bps equivalent payoff.",
                    "stop": f"Cut risk at approximately {round(risk_budget_bps, 1)} bps equivalent loss.",
                    "expected_holding_period_days": _holding_period_days(horizon),
                    "catalyst_path": [catalyst_id],
                    "risk_reward_ratio": round(1.8, 1),
                    "confidence_score": confidence,
                    "quality_score": round(min(95.0, confidence + 4.0), 1),
                    "kill_criteria": _kill_criteria(portfolio_constraints),
                }
            )

        response = {
            "as_of": _iso_now(),
            "ideas": ideas,
        }
        artifact_id = self.run_store.save_skill_artifact(
            skill_name="trade-ideas",
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            payload=response,
        )
        response["artifact_id"] = artifact_id
        return response

    async def analyze_risk_lens(
        self,
        *,
        portfolio_id: str,
        positions: list[dict[str, Any]],
        upcoming_catalyst_ids: list[str],
        nav_usd: float,
        session_id: str | None,
        agent_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        factor_totals: dict[str, float] = {}
        gross_notional = 0.0
        for position in positions:
            notional = float(position.get("notional_usd") or 0.0)
            gross_notional += abs(notional)
            factor = f"{position.get('asset_class', 'other')}_level"
            direction = -1.0 if str(position.get("direction") or "").lower() == "short" else 1.0
            factor_totals[factor] = factor_totals.get(factor, 0.0) + direction * notional

        exposures = [
            {"factor": factor, "net_beta_usd": round(beta, 2)}
            for factor, beta in sorted(factor_totals.items())
        ]
        concentration = round(min(100.0, (gross_notional / max(nav_usd, 1.0)) * 35.0), 1)
        event_risk = round(min(100.0, 40.0 + len(upcoming_catalyst_ids) * 8.0), 1)
        overall = round(min(100.0, (concentration * 0.55) + (event_risk * 0.45)), 1)
        event_at_risk = [
            {
                "event_id": catalyst_id,
                "scenario": "adverse_move",
                "estimated_pnl_bps_nav": round(
                    -min(25.0, (gross_notional / max(nav_usd, 1.0)) * 10.0),
                    1,
                ),
            }
            for catalyst_id in upcoming_catalyst_ids[:5]
        ]

        response = {
            "portfolio_id": portfolio_id,
            "as_of": _iso_now(),
            "risk_summary": {
                "overall_risk_score": overall,
                "factor_concentration_score": concentration,
                "event_risk_score": event_risk,
                "liquidity_stress_score": round(min(100.0, concentration * 0.6), 1),
            },
            "factor_exposures": exposures,
            "event_at_risk": event_at_risk,
            "top_hidden_risks": _hidden_risks(exposures, upcoming_catalyst_ids),
        }
        artifact_id = self.run_store.save_skill_artifact(
            skill_name="risk-lens",
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            payload=response,
        )
        response["artifact_id"] = artifact_id
        return response

    async def _load_json_rows(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            result = await self.pylon.execute_tool(tool_name, payload)
        except Exception:
            return []
        if not result.success:
            return []
        try:
            parsed = json.loads(result.to_content())
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]
        if isinstance(parsed, dict):
            if isinstance(parsed.get("results"), list):
                return [row for row in parsed["results"] if isinstance(row, dict)]
            if isinstance(parsed.get("releases"), list):
                return [row for row in parsed["releases"] if isinstance(row, dict)]
        return []


def _bucketize(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _default_expression(*, style: str) -> str:
    if "relative_value" in style:
        return "Relative-value expression in liquid macro instruments"
    if "directional" in style:
        return "Directional view with explicit stop and target"
    return "Liquid expression matched to the catalyst horizon"


def _holding_period_days(horizon: str) -> int:
    normalized = horizon.lower().strip()
    if normalized == "intraday":
        return 1
    if normalized == "swing":
        return 10
    return 3


def _kill_criteria(portfolio_constraints: dict[str, Any]) -> list[str]:
    criteria = ["No follow-through after the catalyst window opens."]
    if portfolio_constraints:
        criteria.append("Constraint breach or concentration increase beyond limits.")
    return criteria


def _hidden_risks(
    exposures: list[dict[str, Any]],
    upcoming_catalyst_ids: list[str],
) -> list[str]:
    if not exposures:
        return ["Portfolio has no mapped exposures yet; ingest positions before relying on this view."]
    risks = [
        f"Concentration is highest in {exposures[0]['factor']}."
    ]
    if upcoming_catalyst_ids:
        risks.append("Catalyst clustering may amplify gap risk across correlated positions.")
    risks.append("Risk scores are deterministic first-pass estimates, not scenario-complete VaR.")
    return risks


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()
