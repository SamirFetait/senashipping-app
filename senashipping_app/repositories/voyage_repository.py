"""
Repository for voyages and loading conditions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session

from senashipping_app.repositories.database import Base
from senashipping_app.models import Voyage, LoadingCondition


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware). Replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


class VoyageORM(Base):
    __tablename__ = "voyages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(Integer, ForeignKey("ships.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    departure_port: Mapped[str] = mapped_column(String(128), default="")
    arrival_port: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class LoadingConditionORM(Base):
    __tablename__ = "loading_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voyage_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("voyages.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tank_volumes_json: Mapped[str] = mapped_column(Text, default="{}")
    pen_loadings_json: Mapped[str] = mapped_column(Text, default="{}")
    displacement_t: Mapped[float] = mapped_column(Float, default=0.0)
    draft_m: Mapped[float] = mapped_column(Float, default=0.0)
    trim_m: Mapped[float] = mapped_column(Float, default=0.0)
    gm_m: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class VoyageRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, voyage: Voyage) -> Voyage:
        if voyage.ship_id is None:
            raise ValueError("Voyage.ship_id must be set")
        obj = VoyageORM(
            ship_id=voyage.ship_id,
            name=voyage.name,
            departure_port=voyage.departure_port,
            arrival_port=voyage.arrival_port,
        )
        self._db.add(obj)
        self._db.commit()
        self._db.refresh(obj)
        voyage.id = obj.id
        voyage.created_at = obj.created_at
        return voyage

    def get(self, voyage_id: int) -> Optional[Voyage]:
        obj = self._db.get(VoyageORM, voyage_id)
        if not obj:
            return None
        return Voyage(
            id=obj.id,
            ship_id=obj.ship_id,
            name=obj.name,
            departure_port=obj.departure_port,
            arrival_port=obj.arrival_port,
            created_at=obj.created_at,
            conditions=[],
        )

    def list_for_ship(self, ship_id: int) -> List[Voyage]:
        voyages: List[Voyage] = []
        for obj in (
            self._db.query(VoyageORM)
            .filter(VoyageORM.ship_id == ship_id)
            .order_by(VoyageORM.name)
            .all()
        ):
            voyages.append(
                Voyage(
                    id=obj.id,
                    ship_id=obj.ship_id,
                    name=obj.name,
                    departure_port=obj.departure_port,
                    arrival_port=obj.arrival_port,
                    created_at=obj.created_at,
                    conditions=[],
                )
            )
        return voyages

    def update(self, voyage: Voyage) -> Voyage:
        if voyage.id is None:
            raise ValueError("Voyage.id must be set for update")
        obj = self._db.get(VoyageORM, voyage.id)
        if obj is None:
            raise ValueError(f"Voyage with id {voyage.id} not found")
        obj.name = voyage.name
        obj.departure_port = voyage.departure_port
        obj.arrival_port = voyage.arrival_port
        self._db.commit()
        self._db.refresh(obj)
        return voyage

    def delete(self, voyage_id: int) -> None:
        obj = self._db.get(VoyageORM, voyage_id)
        if obj is None:
            return
        self._db.delete(obj)
        self._db.commit()


class ConditionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _parse_volumes(self, json_str: str) -> Dict[int, float]:
        try:
            if not json_str:
                return {}
            d = json.loads(json_str)
            if not isinstance(d, dict):
                return {}
            result = {}
            for k, v in d.items():
                try:
                    result[int(k)] = float(v)
                except (TypeError, ValueError):
                    continue
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    def _serialize_volumes(self, volumes: Dict[int, float]) -> str:
        return json.dumps({str(k): v for k, v in volumes.items()})

    def _parse_pen_loadings(self, json_str: str) -> Dict[int, int]:
        try:
            if not json_str:
                return {}
            d = json.loads(json_str)
            if not isinstance(d, dict):
                return {}
            result = {}
            for k, v in d.items():
                try:
                    result[int(k)] = int(v)
                except (TypeError, ValueError):
                    continue
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    def _serialize_pen_loadings(self, loadings: Dict[int, int]) -> str:
        return json.dumps({str(k): v for k, v in loadings.items()})

    def create(self, condition: LoadingCondition) -> LoadingCondition:
        if condition.voyage_id is None:
            raise ValueError("Condition.voyage_id must be set")
        obj = LoadingConditionORM(
            voyage_id=condition.voyage_id,
            name=condition.name,
            tank_volumes_json=self._serialize_volumes(condition.tank_volumes_m3),
            pen_loadings_json=self._serialize_pen_loadings(
                getattr(condition, "pen_loadings", {}) or {}
            ),
            displacement_t=condition.displacement_t,
            draft_m=condition.draft_m,
            trim_m=condition.trim_m,
            gm_m=condition.gm_m,
        )
        self._db.add(obj)
        self._db.commit()
        self._db.refresh(obj)
        condition.id = obj.id
        condition.created_at = obj.created_at
        return condition

    def get(self, condition_id: int) -> Optional[LoadingCondition]:
        obj = self._db.get(LoadingConditionORM, condition_id)
        if not obj:
            return None
        pen_loadings = self._parse_pen_loadings(
            getattr(obj, "pen_loadings_json", "{}") or "{}"
        )
        return LoadingCondition(
            id=obj.id,
            voyage_id=obj.voyage_id,
            name=obj.name,
            tank_volumes_m3=self._parse_volumes(obj.tank_volumes_json),
            pen_loadings=pen_loadings,
            displacement_t=obj.displacement_t,
            draft_m=obj.draft_m,
            trim_m=obj.trim_m,
            gm_m=obj.gm_m,
            created_at=obj.created_at,
        )

    def list_for_voyage(self, voyage_id: int) -> List[LoadingCondition]:
        conditions: List[LoadingCondition] = []
        for obj in (
            self._db.query(LoadingConditionORM)
            .filter(LoadingConditionORM.voyage_id == voyage_id)
            .order_by(LoadingConditionORM.name)
            .all()
        ):
            pen_loadings = self._parse_pen_loadings(
                getattr(obj, "pen_loadings_json", "{}") or "{}"
            )
            conditions.append(
                LoadingCondition(
                    id=obj.id,
                    voyage_id=obj.voyage_id,
                    name=obj.name,
                    tank_volumes_m3=self._parse_volumes(obj.tank_volumes_json),
                    pen_loadings=pen_loadings,
                    displacement_t=obj.displacement_t,
                    draft_m=obj.draft_m,
                    trim_m=obj.trim_m,
                    gm_m=obj.gm_m,
                    created_at=obj.created_at,
                )
            )
        return conditions

    def update(self, condition: LoadingCondition) -> LoadingCondition:
        if condition.id is None:
            raise ValueError("Condition.id must be set for update")
        obj = self._db.get(LoadingConditionORM, condition.id)
        if obj is None:
            raise ValueError(f"Condition with id {condition.id} not found")
        obj.name = condition.name
        obj.tank_volumes_json = self._serialize_volumes(condition.tank_volumes_m3)
        if hasattr(obj, "pen_loadings_json"):
            obj.pen_loadings_json = self._serialize_pen_loadings(
                getattr(condition, "pen_loadings", {}) or {}
            )
        obj.displacement_t = condition.displacement_t
        obj.draft_m = condition.draft_m
        obj.trim_m = condition.trim_m
        obj.gm_m = condition.gm_m
        self._db.commit()
        self._db.refresh(obj)
        return condition

    def delete(self, condition_id: int) -> None:
        obj = self._db.get(LoadingConditionORM, condition_id)
        if obj is None:
            return
        self._db.delete(obj)
        self._db.commit()
