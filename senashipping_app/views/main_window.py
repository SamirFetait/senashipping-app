"""
Qt main window for the senashipping desktop app.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict

from PyQt6.QtGui import QIcon, QDesktopServices
from PyQt6.QtCore import Qt, QSize, QUrl
from PyQt6.QtGui import QAction, QIcon, QActionGroup, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
    QToolBar,
    QLabel,
    QStatusBar,
    QFrame,
    QStyle,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
    QDialog,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
    QScrollArea,
    QGridLayout,
    QAbstractItemView,
)

from typing import Dict

from senashipping_app.config.settings import Settings
from senashipping_app.config.stability_manual_ref import (
    MANUAL_VESSEL_NAME,
    MANUAL_IMO,
    MANUAL_REF,
    MANUAL_SOURCE,
    OPERATING_RESTRICTIONS,
)
from senashipping_app.services.file_service import save_condition_to_file, load_condition_from_file
from senashipping_app.reports import export_condition_to_excel, export_condition_to_pdf
from senashipping_app.repositories import database
from senashipping_app.views.ship_manager_view import ShipManagerView
from senashipping_app.views.voyage_planner_view import VoyagePlannerView
from senashipping_app.views.condition_editor_view import ConditionEditorView
from senashipping_app.views.results_view import ResultsView
from senashipping_app.views.cargo_library_dialog import CargoLibraryDialog
from senashipping_app.views.curves_view import CurvesView
from senashipping_app.services import historian_service


@dataclass
class _PageIndexes:
    ship_manager: int
    voyage_planner: int
    condition_editor: int
    results: int
    curves: int


class MainWindow(QMainWindow):
    """Main application window with navigation and central stacked views."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Sena Shipping for Livestock Carriers")
        self.setMinimumSize(1200, 800)
        self.showMaximized()
        icon_path = self._settings.project_root / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._stack = QStackedWidget(self)
        self.setCentralWidget(self._stack)

        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)

        # Track navigation actions for checked state
        self._nav_actions: dict[int, QAction] = {}

        # Track current file path for save
        self._current_file_path: Path | None = None

        self._page_indexes = self._create_pages()
        self._create_menu()
        self._create_toolbar()
        self._create_status_panel()

        # Single-ship app: open on Loading Condition; Ship/Voyage are setup-only
        self._switch_page(self._page_indexes.condition_editor, "Loading Condition")
        self._status_bar.showMessage("Ready")

    def _create_pages(self) -> _PageIndexes:
        """Create core application pages and add them to the stacked widget."""
        # Keep references to views to allow signal wiring between them
        self._ship_manager = ShipManagerView(self)
        self._voyage_planner = VoyagePlannerView(self)
        self._condition_editor = ConditionEditorView(self)
        self._results_view = ResultsView(self)
        self._curves_view = CurvesView(self)  # GZ curve from KN table (matplotlib)

        ship_idx = self._stack.addWidget(self._ship_manager)
        voy_idx = self._stack.addWidget(self._voyage_planner)
        cond_idx = self._stack.addWidget(self._condition_editor)
        res_idx = self._stack.addWidget(self._results_view)
        curves_idx = self._stack.addWidget(self._curves_view)

        # Default page
        self._stack.setCurrentIndex(cond_idx)

        pages = _PageIndexes(
            ship_manager=ship_idx,
            voyage_planner=voy_idx,
            condition_editor=cond_idx,
            results=res_idx,
            curves=curves_idx,
        )

        # Wire condition editor to results and curves views
        self._condition_editor.condition_computed.connect(
            self._results_view.update_results
        )
        self._condition_editor.condition_computed.connect(
            self._curves_view.update_curve
        )
        # Save Condition button (no voyage): trigger File → Save / Save As
        self._condition_editor.save_condition_requested.connect(self._on_save)

        # Wire voyage planner: when user clicks Edit Condition, switch to editor and load it
        self._voyage_planner.condition_selected.connect(
            self._on_condition_selected_from_voyage
        )

        # TODO: Add button to add tank or pen
        # Wire condition table '+' button: switch to Ship & data setup to add tanks/pens
        # self._condition_editor._condition_table.add_requested.connect(
        #     lambda: self._switch_page(self._page_indexes.ship_manager, "Ship & data setup – add tanks and pens")
        # ) # 

        return pages

    def _on_condition_selected_from_voyage(self, voyage_id: int, condition_id: int) -> None:
        self._condition_editor.load_condition(voyage_id, condition_id)
        self._stack.setCurrentIndex(self._page_indexes.condition_editor)
        self._status_bar.showMessage("Loading Condition")

    def _create_menu(self) -> None:
        """Create the menu bar and actions."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        edit_menu = menu_bar.addMenu("&Edit")
        view_menu = menu_bar.addMenu("&View")
        tools_menu = menu_bar.addMenu("&Tools")
        damage_menu = menu_bar.addMenu("&Damage")
        grounding_menu = menu_bar.addMenu("&Grounding")
        historian_menu = menu_bar.addMenu("&Historian")
        help_menu = menu_bar.addMenu("&Help")

        # File actions
        new_action = QAction("&New Loading condition ...", self)
        new_action.triggered.connect(self._on_new_condition)
        file_menu.addAction(new_action)
        new_action.setShortcut("Ctrl+N")

        open_action = QAction("&Open Loading condition ...", self)
        open_action.triggered.connect(self._on_open_condition)
        file_menu.addAction(open_action)
        open_action.setShortcut("Ctrl+O")

        file_menu.addSeparator()

        save_action = QAction("&Save Loading condition ...", self)
        save_action.triggered.connect(self._on_save)
        file_menu.addAction(save_action)
        save_action.setShortcut("Ctrl+S")

        save_as_action = QAction("&Save Loading condition As ...", self)
        save_as_action.triggered.connect(self._on_save_as)
        save_as_action.setShortcut("Ctrl+Shift+S")
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        import_action = QAction("&Import from Excel ...", self)
        import_action.triggered.connect(self._on_import_excel)
        file_menu.addAction(import_action)

        export_action = QAction("&Export to Excel ...", self)
        export_action.triggered.connect(self._on_export_excel)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        summary_action = QAction("&Summary Info ...", self)
        summary_action.triggered.connect(self._on_summary_info)
        file_menu.addAction(summary_action)

        program_notes_action = QAction("&Program Notes ...", self)
        program_notes_action.triggered.connect(self._on_program_notes)
        file_menu.addAction(program_notes_action)

        send_loading_condition_by_email_action = QAction("&Send Loading condition by email ...", self)
        send_loading_condition_by_email_action.triggered.connect(self._on_send_loading_condition_by_email)
        file_menu.addAction(send_loading_condition_by_email_action)

        file_menu.addSeparator()

        print_action = QAction("&Print/Export ...", self)
        print_action.triggered.connect(self._on_print_export)
        file_menu.addAction(print_action)
        print_action.setShortcut("Ctrl+P")

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        exit_action.setShortcut("Ctrl+Q")

        # Edit actions
        edit_item_action = QAction("&Edit item ...", self)
        edit_item_action.triggered.connect(self._on_edit_item)
        edit_menu.addAction(edit_item_action)

        delete_item_action = QAction("&Delete item(s) ...", self)
        delete_item_action.triggered.connect(self._on_delete_items)
        edit_menu.addAction(delete_item_action)
        delete_item_action.setShortcut("Del")

        edit_menu.addSeparator()

        search_new_misc_weight_action = QAction("&Search item ...", self)
        search_new_misc_weight_action.triggered.connect(self._on_search_item)
        edit_menu.addAction(search_new_misc_weight_action)

        edit_menu.addSeparator()

        add_new_item_action = QAction("&Add new item ...", self)
        add_new_item_action.triggered.connect(self._on_add_new_item)
        edit_menu.addAction(add_new_item_action)

        empty_space_action = QAction("&Empty space(s)...", self)
        empty_space_action.triggered.connect(self._on_empty_spaces)
        edit_menu.addAction(empty_space_action)

        fill_space_action = QAction("&Fill space(s)...", self)
        fill_space_action.triggered.connect(self._on_fill_spaces)
        edit_menu.addAction(fill_space_action)

        fill_spaces_action = QAction("&Fill spaces To..", self)
        fill_spaces_action.triggered.connect(self._on_fill_spaces_to)
        edit_menu.addAction(fill_spaces_action)

        edit_menu.addSeparator()

        select_all_action = QAction("&Select all", self)
        select_all_action.triggered.connect(self._on_select_all)
        edit_menu.addAction(select_all_action)
        select_all_action.setShortcut("Ctrl+A")

        clear_selection_action = QAction("&Clear selection", self)
        clear_selection_action.triggered.connect(self._on_clear_selection)
        edit_menu.addAction(clear_selection_action)
        clear_selection_action.setShortcut("Ctrl+Shift+A")

        # View actions
        default_view_action = QAction("&Default view model", self)
        default_view_action.triggered.connect(self._on_default_view_model)
        view_menu.addAction(default_view_action)

        change_layout_action = QAction("&Change layout", self)
        change_layout_action.triggered.connect(self._on_change_layout)
        view_menu.addAction(change_layout_action)

        maximize_view_action = QAction("&Maximize window", self)
        maximize_view_action.triggered.connect(self.showMaximized)
        view_menu.addAction(maximize_view_action)

        change_active_view_action = QAction("&Change Active view...", self)
        change_active_view_action.triggered.connect(self._on_change_active_view)
        view_menu.addAction(change_active_view_action)

        view_menu.addSeparator()

        # Toggle the right-side results panel in the Loading Condition view
        self._show_results_bar_action = QAction("&Show Results Bar", self)
        self._show_results_bar_action.setCheckable(True)
        self._show_results_bar_action.setChecked(True)
        self._show_results_bar_action.triggered.connect(self._on_toggle_results_bar)
        view_menu.addAction(self._show_results_bar_action)

        view_menu.addSeparator()

        # Page navigation via View menu – mirrors toolbar tabs
        loading_view_action = QAction("Loading Condition", self)
        loading_view_action.setShortcuts(
            [QKeySequence("F2"), QKeySequence("Ctrl+1")]
        )
        loading_view_action.triggered.connect(
            lambda: self._switch_page(self._page_indexes.condition_editor, "Loading Condition")
        )
        view_menu.addAction(loading_view_action)

        results_view_action = QAction("Results", self)
        results_view_action.setShortcuts(
            [QKeySequence("F3"), QKeySequence("Ctrl+2")]
        )
        results_view_action.triggered.connect(
            lambda: self._switch_page(self._page_indexes.results, "Results")
        )
        view_menu.addAction(results_view_action)

        curves_view_action = QAction("Curves", self)
        curves_view_action.setShortcuts(
            [QKeySequence("Ctrl+3")]
        )
        curves_view_action.triggered.connect(
            lambda: self._switch_page(self._page_indexes.curves, "Curves")
        )
        view_menu.addAction(curves_view_action)
        view_menu.addSeparator()

        program_options_action = QAction("&Program Options", self)
        program_options_action.triggered.connect(self._on_program_options)
        view_menu.addAction(program_options_action)

        display_options_action = QAction("&Display Options", self)
        display_options_action.triggered.connect(self._on_display_options)
        view_menu.addAction(display_options_action)

        restore_workspace_action = QAction("&Restore Default Workspace settings...", self)
        restore_workspace_action.triggered.connect(self._on_restore_workspace)
        view_menu.addAction(restore_workspace_action)

        restore_units_action = QAction("&Restore Default Units and Precision...", self)
        restore_units_action.triggered.connect(self._on_restore_units)
        view_menu.addAction(restore_units_action)

        # Tools for Selected Deadweight Items...
        tools_action = QAction("Tools for Selected Deadweight Items...", self)
        tools_action.setShortcut("Ctrl+T")
        tools_action.triggered.connect(
            lambda: self._status_bar.showMessage("Tools for Selected Deadweight Items")
        )
        tools_menu.addAction(tools_action)

        tools_menu.addSeparator()

        # Auto Update Calculations (✔ checkable)
        self.auto_update_action = QAction("Auto Update Calculations", self)
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(True)
        self.auto_update_action.triggered.connect(
            lambda: self._status_bar.showMessage("Auto Update Calculations toggled")
        )
        tools_menu.addAction(self.auto_update_action)

        # Update Calculations (F9)
        update_calc_action = QAction("Update Calculations", self)
        update_calc_action.setShortcut("F9")
        update_calc_action.triggered.connect(self._on_compute)
        tools_menu.addAction(update_calc_action)

        # Stop Calculations (Ctrl+F9)
        stop_calc_action = QAction("Stop Calculations", self)
        stop_calc_action.setShortcut("Ctrl+F9")
        stop_calc_action.triggered.connect(
            lambda: self._status_bar.showMessage("Stop Calculations")
        )
        tools_menu.addAction(stop_calc_action)

        tools_menu.addSeparator()

        # Cargo Library – edit cargo types (affects loading condition)
        cargo_lib_action = QAction("Cargo Library...", self)
        cargo_lib_action.setToolTip("Edit cargo type library")
        cargo_lib_action.triggered.connect(self._on_cargo_library)
        tools_menu.addAction(cargo_lib_action)

        # Import STL meshes as tank objects (volume and LCG, VCG, TCG from mesh)
        import_stl_action = QAction("Import tanks from STL...", self)
        import_stl_action.setToolTip("Load STL file(s) and create tanks with volume and LCG/VCG/TCG from mesh")
        import_stl_action.triggered.connect(self._on_import_tanks_from_stl)
        tools_menu.addAction(import_stl_action)

        # Hydrostatic Calculator – opens dialog with current ship
        hydro_action = QAction("Hydrostatic Calculator...", self)
        hydro_action.triggered.connect(self._on_hydrostatic_calculator)
        tools_menu.addAction(hydro_action)

        # Remaining items
        items = [
            "Observed Drafts...",
            "Draft Survey...",
            "Tank/Weight Transfer...",
            "Advanced Load/Discharge Sequencer...",
            "Load/Discharge/BWE Sequence...",
            "Ship Squat Entry...",
            "Air Drafts...",
            "Navigation Drafts..."
        ]

        for text in items:
            action = QAction(text, self)
            action.triggered.connect(
                lambda checked=False, t=text: self._status_bar.showMessage(t)
            )
            tools_menu.addAction(action)

        # Damage menu actions
        # Clear Damage
        clear_damage_action = QAction("Clear Damage", self)
        clear_damage_action.triggered.connect(
            lambda: self._status_bar.showMessage("Clear Damage")
        )
        damage_menu.addAction(clear_damage_action)
        clear_damage_action.setDisabled(True)

        damage_menu.addSeparator()

        # Damage Selected Items (Ctrl+D)
        damage_selected_action = QAction("Damage Selected Items", self)
        damage_selected_action.setShortcut("Ctrl+D")
        damage_selected_action.triggered.connect(
            lambda: self._status_bar.showMessage("Damage Selected Items")
        )
        damage_menu.addAction(damage_selected_action)
        damage_selected_action.setDisabled(True)

        # Undamage Selected Items (Ctrl+U)
        undamage_selected_action = QAction("Undamage Selected Items", self)
        undamage_selected_action.setShortcut("Ctrl+U")
        undamage_selected_action.triggered.connect(
            lambda: self._status_bar.showMessage("Undamage Selected Items")
        )
        damage_menu.addAction(undamage_selected_action)
        undamage_selected_action.setDisabled(True)

        damage_menu.addSeparator()

        # Applied GZ Moment Entry...
        gz_moment_action = QAction("Applied GZ Moment Entry...", self)
        gz_moment_action.triggered.connect(
            lambda: self._status_bar.showMessage("Applied GZ Moment Entry")
        )
        damage_menu.addAction(gz_moment_action)

        # Grounding Menu actions
        clear_ground_action = QAction("Clear Grounding", self)
        clear_ground_action.triggered.connect(
            lambda: self._status_bar.showMessage("Clear Grounding")
        )
        grounding_menu.addAction(clear_ground_action)
        clear_ground_action.setDisabled(True)

        grounding_menu.addSeparator()

        define_ground_action = QAction("Define Grounding", self)
        define_ground_action.triggered.connect(
            lambda: self._status_bar.showMessage("Define Grounding")
        )
        grounding_menu.addAction(define_ground_action)
        define_ground_action.setShortcut("Ctrl+G")

        # Historian Menu actions
        take_snapshot_action = QAction("Take Snapshot", self)
        take_snapshot_action.triggered.connect(self._on_take_snapshot)
        historian_menu.addAction(take_snapshot_action)

        historian_menu.addSeparator()

        field_selection_action = QAction("Field Selection...", self)
        field_selection_action.triggered.connect(self._on_historian_field_selection)
        historian_menu.addAction(field_selection_action)

        visualize_date_action = QAction("Visualize Data...", self)
        visualize_date_action.triggered.connect(self._on_historian_visualize)
        historian_menu.addAction(visualize_date_action)

        export_data_action = QAction("Export Data...", self)
        export_data_action.triggered.connect(self._on_historian_export)
        historian_menu.addAction(export_data_action)

        # Help menu

        vessel_documentation_action = QAction("Vessel Documentation", self)
        vessel_documentation_action.triggered.connect(self._open_vessel_documentation)
        help_menu.addAction(vessel_documentation_action)

        help_menu.addSeparator()

        help_contents_action = QAction("Help Contents", self)
        help_contents_action.triggered.connect(self._show_help_contents)
        help_menu.addAction(help_contents_action)
        help_contents_action.setShortcut("F1")

        sena_website_action = QAction("Sena Website", self)
        sena_website_action.triggered.connect(self._open_sena_website)
        help_menu.addAction(sena_website_action)

        show_program_log_action = QAction("Show Program Log", self)
        show_program_log_action.triggered.connect(self._show_program_log)
        help_menu.addAction(show_program_log_action)

        help_menu.addSeparator()

        about_action = QAction("&About senashipping", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        # Apply modern styling to main window
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QMenuBar {
                background-color: white;
                border-bottom: 1px solid #ddd;
                padding: 2px;
            }
            QMenuBar::item {
                padding: 4px 8px;
                background-color: transparent;
            }
            QMenuBar::item:selected {
                background-color: #e0e0e0;
            }
            QToolBar {
                background-color: white;
                border-bottom: 1px solid #ddd;
                spacing: 2px;
            }
            QToolButton {
                padding: 4px;
                border-radius: 3px;
            }
            QToolButton:hover {
                background-color: #e0e0e0;
            }
            QToolButton:checked {
                background-color: #4A90E2;
                color: white;
            }
            QStatusBar {
                background-color: #f0f0f0;
                border-top: 1px solid #ddd;
            }
        """)

    def _create_toolbar(self) -> None:
        """Create comprehensive toolbar with text labels (no icons to avoid QPainter engine==0 on some platforms)."""
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        # File actions (text-only to avoid pixmap paint device errors)
        new_action = QAction("New", self)
        new_action.setShortcut("Ctrl+N")
        new_action.setToolTip("New Loading Condition (Ctrl+N)")
        new_action.triggered.connect(self._on_new_condition)
        toolbar.addAction(new_action)

        open_action = QAction("Open", self)
        open_action.setShortcut("Ctrl+O")
        open_action.setToolTip("Open Loading Condition (Ctrl+O)")
        open_action.triggered.connect(self._on_open_condition)
        toolbar.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.setToolTip("Save Loading Condition (Ctrl+S)")
        save_action.triggered.connect(self._on_save)
        toolbar.addAction(save_action)

        print_action = QAction("Print/Export", self)
        print_action.setShortcut("Ctrl+P")
        print_action.setToolTip("Print or Export (Ctrl+P)")
        print_action.triggered.connect(self._on_print_export)
        toolbar.addAction(print_action)

        toolbar.addSeparator()

        # Navigation actions with checkable buttons
        nav_group = QActionGroup(self)
        nav_group.setExclusive(True)

        def add_nav_action(text: str, page_index: int, status: str, shortcut: str | None = None) -> None:
            action = QAction(text, self)
            action.setCheckable(True)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(
                lambda _checked=False, idx=page_index, msg=status: self._switch_page(idx, msg)
            )
            toolbar.addAction(action)
            nav_group.addAction(action)
            self._nav_actions[page_index] = action

        # Single-ship app: Loading Condition, Results, Curves in main nav
        add_nav_action("Loading Condition", self._page_indexes.condition_editor, "Loading Condition", "F2")
        add_nav_action("Results", self._page_indexes.results, "Results", "F3")
        add_nav_action("Curves", self._page_indexes.curves, "Curves")

        toolbar.addSeparator()

        # Compute action
        compute_action = QAction("Compute", self)
        compute_action.setShortcut("F9")
        compute_action.setToolTip("Compute Results (F9)")
        compute_action.triggered.connect(self._on_compute)
        toolbar.addAction(compute_action)

        toolbar.addSeparator()

        # View/zoom actions for graphics in Loading Condition view
        self._zoom_in_action = QAction("Zoom In", self)
        self._zoom_in_action.setToolTip("Zoom in profile and deck views (Loading Condition)")
        self._zoom_in_action.triggered.connect(self._on_zoom_in)
        toolbar.addAction(self._zoom_in_action)

        self._zoom_out_action = QAction("Zoom Out", self)
        self._zoom_out_action.setToolTip("Zoom out profile and deck views (Loading Condition)")
        self._zoom_out_action.triggered.connect(self._on_zoom_out)
        toolbar.addAction(self._zoom_out_action)

        self._fit_view_action = QAction("Fit View", self)
        self._fit_view_action.setToolTip("Fit ship profile and deck drawings to view")
        self._fit_view_action.triggered.connect(self._on_fit_to_view)
        toolbar.addAction(self._fit_view_action)

    def _create_status_panel(self) -> None:
        """Create status panel with Alarms/Log/Offline buttons in top right."""
        # Create a widget for the status panel
        status_widget = QWidget(self)
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(4, 4, 4, 4)
        status_layout.setSpacing(4)

        # Alarms button (red)
        alarms_btn = QPushButton("Alarms", self)
        alarms_btn.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #a93226;
            }
        """)
        alarms_btn.clicked.connect(self._on_alarms_clicked)
        status_layout.addWidget(alarms_btn)


        # Status indicator (green circle)
        status_indicator = QLabel("●", self)
        status_indicator.setStyleSheet("color: #27ae60; font-size: 16px;")
        status_indicator.setToolTip("Online")
        status_layout.addWidget(status_indicator)

        # Add to menu bar area (right side)
        # We'll add it as a custom widget in the menu bar
        menu_bar = self.menuBar()
        menu_bar.setCornerWidget(status_widget, Qt.Corner.TopRightCorner)

    def _switch_page(self, index: int, status_message: str) -> None:
        self._stack.setCurrentIndex(index)
        self._status_bar.showMessage(status_message)

        # Update toolbar checked state (Loading Condition / Results / Curves have nav buttons)
        for idx, action in self._nav_actions.items():
            action.setChecked(idx == index)

        # Enable zoom actions only when the Loading Condition view is active
        current_widget = self._stack.currentWidget()
        is_condition_view = isinstance(current_widget, ConditionEditorView)
        for attr in ("_zoom_in_action", "_zoom_out_action", "_fit_view_action"):
            action = getattr(self, attr, None)
            if action is not None:
                action.setEnabled(is_condition_view)

    # ------------------------------------------------------------------
    # Edit menu helpers
    # ------------------------------------------------------------------

    def _get_condition_editor(self) -> ConditionEditorView | None:
        """Return the Loading Condition editor when it is the active page."""
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, ConditionEditorView) else None

    def _on_edit_item(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.edit_selected_item()
        else:
            self._status_bar.showMessage("Edit item is available in the Loading Condition view.", 4000)

    def _on_delete_items(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.delete_selected_items()
        else:
            self._status_bar.showMessage("Delete item(s) is available in the Loading Condition view.", 4000)

    def _on_search_item(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.search_item()
        else:
            self._status_bar.showMessage("Search item is available in the Loading Condition view.", 4000)

    def _on_add_new_item(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.add_new_item()
        else:
            # Fallback: open Ship & data setup so user can define new items
            self._switch_page(self._page_indexes.ship_manager, "Ship & data setup – add tanks and pens")

    def _on_empty_spaces(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.empty_spaces()
        else:
            self._status_bar.showMessage("Empty space(s) is available in the Loading Condition view.", 4000)

    def _on_fill_spaces(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.fill_spaces()
        else:
            self._status_bar.showMessage("Fill space(s) is available in the Loading Condition view.", 4000)

    def _on_fill_spaces_to(self) -> None:
        editor = self._get_condition_editor()
        if not editor:
            self._status_bar.showMessage("Fill spaces To is available in the Loading Condition view.", 4000)
            return
        from PyQt6.QtWidgets import QInputDialog

        value, ok = QInputDialog.getDouble(
            self,
            "Fill spaces to",
            "Fill selected spaces/tanks to (% full):",
            100.0,
            0.0,
            100.0,
            1,
        )
        if not ok:
            return
        editor.fill_spaces_to(value)

    def _on_select_all(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.select_all_items()
        else:
            self._status_bar.showMessage("Select all is available in the Loading Condition view.", 4000)

    def _on_clear_selection(self) -> None:
        editor = self._get_condition_editor()
        if editor:
            editor.clear_selection()
        else:
            self._status_bar.showMessage("Clear selection is available in the Loading Condition view.", 4000)

    def _on_toggle_results_bar(self, checked: bool) -> None:
        """
        Show or hide the right-side results panel in the Loading Condition view.

        Connected to View → Show Results Bar.
        """
        cond_editor = self._stack.widget(self._page_indexes.condition_editor)
        if isinstance(cond_editor, ConditionEditorView):
            cond_editor.set_results_panel_visible(checked)

    def _on_default_view_model(self) -> None:
        """
        Restore the main layout to a sensible default "Loading Condition" view.

        View → Default view model calls this to get back to the standard layout.
        """
        # Show main toolbar and unhide key panels in the editor
        for tb in self.findChildren(QToolBar):
            tb.setVisible(True)
        cond_editor = self._stack.widget(self._page_indexes.condition_editor)
        if isinstance(cond_editor, ConditionEditorView):
            cond_editor.set_default_view_layout()
        # Ensure results bar toggle is in sync
        self._show_results_bar_action.setChecked(True)
        # Switch to Loading Condition page
        self._switch_page(self._page_indexes.condition_editor, "Loading Condition")

    def _on_change_layout(self) -> None:
        """
        Toggle between showing and hiding the bottom condition table.

        This gives a simple "layout" change: more space for graphics/results vs.
        full editor with the tabbed condition table visible.
        """
        cond_editor = self._stack.widget(self._page_indexes.condition_editor)
        if not isinstance(cond_editor, ConditionEditorView):
            self._status_bar.showMessage("Open Loading Condition view to change layout")
            return
        currently_visible = cond_editor._condition_table.isVisible()
        cond_editor._condition_table.setVisible(not currently_visible)
        if currently_visible:
            self._status_bar.showMessage("Layout: graphics/results focus (condition table hidden)", 4000)
        else:
            self._status_bar.showMessage("Layout: full editor (condition table shown)", 4000)

    def _on_change_active_view(self) -> None:
        """
        Cycle the active central view between Loading Condition → Results → Curves.

        Called from View → Change Active view...
        """
        order = [
            self._page_indexes.condition_editor,
            self._page_indexes.results,
            self._page_indexes.curves,
        ]
        current = self._stack.currentIndex()
        try:
            idx = order.index(current)
        except ValueError:
            idx = 0
        next_index = order[(idx + 1) % len(order)]
        label = "Loading Condition" if next_index == self._page_indexes.condition_editor else (
            "Results" if next_index == self._page_indexes.results else "Curves"
        )
        self._switch_page(next_index, label)

    def _on_program_options(self) -> None:
        """
        Placeholder Program Options dialog.

        View → Program Options opens this until a full options system is implemented.
        """
        QMessageBox.information(
            self,
            "Program Options",
            "Program-wide options are not configurable in this demo build.\n\n"
            "Core behaviour (computation, results, and layout) is fixed for now."
        )

    def _on_display_options(self) -> None:
        """
        Placeholder Display Options dialog.

        View → Display Options allows basic explanation instead of doing nothing.
        """
        QMessageBox.information(
            self,
            "Display Options",
            "Display options (themes, fonts, colours) are not configurable in this build.\n\n"
            "The current layout is optimised for clarity on typical shipboard laptops."
        )

    def _on_restore_workspace(self) -> None:
        """
        Restore default workspace-like layout.

        For now this mirrors Default view model and also normalises the window size.
        """
        self.showNormal()
        self.resize(1200, 800)
        self._on_default_view_model()
        self._status_bar.showMessage("Workspace layout restored to defaults", 4000)

    def _on_restore_units(self) -> None:
        """
        Inform the user that units/precision are fixed in this build.

        Keeps View → Restore Default Units and Precision from being a no-op.
        """
        QMessageBox.information(
            self,
            "Units and Precision",
            "Units and precision are fixed to SI / metric values in this build.\n\n"
            "Drafts: metres, Displacement: tonnes, GM: metres, Shear/BM: metric units."
        )

    def _on_cargo_library(self) -> None:
        """Open Edit Cargo Library dialog; refresh condition editor combo and dropdowns when closed."""
        dlg = CargoLibraryDialog(self)
        dlg.exec()
        cond_editor = self._stack.widget(self._page_indexes.condition_editor)
        if isinstance(cond_editor, ConditionEditorView):
            cond_editor._refresh_cargo_types()
            # Update cargo types in condition table widget and refresh dropdowns
            if hasattr(cond_editor, '_condition_table') and hasattr(cond_editor._condition_table, 'update_cargo_types'):
                cond_editor._condition_table.update_cargo_types(cond_editor._cargo_types)

    def _on_hydrostatic_calculator(self) -> None:
        """
        Open Hydrostatic Calculator.

        The full calculator dialog is not implemented yet in this project;
        for now, show a non-crashing placeholder message instead of raising
        a NameError when the menu item is used.
        """
        QMessageBox.information(
            self,
            "Hydrostatic Calculator",
            "Hydrostatic Calculator is not available in this build.\n\n"
            "Use the main Results and Curves views for stability checks."
        )

    def _on_import_tanks_from_stl(self) -> None:
        """Import STL mesh(es) as tank objects; volume and LCG, VCG, TCG from mesh."""
        cond_editor = self._stack.widget(self._page_indexes.condition_editor)
        if not isinstance(cond_editor, ConditionEditorView):
            self._status_bar.showMessage("Switch to Loading Condition first")
            return
        ship = getattr(cond_editor, "_current_ship", None)
        if not ship or not getattr(ship, "id", None):
            QMessageBox.information(
                self,
                "Import tanks from STL",
                "Select a ship first (Tools → Ship & data setup).",
            )
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select STL file",
            str(Path.home()),
            "STL (*.stl);;All (*)",
        )
        if not file_path:
            return
        from PyQt6.QtWidgets import QInputDialog
        deck_name, ok = QInputDialog.getItem(
            self,
            "Import tanks from STL",
            "Deck name (for tank grouping):",
            ["A", "B", "C", "D", "E", "F", "G", "H"],
            0,
            False,
        )
        if not ok:
            return
        try:
            from senashipping_app.services.stl_mesh_service import create_tanks_from_stl, TRIMESH_AVAILABLE
            if not TRIMESH_AVAILABLE:
                QMessageBox.critical(
                    self,
                    "Import tanks from STL",
                    "trimesh is required. Install with: pip install trimesh",
                )
                return
            from senashipping_app.repositories import database
            from senashipping_app.repositories.tank_repository import TankRepository
            with database.SessionLocal() as db:
                tank_repo = TankRepository(db)
                created = create_tanks_from_stl(
                    Path(file_path),
                    ship.id,
                    deck_name,
                    tank_repo,
                )
            cond_editor._set_current_ship(ship)
            QMessageBox.information(
                self,
                "Import tanks from STL",
                f"Created {len(created)} tank(s) with volume and LCG/VCG/TCG from mesh.",
            )
            self._status_bar.showMessage(f"Imported {len(created)} tanks from STL")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import STL:\n{str(e)}",
            )

    def _on_new_condition(self) -> None:
        """Handle new condition action from toolbar."""
        # Ask if user wants to save current condition
        if self._current_file_path:
            reply = QMessageBox.question(
                self,
                "New Condition",
                "Do you want to save the current condition before creating a new one?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_save()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        # Switch to condition editor if not already there
        if self._stack.currentIndex() != self._page_indexes.condition_editor:
            self._switch_page(self._page_indexes.condition_editor, "Loading Condition")

        # Create new condition
        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ConditionEditorView):
            current_widget.new_condition()
            self._current_file_path = None
            self.setWindowTitle("senashipping for Livestock Demo - [New]")
            self._status_bar.showMessage("New condition created")
        else:
            self._status_bar.showMessage("Switch to Loading Condition view first")

    def _on_open_condition(self) -> None:
        """Handle open condition action from toolbar - opens file dialog."""
        # Ask if user wants to save current condition
        if self._current_file_path:
            reply = QMessageBox.question(
                self,
                "Open Condition",
                "Do you want to save the current condition before opening a new one?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_save()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Loading Condition",
            str(Path.home()),
            "senashipping Files (*.senashipping);;JSON Files (*.json);;All Files (*)",
        )

        if not file_path:
            return

        try:
            condition = load_condition_from_file(Path(file_path))

            # Switch to condition editor
            if self._stack.currentIndex() != self._page_indexes.condition_editor:
                self._switch_page(self._page_indexes.condition_editor, "Loading Condition")

            current_widget = self._stack.currentWidget()
            if isinstance(current_widget, ConditionEditorView):
                # Load condition into editor
                self._current_file_path = Path(file_path)
                self.setWindowTitle(f"Sena Marine for Livestock Carriers - {Path(file_path).name}")

                # Set condition name and cargo type (single-ship: user sees cargo type)
                current_widget._condition_name_edit.setText(condition.name)
                current_widget._set_cargo_type_text(condition.name)

                # Load condition data into editor
                current_widget._current_condition = condition

                # Load tank volumes and pen loadings
                if current_widget._current_ship:
                    current_widget._set_current_ship(current_widget._current_ship)

                    # Update tank table with loaded volumes
                    if condition.tank_volumes_m3 and database.SessionLocal:
                        with database.SessionLocal() as db:
                            from senashipping_app.services.condition_service import ConditionService
                            cond_service = ConditionService(db)
                            tanks = cond_service.get_tanks_for_ship(current_widget._current_ship.id)
                            tank_by_id = {t.id: t for t in tanks}

                            # Update fill percentages in tank table
                            for row in range(current_widget._tank_table.rowCount()):
                                name_item = current_widget._tank_table.item(row, 0)
                                if name_item:
                                    tank_id = name_item.data(Qt.ItemDataRole.UserRole)
                                    if tank_id and int(tank_id) in condition.tank_volumes_m3:
                                        tank = tank_by_id.get(int(tank_id))
                                        if tank and tank.capacity_m3 > 0:
                                            vol = condition.tank_volumes_m3[int(tank_id)]
                                            fill_pct = (vol / tank.capacity_m3) * 100.0
                                            fill_item = current_widget._tank_table.item(row, 2)
                                            if fill_item:
                                                fill_item.setText(f"{fill_pct:.1f}")

                    # Update pen table with loaded head counts
                    if condition.pen_loadings:
                        pens = []
                        if database.SessionLocal:
                            with database.SessionLocal() as db:
                                from senashipping_app.services.condition_service import ConditionService
                                cond_service = ConditionService(db)
                                pens = cond_service.get_pens_for_ship(current_widget._current_ship.id)

                        for row in range(current_widget._pen_table.rowCount()):
                            name_item = current_widget._pen_table.item(row, 0)
                            if name_item:
                                pen_id = name_item.data(Qt.ItemDataRole.UserRole)
                                if pen_id and int(pen_id) in condition.pen_loadings:
                                    heads = condition.pen_loadings[int(pen_id)]
                                    head_item = current_widget._pen_table.item(row, 3)
                                    if head_item:
                                        head_item.setText(str(heads))

                    # Update condition table
                    pens = []
                    tanks = []
                    if database.SessionLocal:
                        with database.SessionLocal() as db:
                            from senashipping_app.services.condition_service import ConditionService
                            cond_service = ConditionService(db)
                            pens = cond_service.get_pens_for_ship(current_widget._current_ship.id)
                            tanks = cond_service.get_tanks_for_ship(current_widget._current_ship.id)

                    current_widget._update_condition_table(
                        pens, tanks,
                        condition.pen_loadings or {},
                        condition.tank_volumes_m3 or {}
                    )

                self._status_bar.showMessage(f"Loaded condition from {Path(file_path).name}", 3000)
            else:
                self._status_bar.showMessage("Failed to load condition")

        except Exception as e:
            QMessageBox.critical(
                self,
                "Open Error",
                f"Failed to open condition file:\n{str(e)}"
            )
            self._status_bar.showMessage("Failed to open file", 3000)

    def _on_save(self) -> None:
        """Handle save action from toolbar."""
        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ConditionEditorView):
            # If we have a file path, save to that file
            if self._current_file_path:
                self._save_to_file(self._current_file_path, current_widget)
            else:
                # Otherwise, show save as dialog
                self._on_save_as()
        else:
            self._status_bar.showMessage("Switch to Loading Condition view to save")

    def _on_save_as(self) -> None:
        """Handle save as action - shows file dialog."""
        current_widget = self._stack.currentWidget()
        if not isinstance(current_widget, ConditionEditorView):
            self._status_bar.showMessage("Switch to Loading Condition view to save")
            return

        # Show save dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Loading Condition",
            str(self._current_file_path or Path.home() / "condition.senashipping"),
            "senashipping Files (*.senashipping);;JSON Files (*.json);;All Files (*)",
        )

        if not file_path:
            return

        # Ensure .senashipping extension if not provided
        if not file_path.endswith(('.senashipping', '.json')):
            file_path += '.senashipping'

        self._save_to_file(Path(file_path), current_widget)

    def _save_to_file(self, file_path: Path, condition_widget: ConditionEditorView) -> None:
        """Save condition to file."""
        # Get or create condition from current state
        condition = condition_widget._current_condition

        if not condition:
            # Create condition from current form state (condition name from field, else cargo type)
            from senashipping_app.models import LoadingCondition
            condition_name = condition_widget._condition_name_edit.text().strip() or condition_widget._cargo_type_combo.currentText().strip() or "Condition"
            condition = LoadingCondition(
                voyage_id=condition_widget._current_voyage.id if condition_widget._current_voyage else None,
                name=condition_name,
            )

        # Keep condition name in sync with the form (e.g. user edited after Compute)
        name_from_form = condition_widget._condition_name_edit.text().strip()
        if name_from_form:
            condition.name = name_from_form

        # Build tank volumes and pen loadings from current UI state.
        # Use the condition table (new UI) as the source of truth, with the
        # legacy simple tables as a fallback, so tank and pen loadings are
        # always saved exactly as shown on screen.
        tank_volumes: Dict[int, float] = {}
        pen_loadings: Dict[int, int] = {}

        # Start with simple tank table (Fill % * capacity)
        tank_volumes = condition_widget._tank_volumes_from_simple_table()

        # Overlay volumes from condition table so Volume/Weight-driven edits win
        if hasattr(condition_widget, "_condition_table"):
            ct_vols = condition_widget._condition_table.get_tank_volumes_from_tables()
            for tid, vol in ct_vols.items():
                tank_volumes[tid] = vol

            # Pen loadings: prefer condition table (livestock decks)
            ct_pen_loads = condition_widget._condition_table.get_pen_loadings_from_tables()
            if ct_pen_loads:
                pen_loadings = {pid: h for pid, h in ct_pen_loads.items() if h > 0}

        # Fallback to legacy pen table if condition table has no loads
        if not pen_loadings:
            pen_loadings = condition_widget._pen_loadings_from_pen_table()

        condition.tank_volumes_m3 = tank_volumes
        condition.pen_loadings = pen_loadings

        try:
            save_condition_to_file(file_path, condition)
            self._current_file_path = file_path
            self.setWindowTitle(f"Sena Marine for Livestock Carriers - {file_path.name}")
            self._status_bar.showMessage(f"Condition saved to {file_path.name}", 3000)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save condition file:\n{str(e)}"
            )
            self._status_bar.showMessage("Failed to save file", 3000)

    def _on_import_excel(self) -> None:
        """Handle import from Excel action."""
        # Open file dialog for Excel import
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Excel",
            str(Path.home()),
            "Excel Files (*.xlsx *.xls);;All Files (*)",
        )

        if not file_path:
            return

        try:
            # TODO: Implement Excel import logic
            # For now, show a message
            QMessageBox.information(
                self,
                "Import Excel",
                f"Excel import from {Path(file_path).name} - Coming soon.\n\n"
                "This feature will allow importing tank volumes and pen loadings from Excel files."
            )
            self._status_bar.showMessage(f"Import from {Path(file_path).name} - Feature coming soon", 3000)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import Excel file:\n{str(e)}"
            )

    def _on_export_excel(self) -> None:
        """Handle export to Excel action."""
        # Check if we have results to export
        if not hasattr(self._results_view, '_last_results') or not self._results_view._last_results:
            QMessageBox.information(
                self,
                "Export Excel",
                "Please compute a condition first before exporting."
            )
            # Switch to condition editor to compute
            if self._stack.currentIndex() != self._page_indexes.condition_editor:
                self._switch_page(self._page_indexes.condition_editor, "Loading Condition")
            return

        # Open file dialog for Excel export
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Excel",
            str(Path.home() / "condition_export.xlsx"),
            "Excel Files (*.xlsx);;All Files (*)",
        )

        if not file_path:
            return

        # Ensure .xlsx extension
        if not file_path.endswith('.xlsx'):
            file_path += '.xlsx'

        try:
            # Switch to results view to use its export method
            if self._stack.currentIndex() != self._page_indexes.results:
                self._switch_page(self._page_indexes.results, "Results")

            # Use results view export method
            self._results_view._on_export_excel()
            self._status_bar.showMessage(f"Exported to {Path(file_path).name}", 3000)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export Excel file:\n{str(e)}"
            )

    def _on_take_snapshot(self) -> None:
        """Save current calculation result as a historian snapshot (Historian → Take Snapshot)."""
        if not hasattr(self._results_view, "_last_results") or not self._results_view._last_results:
            QMessageBox.information(
                self,
                "Take Snapshot",
                "Compute a condition first, then use Take Snapshot to save it to the historian.",
            )
            if self._stack.currentIndex() != self._page_indexes.condition_editor:
                self._switch_page(self._page_indexes.condition_editor, "Loading Condition")
            return
        snapshot = getattr(self._results_view._last_results, "snapshot", None)
        if not snapshot or not hasattr(snapshot, "to_dict"):
            QMessageBox.information(
                self,
                "Take Snapshot",
                "No traceability snapshot available for the last calculation.",
            )
            return
        data_dir = self._settings.data_dir
        try:
            sid = historian_service.save_snapshot(data_dir, snapshot.to_dict())
            self._status_bar.showMessage(f"Snapshot saved (id: {sid})", 4000)
            QMessageBox.information(
                self,
                "Take Snapshot",
                "Current calculation has been saved to the historian.",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Take Snapshot",
                f"Could not save snapshot:\n{e}",
            )

    def _on_historian_field_selection(self) -> None:
        """Open dialog to choose which fields to show in Historian view/export."""
        data_dir = self._settings.data_dir
        selected = historian_service.load_field_selection(data_dir)
        dlg = QDialog(self)
        dlg.setWindowTitle("Historian – Field Selection")
        QShortcut(Qt.Key.Key_Escape, dlg, activated=dlg.reject)
        layout = QVBoxLayout(dlg)
        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        scroll_w = QWidget()
        grid = QGridLayout(scroll_w)
        checks = {}
        for i, field in enumerate(historian_service.HISTORIAN_ALL_FIELDS):
            cb = QCheckBox(field.replace("_", " ").title(), dlg)
            cb.setChecked(field in selected)
            checks[field] = cb
            grid.addWidget(cb, i // 3, i % 3)
        scroll.setWidget(scroll_w)
        layout.addWidget(scroll)
        ok_btn = QPushButton("OK", dlg)
        cancel_btn = QPushButton("Cancel", dlg)

        def save_and_accept() -> None:
            chosen = [f for f, cb in checks.items() if cb.isChecked()]
            if chosen:
                historian_service.save_field_selection(data_dir, chosen)
            dlg.accept()

        ok_btn.clicked.connect(save_and_accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        dlg.exec()
        self._status_bar.showMessage("Historian field selection", 2000)

    def _on_historian_visualize(self) -> None:
        """Show historian snapshots in a table (Historian → Visualize Data)."""
        data_dir = self._settings.data_dir
        snapshots = historian_service.load_snapshots(data_dir)
        columns = historian_service.load_field_selection(data_dir)
        dlg = QDialog(self)
        dlg.setWindowTitle("Historian – Visualize Data")
        dlg.setMinimumSize(700, 400)
        QShortcut(Qt.Key.Key_Escape, dlg, activated=dlg.reject)
        layout = QVBoxLayout(dlg)
        table = QTableWidget(dlg)
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels([c.replace("_", " ").title() for c in columns])
        table.setRowCount(len(snapshots))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for row, snap in enumerate(snapshots):
            row_data = historian_service.snapshot_to_flat_row(snap, columns)
            for col, key in enumerate(columns):
                val = row_data.get(key, "")
                if val is None:
                    val = ""
                if isinstance(val, dict):
                    val = json.dumps(val)[:80]
                table.setItem(row, col, QTableWidgetItem(str(val)))
        layout.addWidget(table)
        ok_btn = QPushButton("OK", dlg)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn)
        dlg.exec()
        self._status_bar.showMessage(f"Historian: {len(snapshots)} snapshot(s)", 2000)

    def _on_historian_export(self) -> None:
        """Export historian snapshots to CSV (Historian → Export Data)."""
        data_dir = self._settings.data_dir
        snapshots = historian_service.load_snapshots(data_dir)
        if not snapshots:
            QMessageBox.information(
                self,
                "Export Data",
                "No historian snapshots. Use Take Snapshot after computing a condition.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Historian Data",
            str(Path.home() / "historian_export.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"
        columns = historian_service.load_field_selection(data_dir)
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for snap in snapshots:
                    row_data = historian_service.snapshot_to_flat_row(snap, columns)
                    row = []
                    for c in columns:
                        v = row_data.get(c, "")
                        if isinstance(v, dict):
                            v = json.dumps(v)
                        row.append(v if v is not None else "")
                    writer.writerow(row)
            self._status_bar.showMessage(f"Exported to {Path(path).name}", 3000)
            QMessageBox.information(
                self,
                "Export Data",
                f"Exported {len(snapshots)} snapshot(s) to\n{path}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Data",
                f"Could not export:\n{e}",
            )

    def _on_summary_info(self) -> None:
        """Show a brief summary dialog for the current ship."""
        cond_editor = self._condition_editor
        ship = getattr(cond_editor, "_current_ship", None)
        if not ship or not getattr(ship, "id", None):
            self._status_bar.showMessage("Select a ship first (Tools → Ship & data setup)", 4000)
            QMessageBox.information(
                self,
                "Summary Info",
                "No ship selected.\n\nGo to Tools → Ship & data setup to select or create a ship.",
            )
            return
        lines = [
            "Ship brief",
            "─────────",
            f"Name: {ship.name or '—'}",
            f"IMO: {ship.imo_number or '—'}",
            f"Flag: {ship.flag or '—'}",
            "",
            "Principal dimensions",
            "──────────────────",
            f"Length overall: {ship.length_overall_m or 0:.2f} m",
            f"Breadth:        {ship.breadth_m or 0:.2f} m",
            f"Depth:          {ship.depth_m or 0:.2f} m",
            f"Design draft:   {ship.design_draft_m or 0:.2f} m",
            f"Lightship draft: {ship.lightship_draft_m or 0:.2f} m",
            f"Lightship displacement: {ship.lightship_displacement_t or 0:.1f} t",
        ]
        if database.SessionLocal and ship.id:
            try:
                with database.SessionLocal() as db:
                    from senashipping_app.services.condition_service import ConditionService
                    cond_svc = ConditionService(db)
                    tanks = cond_svc.get_tanks_for_ship(ship.id)
                    pens = cond_svc.get_pens_for_ship(ship.id)
                    lines.extend([
                        "",
                        "Data setup",
                        "──────────",
                        f"Tanks: {len(tanks)}",
                        f"Pens (decks): {len(pens)}",
                    ])
            except Exception:
                pass
        text = "\n".join(lines)
        dlg = QDialog(self)
        dlg.setWindowTitle("Summary Info – Ship brief")
        QShortcut(Qt.Key.Key_Escape, dlg, activated=dlg.reject)
        layout = QVBoxLayout(dlg)
        te = QPlainTextEdit(dlg)
        te.setPlainText(text)
        te.setReadOnly(True)
        te.setMinimumSize(420, 320)
        layout.addWidget(te)
        ok_btn = QPushButton("OK", dlg)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn)
        dlg.exec()
        self._status_bar.showMessage("Summary Info", 2000)

    def _on_program_notes(self) -> None:
        """Show Program Notes dialog with stability manual reference and operating restrictions."""
        lines = [
            f"Stability manual reference: {MANUAL_SOURCE}",
            f"Vessel: {MANUAL_VESSEL_NAME}  IMO: {MANUAL_IMO}",
            f"Criteria: {MANUAL_REF}",
            "",
            "Operating restrictions (from Loading Manual):",
        ]
        for r in OPERATING_RESTRICTIONS:
            lines.append(f"  • {r}")
        text = "\n".join(lines)
        dlg = QDialog(self)
        dlg.setWindowTitle("Program Notes – Stability Manual Reference")
        QShortcut(Qt.Key.Key_Escape, dlg, activated=dlg.reject)
        layout = QVBoxLayout(dlg)
        te = QPlainTextEdit(dlg)
        te.setPlainText(text)
        te.setReadOnly(True)
        te.setMinimumSize(480, 280)
        layout.addWidget(te)
        ok_btn = QPushButton("OK", dlg)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn)
        dlg.exec()

    def _on_send_loading_condition_by_email(self) -> None:
        """Save the current loading condition (if needed), open default email client and the file's folder for attaching."""
        current_widget = self._stack.currentWidget()
        if not isinstance(current_widget, ConditionEditorView):
            self._switch_page(self._page_indexes.condition_editor, "Loading Condition")
            current_widget = self._stack.currentWidget()
        if not isinstance(current_widget, ConditionEditorView):
            self._status_bar.showMessage("Switch to Loading Condition view first", 3000)
            return
        # Ensure we have a file to send: use current path or save to a temp file
        file_path = self._current_file_path
        if not file_path:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = Path(tempfile.gettempdir()) / f"loading_condition_{stamp}.senashipping"
        else:
            file_path = Path(file_path)
        # Save current condition to that path
        try:
            self._save_to_file(file_path, current_widget)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Send by email",
                f"Could not save the condition:\n{str(e)}",
            )
            self._status_bar.showMessage("Save failed", 3000)
            return
        # Build mailto subject and body
        subject = f"Loading Condition: {file_path.name}"
        body = (
            "Please find the loading condition file attached.\n\n"
            f"File: {file_path}\n\n"
            "A folder window has been opened — drag the file into your email to attach it."
        )
        mailto = f"mailto:?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
        if not QDesktopServices.openUrl(QUrl(mailto)):
            QMessageBox.warning(
                self,
                "Send by email",
                "Could not open your email client. You can attach the file manually from the folder that will open.",
            )
        # Open the folder containing the file so user can attach it (mailto does not support attachments)
        folder_url = QUrl.fromLocalFile(str(file_path.resolve().parent))
        QDesktopServices.openUrl(folder_url)
        self._status_bar.showMessage(f"Condition saved. Attach {file_path.name} from the opened folder.", 5000)

    def _on_print_export(self) -> None:
        """Handle print/export action from toolbar."""
        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ResultsView):
            # Show export dialog
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(self)
            pdf_action = menu.addAction("Export to PDF")
            excel_action = menu.addAction("Export to Excel")
            # Get position for menu (near toolbar)
            pos = self.mapToGlobal(self.rect().topLeft())
            pos.setY(pos.y() + 50)  # Offset below menu bar
            action = menu.exec(pos)
            if action == pdf_action:
                current_widget._on_export_pdf()
            elif action == excel_action:
                current_widget._on_export_excel()
        else:
            # Check if we have results available
            if isinstance(self._results_view, ResultsView) and hasattr(self._results_view, '_last_results'):
                # Switch to results view and show menu
                self._switch_page(self._page_indexes.results, "Results")
                self._on_print_export()  # Recursive call now that we're on results view
            else:
                self._status_bar.showMessage("Compute a condition first, then export from Results view", 3000)

    def _on_compute(self) -> None:
        """Handle compute action from toolbar."""
        # Remember which page the user was on to return appropriately after compute
        previous_index = self._stack.currentIndex()
        previous_was_curves = previous_index == self._page_indexes.curves

        # Switch to condition editor if not already there to run the calculation
        if previous_index != self._page_indexes.condition_editor:
            self._switch_page(self._page_indexes.condition_editor, "Loading Condition")

        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ConditionEditorView):
            if current_widget.compute_condition():
                self._status_bar.showMessage("Computation completed", 3000)
                # If user started from Curves, return to Curves so the refreshed
                # GZ plot is shown immediately; otherwise go to Results as before.
                if previous_was_curves:
                    self._switch_page(self._page_indexes.curves, "Curves")
                else:
                    self._switch_page(self._page_indexes.results, "Results")
            else:
                self._status_bar.showMessage("Computation failed - check inputs", 3000)
        else:
            self._status_bar.showMessage("Switch to Loading Condition view first")

    def _on_zoom_in(self) -> None:
        """Handle zoom in action from toolbar."""
        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ConditionEditorView):
            current_widget.zoom_in_graphics()
            self._status_bar.showMessage("Zoomed in", 1000)
        else:
            self._status_bar.showMessage("Zoom available in Loading Condition view")

    def _on_zoom_out(self) -> None:
        """Handle zoom out action from toolbar."""
        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ConditionEditorView):
            current_widget.zoom_out_graphics()
            self._status_bar.showMessage("Zoomed out", 1000)
        else:
            self._status_bar.showMessage("Zoom available in Loading Condition view")

    def _on_fit_to_view(self) -> None:
        """Handle fit to view action from toolbar."""
        current_widget = self._stack.currentWidget()
        if isinstance(current_widget, ConditionEditorView):
            current_widget.reset_zoom_graphics()
            self._status_bar.showMessage("Fitted to view", 1000)
        else:
            self._status_bar.showMessage("Fit to view available in Loading Condition view")

    def _on_alarms_clicked(self) -> None:
        """Handle alarms button click."""
        # Switch to Results view and show alarms
        self._stack.setCurrentIndex(self._page_indexes.results)
        self._switch_page(self._page_indexes.results, "Alarms")
        QMessageBox.information(self, "Alarms", "Viewing alarm status. Check the Results tab for details.")

    def _on_log_clicked(self) -> None:
        """Handle log button click - show program log."""
        self._show_program_log()

    def _on_offline_clicked(self) -> None:
        """Handle offline button click."""
        QMessageBox.information(self, "Offline Mode", "Offline mode - coming soon")

    def _open_vessel_documentation(self) -> None:
        """Open vessel documentation PDF (MV OSAMA BEY Ship's Particulars) in default viewer.
        Copies to a temp file before opening so it works when the app is frozen (PyInstaller);
        the system viewer gets a normal path instead of one inside the extract folder.
        """
        pdf_path = self._settings.project_root / "assets" / "MV OSAMA BEY- Ship's Particulars.pdf"
        if not pdf_path.exists():
            QMessageBox.warning(
                self,
                "Vessel Documentation",
                f"Reference file not found:\n{pdf_path}",
            )
            return
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="senashipping_vessel_")
            os.close(fd)
            shutil.copy2(pdf_path, tmp_path)
            url = QUrl.fromLocalFile(tmp_path)
            if not QDesktopServices.openUrl(url):
                QMessageBox.warning(
                    self,
                    "Vessel Documentation",
                    "Could not open the PDF. Check that a default viewer is set.",
                )
        except OSError as e:
            QMessageBox.warning(
                self,
                "Vessel Documentation",
                f"Could not prepare PDF for viewing: {e}",
            )

    def _show_help_contents(self) -> None:
        """Show USER_GUIDE.md in a read-only dialog."""
        guide_path = self._settings.project_root / "USER_GUIDE.md"
        if not guide_path.exists():
            QMessageBox.warning(
                self,
                "Help Contents",
                f"User guide not found:\n{guide_path}",
            )
            return
        try:
            text = guide_path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(
                self,
                "Help Contents",
                f"Could not read user guide: {e}",
            )
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("User Guide")
        dlg.setMinimumSize(700, 500)
        layout = QVBoxLayout(dlg)
        view = QPlainTextEdit(dlg)
        view.setPlainText(text)
        view.setReadOnly(True)
        layout.addWidget(view)
        close_btn = QPushButton("Close", dlg)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def _show_program_log(self) -> None:
        """Show program log file (senashipping.log) in a read-only dialog."""
        log_path = self._settings.data_dir / "senashipping.log"
        if not log_path.exists():
            QMessageBox.information(
                self,
                "Program Log",
                f"Log file not found yet:\n{log_path}\n\nIt will be created when the app has written log output.",
            )
            return
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(
                self,
                "Program Log",
                f"Could not read log file: {e}",
            )
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Program Log")
        dlg.setMinimumSize(700, 400)
        layout = QVBoxLayout(dlg)
        view = QPlainTextEdit(dlg)
        view.setPlainText(text)
        view.setReadOnly(True)
        layout.addWidget(view)
        close_btn = QPushButton("Close", dlg)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def _open_sena_website(self) -> None:
        """Open Sena Shipping website in default browser."""
        url = QUrl("https://senashipping.com/")
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "Sena Website",
                "Could not open the default browser.",
            )

    def _show_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Sena Marine",
            "<h2>Sena Marine</h2>"
            "<p>Version 1.0.0</p>"
            "<p>Maritime loading condition calculator for livestock carriers.</p>"
            "<p>&copy; 2026 Sena Marine</p>"
        )
