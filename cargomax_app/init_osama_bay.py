from __future__ import annotations

"""
One-time initializer for the static Osama Bay ship, tanks, and livestock pens.

Run from the project root (where main.py lives) with:

    python -m cargomax_app.init_osama_bay

This will:
- create the ship "OSAMA BAY" if it does not exist,
- add some example tanks (you can edit/extend them),
- add some example pens on decks A/B (edit to match your real layout).
"""

from typing import List

from .config.settings import Settings, init_logging
from .repositories.database import SessionLocal, init_database
from .repositories.ship_repository import ShipRepository
from .repositories.tank_repository import TankRepository
from .repositories.livestock_pen_repository import LivestockPenRepository
from .models.ship import Ship
from .models.tank import Tank, TankType
from .models.livestock_pen import LivestockPen


def _get_or_create_osama_bay(ship_repo: ShipRepository) -> Ship:
    ships: List[Ship] = ship_repo.list()
    ship = next((s for s in ships if s.name.upper() == "OSAMA BAY"), None)
    if ship is not None:
        return ship

    ship = Ship(
        name="OSAMA BAY",
        imo_number="",
        flag="",
        length_overall_m=0.0,
        breadth_m=0.0,
        depth_m=0.0,
        design_draft_m=0.0,
    )
    return ship_repo.create(ship)


def init_osama_bay() -> None:
    # Ensure the database/session are initialized, just like main.py does.
    global SessionLocal
    if SessionLocal is None:
        settings = Settings.default()
        init_logging(settings)
        SessionLocal = init_database(settings.db_path)

    with SessionLocal() as db:
        ship_repo = ShipRepository(db)
        tank_repo = TankRepository(db)
        pen_repo = LivestockPenRepository(db)

        ship = _get_or_create_osama_bay(ship_repo)

        # Only seed demo data if there are currently no tanks/pens
        if not tank_repo.list_for_ship(ship.id):
            # TODO: replace these example tanks with your real Osama Bay tanks
            tank_repo.create(Tank(
                ship_id=ship.id,
                name="P1-1",
                description="Example cargo tank",
                capacity_m3=100.0,
                density_t_per_m3=1.0,
                longitudinal_pos=0.2,
                kg_m=5.0,
                tcg_m=0.0,
                lcg_m=20.0,
                tank_type=TankType.CARGO,
            ))
            tank_repo.create(Tank(
                ship_id=ship.id,
                name="P1-2",
                description="Example cargo tank",
                capacity_m3=120.0,
                density_t_per_m3=1.0,
                longitudinal_pos=0.3,
                kg_m=5.5,
                tcg_m=0.0,
                lcg_m=30.0,
                tank_type=TankType.CARGO,
            ))

        if not pen_repo.list_for_ship(ship.id):
            # TODO: replace these example pens with your real ones and deck codes
            pen_repo.create(LivestockPen(
                ship_id=ship.id,
                name="PEN 1-1",
                deck="A",
                area_m2=10.0,
                capacity_head=50,
                vcg_m=5.0,
                lcg_m=20.0,
                tcg_m=2.0,
            ))
            pen_repo.create(LivestockPen(
                ship_id=ship.id,
                name="PEN 1-2",
                deck="B",
                area_m2=12.0,
                capacity_head=60,
                vcg_m=5.5,
                lcg_m=25.0,
                tcg_m=2.5,
            ))

    print("Osama Bay ship/tanks/pens initialized.")


if __name__ == "__main__":
    init_osama_bay()

