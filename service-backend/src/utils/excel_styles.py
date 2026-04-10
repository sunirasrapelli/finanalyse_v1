"""
xlsxwriter format objects for the financial analysis workbook.
All formats are created once from a Workbook and reused across sheets.
"""
import xlsxwriter

from config.settings import (
    COLOR_FAIL_RED,
    COLOR_GOLD,
    COLOR_LIGHT_BLUE,
    COLOR_NAVY,
    COLOR_PASS_GREEN,
    COLOR_SECTION_GRAY,
    COLOR_WHITE,
)


class StyleBook:
    """Factory for all xlsxwriter Format objects used in the workbook."""

    def __init__(self, wb: xlsxwriter.Workbook):
        self.wb = wb
        self._build()

    def _fmt(self, props: dict):
        return self.wb.add_format(props)

    def _build(self):
        # ── Header / Title ────────────────────────────────────────────────────
        self.title = self._fmt({
            "bold": True, "font_size": 16,
            "font_color": COLOR_NAVY, "align": "center", "valign": "vcenter",
        })
        self.subtitle = self._fmt({
            "bold": True, "font_size": 11,
            "font_color": COLOR_NAVY, "align": "center",
        })

        # ── Column Headers (navy bg, white text) ─────────────────────────────
        self.col_header = self._fmt({
            "bold": True, "font_size": 10,
            "bg_color": COLOR_NAVY, "font_color": COLOR_WHITE,
            "align": "center", "valign": "vcenter",
            "border": 1, "border_color": "#FFFFFF",
            "text_wrap": True,
        })
        self.col_header_gold = self._fmt({
            "bold": True, "font_size": 10,
            "bg_color": COLOR_GOLD, "font_color": COLOR_WHITE,
            "align": "center", "valign": "vcenter",
            "border": 1,
        })

        # ── Section Labels (indented, gray bg) ───────────────────────────────
        self.section_label = self._fmt({
            "bold": True, "font_size": 10,
            "bg_color": COLOR_SECTION_GRAY, "font_color": COLOR_NAVY,
            "left": 2, "left_color": COLOR_NAVY,
        })
        self.line_label = self._fmt({
            "font_size": 10, "indent": 1,
            "bg_color": COLOR_WHITE,
        })
        self.line_label_alt = self._fmt({
            "font_size": 10, "indent": 1,
            "bg_color": COLOR_LIGHT_BLUE,
        })
        self.subtotal_label = self._fmt({
            "bold": True, "font_size": 10, "indent": 0,
            "bg_color": COLOR_LIGHT_BLUE,
            "top": 1, "bottom": 1,
        })

        # ── Number Formats ────────────────────────────────────────────────────
        _num_base = {"font_size": 10, "num_format": "#,##0.00", "align": "right"}
        _num_alt = {**_num_base, "bg_color": COLOR_LIGHT_BLUE}
        _num_sub = {**_num_base, "bold": True, "bg_color": COLOR_LIGHT_BLUE,
                    "top": 1, "bottom": 1}
        _num_neg = {**_num_base, "font_color": "red"}

        self.num = self._fmt(_num_base)
        self.num_alt = self._fmt(_num_alt)
        self.num_sub = self._fmt(_num_sub)
        self.num_neg = self._fmt(_num_neg)

        # Large integers (shares outstanding, market cap)
        self.num_int = self._fmt({**_num_base, "num_format": "#,##0"})

        # ── Percentage Formats ────────────────────────────────────────────────
        _pct_base = {"font_size": 10, "num_format": "0.0%", "align": "right"}
        self.pct = self._fmt(_pct_base)
        self.pct_alt = self._fmt({**_pct_base, "bg_color": COLOR_LIGHT_BLUE})
        self.pct_sub = self._fmt({**_pct_base, "bold": True,
                                  "bg_color": COLOR_LIGHT_BLUE,
                                  "top": 1, "bottom": 1})
        self.pct_growth_pos = self._fmt({**_pct_base, "font_color": "#006100"})
        self.pct_growth_neg = self._fmt({**_pct_base, "font_color": "red"})

        # ── Verification Status ───────────────────────────────────────────────
        self.pass_fmt = self._fmt({
            "bold": True, "font_size": 10,
            "bg_color": COLOR_PASS_GREEN, "font_color": "#276221",
            "align": "center", "border": 1,
        })
        self.fail_fmt = self._fmt({
            "bold": True, "font_size": 10,
            "bg_color": COLOR_FAIL_RED, "font_color": "#9C0006",
            "align": "center", "border": 1,
        })
        self.warn_fmt = self._fmt({
            "bold": True, "font_size": 10,
            "bg_color": "#FFEB9C", "font_color": "#9C6500",
            "align": "center", "border": 1,
        })

        # ── Settings / Input Cells ────────────────────────────────────────────
        self.input_cell = self._fmt({
            "font_size": 10, "bg_color": "#FFFFC0",
            "border": 1, "border_color": COLOR_GOLD,
            "num_format": "0.0%",
        })
        self.input_cell_num = self._fmt({
            "font_size": 10, "bg_color": "#FFFFC0",
            "border": 1, "border_color": COLOR_GOLD,
            "num_format": "#,##0.00",
        })

        # ── Cover Page ────────────────────────────────────────────────────────
        self.cover_title = self._fmt({
            "bold": True, "font_size": 20,
            "font_color": COLOR_NAVY, "align": "center", "valign": "vcenter",
        })
        self.cover_sub = self._fmt({
            "font_size": 13, "font_color": COLOR_GOLD,
            "align": "center", "valign": "vcenter",
        })
        self.cover_body = self._fmt({
            "font_size": 11, "font_color": COLOR_NAVY,
            "align": "center",
        })
        self.cover_link = self._fmt({
            "font_size": 11, "font_color": "#0563C1",
            "underline": True, "align": "left",
        })
        self.cover_footer = self._fmt({
            "font_size": 9, "italic": True, "font_color": "#808080",
            "align": "center",
        })
