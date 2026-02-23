# Stability Calculations — How Everything Is Calculated

This document explains how the Sena Marine app computes loading conditions: displacement, draft, trim, stability (GM), longitudinal strength, and the criteria used for pass/fail. It is intended for users who want to understand the numbers on the Results panel and for anyone reviewing or extending the calculation logic.

**References:** The formulas and limits follow the vessel **Loading Manual** (e.g. `assets/stability.pdf`) and **IMO IS Code A.749(18)** (intact stability). Livestock-specific rules follow **AMSA MO43** / IMO livestock guidelines. Numeric limits are in `senashipping_app/config/limits.py`; symbol and formula references are in `senashipping_app/config/stability_manual_ref.py`.

---

## Table of contents

1. [Calculation flow (big picture)](#1-calculation-flow-big-picture)
2. [Inputs: ship, tanks, condition, livestock](#2-inputs-ship-tanks-condition-livestock)
3. [Mass and centers of gravity](#3-mass-and-centers-of-gravity)
4. [Displacement](#4-displacement)
5. [Hydrostatic curves (draft ↔ displacement)](#5-hydrostatic-curves-draft--displacement)
6. [Draft solver: finding mean draft](#6-draft-solver-finding-mean-draft)
7. [Trim: LCG vs LCB and MTC](#7-trim-lcg-vs-lcb-and-mtc)
8. [Stability: KB, BM, KM, GM](#8-stability-kb-bm-km-gm)
9. [Draft at marks (aft / mid / fwd)](#9-draft-at-marks-aft--mid--fwd)
10. [Heel from TCG](#10-heel-from-tcg)
11. [Free surface correction (effective GM)](#11-free-surface-correction-effective-gm)
12. [Longitudinal strength (simplified)](#12-longitudinal-strength-simplified)
13. [Ancillary: prop immersion, visibility, air draft](#13-ancillary-prop-immersion-visibility-air-draft)
14. [Validation: what triggers FAILED / WARNING](#14-validation-what-triggers-failed--warning)
15. [Criteria: IMO and livestock](#15-criteria-imo-and-livestock)
16. [Symbols and units](#16-symbols-and-units)

---

## 1. Calculation flow (big picture)

When you press **Compute**, the app:

1. **Sums all weights** from tank fill volumes (× cargo density) and livestock pen head counts (× mass per head) → **total mass = displacement** (in seawater).
2. **Finds mean draft** so that the buoyancy (displacement at that draft) equals that total weight — **Draft solver: Displacement(draft) = total weight**.
3. **Computes trim** from the longitudinal balance: LCG vs LCB, using **Moment to Change Trim (MTC)** so that trim (m) is consistent with the loading.
4. **Computes stability:** KG from weight moments, KB and BM from hydrostatics, then **GM = KM − KG** (with optional free surface correction).
5. **Draft at marks:** Aft and forward drafts from mean draft ± half trim; mid is mean draft.
6. **Heel** from transverse center of gravity (TCG).
7. **Longitudinal strength:** Simplified still-water bending moment and shear, and their percentage of “design” limits.
8. **Ancillary:** Propeller immersion %, visibility (bridge to bow waterline), air draft.
9. **Validation:** Checks GM, trim, draft, BM against limits → sets **Calculation Status** (OK / WARNING / FAILED).
10. **Criteria:** IMO (min GM, trim limit, draft limit) and livestock (GM, roll period, freeboard) plus ancillary (prop, visibility, air draft) → Alarms and Criteria tabs.

So **“FAILED”** means one or more of these **limits or criteria are not met**; the numbers (draft, GM, etc.) are still the result of a successful **calculation**.

---

## 2. Inputs: ship, tanks, condition, livestock

- **Ship:** Length overall (LOA), breadth, depth, design draft. Used for hydrostatics, limits, and ancillary formulas.
- **Tanks:** For each tank: capacity (m³), longitudinal position (0–1 from AP), KG (m), TCG (m). Fill is given as **volume (m³)** per tank in the condition.
- **Condition:** Tank volumes (m³) and, for livestock, **pen loadings** (number of heads per pen).
- **Cargo type (optional):** Density for tanks (t/m³), and for livestock: mass per head (kg → t), VCG above deck (m).
- **Sea water:** Density **ρ = 1.025 t/m³** (from Loading Manual).

---

## 3. Mass and centers of gravity

**Tanks**

- Mass per tank: **mass = volume × cargo_density** (t).
- Vertical moment: **mass × tank.KG**.
- Longitudinal moment: **mass × tank.longitudinal_pos × L** (position 0–1 × LOA).
- Transverse moment: **mass × tank.TCG**.

If a **tank CoG override** is provided (e.g. from soundings), the app uses the given (VCG, LCG, TCG) for that tank instead of the tank’s default KG and longitudinal position.

**Livestock pens**

- Mass per pen: **heads × mass_per_head** (t).
- VCG = **pen.VCG + vcg_from_deck** (deck height + CoG above deck from cargo type).
- Moments: **mass × (VCG, pen.LCG, pen.TCG)**.

**Totals**

- **Total mass** = sum of all tank masses + all pen masses = **displacement** (t).
- **LCG (normalized 0–1)** = total longitudinal moment ÷ (total mass × L).
- **KG (m)** = total vertical moment ÷ total mass.
- **TCG (m)** = total transverse moment ÷ total mass.

These are used for trim (LCG), stability (KG), and heel (TCG).

---

## 4. Displacement

**Displacement Δ (t)** = total mass of all tanks + all livestock in the condition.

The ship is assumed in **salt water (ρ = 1.025 t/m³)**. Underwater volume (m³) = Δ / ρ; the **draft solver** finds the mean draft at which the hydrostatic displacement equals Δ.

---

## 5. Hydrostatic curves (draft ↔ displacement)

The app can use:

- **Formula-based curves (Path B):** Built from ship dimensions (L, B, design draft) and a block coefficient **Cb ≈ 0.78**.
- **Curves from tables (if loaded):** Draft vs displacement, KB, LCB, waterplane inertias I_T, I_L.

**Formula-based generation** (`hydrostatic_curves.build_curves_from_formulas`):

- For a range of drafts, **displacement** at each draft: **Δ = L × B × T × Cb × ρ**.
- **KB:** Typical ship form **KB/T ≈ 0.535 − 0.055×Cb** → **KB = (KB/T) × draft**.
- **LCB:** Taken **0.5** (amidships) for the simplified form.
- **Waterplane inertias** (rectangular waterplane):  
  **I_T = L×B³/12**, **I_L = B×L³/12** (same at all drafts in this simplified model).

These curves are used to get **draft from displacement** and **KB, I_T, I_L** at that draft for trim and GM.

---

## 6. Draft solver: finding mean draft

**Goal:** Find mean draft **T** such that **Displacement(T) = total weight (Δ)**.

- **With hydrostatic curves:** Draft is found by **inverse interpolation** on the curve **draft ↔ displacement** so that displacement at that draft equals Δ.
- **Without curves:** **Box approximation**  
  **Δ = L × B × T × Cb × ρ**  
  ⇒ **T = Δ / (L × B × Cb × ρ)**.

Result: **mean draft** (m) at the LCF (simplified as amidships). Aft and forward drafts come from this mean draft and trim (below).

---

## 7. Trim: LCG vs LCB and MTC

Trim (m) is **positive = stern down**. It is found from longitudinal equilibrium: **LCG** vs **LCB**.

**Loading Manual formula:**  
**t = Δ × (LCB − LCG) / MTC** (with sign convention so that trim direction matches LCG/LCB).

- **LCG** (m from AP) = **LCG_norm × L** (from weight moments).
- **LCB** (m from AP) = from curves at current draft, or **0.5×L** if not available.
- **Moment to Change Trim 1 m (MTC)** in tonne·m/m:  
  **BM_L = I_L / V**, **MTC = Δ × BM_L / (L × 100)** (with appropriate factor for 1 m trim).  
  **I_L** = longitudinal waterplane inertia (from curves or **B×L³/12**), **V** = Δ/ρ.

Then: **trim_m = (LCG_m − LCB_m) × Δ / MTC** (with correct sign so stern goes down when LCG is aft of LCB).

So: **trim** is fully determined by **displacement**, **LCG**, **LCB**, and **MTC** at the solved draft.

---

## 8. Stability: KB, BM, KM, GM

**KB (m)** — center of buoyancy above baseline:

- From curves at the solved draft, or  
- **KB ≈ 0.53 × draft** (typical ship form).

**BM_T (m)** — transverse metacentric radius:

- **BM_T = I_T / V**, with **I_T** = transverse waterplane inertia (from curves or **L×B³/12**), **V** = Δ/ρ.

**KM (m)** — transverse metacentric height above keel:

- **KM = KB + BM_T**.

**KG (m)** — center of gravity above baseline:

- **KG = total vertical moment / total mass** (tanks + pens).

**GM (m)** — transverse metacentric height (intact stability):

- **GM = KM − KG**  
  (clamped to ≥ 0 for display).

**Effective GM (after free surface):**  
**GM_eff = GM − FSC**, where **FSC** is the free surface correction (see below). Validation and criteria use **GM_eff**.

---

## 9. Draft at marks (aft / mid / fwd)

With **trim** positive = stern down:

- **Draft at AP (aft):** **draft_aft = mean_draft + trim/2**
- **Draft at FP (fwd):** **draft_fwd = mean_draft − trim/2**
- **Draft mid:** **mean_draft** (or average of aft and fwd).

The app shows **Draft at Marks - Aft / Mid / Fwd** in the results panel.

---

## 10. Heel from TCG

A simple equilibrium heel from transverse shift of center of gravity:

- **heel_deg = atan(TCG / GM)** (in degrees),  
  with **TCG** = total transverse moment / total mass.

If **GM** is zero or negative, heel is set to 0. This is an approximate steady heel from TCG; no full GZ curve is used here.

---

## 11. Free surface correction (effective GM)

**Slack tanks** (partially filled) reduce effective stability. The app applies a **free surface correction (FSC)** in metres:

- For each tank with fill ratio between about **5% and 95%**, a correction term is added based on tank mass, displacement, and a **free surface factor** (see `config/limits.py`: `FREE_SURFACE_FACTOR`).
- **GM_effective = GM − FSC** (not below zero).

**Loading Manual:**  
**GG' = Total FSM / Δ**, **GM = KM − KG − GG'**.  
The app’s FSC is a simplified implementation of this idea. Validation and criteria use **GM_effective** when checking minimum GM.

---

## 12. Longitudinal strength (simplified)

The app uses a **simplified** still-water model:

- **LCG** from weight distribution (tanks + pens).
- **Eccentricity** from amidships: **ecc = |LCG_norm − 0.5|**.
- **Still-water BM** approximated as **≈ Δ × L × ecc × 0.25** (simplified).
- **Shear:** **max shear ≈ Δ × 0.1 × ecc × 2** (simplified).
- **Design limits:** Placeholder **design_BM = Δ × L × 0.12**, **design_SF = Δ × 0.15**.
- **Max BM % Allow** = **|SWBM| / design_BM × 100**; **Max Shear % Allow** = **max shear / design_SF × 100**.

These are indicative. For class or approval, use the vessel’s approved loading manual or dedicated strength software.

---

## 13. Ancillary: prop immersion, visibility, air draft

**Propeller immersion (%)**

- Prop center height above baseline (default **~5% of depth**), prop diameter (default **~3% of LOA**).
- **Immersion = max(0, draft_aft − prop_center_height)**.
- **% = min(100, 100 × immersion / prop_diameter)**.

**Visibility (m)**

- Bridge position (default **~85% L from AP**) and height (default **≈ depth**).
- Approximate distance from bridge to water at bow (sight line / trim geometry); positive means water visible ahead.

**Air draft (m)**

- **Air draft = mast_height − mean_draft** (clearance above waterline to highest point). Mast height default **≈ 1.8 × depth**.

**GZ criteria (simplified)**

- Pass if **GM ≥ 0.15 m** and **|heel| < 5°**. Full GZ curve (area 0–30°, 30–40°, etc.) is not computed.

---

## 14. Validation: what triggers FAILED / WARNING

**Validation** runs after the condition is calculated and sets **Calculation Status** and Alarms:

- **ERROR (status FAILED):**
  - **GM_effective < MIN_GM_M** (0.15 m).
  - **|trim| > L × MAX_TRIM_FRACTION** (e.g. 2% LOA).
  - **draft > design_draft × MAX_DRAFT_FRACTION** (e.g. 105% design draft).
- **WARNING:**
  - GM marginal (e.g. below 1.5 × MIN_GM_M).
  - Still-water BM over a fraction of “design” BM.
  - Zero displacement.
  - Volume given for unknown tank ID.

So **“FAILED”** = one or more **validation errors** (limits exceeded); the underlying hydrostatic and stability **numbers are still calculated** and shown.

---

## 15. Criteria: IMO and livestock

**IMO (intact stability)**

- **Minimum GM:** GM_effective ≥ **0.15 m** (IS Code).
- **Trim limit:** |trim| ≤ **L × 2%** (configurable).
- **Draft limit:** draft ≤ **design_draft × 105%** (configurable).

**Livestock (AMSA MO43 / IMO livestock)**

- **Minimum GM (stricter):** GM_effective ≥ **0.20 m**.
- **Roll period:** **T = 2π × K × B / √(g × GM)** (K ≈ 0.45); must be ≤ **MAX_ROLL_PERIOD_S** (e.g. 15 s) for animal welfare.
- **Freeboard:** **freeboard = depth − draft − 0.5×|trim|** ≥ **MIN_FREEBORD_M** (e.g. 0.3 m).

**Ancillary**

- GZ status (simplified GM/heel pass).
- **Prop immersion** ≥ e.g. **60%**.
- **Visibility** ≥ e.g. **1.0 m**.
- **Air draft** ≥ e.g. **5.0 m**.

All limits are in **`senashipping_app/config/limits.py`**. Results appear in the **Criteria** tab with pass/fail and margin per line.

---

## 16. Symbols and units

| Symbol | Meaning | Unit |
|--------|----------|------|
| Δ | Displacement | t (tonnes) |
| L | Length overall | m |
| B | Breadth | m |
| T, draft | Draft (mean) | m |
| KB | Center of buoyancy above baseline | m |
| LCB | Longitudinal center of buoyancy | m or 0–1 |
| LCG | Longitudinal center of gravity | m or 0–1 |
| KG | Vertical center of gravity above baseline | m |
| KM | Transverse metacentric height above keel | m |
| GM | Transverse metacentric height above KG | m |
| MTC | Moment to change trim 1 m | tonne·m/m |
| ρ | Sea water density | 1.025 t/m³ |
| Cb | Block coefficient | — |
| GZ | Righting lever | m |
| θ | Angle of heel | deg |

---

**Summary:** The app solves **Displacement(draft) = total weight**, then **trim** from LCG/LCB/MTC, then **GM = KM − KG** (with optional FSC), and finally validates and evaluates criteria. So you see both the **calculated results** (draft, trim, GM, etc.) and a **status** (OK / WARNING / FAILED) that reflects whether the condition **meets the configured limits and criteria**, not whether the math failed.
