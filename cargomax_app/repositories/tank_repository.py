from __future__ import annotations

import json
from typing import List

from sqlalchemy import Integer, String, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base
from ..models import Tank, TankType


def _parse_outline(s: str | None) -> list[tuple[float, float]] | None:
    if not s:
        return None
    try:
        import json
        raw = json.loads(s)
        return [tuple(p) for p in raw] if isinstance(raw, list) else None
    except Exception:
        return None


def _serialize_outline(outline: list[tuple[float, float]] | None) -> str | None:
    if not outline:
        return None
    return json.dumps(outline)


class TankORM(Base):
    __tablename__ = "tanks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tank_type: Mapped[str] = mapped_column(String(32), nullable=False)
    capacity_m3: Mapped[float] = mapped_column(Float, default=0.0)
    density_t_per_m3: Mapped[float] = mapped_column(Float, default=1.0)
    longitudinal_pos: Mapped[float] = mapped_column(Float, default=0.5)
    kg_m: Mapped[float] = mapped_column(Float, default=0.0)
    tcg_m: Mapped[float] = mapped_column(Float, default=0.0)
    lcg_m: Mapped[float] = mapped_column(Float, default=0.0)
    outline_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    deck_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, default="Misc. Tanks")


class TankRepository:
    """Repository for CRUD operations on tanks."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_ship(self, ship_id: int) -> List[Tank]:
        tanks: List[Tank] = []
        for obj in (
            self._db.query(TankORM)
            .filter(TankORM.ship_id == ship_id)
            .order_by(TankORM.name)
            .all()
        ):
            cat = getattr(obj, "category", None) or "Misc. Tanks"
            tanks.append(
                Tank(
                    id=obj.id,
                    ship_id=obj.ship_id,
                    name=obj.name,
                    description=getattr(obj, "description", None) or "",
                    tank_type=TankType[obj.tank_type],
                    category=cat,
                    capacity_m3=obj.capacity_m3,
                    density_t_per_m3=getattr(obj, "density_t_per_m3", 1.0) or 1.0,
                    longitudinal_pos=obj.longitudinal_pos,
                    kg_m=obj.kg_m,
                    tcg_m=obj.tcg_m,
                    lcg_m=obj.lcg_m,
                    outline_xy=_parse_outline(getattr(obj, "outline_json", None)),
                    deck_name=getattr(obj, "deck_name", None),
                )
            )
        return tanks

    def create(self, tank: Tank) -> Tank:
        if tank.ship_id is None:
            raise ValueError("Tank.ship_id must be set for create")
        obj = TankORM(
            ship_id=tank.ship_id,
            name=tank.name,
            description=getattr(tank, "description", None) or "",
            tank_type=tank.tank_type.name,
            category=getattr(tank, "category", None) or "Misc. Tanks",
            capacity_m3=tank.capacity_m3,
            density_t_per_m3=getattr(tank, "density_t_per_m3", 1.0) or 1.0,
            longitudinal_pos=tank.longitudinal_pos,
            kg_m=tank.kg_m,
            tcg_m=tank.tcg_m,
            lcg_m=tank.lcg_m,
            outline_json=_serialize_outline(tank.outline_xy) if tank.outline_xy else None,
            deck_name=tank.deck_name,
        )
        self._db.add(obj)
        self._db.commit()
        self._db.refresh(obj)
        tank.id = obj.id
        return tank

    def update(self, tank: Tank) -> Tank:
        if tank.id is None:
            raise ValueError("Tank.id must be set for update")
        obj = self._db.get(TankORM, tank.id)
        if obj is None:
            raise ValueError(f"Tank with id {tank.id} not found")

        obj.name = tank.name
        obj.description = getattr(tank, "description", None) or ""
        obj.tank_type = tank.tank_type.name
        obj.category = getattr(tank, "category", None) or "Misc. Tanks"
        obj.capacity_m3 = tank.capacity_m3
        obj.density_t_per_m3 = getattr(tank, "density_t_per_m3", 1.0) or 1.0
        obj.longitudinal_pos = tank.longitudinal_pos
        obj.kg_m = tank.kg_m
        obj.tcg_m = tank.tcg_m
        obj.lcg_m = tank.lcg_m
        obj.outline_json = _serialize_outline(tank.outline_xy) if tank.outline_xy else None
        obj.deck_name = tank.deck_name

        self._db.commit()
        self._db.refresh(obj)
        return tank

    def delete(self, tank_id: int) -> None:
        obj = self._db.get(TankORM, tank_id)
        if obj is None:
            return
        self._db.delete(obj)
        self._db.commit()


