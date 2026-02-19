"""
Results panel widget for displaying calculated condition parameters.

Shows real-time calculation results with color-coded status indicators.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QSizePolicy,
)

from ..services.stability_service import ConditionResults


class StatusLabel(QLabel):
    """Label with color-coded status indicator."""
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumWidth(120)  # Reduced to fit within panel
        self.setMinimumWidth(100)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.setWordWrap(False)
        self.setTextFormat(Qt.TextFormat.PlainText)
        
    def set_status(self, text: str, is_ok: bool = True) -> None:
        """Set text with green (OK) or red (warning/error) color."""
        # Elide text if too long to prevent overflow
        font_metrics = self.fontMetrics()
        elided_text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, self.maximumWidth())
        self.setText(elided_text)
        if is_ok:
            self.setStyleSheet("color: #27ae60; font-weight: bold;")  # Green
        else:
            self.setStyleSheet("color: #c0392b; font-weight: bold;")  # Red


class ResultsPanel(QWidget):
    """
    Right-side panel displaying calculated condition parameters.
    
    Shows displacement, drafts, trim, heel, GM, and other stability
    parameters with color-coded status indicators.
    """
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setMaximumWidth(300)  # Reduced maximum width
        # Prevent widget from expanding beyond window
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        
        # Status labels
        self._calc_status_label = StatusLabel(self)
        self._calc_method_label = StatusLabel(self)
        
        # Parameter labels
        self._sea_sg_label = QLabel(self)
        self._displacement_label = StatusLabel(self)
        self._avail_dwt_label = StatusLabel(self)
        self._draft_aft_label = StatusLabel(self)
        self._draft_mid_label = StatusLabel(self)
        self._draft_fwd_label = StatusLabel(self)
        self._trim_label = StatusLabel(self)
        self._heel_label = StatusLabel(self)
        self._prop_imm_label = StatusLabel(self)
        self._vis_margin_label = StatusLabel(self)
        self._gmt_label = StatusLabel(self)
        self._gmt_margin_label = StatusLabel(self)
        self._max_bmom_label = StatusLabel(self)
        self._max_shear_label = StatusLabel(self)
        self._air_draft_label = StatusLabel(self)
        
        self._build_layout()
        self._clear_all()
        
    def _build_layout(self) -> None:
        """Build the vertical layout with all parameter rows."""
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 8, 6, 8)  # Reduced side margins
        
        def add_row(label_text: str, value_label: QLabel) -> None:
            """Helper to add a label-value row."""
            row = QHBoxLayout()
            row.setSpacing(6)  # Reduced spacing
            row.setContentsMargins(0, 0, 0, 0)  # No extra margins
            label = QLabel(label_text, self)
            label.setMinimumWidth(130)  # Reduced minimum width
            label.setMaximumWidth(150)  # Reduced maximum width
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            label.setWordWrap(False)
            row.addWidget(label)
            row.addWidget(value_label, 0)  # Fixed width label, no stretch
            layout.addLayout(row)
        
        # Calculation Status
        add_row("Calculation Status:", self._calc_status_label)
        add_row("Calculation Method:", self._calc_method_label)
        
        # Separator
        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)
        
        add_row("Sea Specific Gravity:", self._sea_sg_label)
        add_row("Displacement:", self._displacement_label)
        add_row("Avail Deadweight:", self._avail_dwt_label)
        add_row("Draft at Marks - Aft:", self._draft_aft_label)
        add_row("Draft at Marks - Mid:", self._draft_mid_label)
        add_row("Draft at Marks - Fwd:", self._draft_fwd_label)
        add_row("Trim at Marks:", self._trim_label)
        add_row("Heel Angle:", self._heel_label)
        add_row("Prop Immersion:", self._prop_imm_label)
        add_row("Vis. Margin:", self._vis_margin_label)
        add_row("GMt:", self._gmt_label)
        add_row("GMt Margin:", self._gmt_margin_label)
        add_row("Max BMom %Allow:", self._max_bmom_label)
        add_row("Max Shear %Allow:", self._max_shear_label)
        add_row("Air Draft:", self._air_draft_label)
        
        layout.addStretch()
        
    def _clear_all(self) -> None:
        """Clear all values."""
        self._calc_status_label.setText("—")
        self._calc_method_label.setText("—")
        self._sea_sg_label.setText("—")
        self._displacement_label.setText("—")
        self._avail_dwt_label.setText("—")
        self._draft_aft_label.setText("—")
        self._draft_mid_label.setText("—")
        self._draft_fwd_label.setText("—")
        self._trim_label.setText("—")
        self._heel_label.setText("—")
        self._prop_imm_label.setText("—")
        self._vis_margin_label.setText("—")
        self._gmt_label.setText("—")
        self._gmt_margin_label.setText("—")
        self._max_bmom_label.setText("—")
        self._max_shear_label.setText("—")
        self._air_draft_label.setText("—")
        
    def update_results(self, results: ConditionResults, ship_dwt: float = 0.0) -> None:
        """
        Update panel with calculation results.
        
        Args:
            results: The computed condition results
            ship_dwt: Ship's deadweight capacity (for available DWT calculation)
        """
        # Calculation Status
        validation = getattr(results, "validation", None)
        has_errors = getattr(validation, "has_errors", False) if validation else False
        has_warnings = getattr(validation, "has_warnings", False) if validation else False
        
        # Check for zero displacement (no cargo loaded)
        if results.displacement_t < 0.001:  # Essentially zero
            self._calc_status_label.set_status("NO CARGO", False)
        elif has_errors:
            self._calc_status_label.set_status("FAILED", False)
        elif has_warnings:
            self._calc_status_label.set_status("WARNING", False)
        else:
            self._calc_status_label.set_status("OK", True)
            
        self._calc_method_label.set_status("Intact", True)
        
        # Sea Specific Gravity (standard seawater)
        self._sea_sg_label.setText("1.02500")
        
        # Displacement
        disp_str = f"{results.displacement_t:,.2f} MT"
        self._displacement_label.set_status(disp_str, True)
        
        # Available Deadweight
        avail_dwt = max(0.0, ship_dwt - results.displacement_t) if ship_dwt > 0 else 0.0
        avail_dwt_str = f"{avail_dwt:,.2f} MT"
        self._avail_dwt_label.set_status(avail_dwt_str, avail_dwt >= 0)
        
        # Drafts
        draft_aft = getattr(results, "draft_aft_m", results.draft_m + results.trim_m / 2)
        draft_fwd = getattr(results, "draft_fwd_m", results.draft_m - results.trim_m / 2)
        
        self._draft_aft_label.set_status(f"{draft_aft:.3f} m", True)
        self._draft_mid_label.set_status(f"{results.draft_m:.3f} m", True)
        
        # Forward draft might be problematic if too low
        draft_fwd_ok = draft_fwd >= 0.0
        self._draft_fwd_label.set_status(f"{draft_fwd:.3f} m", draft_fwd_ok)
        
        # Trim
        trim_str = f"{results.trim_m:.3f}A m" if results.trim_m >= 0 else f"{abs(results.trim_m):.3f}F m"
        self._trim_label.set_status(trim_str, True)
        
        # Heel
        heel = getattr(results, "heel_deg", 0.0)
        heel_ok = abs(heel) < 5.0  # Consider >5° as warning
        heel_str = f"{abs(heel):.2f}{'S' if heel >= 0 else 'P'} deg"
        self._heel_label.set_status(heel_str, heel_ok)
        
        # Prop Immersion
        ancillary = getattr(results, "ancillary", None)
        if ancillary:
            prop_imm = getattr(ancillary, "prop_immersion_pct", 0.0)
            prop_imm_str = f"{prop_imm:.2f} %"
            prop_imm_ok = prop_imm >= 100.0  # 100%+ is good
            self._prop_imm_label.set_status(prop_imm_str, prop_imm_ok)
        else:
            self._prop_imm_label.setText("—")
            
        # Visibility Margin
        if ancillary:
            vis_margin = getattr(ancillary, "visibility_m", 0.0)
            vis_margin_str = f"{vis_margin:.3f} m"
            vis_margin_ok = vis_margin >= 0.0
            self._vis_margin_label.set_status(vis_margin_str, vis_margin_ok)
        else:
            self._vis_margin_label.setText("—")
            
        # GMt
        gm_display = getattr(validation, "gm_effective", results.gm_m) if validation else results.gm_m
        gmt_str = f"{gm_display:.3f} m"
        gmt_ok = gm_display > 0.0
        self._gmt_label.set_status(gmt_str, gmt_ok)
        
        # GMt Margin (simplified - would need ship-specific limits)
        self._gmt_margin_label.setText("N/A")
        
        # Max BMom %Allow
        strength = getattr(results, "strength", None)
        if strength and hasattr(strength, "bm_pct_allow"):
            bm_pct = strength.bm_pct_allow
            bm_str = f"{bm_pct:.2f} %"
            bm_ok = -100 <= bm_pct <= 100
            self._max_bmom_label.set_status(bm_str, bm_ok)
        else:
            self._max_bmom_label.setText("—")
            
        # Max Shear %Allow
        if strength and hasattr(strength, "sf_pct_allow"):
            sf_pct = strength.sf_pct_allow
            sf_str = f"{sf_pct:.2f} %"
            sf_ok = -100 <= sf_pct <= 100
            self._max_shear_label.set_status(sf_str, sf_ok)
        else:
            self._max_shear_label.setText("—")
            
        # Air Draft
        if ancillary:
            air_draft = getattr(ancillary, "air_draft_m", 0.0)
            air_draft_str = f"{air_draft:.3f} m"
            self._air_draft_label.set_status(air_draft_str, True)
        else:
            self._air_draft_label.setText("—")
