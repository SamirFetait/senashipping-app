## senashipping – User Guide

This document explains **how to install, start, and use** the senashipping desktop app for **loading condition and stability checks on livestock carriers**.


## 1. Main window layout

The main window contains:

- **Menu bar**: traditional menus (`File`, `Edit`, `View`, `Tools`, `Damage`, `Grounding`, `Historian`, `Help`).
- **Toolbar**: quick actions (`New`, `Open`, `Save`, `Print/Export`, `Loading Condition`, `Results`, `Curves`, `Compute`, `Zoom` controls).
- **Navigation pages** (central area):
  - **Ship & data setup** – configure ship particulars, tanks, and livestock pens.
  - **Voyage planner** – define voyages and assign loading conditions.
  - **Loading Condition** – main editor for tanks, pens, and cargo distribution.
  - **Results** – calculated drafts, GM, strength, criteria and alarms.
  - **Curves** – stability curves (GZ curve) for the current condition.
- **Status bar**: messages, alarms and general status at the bottom; small **Alarms** button and online indicator at the top-right.

The app **opens directly on the “Loading Condition” page**, since this is used most frequently in day-to-day work.

---

## 2. Typical workflow

### 2.1 One-time setup – Ship & data

- **Open** `Tools → Ship & data setup...`
- Define or review:
  - **Ship particulars** (length, displacement data, etc.).
  - **Tanks** and their capacities, positions and decks.
  - **Livestock pens** (capacity, deck, LCG/VCG, etc.).
- Save and close the setup view. This configuration is then used by the Loading Condition and Results views.

### 2.2 Create or open a loading condition

- To **create a new condition**:
  - Use `File → New Loading condition...` or the **New** button on the toolbar.
  - Optionally save the current condition if prompted.
  - A blank condition is created in the **Loading Condition** view.

- To **open an existing condition file**:
  - Use `File → Open Loading condition...` or the **Open** toolbar button.
  - Choose a `.senashipping` or `.json` file.
  - The condition is loaded into the editor; tank fills and pen head counts are restored.

- To **save the current condition**:
  - Use `File → Save Loading condition...` or `File → Save Loading condition As...`, or the **Save** toolbar button.
  - Files are normally saved with a `.senashipping` extension.

### 2.3 Editing the Loading Condition

In the **Loading Condition** page you can:

- **Adjust tank fills**
  - Enter or edit **fill percentages** or volumes for each tank.
  - Use commands like **Empty space(s)**, **Fill space(s)**, or **Fill spaces To...** from the `Edit` menu to bulk-edit selected tanks.

- **Adjust livestock pens**
  - Set **head counts** per pen (by deck and pen name).
  - The app converts head counts to tonnage automatically using the configured **mass per head**.

- **Use the condition table**
  - The bottom **condition table** gives a combined view of tanks and livestock on each deck.
  - You can edit volumes / weights here; this table is treated as the **source of truth** when saving the condition.

- **Layout controls**
  - `View → Default view model` restores the standard layout.
  - `View → Change layout` toggles visibility of the bottom condition table (more space for graphics vs. full editor).
  - **Zoom In / Zoom Out / Fit View** toolbar buttons affect the ship profile / deck drawings.

### 2.4 Computing results

- Use **Tools → Update Calculations** or the **Compute** toolbar button (shortcut **F9**).
- The app:
  - Computes drafts, trim, heel, GM, KG, KM, displacement.
  - Calculates approximate **strength** (still water bending moment and shear).
  - Applies **IMO / livestock / ancillary criteria** and builds a checklist.
  - Generates a detailed **text report**.
- After a successful compute:
  - The app automatically navigates to **Results** (or back to **Curves** if you started there).

---

## 3. Results view

Open via:

- `View → Results` or the **Results** toolbar button.

The **Results** view shows:

- **Calculation Summary** (right side)
  - Ship and condition names.
  - Displacement, drafts (mid, aft, fwd), trim, heel.
  - GM, KG, KM.
  - Still-water BM and strength utilisation percentages (where design limits exist).

