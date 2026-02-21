---
name: CG Tanks 3D Results Flow
overview: Your intended workflow is correct. The app already makes ship CG depend on tank weights; 3D drawings support both visual display (ship/deck STLs) and tank geometry (import tank STLs for volume and CoG); then calculation populates the results page.
todos:
  - id: todo-1771711456857-i4bg6kwub
    content: ""
    status: pending
isProject: false
---

# CG, 3D Drawings, and Results Workflow

Your sequence is **right**. Here is how it maps to the app and what to do next.

## 1. CG depending on weight in tanks

**Already implemented.** The ship’s center of gravity (KG, LCG, TCG) is computed from tank (and pen) weights:

- In [senashipping_app/services/stability_service.py](senashipping_app/services/stability_service.py), `compute_condition`:
  - For each tank: **mass = volume × density** (volume comes from the condition’s tank fill %).
  - Moments use each tank’s position: **VCG** = `tank.kg_m`, **LCG** = `tank.longitudinal_pos`, **TCG** = `tank.tcg_m`.
  - **KG** = total VCG moment ÷ total mass (and similarly for LCG/TCG and trim/heel).

So CG **already** depends on weight in the tanks. To make CG reflect the real ship, ensure tank **positions** (VCG, LCG, TCG) are correct—either from Ship Manager or from 3D (see below).

### Do you need sounding tables?

**No, not for the current implementation.** The app does not use sounding tables. It works with:

- **Volume**: From tank **capacity** (m³) and **fill %** you enter in the condition: `volume = capacity × (fill% / 100)`.
- **CoG per tank**: A single VCG, LCG, TCG per tank (from Ship Manager or from “Import tanks from STL”), used for all fill levels.

So CG-from-weights works without any sounding tables.

**When sounding tables would be useful (optional later):**

1. **Input**: If you want to enter **sounding** (measured liquid depth) instead of fill %, you need **sounding → volume** tables (tank calibration tables) to convert sounding to volume.
2. **Accuracy for partial fills**: For partially filled tanks, the liquid’s VCG (and sometimes LCG/TCG) changes with fill level. The app currently uses one fixed CoG per tank. For more accuracy you could add **sounding/volume → VCG** (and LCG/TCG) tables per tank so that CG reflects the actual liquid surface.

Summary: **You do not need sounding tables** for “CG depending on weight in tanks” as it works today; they would only be needed for a sounding-based input workflow or for fill-level-dependent tank CoG.

## 2. Entering 3D drawings for the ship

There are **two** uses of 3D in the app:


| Purpose                          | Where / How                                                                                                                                          | What it affects                                                                                                                                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ship and deck display**        | Put STL files in `senashipping_app/cads/`: `ship.stl` (or `hull.stl` / `profile.stl`) for the top profile; `deck_A.stl` … `deck_H.stl` for deck tabs | Visual only: 3D view in Condition Editor shows your hull and decks (see [NextMove.txt](NextMove.txt) and [senashipping_app/views/deck_profile_widget.py](senashipping_app/views/deck_profile_widget.py)).        |
| **Tank geometry (volume + CoG)** | Use **Tools → Import tanks from STL** to load tank STL(s)                                                                                            | Creates/updates tank objects with **volume** and **LCG, VCG, TCG** from the mesh. These values are then used in the stability calculation, so CG **does** depend on this 3D data when you import tanks from STL. |


So “enter 3D drawings” can mean:

- Add STLs in `cads/` for **visual** ship/deck 3D, and/or
- **Import tanks from STL** so tank **weights and CoG** (and thus ship CG) come from 3D.

## 3. Calculate and see data on the Results page

Flow in the app:

1. **Condition Editor**: Select ship, condition; set **tank fill %** (and pen loadings if used).
2. **Calculate**: Run calculation (e.g. “Calculate” / F5). This calls [ConditionService.compute](senashipping_app/services/condition_service.py), which uses `compute_condition()` and then validation/criteria/traceability.
3. **Results**:
  - **Results panel** (right side of Condition Editor) updates immediately with displacement, drafts, trim, GM, KG, etc.
  - **Results page** (main “Results” tab) is updated via `condition_computed` and shows the same results in detail (alarms, criteria, export PDF/Excel).

So: **Calculate → data on Results page** is correct and already wired.

## Recommended order of work

1. **Ship, decks, tanks** (already entered).
2. **Optional but recommended**:
  - Put **ship/profile** and **deck** STLs in `senashipping_app/cads/` for 3D display.
  - Use **Import tanks from STL** so tank volume and LCG/VCG/TCG come from 3D (then CG will depend on both weight and 3D geometry).
3. In **Condition Editor**, set tank fill levels (and pens if needed), then **Calculate**.
4. Check **Results** tab (and right-hand results panel) for displacement, draft, trim, KG, GM, alarms, criteria.

## Summary

- **CG from tank weights**: Already in place; tank fill (volume × density) and tank VCG/LCG/TCG drive KG and trim/heel.
- **3D drawings**: Two roles—(1) ship/deck STLs in `cads/` for display, (2) “Import tanks from STL” for tank volume and CoG used in calculation.
- **Calculate → Results page**: Correct flow; calculation runs from Condition Editor and populates both the side panel and the main Results page.

No code changes are required for this workflow; the app already supports it. If you want to extend it (e.g. hydrostatic tables, GZ curves, or a dedicated “CG from tanks” UI), that can be planned as a next step.
