from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Integer, String, Float
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base
from ..models import Ship


class ShipORM(Base):
    __tablename__ = "ships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    imo_number: Mapped[str] = mapped_column(String(32), default="")
    flag: Mapped[str] = mapped_column(String(64), default="")
    length_overall_m: Mapped[float] = mapped_column(Float, default=0.0)
    breadth_m: Mapped[float] = mapped_column(Float, default=0.0)
    depth_m: Mapped[float] = mapped_column(Float, default=0.0)
    design_draft_m: Mapped[float] = mapped_column(Float, default=0.0)
    lightship_draft_m: Mapped[float] = mapped_column(Float, default=0.0)
    lightship_displacement_t: Mapped[float] = mapped_column(Float, default=0.0)


class ShipRepository:
    """Repository for CRUD operations on ships."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, ship: Ship) -> Ship:
        obj = ShipORM(
            name=ship.name,
            imo_number=ship.imo_number,
            flag=ship.flag,
            length_overall_m=ship.length_overall_m,
            breadth_m=ship.breadth_m,
            depth_m=ship.depth_m,
            design_draft_m=ship.design_draft_m,
            lightship_draft_m=getattr(ship, "lightship_draft_m", 0.0),
            lightship_displacement_t=getattr(ship, "lightship_displacement_t", 0.0),
        )
        self._db.add(obj)
        self._db.commit()
        self._db.refresh(obj)
        ship.id = obj.id
        return ship

    def get(self, ship_id: int) -> Optional[Ship]:
        obj = self._db.get(ShipORM, ship_id)
        if not obj:
            return None
        return Ship(
            id=obj.id,
            name=obj.name,
            imo_number=obj.imo_number,
            flag=obj.flag,
            length_overall_m=obj.length_overall_m,
            breadth_m=obj.breadth_m,
            depth_m=obj.depth_m,
            design_draft_m=obj.design_draft_m,
            lightship_draft_m=getattr(obj, "lightship_draft_m", 0.0),
            lightship_displacement_t=getattr(obj, "lightship_displacement_t", 0.0),
        )

    def list(self) -> List[Ship]:
        ships: List[Ship] = []
        for obj in self._db.query(ShipORM).order_by(ShipORM.name).all():
            ships.append(
                Ship(
                    id=obj.id,
                    name=obj.name,
                    imo_number=obj.imo_number,
                    flag=obj.flag,
                    length_overall_m=obj.length_overall_m,
                    breadth_m=obj.breadth_m,
                    depth_m=obj.depth_m,
                    design_draft_m=obj.design_draft_m,
                    lightship_draft_m=getattr(obj, "lightship_draft_m", 0.0),
                    lightship_displacement_t=getattr(obj, "lightship_displacement_t", 0.0),
                )
            )
        return ships

    def update(self, ship: Ship) -> Ship:
        if ship.id is None:
            raise ValueError("Ship.id must be set for update")
        obj = self._db.get(ShipORM, ship.id)
        if obj is None:
            raise ValueError(f"Ship with id {ship.id} not found")

        obj.name = ship.name
        obj.imo_number = ship.imo_number
        obj.flag = ship.flag
        obj.length_overall_m = ship.length_overall_m
        obj.breadth_m = ship.breadth_m
        obj.depth_m = ship.depth_m
        obj.design_draft_m = ship.design_draft_m
        obj.lightship_draft_m = getattr(ship, "lightship_draft_m", 0.0)
        obj.lightship_displacement_t = getattr(ship, "lightship_displacement_t", 0.0)

        self._db.commit()
        self._db.refresh(obj)
        return ship

    def delete(self, ship_id: int) -> None:
        obj = self._db.get(ShipORM, ship_id)
        if obj is None:
            return
        self._db.delete(obj)
        self._db.commit()


