"""
STL mesh handling using trimesh.

Load STL drawings (hull, tanks, etc.) and query volume, centroid, bounds.
Tank volume and LCG, VCG, TCG are calculated from STL (replacing DXF).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Tuple

if TYPE_CHECKING:
    from senashipping_app.models import Tank

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False
    trimesh = None


def load_stl(path: str | Path) -> Any:
    """
    Load an STL file and return a trimesh mesh (or Scene).

    Returns:
        trimesh.Trimesh or trimesh.Scene. For a single mesh STL you get Trimesh.
    Raises:
        ImportError: if trimesh is not installed.
        OSError: if file cannot be read.
    """
    if not TRIMESH_AVAILABLE:
        raise ImportError("trimesh is required for STL support. Install with: pip install trimesh")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"STL file not found: {path}")
    result = trimesh.load_mesh(str(path))
    return result


def mesh_volume(mesh: Any) -> float:
    """Volume in m³ (or same units as STL). Returns 0 if not a single solid mesh."""
    if not TRIMESH_AVAILABLE:
        return 0.0
    if isinstance(mesh, trimesh.Scene):
        return sum(mesh_volume(g) for g in mesh.geometry.values())
    if hasattr(mesh, "volume"):
        return float(mesh.volume)
    return 0.0


def mesh_centroid(mesh: Any) -> Tuple[float, float, float]:
    """Center of mass (x, y, z). Returns (0,0,0) if not available."""
    if not TRIMESH_AVAILABLE:
        return 0.0, 0.0, 0.0
    if isinstance(mesh, trimesh.Scene):
        # Use first geometry or weighted average; simple case use first
        geos = list(mesh.geometry.values())
        if not geos:
            return 0.0, 0.0, 0.0
        return mesh_centroid(geos[0])
    if hasattr(mesh, "centroid"):
        c = mesh.centroid
        return float(c[0]), float(c[1]), float(c[2])
    return 0.0, 0.0, 0.0


def mesh_bounds(mesh: Any) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Axis-aligned bounds: ((xmin, ymin, zmin), (xmax, ymax, zmax))."""
    if not TRIMESH_AVAILABLE:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    if isinstance(mesh, trimesh.Scene):
        geos = list(mesh.geometry.values())
        if not geos:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        low, high = mesh_bounds(geos[0])
        for g in geos[1:]:
            l, h = mesh_bounds(g)
            low = (min(low[0], l[0]), min(low[1], l[1]), min(low[2], l[2]))
            high = (max(high[0], h[0]), max(high[1], h[1]), max(high[2], h[2]))
        return low, high
    if hasattr(mesh, "bounds"):
        b = mesh.bounds
        return (float(b[0][0]), float(b[0][1]), float(b[0][2])), (
            float(b[1][0]),
            float(b[1][1]),
            float(b[1][2]),
        )
    return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)


def is_watertight(mesh: Any) -> bool:
    """True if the mesh is closed (no holes); required for meaningful volume."""
    if not TRIMESH_AVAILABLE:
        return False
    if isinstance(mesh, trimesh.Scene):
        return all(is_watertight(g) for g in mesh.geometry.values())
    return bool(getattr(mesh, "is_watertight", False))


# --- Tank creation from STL (volume + LCG, VCG, TCG from mesh) ---

    mesh: Any,
    name: str,
    ship_id: int,
    deck_name: str,
    density_t_per_m3: float = 1.0,
) -> Tank:
    """Build one Tank from a single mesh: volume and centroid → LCG, VCG, TCG (x=LCG, y=TCG, z=VCG)."""
    from senashipping_app.models import Tank as TankModel
    from senashipping_app.models.tank import TankType

    vol = mesh_volume(mesh)
    cx, cy, cz = mesh_centroid(mesh)
    return TankModel(
        ship_id=ship_id,
        name=name,
        capacity_m3=vol,
        density_t_per_m3=density_t_per_m3,
        longitudinal_pos=0.5,
        kg_m=cz,
        tcg_m=cy,
        lcg_m=cx,
        tank_type=TankType.CARGO,
        category="Misc. Tanks",
        deck_name=deck_name,
        outline_xy=None,
    )


def tanks_from_stl(
    stl_path: str | Path,
    ship_id: int,
    deck_name: str,
    density_t_per_m3: float = 1.025,
) -> List[Tank]:
    """
    Load STL and create Tank instances (not persisted) with volume and LCG, VCG, TCG
    from mesh volume and centroid. One tank per mesh (single mesh STL → one tank;
    multi-body STL → one tank per geometry). Coordinate convention: x=LCG, y=TCG, z=VCG.
    """
    if not TRIMESH_AVAILABLE:
        raise ImportError("trimesh is required for STL tanks. Install with: pip install trimesh")
    path = Path(stl_path)
    if not path.exists():
        raise FileNotFoundError(f"STL file not found: {path}")
    result = trimesh.load_mesh(str(path))  # type: ignore[union-attr]
    tanks: List[Tank] = []
    if isinstance(result, trimesh.Scene):  # type: ignore[union-attr]
        for i, (geom_name, geom) in enumerate(result.geometry.items()):
            name = geom_name or path.stem or f"Tank_{i + 1}"
            tanks.append(_tank_from_mesh(geom, name, ship_id, deck_name, density_t_per_m3))
    else:
        name = path.stem or "Tank_1"
        tanks.append(_tank_from_mesh(result, name, ship_id, deck_name, density_t_per_m3))
    return tanks


def create_tanks_from_stl(
    stl_path: str | Path,
    ship_id: int,
    deck_name: str,
    tank_repo: Any,
    density_t_per_m3: float = 1.025,
) -> List[Tank]:
    """Load STL, create Tank instances with volume and LCG/VCG/TCG from mesh, persist and return them."""
    tank_models = tanks_from_stl(stl_path, ship_id, deck_name, density_t_per_m3)
    created: List[Tank] = []
    for t in tank_models:
        created.append(tank_repo.create(t))
    return created
