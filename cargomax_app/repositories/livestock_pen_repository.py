"""
Repository for livestock pens.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Integer, String, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, Session

from .database import Base
from ..models.livestock_pen import LivestockPen


class LivestockPenORM(Base):
    __tablename__ = "livestock_pens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ships.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    deck: Mapped[str] = mapped_column(String(32), default="")
    pen_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vcg_m: Mapped[float] = mapped_column(Float, default=0.0)
    lcg_m: Mapped[float] = mapped_column(Float, default=0.0)
    tcg_m: Mapped[float] = mapped_column(Float, default=0.0)
    area_m2: Mapped[float] = mapped_column(Float, default=0.0)
    capacity_head: Mapped[int] = mapped_column(Integer, default=0)
    area_a_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_b_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_c_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_d_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    tcg_a_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    tcg_b_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    tcg_c_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    tcg_d_m: Mapped[float | None] = mapped_column(Float, nullable=True)


class LivestockPenRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_ship(self, ship_id: int) -> List[LivestockPen]:
        pens: List[LivestockPen] = []
        for obj in (
            self._db.query(LivestockPenORM)
            .filter(LivestockPenORM.ship_id == ship_id)
            .order_by(LivestockPenORM.deck, LivestockPenORM.name)
            .all()
        ):
            pens.append(
                LivestockPen(
                    id=obj.id,
                    ship_id=obj.ship_id,
                    name=obj.name,
                    deck=obj.deck,
                    pen_no=getattr(obj, "pen_no", None),
                    vcg_m=obj.vcg_m,
                    lcg_m=obj.lcg_m,
                    tcg_m=obj.tcg_m,
                    area_m2=obj.area_m2,
                    capacity_head=obj.capacity_head,
                    area_a_m2=getattr(obj, "area_a_m2", None),
                    area_b_m2=getattr(obj, "area_b_m2", None),
                    area_c_m2=getattr(obj, "area_c_m2", None),
                    area_d_m2=getattr(obj, "area_d_m2", None),
                    tcg_a_m=getattr(obj, "tcg_a_m", None),
                    tcg_b_m=getattr(obj, "tcg_b_m", None),
                    tcg_c_m=getattr(obj, "tcg_c_m", None),
                    tcg_d_m=getattr(obj, "tcg_d_m", None),
                )
            )
        return pens

    def get(self, pen_id: int) -> Optional[LivestockPen]:
        obj = self._db.get(LivestockPenORM, pen_id)
        if not obj:
            return None
        return LivestockPen(
            id=obj.id,
            ship_id=obj.ship_id,
            name=obj.name,
            deck=obj.deck,
            pen_no=getattr(obj, "pen_no", None),
            vcg_m=obj.vcg_m,
            lcg_m=obj.lcg_m,
            tcg_m=obj.tcg_m,
            area_m2=obj.area_m2,
            capacity_head=obj.capacity_head,
            area_a_m2=getattr(obj, "area_a_m2", None),
            area_b_m2=getattr(obj, "area_b_m2", None),
            area_c_m2=getattr(obj, "area_c_m2", None),
            area_d_m2=getattr(obj, "area_d_m2", None),
            tcg_a_m=getattr(obj, "tcg_a_m", None),
            tcg_b_m=getattr(obj, "tcg_b_m", None),
            tcg_c_m=getattr(obj, "tcg_c_m", None),
            tcg_d_m=getattr(obj, "tcg_d_m", None),
        )

    def create(self, pen: LivestockPen) -> LivestockPen:
        if pen.ship_id is None:
            raise ValueError("LivestockPen.ship_id must be set")
        obj = LivestockPenORM(
            ship_id=pen.ship_id,
            name=pen.name,
            deck=pen.deck,
            pen_no=pen.pen_no,
            vcg_m=pen.vcg_m,
            lcg_m=pen.lcg_m,
            tcg_m=pen.tcg_m,
            area_m2=pen.area_m2,
            capacity_head=pen.capacity_head,
            area_a_m2=pen.area_a_m2,
            area_b_m2=pen.area_b_m2,
            area_c_m2=pen.area_c_m2,
            area_d_m2=pen.area_d_m2,
            tcg_a_m=pen.tcg_a_m,
            tcg_b_m=pen.tcg_b_m,
            tcg_c_m=pen.tcg_c_m,
            tcg_d_m=pen.tcg_d_m,
        )
        self._db.add(obj)
        self._db.commit()
        self._db.refresh(obj)
        pen.id = obj.id
        return pen

    def update(self, pen: LivestockPen) -> LivestockPen:
        if pen.id is None:
            raise ValueError("LivestockPen.id must be set for update")
        obj = self._db.get(LivestockPenORM, pen.id)
        if obj is None:
            raise ValueError(f"LivestockPen with id {pen.id} not found")
        obj.name = pen.name
        obj.deck = pen.deck
        obj.pen_no = pen.pen_no
        obj.vcg_m = pen.vcg_m
        obj.lcg_m = pen.lcg_m
        obj.tcg_m = pen.tcg_m
        obj.area_m2 = pen.area_m2
        obj.capacity_head = pen.capacity_head
        obj.area_a_m2 = pen.area_a_m2
        obj.area_b_m2 = pen.area_b_m2
        obj.area_c_m2 = pen.area_c_m2
        obj.area_d_m2 = pen.area_d_m2
        obj.tcg_a_m = pen.tcg_a_m
        obj.tcg_b_m = pen.tcg_b_m
        obj.tcg_c_m = pen.tcg_c_m
        obj.tcg_d_m = pen.tcg_d_m
        self._db.commit()
        self._db.refresh(obj)
        return pen

    def delete(self, pen_id: int) -> None:
        obj = self._db.get(LivestockPenORM, pen_id)
        if obj is None:
            return
        self._db.delete(obj)
        self._db.commit()
