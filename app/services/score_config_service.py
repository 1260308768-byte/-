"""AI Score 配置服务。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_selection import ScoreConfig
from app.score_engine.rules import DEFAULT_RULES
from app.score_engine.weights import DEFAULT_WEIGHTS
from app.score_engine.weights import normalize_weights


def get_score_weights(db: Session) -> dict[str, float]:
    """读取当前启用的评分权重。"""
    config = _get_active_config(db, "score_weights")
    if not config:
        return DEFAULT_WEIGHTS.copy()

    return normalize_weights(json.loads(config.config_value_json))


def update_score_weights(db: Session, weights: dict[str, float]) -> dict[str, float]:
    """更新评分权重配置，并立即生效。"""
    normalized = normalize_weights(weights)
    _upsert_config(db, "score_weights", normalized)
    return normalized


def get_score_rules(db: Session) -> dict[str, Any]:
    """读取当前评分规则。"""
    config = _get_active_config(db, "score_rules")
    if not config:
        return DEFAULT_RULES.copy()

    return _merge_default_rules(json.loads(config.config_value_json))


def update_score_rules(db: Session, rules: dict[str, Any]) -> dict[str, Any]:
    """更新评分规则配置，并立即生效。"""
    _upsert_config(db, "score_rules", rules)
    return rules


def get_config_center_data(db: Session) -> dict[str, Any]:
    """读取配置中心页面所需的数据。"""
    return {
        "weights": get_score_weights(db),
        "rules": get_score_rules(db),
        "plugins": [
            {
                "name": "supplier_score",
                "display_name": "Supplier Score",
                "enabled": True,
                "included_in_total": True,
            },
            {
                "name": "product_score",
                "display_name": "Product Score",
                "enabled": True,
                "included_in_total": True,
            },
            {
                "name": "profit_score",
                "display_name": "Profit Score",
                "enabled": True,
                "included_in_total": True,
            },
            {
                "name": "price_score",
                "display_name": "Price Score",
                "enabled": True,
                "included_in_total": True,
            },
            {
                "name": "fulfillment_score",
                "display_name": "Fulfillment Score",
                "enabled": True,
                "included_in_total": True,
            },
            {
                "name": "competition_score",
                "display_name": "Competition Score",
                "enabled": False,
                "included_in_total": False,
            },
            {
                "name": "supplier_stability_score",
                "display_name": "Supplier Stability Score",
                "enabled": False,
                "included_in_total": False,
            },
        ],
    }


def _get_active_config(db: Session, config_key: str) -> ScoreConfig | None:
    """根据配置键读取启用中的配置。"""
    return db.scalar(
        select(ScoreConfig)
        .where(ScoreConfig.config_key == config_key)
        .where(ScoreConfig.is_active.is_(True))
        .order_by(ScoreConfig.updated_at.desc())
    )


def _upsert_config(db: Session, config_key: str, value: Any) -> None:
    """新增或更新配置。"""
    config = _get_active_config(db, config_key)
    value_json = json.dumps(value, ensure_ascii=False)

    if config:
        config.config_value_json = value_json
    else:
        db.add(
            ScoreConfig(
                config_key=config_key,
                config_value_json=value_json,
                is_active=True,
            )
        )

    db.commit()


def _merge_default_rules(saved_rules: dict[str, Any]) -> dict[str, Any]:
    """把历史规则与最新默认规则合并，确保新增配置项立即可用。"""
    merged: dict[str, Any] = {}
    for group_key, default_group in DEFAULT_RULES.items():
        saved_group = saved_rules.get(group_key, {})
        if isinstance(default_group, dict) and isinstance(saved_group, dict):
            merged[group_key] = {**default_group, **saved_group}
        else:
            merged[group_key] = saved_group or default_group

    for group_key, saved_group in saved_rules.items():
        if group_key not in merged:
            merged[group_key] = saved_group

    return merged
