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
| **Loading condition** | Cargo type, tank fill (%), livestock deck head counts (Livestock-DK1…DK8). |
| **Compute** | Displacement, draft (aft/mid/fwd), trim, heel, GM (with free surface correction), longitudinal strength (BM %, SF %). |
| **Results** | Calculation status, alarms table, IMO & livestock criteria checklist, traceability, text report. |
| **Export** | PDF and Excel from the Results view. |
| **Ship & data** | Ship particulars, tanks (with categories), livestock pens per deck, cargo type library (mass per head, area per head, VCG from deck). |
| **Stability manual** | Operating restrictions and reference from the vessel Loading Manual (Program Notes + Results tab). |

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
│   ├── services/              # Stability, validation, criteria, alarms, hydrostatics, etc.
│   ├── reports/               # Text, PDF, Excel export
│   ├── views/                 # PyQt6 UI (main window, condition editor, results, ship manager, …)
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
- **Navigation**: Use the top bar to switch between **Loading Condition** and **Results**. Use **Tools → Ship & data setup** to add ships, tanks, and livestock pens.
- **Compute**: In the Loading Condition view, set cargo type and tank/livestock data, then click **Compute Results** (or **F9**). Check the Results tab for status and criteria.

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