- **Tabs (left side)**
  - **Alarms** – table of pass / fail / warning messages for criteria, with thresholds and attained values.
  - **Weights** – breakdown of total displacement into:
    - Total displacement.
    - Livestock (from pen head counts).
    - Tanks & other.
  - **Trim & Stability** – key hydrostatic parameters (drafts, trim, heel, GM, KG, KM).
  - **Strength** – still water BM, shear forces and percentage of allowable where applicable.
  - **Cargo** – livestock per pen (name, deck, head count, weight per pen and totals).

- **Validation messages**
  - A coloured status label summarises whether the condition **passes**, **fails** or has **warnings**.
  - A list of messages explains issues or checks to review.

- **Criteria checklist**
  - Table of IMO and livestock criteria:
    - Rule set, code, name, result, value, limit, margin.

- **Calculation traceability**
  - Text summarising timestamp, ship, condition and criteria summary.

- **Stability manual reference**
  - A short embedded extract from the loading manual and **operating restrictions** for the vessel.

- **Text report**
  - Scrollable report generated from the `reports` module, suitable for copying into emails or documents.

---

## 4. Curves view

Open via:

- `View → Curves` or the **Curves** toolbar button.

The **Curves** page shows an approximate **GZ (righting lever) curve** for the current condition:

- Based on the computed **GM** and validation results.
- The curve is also used in the **PDF report**.
- Re-run **Compute (F9)** anytime you change the condition to refresh the curve.

---

## 5. Exporting reports

### 5.1 Export from the Results view

At the bottom of the **Results** view:

- **Export PDF**
  - Click **Export PDF**, choose a `.pdf` file name.
  - The app calls `export_condition_to_pdf` and generates a formatted **Loading Condition Report**, including:
    - Condition summary and equilibrium data.
    - Weight items and free-surface summary (when available).
    - IMO / livestock criteria table (when available).
    - An approximate **GZ curve** plot.

- **Export Excel**
  - Click **Export Excel**, choose a `.xlsx` file name.
  - The app calls `export_condition_to_excel` and writes a structured Excel workbook for further analysis or record-keeping.

> You must **compute a condition first** before exporting; otherwise you will be prompted to run a calculation.

### 5.2 Export from the toolbar

- Use the **Print/Export** toolbar button or `File → Print/Export...`.
- When on the **Results** view this opens a small menu letting you pick **Export to PDF** or **Export to Excel**.

---

## 6. Advanced / specialist tools

Some menu items are present for future expansion or specialist workflows:

- **Cargo Library** (`Tools → Cargo Library...`)
  - Opens a dialog to manage **cargo types** used for loading conditions.
  - After closing, cargo types are refreshed in the Loading Condition view.

- **Import tanks from STL** (`Tools → Import tanks from STL...`)
  - Converts 3D **STL meshes** into tanks with calculated **volume and LCG/VCG/TCG**.
  - Requires the `trimesh` library (see `requirements.txt`).

- **Hydrostatic Calculator...**
  - Currently shows an informational placeholder; full calculator is not yet implemented.

- **Damage / Grounding / Historian**
  - Menu items are mostly placeholders in this build, indicating future features (damage stability, grounding cases, historical snapshots and export).

Where an item is not fully implemented, the app shows a **non-crashing informational message** instead of failing silently.

---

## 7. Tips and best practices

- **Always save before major edits**
  - Use `Ctrl+S` frequently to write the current condition to a `.senashipping` file.

- **One ship, many conditions**
  - Treat `Ship & data setup` as a **one-time configuration**.
  - Create many **Loading Conditions** for different cargo patterns and voyages.

- **Use Results and Curves together**
  - After editing a condition:
    - Run **Compute (F9)**.
    - Review **Results** (criteria, alarms and text report).
    - Switch to **Curves** to see how the GZ curve behaves.

- **Check operating restrictions**
  - Always review the **Stability manual reference** block and ensure conditions respect the listed operating restrictions for the vessel.

If you need to customise or extend the app, see the Python modules under `senashipping_app` for services, views, and report generation.

