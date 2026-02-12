"""
Qt main window for the CargoMax desktop app.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
    QToolBar,
    QLabel,
    QStatusBar,
    QFrame,
    QStyle,
)

from ..config.settings import Settings
from .ship_manager_view import ShipManagerView
from .voyage_planner_view import VoyagePlannerView
from .condition_editor_view import ConditionEditorView
from .results_view import ResultsView


@dataclass
class _PageIndexes:
    ship_manager: int
    voyage_planner: int
    condition_editor: int
    results: int


class MainWindow(QMainWindow):
    """Main application window with navigation and central stacked views."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Osama bay app")
        self.resize(1200, 800)
        self.setWindowIcon(self.style().standardIcon(getattr(QStyle.StandardPixmap, "SP_ComputerIcon")))

        self._stack = QStackedWidget(self)
        self.setCentralWidget(self._stack)

        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)

        self._page_indexes = self._create_pages()
        self._create_menu()

        self._status_bar.showMessage("Ready")

    def _create_pages(self) -> _PageIndexes:
        """Create core application pages and add them to the stacked widget."""
        # Keep references to views to allow signal wiring between them
        self._ship_manager = ShipManagerView(self)
        self._voyage_planner = VoyagePlannerView(self)
        self._condition_editor = ConditionEditorView(self)
        self._results_view = ResultsView(self)

        ship_idx = self._stack.addWidget(self._ship_manager)
        voy_idx = self._stack.addWidget(self._voyage_planner)
        cond_idx = self._stack.addWidget(self._condition_editor)
        res_idx = self._stack.addWidget(self._results_view)

        # Default page
        self._stack.setCurrentIndex(ship_idx)

        pages = _PageIndexes(
            ship_manager=ship_idx,
            voyage_planner=voy_idx,
            condition_editor=cond_idx,
            results=res_idx,
        )

        # Wire condition editor to results view
        self._condition_editor.condition_computed.connect(
            self._results_view.update_results
        )

        # Wire voyage planner: when user clicks Edit Condition, switch to editor and load it
        self._voyage_planner.condition_selected.connect(
            self._on_condition_selected_from_voyage
        )

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
        new_action.triggered.connect(lambda: self._status_bar.showMessage("New Loading Condition"))
        file_menu.addAction(new_action)
        new_action.setShortcut("Ctrl+N")

        open_action = QAction("&Open Loading condition ...", self)
        open_action.triggered.connect(lambda: self._status_bar.showMessage("Open Loading Condition"))
        file_menu.addAction(open_action)
        open_action.setShortcut("Ctrl+O")

        open_recent_action = QAction("&Open Recent Loading conditions ...", self)
        open_recent_action.triggered.connect(lambda: self._status_bar.showMessage("Open Recent Loading Conditions"))
        file_menu.addAction(open_recent_action)

        open_standard_action = QAction("&Open Standard Loading conditions ...", self)
        open_standard_action.triggered.connect(lambda: self._status_bar.showMessage("Open Standard Loading Conditions"))
        file_menu.addAction(open_standard_action)

        file_menu.addSeparator()

        save_action = QAction("&Save Loading condition ...", self)
        save_action.triggered.connect(lambda: self._status_bar.showMessage("Save Loading Condition"))
        file_menu.addAction(save_action)
        save_action.setShortcut("Ctrl+S")

        save_as_action = QAction("&Save Loading condition As ...", self)
        save_as_action.triggered.connect(lambda: self._status_bar.showMessage("Save Loading Condition As"))
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        import_action = QAction("&Import from Excel ...", self)
        import_action.triggered.connect(lambda: self._status_bar.showMessage("Import from Excel"))
        file_menu.addAction(import_action)

        export_action = QAction("&Export to Excel ...", self)
        export_action.triggered.connect(lambda: self._status_bar.showMessage("Export to Excel"))
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        summary_action = QAction("&Summary Info ...", self)
        summary_action.triggered.connect(lambda: self._status_bar.showMessage("Summary Info"))
        file_menu.addAction(summary_action)

        program_notes_action = QAction("&Program Notes ...", self)
        program_notes_action.triggered.connect(lambda: self._status_bar.showMessage("Program Notes"))
        file_menu.addAction(program_notes_action)

        send_loading_condition_by_email_action = QAction("&Send Loading condition by email ...", self)
        send_loading_condition_by_email_action.triggered.connect(lambda: self._status_bar.showMessage("Send Loading Condition by Email"))
        file_menu.addAction(send_loading_condition_by_email_action)

        file_menu.addSeparator()

        print_action = QAction("&Print ...", self)
        print_action.triggered.connect(lambda: self._status_bar.showMessage("Print"))
        file_menu.addAction(print_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        #edit actions
        edit_item_action = QAction("&Edit item ...", self)
        edit_item_action.triggered.connect(lambda: self._status_bar.showMessage("Edit Item"))
        edit_menu.addAction(edit_item_action)

        delete_item_action = QAction("&Delete item(s) ...", self)
        delete_item_action.triggered.connect(lambda: self._status_bar.showMessage("Delete Item(s)"))
        edit_menu.addAction(delete_item_action)

        edit_menu.addSeparator()

        search_new_misc_weight_action = QAction("&Search item ...", self)
        search_new_misc_weight_action.triggered.connect(lambda: self._status_bar.showMessage("Search Item"))
        edit_menu.addAction(search_new_misc_weight_action)

        edit_menu.addSeparator()

        add_new_item_action = QAction("&Add new item ...", self)
        add_new_item_action.triggered.connect(lambda: self._status_bar.showMessage("Add New Item"))
        edit_menu.addAction(add_new_item_action)

        empty_space_action = QAction("&Empty space(s)...", self)
        empty_space_action.triggered.connect(lambda: self._status_bar.showMessage("Empty Space(s)"))
        edit_menu.addAction(empty_space_action)

        fill_space_action = QAction("&Fill space(s)...", self)
        fill_space_action.triggered.connect(lambda: self._status_bar.showMessage("Fill Space(s)"))
        edit_menu.addAction(fill_space_action)

        fill_spaces_action = QAction("&Fill spaces To..", self)
        fill_spaces_action.triggered.connect(lambda: self._status_bar.showMessage("Fill Spaces To.."))
        edit_menu.addAction(fill_spaces_action)

        edit_menu.addSeparator()

        select_all_action = QAction("&Select all", self)
        select_all_action.triggered.connect(lambda: self._status_bar.showMessage("Select All"))
        edit_menu.addAction(select_all_action)

        clear_selection_action = QAction("&Clear selection", self)
        clear_selection_action.triggered.connect(lambda: self._status_bar.showMessage("Clear Selection"))
        edit_menu.addAction(clear_selection_action)

        # View actions
        view_menu_action = QAction("&Default view model", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Default View Model"))
        view_menu.addAction(view_menu_action)

        view_menu_action = QAction("&Change layout", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Change Layout"))
        view_menu.addAction(view_menu_action)

        view_menu_action = QAction("&Maximize Active view...", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Maximize Active View"))
        view_menu.addAction(view_menu_action)

        view_menu_action = QAction("&Change Active view...", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Change Active View"))
        view_menu.addAction(view_menu_action)

        view_menu.addSeparator()

        view_menu_action = QAction("&Show Results Bar", self)
        view_menu_action.setCheckable(True)
        view_menu_action.setChecked(True)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Show Results Bar"))
        view_menu.addAction(view_menu_action)

        view_menu.addSeparator()

        view_menu_action = QAction("&Program Options", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Program Options"))
        view_menu.addAction(view_menu_action)

        view_menu_action = QAction("&Display Options", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Display Options"))
        view_menu.addAction(view_menu_action)

        view_menu_action = QAction("&Restore Default Workspace settings...", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Restore Default Workspace Settings"))
        view_menu.addAction(view_menu_action)

        view_menu_action = QAction("&Restore Default Units and Precision...", self)
        view_menu_action.triggered.connect(lambda: self._status_bar.showMessage("Restore Default Units and Precision"))
        view_menu.addAction(view_menu_action)

        # Tools actions
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
        update_calc_action.triggered.connect(
            lambda: self._status_bar.showMessage("Update Calculations")
        )
        tools_menu.addAction(update_calc_action)

        # Stop Calculations (Ctrl+F9)
        stop_calc_action = QAction("Stop Calculations", self)
        stop_calc_action.setShortcut("Ctrl+F9")
        stop_calc_action.triggered.connect(
            lambda: self._status_bar.showMessage("Stop Calculations")
        )
        tools_menu.addAction(stop_calc_action)

        tools_menu.addSeparator()

        # Remaining items
        items = [
            "Cargo Library...",
            "Observed Drafts...",
            "Draft Survey...",
            "Tank/Weight Transfer...",
            "Advanced Load/Discharge Sequencer...",
            "Load/Discharge/BWE Sequence...",
            "Ship Squat Entry...",
            "Hydrostatic Calculator...",
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
        take_snapshot_action.triggered.connect(
            lambda: self._status_bar.showMessage("Take Snapshot")
        )

        historian_menu.addAction(take_snapshot_action)

        historian_menu.addSeparator()

        field_selection_action = QAction("Field Selection...", self)
        field_selection_action.triggered.connect(
            lambda: self._status_bar.showMessage("Field Selection")
        )

        historian_menu.addAction(field_selection_action)
        visualize_date_action = QAction("Visualize Data...", self)
        visualize_date_action.triggered.connect(
            lambda: self._status_bar.showMessage("Visualize Data")
        )
        historian_menu.addAction(visualize_date_action)

        export_data_action = QAction("Export Data...", self)
        export_data_action.triggered.connect(
            lambda: self._status_bar.showMessage("Export Data")
        )
        historian_menu.addAction(export_data_action)

        # Help menu

        vessel_documentation_action = QAction("Vessel Documentation", self)
        vessel_documentation_action.triggered.connect(
            lambda: self._status_bar.showMessage("Vessel Documentation")
        )
        help_menu.addAction(vessel_documentation_action)

        help_menu.addSeparator()

        help_contents_action = QAction("Help Contents", self)
        help_contents_action.triggered.connect(
            lambda: self._status_bar.showMessage("Help Contents")
        )
        help_menu.addAction(help_contents_action)
        help_contents_action.setShortcut("F1")

        sena_website_action = QAction("Sena Website", self)
        sena_website_action.triggered.connect(
            lambda: self._status_bar.showMessage("Sena Website")
        )
        help_menu.addAction(sena_website_action)

        show_program_log_action = QAction("Show Program Log", self)
        show_program_log_action.triggered.connect(
            lambda: self._status_bar.showMessage("Show Program Log")
        )
        help_menu.addAction(show_program_log_action)

        help_menu.addSeparator()
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self) -> None:
        """Create a simple navigation toolbar."""
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(toolbar)

        def add_nav_button(text: str, page_index: int, status: str) -> None:
            action = toolbar.addAction(text)
            action.triggered.connect(lambda: self._switch_page(page_index, status))

        add_nav_button("Ship Manager", self._page_indexes.ship_manager, "Ship Manager")
        add_nav_button(
            "Voyage Planner", self._page_indexes.voyage_planner, "Voyage Planner"
        )
        add_nav_button(
            "Loading Condition",
            self._page_indexes.condition_editor,
            "Loading Condition",
        )
        add_nav_button("Results", self._page_indexes.results, "Results")

    def _switch_page(self, index: int, status_message: str) -> None:
        self._stack.setCurrentIndex(index)
        self._status_bar.showMessage(status_message)

    def _show_about(self) -> None:
        # Keep it lightweight for now – can replace with a dialog later
        self._status_bar.showMessage("CargoMax Desktop – Prototype", 5000)

