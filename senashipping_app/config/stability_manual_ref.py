"""
Reference data and formulas from the vessel Loading Manual and Intact Stability Information.

Source: assets/stability.pdf (OSAMA BEY – Loading Manual, Infinity Marine Consultants,
IMO 9141041, Livestock). Used for limits, criteria, formulas and operating rules.
Ship documentation: assets/MV OSAMA BEY- Ship's Particulars.pdf (ship particulars).
Tank list is not included; see the PDFs for tank identification.
"""

from __future__ import annotations

# --- Document reference ---
MANUAL_VESSEL_NAME = "OSAMA BEY"
MANUAL_IMO = "9141041"
MANUAL_SOURCE = "Loading Manual and Intact Stability Information, Livestock"
MANUAL_REF = "Infinity Marine Consultants; IMO Resolution A.749(18) IS Code"

# --- General particulars (reference only; actual ship from DB) ---
# From PDF p.7: LOA 118.02 m, LBP 110.04 m, B 19.40 m, D 9.45 m, design draft 7.60 m
REF_LOA_M = 118.02
REF_LBP_M = 110.04
REF_BREADTH_M = 19.40
REF_DEPTH_M = 9.45
REF_DESIGN_DRAFT_M = 7.60

# From stability.txt Load Case NO.01 – LIGHT WEIGHT: empty ship still has weight and floats
REF_LIGHTSHIP_DRAFT_M = 4.188
REF_LIGHTSHIP_DISPLACEMENT_T = 5076.0
REF_LIGHTSHIP_KG_M = 7.79  # VCG (m) for lightship from manual
# Longitudinal arm 47.72 m from AP. For consistency with the rest of the code,
# which uses LOA as the longitudinal reference length (e.g. tank.longitudinal_pos
# and trim solver), we normalise this by REF_LOA_M, not LBP.
REF_LIGHTSHIP_LCG_NORM = 47.72 / REF_LOA_M  # dimensionless 0–1 (0=aft, 1=fwd) based on LOA
REF_LIGHTSHIP_TCG_M = 0.0  # Trans. arm 0.000 from manual

# --- Fluid densities (PDF p.9) – used for sea water, conversions ---
# Sea Water 1.025, Fresh Water 1.000, Diesel 0.840, Fuel oil 0.9443, Sewage 1.0, Slop 0.913
FLUID_DENSITY_SEA = 1.025
FLUID_DENSITY_FRESH = 1.000
FLUID_DENSITY_DIESEL = 0.840
FLUID_DENSITY_FUEL = 0.9443
FLUID_DENSITY_SEWAGE = 1.000
FLUID_DENSITY_SLOP = 0.913

# --- Tolerances used in the calculations (PDF p.9) ---
# Displacement 0.01 %, Trim (LCG-LCB) 0.01 % of LBP, Heel (TCG-TCB) 0.01 % of LBP
TOLERANCE_DISPLACEMENT_PCT = 0.01
TOLERANCE_TRIM_HEEL_PCT_LBP = 0.01

# --- IMO general intact stability criteria (PDF p.13, IS Code Ch.3) ---
# 3.1.2.1 Area under GZ: not less than 0.055 m·rad up to 30°, 0.09 m·rad up to 40° (or θf);
#          between 30° and 40° (or θf): not less than 0.03 m·rad
# 3.1.2.2 GZ ≥ 0.20 m at angle of heel ≥ 30°
# 3.1.2.3 Max righting arm preferably at angle > 30°, not less than 25°
# 3.1.2.4 Initial metacentric height GMo ≥ 0.15 m
IMO_GZ_AREA_UP_TO_30_DEG_MRAD = 0.055
IMO_GZ_AREA_UP_TO_40_DEG_MRAD = 0.09
IMO_GZ_AREA_30_TO_40_MRAD = 0.03
IMO_GZ_MIN_AT_30_DEG_M = 0.20
IMO_GZ_MAX_ANGLE_MIN_DEG = 25
IMO_GM_MIN_M = 0.15

# --- Weather criterion (PDF p.14) – wind pressure 504 Pa; area b ≥ area a ---
WEATHER_WIND_PRESSURE_PA = 504
GRAVITATIONAL_ACCELERATION_MS2 = 9.81

# --- Applied livestock stability (PDF §3.3; AMSA MO43 / IMO livestock) ---
# Stricter GM for livestock; max roll period for animal welfare; min freeboard
# Numeric values are in config.limits (MIN_GM_LIVESTOCK_M, MAX_ROLL_PERIOD_S, MIN_FREEBORD_M)

# --- Draft calculation formulas (PDF p.11) ---
# t = Disp * (LCB - LCG) / MT1 * 100  (m)   [MT1 = moment to change trim 1 cm]
# df = dLCF - t * (LBP - LCF) / LBP  (m)   draught at FP
# da = df + t  (m)   draught at AP
# dm = (dA + dF) / 2  (m)   mean
DRAFT_FORMULA_TRIM = "t = Disp * (LCB - LCG) / MT1 * 100  [m]"
DRAFT_FORMULA_DF = "df = dLCF - t * (LBP - LCF) / LBP  [m]"
DRAFT_FORMULA_DA = "da = df + t  [m]"
DRAFT_FORMULA_DM = "dm = (dA + dF) / 2  [m]"

# --- GM calculation (PDF p.11) ---
# GG' = Total FSM / Disp  (m)
# GM = KM - KG - GG'  (m)
# KG' = KG + GG'  (m)
GM_FORMULA_FSC = "GG' = Total FSM / Disp  [m]"
GM_FORMULA_GM = "GM = KM - KG - GG'  [m]"
GM_FORMULA_KG_PRIME = "KG' = KG + GG'  [m]"

# --- GZ from cross curves (PDF p.12) ---
# GZ = KN - KG * sin(θ)  [m]
GZ_FORMULA = "GZ = KN - KG * sin(θ)  [m]"

# --- Operating restrictions (PDF p.8) ---
OPERATING_RESTRICTIONS = (
    "Hydrostatics are for design trim; keep vessel close to designed trim.",
    "All watertight hatches/openings must remain watertight sealed.",
    "No tanks shall be filled exceeding the limits shown in loading conditions.",
    "Any condition violating the booklet loading conditions may endanger the vessel.",
)

# --- Symbols (PDF p.10) – for display/reports ---
SYMBOLS = {
    "Δ": "Displacement (MT)",
    "V": "Volume (m³)",
    "KB": "Vertical Centre of Buoyancy above baseline (m)",
    "LCB": "Longitudinal Centre of Buoyancy from amidship (m)",
    "LCG": "Longitudinal Centre of Gravity from amidship (m)",
    "KG": "Vertical Centre of Gravity above baseline (m)",
    "LCF": "Longitudinal Centre of Flotation from amidships (m)",
    "MCT": "Moment to Change Trim 1 m (tonne·m)",
    "GM": "Transverse Metacentric Height above KG (m)",
    "θ": "Angle of Heel (degrees)",
    "GZ": "Righting Lever (m)",
}
