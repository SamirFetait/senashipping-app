<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/PyQt6-6.6+-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt6"/>
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0+-D71F00?style=for-the-badge&logo=sqlalchemy" alt="SQLAlchemy"/>
</p>

---

# Sena Marine for Livestock Carriers

<div align="center">

**Maritime loading condition calculator for livestock carriers**

*Intact stability • IMO & livestock criteria • Tank & pen management • Export to PDF/Excel*

</div>

---

## Table of contents

- [📋 Overview](#-overview)
- [✨ Features](#-features)
- [🖼️ Screenshots](#-screenshots)
- [📁 Project structure](#-project-structure)
- [📦 Requirements](#-requirements)
- [🚀 Installation](#-installation)
- [▶️ Running the app](#-running-the-app)
- [⚙️ Configuration](#-configuration)
- [📖 Stability manual reference](#-stability-manual-reference)
- [📐 Hydrostatic curves & draft solver](#-hydrostatic-curves--draft-solver)
- [📘 Stability calculations (how everything is calculated)](#-stability-calculations-how-everything-is-calculated)
- [🧪 Testing](#-testing)
- [📄 License & credits](#-license--credits)

---

## 📋 Overview

**Sena Marine** is a desktop application for preparing and checking **loading conditions** on livestock carriers. It computes intact stability (draft, trim, GM, longitudinal strength), evaluates **IMO** and **livestock-specific criteria** (e.g. AMSA MO43), and lets you manage ships, tanks, livestock pens, and cargo types in one place.

- **Single-ship mode**: Configure your vessel once (Tools → Ship & data setup), then work with loading conditions and cargo types.
- **Criteria**: Minimum GM, trim/draft limits, livestock GM, roll period, freeboard; results shown as pass/fail with margins.
- **Data**: SQLite database; conditions can be saved/loaded from file and exported to **PDF** or **Excel**.

---

## ✨ Features

| Area | Description |
|------|-------------|
| **Loading condition** | Condition name (saved on Compute, used in PDF/Excel), cargo type, tank fill (%), livestock deck head counts (Livestock-DK1…DK8). Save Condition button saves to file (prompts for path if needed). |
| **Compute** | Draft solver: Displacement(draft) = total weight. Trim from LCG/LCB balance. Displacement, draft (aft/mid/fwd), trim, heel, GM (with free surface correction), longitudinal strength (BM %, SF %). Waterline on profile redraws from solved draft. |
| **Results** | Calculation status, alarms, Weights / Trim & Stability / Strength / Cargo tabs, IMO & livestock criteria checklist, traceability, text report. Cargo tab shows pen name and deck (not pen ID). |
| **Curves** | Dedicated page (F4) showing app-generated hydrostatic curves: displacement vs draft, KB, LCB, waterplane I_T/I_L. Built from ship dimensions; no import. |
| **Export** | PDF and Excel from the Results view (condition name from Compute). |
| **Ship & data** | Ship particulars, tanks (with categories), livestock pens per deck, cargo type library (mass per head, area per head, VCG from deck). |
| **Stability manual** | Operating restrictions and reference from the vessel Loading Manual (Program Notes + Results tab). |
| **Tools** | Ship & data setup; Hydrostatic Calculator (optional quick draft/trim from displacement). |

---

## 🖼️ Screenshots

*Main window: Loading Condition view (deck profile, results panel, condition table) and Results view (alarms, criteria, report).*

---

## 📁 Project structure

```
senashipping-app/
├── assets/
│   ├── stability.pdf                    # Vessel Loading Manual (reference; used for limits & UI)
│   └── MV OSAMA BEY- Ship's Particulars.pdf   # Ship documentation (particulars, capacities, etc.)
├── senashipping_app/
│   ├── main.py                # Entry point
│   ├── config/
│   │   ├── limits.py          # GM, trim, draft, livestock limits
│   │   ├── settings.py        # Logging, DB path
│   │   └── stability_manual_ref.py   # Manual-derived constants & operating restrictions
│   ├── models/                # Ship, Tank, LivestockPen, Voyage, LoadingCondition, CargoType
│   ├── repositories/         # SQLite/ORM access
│   ├── services/              # Stability, validation, criteria, alarms, hydrostatics, hydrostatic_curves, etc.
│   ├── reports/               # Text, PDF, Excel export
│   ├── views/                 # PyQt6 UI (main window, condition editor, results, curves view, ship manager, …)
│   └── tests/
├── senashipping_app_data/     # Default DB & log (created at runtime)
├── requirements.txt
└── README.md
```

---

## 📦 Requirements

- **Python** 3.10+
- **PyQt6** 6.6+
- **SQLAlchemy** 2.0+
- **matplotlib**, **pandas**, **openpyxl**, **reportlab**, **ezdxf** (reports, Excel, PDF, DXF)

---

## 🚀 Installation

1. **Clone or download** the project and open a terminal in the project root.

2. **Create a virtual environment** (recommended):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate    # Windows
   # source .venv/bin/activate   # macOS/Linux
   ```

3. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

---

## ▶️ Running the app

From the **project root** (so that `senashipping_app` is on the path):

```bash
python -m senashipping_app.main
```

Or:

```bash
python senashipping_app/main.py
```

- **First run**: The app creates the SQLite database and default data path (e.g. `senashipping_app_data/`). You can preload the *Osama Bay* ship/tanks/pens via the initializer if provided.
- **Navigation**: Toolbar: **Loading Condition** (F2), **Results** (F3), **Curves** (F4). Use **Tools → Ship & data setup** to add ships, tanks, and livestock pens.
- **Condition name**: Enter a name in the Loading Condition view (before cargo type); it is saved when you click **Compute Results** and used in PDF/Excel export.
- **Compute**: Set condition name, cargo type, and tank/livestock data, then click **Compute Results** (or **F9**). Draft and trim are solved from displacement and LCG/LCB; the profile waterline updates. Check the Results view for status and criteria.
- **Save Condition**: Saves the current condition to file (or opens Save As if no path). **Curves** page shows generated hydrostatic curves for the current ship.

---

## 📦 Building the executable (freeze)

To create a standalone executable (no Python required on the target machine):

```bash
pip install -r requirements.txt
pyinstaller senashipping_app.spec
```

The built executable **OsamaBayApp.exe** will appear in `dist/`. It bundles:

- **Database**: `senashipping_app_data/senashipping.db` (if present at build time) is copied to the user data folder on first run
- **CAD files**: All `cads/*.dxf` (profile, deck_A–H)
- **Assets**: `assets/` (KN tables, SOUNDING Excel files, icon, PDFs)

At runtime, user data (DB, logs) is stored next to the executable in `senashipping_app_data/`.

---

## ⚙️ Configuration

| Item | Location | Description |
|------|----------|-------------|
| **Database** | `config/settings.py` / `Settings.db_path` | SQLite file path (default under `senashipping_app_data/`). |
| **Limits** | `config/limits.py` | Min GM, livestock GM, max roll period, min freeboard, max trim/draft fractions, etc. |
| **Stability manual** | `config/stability_manual_ref.py` | Reference values and operating restrictions from the vessel Loading Manual. |

---

## 📖 Stability manual reference

The app uses data from the vessel **Loading Manual and Intact Stability Information** (e.g. `assets/stability.pdf`):

- **Limits and criteria** in `config/limits.py` and `services/criteria_rules.py` are aligned with the manual and IMO IS Code (A.749(18)) / AMSA MO43 livestock guidelines.
- **Operating restrictions** and document reference are shown in:
  - **File → Program Notes** (dialog)
  - **Results** tab → *Stability manual reference* section.

Tank list is not embedded in the app; refer to the PDF for tank identification.

---

## 📐 Hydrostatic curves & draft solver

The app **generates** hydrostatic curves in two ways (no need to import if you don’t want to):

1. **From ship dimensions (default)** — Formula-based curves from L, B, design draft (and block coefficient). Use *Use ship dimensions* on the Curves page to (re)generate.
2. **From a hull STL (Python library)** — Use **trimesh** (pure Python, no Rust) to generate curves from a 3D hull mesh. On the Curves page (F4), click *Generate from hull (STL)…* and select an STL file (units: metres). Requires: `pip install trimesh`. The app integrates waterplane areas over draft to get displacement, KB, LCB, and uses waterplane I_T, I_L at each draft.

You can also **import** curves from JSON (e.g. digitized from your stability PDF) via *Import curves from JSON…*.

- **Curves page (F4)** — **Dynamic like your stability PDF**: Query by **draft (m)** or **displacement (t)** to see the operating point and read off Draft, Displacement, KB, LCB, I_T, I_L, MTC. A red marker and reference lines show the selected condition on each plot.
- **Draft solver (Step 2)**: Solves **Displacement(draft) = total weight** using the displacement curve (or formula fallback) so the ship floats correctly.
- **Trim solver (Step 3)**: Longitudinal balance: trim from **LCG vs LCB** and MTC.
- **Waterline (Step 4)**: After Compute, the profile view redraws the waterline from the solved draft (aft, mid, fwd).

STL generation uses `trimesh` (in `requirements.txt`). If NavalToolbox is installed, it is tried first; if it fails (e.g. Rust not available), the app falls back to trimesh.

---

## 📘 Stability calculations (how everything is calculated)

A separate document **[STABILITY_CALCULATIONS.md](STABILITY_CALCULATIONS.md)** describes in detail how every value is computed: mass and centers of gravity (tanks + livestock), displacement, draft solver, trim (LCG/LCB/MTC), KB, BM, KM, GM, free surface correction, draft at marks, heel, longitudinal strength, ancillary (prop immersion, visibility, air draft), validation rules, and IMO/livestock criteria. Use it to understand the numbers on the Results panel and the meaning of Calculation Status (OK / WARNING / FAILED).

---

## 🧪 Testing

From the project root:

```bash
pytest senashipping_app/tests -v
```

Covers models, services (stability, validation, criteria, ancillary), repositories, and livestock pen integration.

---

## 📄 License & credits

- **Sena Marine** / Sena Shipping for Livestock Carriers.
- Stability criteria and formulas follow **IMO Resolution A.749(18)** (IS Code) and **AMSA MO43** (livestock).
- Loading Manual reference: *OSAMA BEY*, Infinity Marine Consultants (example vessel).

---

<div align="center">

**Sena Marine for Livestock Carriers** — *loading conditions and intact stability, made simple.*

</div>
