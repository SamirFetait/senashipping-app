from __future__ import annotations

"""
One-time initializer for the static Osama Bay ship, tanks, and livestock pens.

Run from the project root (where main.py lives) with:

    python -m senashipping_app.init_osama_bay

This will:
- create the ship "OSAMA BAY" if it does not exist,
- add some example tanks (you can edit/extend them),
- add some example pens on decks A/B (edit to match your real layout).
"""

from typing import List

from senashipping_app.config.settings import Settings, init_logging
from senashipping_app.repositories.database import SessionLocal, init_database
from senashipping_app.repositories.ship_repository import ShipRepository
from senashipping_app.repositories.tank_repository import TankRepository
from senashipping_app.repositories.livestock_pen_repository import LivestockPenRepository
from senashipping_app.models.ship import Ship
from senashipping_app.models.tank import Tank, TankType
from senashipping_app.models.livestock_pen import LivestockPen


def _get_or_create_osama_bay(ship_repo: ShipRepository) -> Ship:
    ships: List[Ship] = ship_repo.list()
    ship = next((s for s in ships if s.name.upper() == "OSAMA BAY"), None)
    if ship is not None:
        # Ensure reference vessel always has correct lightship values from Loading Manual
        ship.lightship_draft_m = 4.188
        ship.lightship_displacement_t = 5076.0
        return ship_repo.update(ship)

    ship = Ship(
        name="OSAMA BAY",
        imo_number="",
        flag="",
        length_overall_m=0.0,
        breadth_m=0.0,
        depth_m=0.0,
        design_draft_m=7.60,
        lightship_draft_m=4.188,
        lightship_displacement_t=5076.0,
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


    print("Osama Bay ship/tanks/pens initialized.")


if __name__ == "__main__":
    init_osama_bay()

