"""
Repository for cargo type library.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Integer, String, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base
from ..models.cargo_type import CargoType


class CargoTypeORM(Base):
    __tablename__ = "cargo_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    color_hex: Mapped[str] = mapped_column(String(32), default="#8844aa")
    pattern: Mapped[str] = mapped_column(String(64), default="Solid")
    in_use: Mapped[bool] = mapped_column(Boolean, default=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="")
    method: Mapped[str] = mapped_column(String(64), default="Livestock")
    cargo_subtype: Mapped[str] = mapped_column(String(128), default="Walk-On, Walk-Off")
    avg_weight_per_head_kg: Mapped[float] = mapped_column(Float, default=520.0)
    vcg_from_deck_m: Mapped[float] = mapped_column(Float, default=1.5)
    deck_area_per_head_m2: Mapped[float] = mapped_column(Float, default=1.85)
    dung_weight_pct_per_day: Mapped[float] = mapped_column(Float, default=1.5)


class CargoTypeRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_all(self) -> List[CargoType]:
        """List all cargo types ordered by display_order, then id."""
        result: List[CargoType] = []
        for obj in (
            self._db.query(CargoTypeORM)
            .order_by(CargoTypeORM.display_order, CargoTypeORM.id)
            .all()
        ):
            result.append(self._to_model(obj))
        return result

    def get(self, cargo_type_id: int) -> Optional[CargoType]:
        obj = self._db.get(CargoTypeORM, cargo_type_id)
        if not obj:
            return None
        return self._to_model(obj)

    def create(self, ct: CargoType) -> CargoType:
        obj = CargoTypeORM(
            display_order=ct.display_order,
            color_hex=ct.color_hex,
            pattern=ct.pattern,
            in_use=ct.in_use,
            name=ct.name,
            description=ct.description,
            method=getattr(ct, "method", "Livestock"),
            cargo_subtype=getattr(ct, "cargo_subtype", "Walk-On, Walk-Off"),
            avg_weight_per_head_kg=getattr(ct, "avg_weight_per_head_kg", 520.0),
            vcg_from_deck_m=getattr(ct, "vcg_from_deck_m", 1.5),
            deck_area_per_head_m2=getattr(ct, "deck_area_per_head_m2", 1.85),
            dung_weight_pct_per_day=getattr(ct, "dung_weight_pct_per_day", 1.5),
        )
        self._db.add(obj)
        self._db.commit()
        self._db.refresh(obj)
        ct.id = obj.id
        return ct

    def update(self, ct: CargoType) -> CargoType:
        if ct.id is None:
            raise ValueError("CargoType.id must be set for update")
        obj = self._db.get(CargoTypeORM, ct.id)
        if obj is None:
            raise ValueError(f"CargoType with id {ct.id} not found")
        obj.display_order = ct.display_order
        obj.color_hex = ct.color_hex
        obj.pattern = ct.pattern
        obj.in_use = ct.in_use
        obj.name = ct.name
        obj.description = ct.description
        obj.method = getattr(ct, "method", "Livestock")
        obj.cargo_subtype = getattr(ct, "cargo_subtype", "Walk-On, Walk-Off")
        obj.avg_weight_per_head_kg = getattr(ct, "avg_weight_per_head_kg", 520.0)
        obj.vcg_from_deck_m = getattr(ct, "vcg_from_deck_m", 1.5)
        obj.deck_area_per_head_m2 = getattr(ct, "deck_area_per_head_m2", 1.85)
        obj.dung_weight_pct_per_day = getattr(ct, "dung_weight_pct_per_day", 1.5)
        self._db.commit()
        self._db.refresh(obj)
        return ct

    def delete(self, cargo_type_id: int) -> None:
        obj = self._db.get(CargoTypeORM, cargo_type_id)
        if obj is None:
            return
        self._db.delete(obj)
        self._db.commit()

    def move_up(self, cargo_type_id: int) -> bool:
        """Move item up in display order. Returns True if order changed."""
        all_ = self.list_all()
        idx = next((i for i, c in enumerate(all_) if c.id == cargo_type_id), None)
        if idx is None or idx == 0:
            return False
        prev = all_[idx - 1]
        curr = all_[idx]
        prev.display_order, curr.display_order = curr.display_order, prev.display_order
        self.update(prev)
        self.update(curr)
        return True

    def move_down(self, cargo_type_id: int) -> bool:
        """Move item down in display order. Returns True if order changed."""
        all_ = self.list_all()
        idx = next((i for i, c in enumerate(all_) if c.id == cargo_type_id), None)
        if idx is None or idx >= len(all_) - 1:
            return False
        curr = all_[idx]
        nxt = all_[idx + 1]
        curr.display_order, nxt.display_order = nxt.display_order, curr.display_order
        self.update(curr)
        self.update(nxt)
        return True

    @staticmethod
    def _to_model(obj: CargoTypeORM) -> CargoType:
        return CargoType(
            id=obj.id,
            display_order=obj.display_order,
            color_hex=obj.color_hex,
            pattern=obj.pattern,
            in_use=obj.in_use,
            name=obj.name,
            description=obj.description,
            method=getattr(obj, "method", "Livestock"),
            cargo_subtype=getattr(obj, "cargo_subtype", "Walk-On, Walk-Off"),
            avg_weight_per_head_kg=getattr(obj, "avg_weight_per_head_kg", 520.0),
            vcg_from_deck_m=getattr(obj, "vcg_from_deck_m", 1.5),
            deck_area_per_head_m2=getattr(obj, "deck_area_per_head_m2", 1.85),
            dung_weight_pct_per_day=getattr(obj, "dung_weight_pct_per_day", 1.5),
        )
