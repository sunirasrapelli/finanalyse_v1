"""
Phase 3 — Charts

Adds two sheets to the workbook:
  Sheet 12 — Chart Data  (hidden helper sheet with clean data ranges)
  Sheet 13 — Charts      (6 embedded professional charts)

Charts included:
  1. Revenue / EBITDA / PAT Trend          (clustered column)
  2. Margin Trends                          (line — Gross, EBITDA, Net)
  3. Cash Flow Breakdown                    (clustered column — CFO / CFI / CFF)
  4. FCF vs PAT                             (column)
  5. Return Metrics — ROE / ROA / ROCE     (line)
  6. Capital Structure — Equity vs Debt    (stacked bar)
"""
from typing import List

import xlsxwriter

from utils.excel_styles import StyleBook
from utils.formula_registry import col_letter

# ── Sheet name constants ───────────────────────────────────────────────────────
SH_IS  = "Income Statement"
SH_BS  = "Balance Sheet"
SH_CF  = "Cash Flow"
SH_RT  = "Ratios"
SH_CD  = "Chart Data"      # hidden helper
SH_CH  = "Charts"

# ── Source row references ─────────────────────────────────────────────────────
IS_REV      = 3
IS_EBITDA   = 16
IS_PAT      = 25
IS_GROSS_M  = 15
IS_EBITDA_M = 17
IS_NET_M    = 26

CF_CFO   = 7
CF_CFI   = 14
CF_CFF   = 22
CF_FCF   = 28

BS_TE  = 39
BS_ND  = 44

# Ratios sheet rows (from excel_builder.R dict)
RT_ROE  = 13
RT_ROA  = 14
RT_ROCE = 15
RT_DE   = 18


# ══════════════════════════════════════════════════════════════════════════════
# Helper: Chart Data sheet
# ══════════════════════════════════════════════════════════════════════════════

# Row layout on Chart Data sheet (1-based)
CD = {
    "years":    1,   # Year labels
    "rev":      2,
    "ebitda":   3,
    "pat":      4,
    "gross_m":  5,
    "ebitda_m": 6,
    "net_m":    7,
    "cfo":      8,
    "cfi":      9,
    "cff":      10,
    "fcf":      11,
    "roe":      12,
    "roa":      13,
    "roce":     14,
    "equity":   15,
    "net_debt": 16,
}

LABELS = {
    "rev":      "Revenue (₹ Cr)",
    "ebitda":   "EBITDA (₹ Cr)",
    "pat":      "PAT / Net Income (₹ Cr)",
    "gross_m":  "Gross Margin %",
    "ebitda_m": "EBITDA Margin %",
    "net_m":    "Net Profit Margin %",
    "cfo":      "Cash from Operations",
    "cfi":      "Cash from Investing",
    "cff":      "Cash from Financing",
    "fcf":      "Free Cash Flow",
    "roe":      "ROE %",
    "roa":      "ROA %",
    "roce":     "ROCE %",
    "equity":   "Total Equity",
    "net_debt": "Net Debt",
}

SOURCE_MAP = {
    "rev":      (SH_IS, IS_REV),
    "ebitda":   (SH_IS, IS_EBITDA),
    "pat":      (SH_IS, IS_PAT),
    "gross_m":  (SH_IS, IS_GROSS_M),
    "ebitda_m": (SH_IS, IS_EBITDA_M),
    "net_m":    (SH_IS, IS_NET_M),
    "cfo":      (SH_CF, CF_CFO),
    "cfi":      (SH_CF, CF_CFI),
    "cff":      (SH_CF, CF_CFF),
    "fcf":      (SH_CF, CF_FCF),
    "roe":      (SH_RT, RT_ROE),
    "roa":      (SH_RT, RT_ROA),
    "roce":     (SH_RT, RT_ROCE),
    "equity":   (SH_BS, BS_TE),
    "net_debt": (SH_BS, BS_ND),
}


def _build_chart_data(wb: xlsxwriter.Workbook, sty: StyleBook,
                      years: List[int]) -> xlsxwriter.Workbook:
    """Build a hidden helper sheet with clean data ranges for charts."""
    ws = wb.add_worksheet(SH_CD)
    ws.hide()

    bold = wb.add_format({"bold": True})

    # Column A: labels
    ws.write(0, 0, "Metric", bold)
    for key, label in LABELS.items():
        ws.write(CD[key] - 1, 0, label)

    # Year headers and data (one column per year)
    for i, yr in enumerate(years):
        col = i + 1
        cx = col_letter(col + 1)   # data col on source sheets (B=yr1, C=yr2 ...)
        ws.write(0, col, str(yr), bold)

        for key, (sheet, src_row) in SOURCE_MAP.items():
            formula = f"='{sheet}'!{cx}{src_row}"
            ws.write_formula(CD[key] - 1, col, formula)

    return ws


# ══════════════════════════════════════════════════════════════════════════════
# Chart factory helpers
# ══════════════════════════════════════════════════════════════════════════════

def _series_range(years: List[int], key: str) -> dict:
    """Build an xlsxwriter series dict for a Chart Data row."""
    n = len(years)
    last_col = col_letter(n + 1)   # last data col letter
    return {
        "name":       [SH_CD, CD[key] - 1, 0],
        "categories": [SH_CD, 0, 1, 0, n],       # year headers
        "values":     [SH_CD, CD[key] - 1, 1, CD[key] - 1, n],
    }


def _chart_base(wb, chart_type: str, subtype: str = None) -> xlsxwriter.chart.Chart:
    kwargs = {"type": chart_type}
    if subtype:
        kwargs["subtype"] = subtype
    return wb.add_chart(kwargs)


def _style_chart(chart, title: str, y_label: str = "", percent: bool = False):
    chart.set_title({"name": title, "name_font": {"bold": True, "size": 12}})
    chart.set_x_axis({"name": "", "num_font": {"size": 9}})
    chart.set_y_axis({
        "name": y_label,
        "num_format": "0%" if percent else "#,##0",
        "num_font": {"size": 9},
        "name_font": {"size": 9},
    })
    chart.set_legend({"position": "bottom", "font": {"size": 9}})
    chart.set_chartarea({"border": {"none": True}})
    chart.set_plotarea({"border": {"color": "#DDDDDD"}})
    chart.set_size({"width": 480, "height": 288})


COLORS = {
    "navy":      "#1F3864",
    "gold":      "#C9A84C",
    "teal":      "#17A589",
    "red":       "#E74C3C",
    "gray":      "#95A5A6",
    "light_blue":"#AED6F1",
}


# ══════════════════════════════════════════════════════════════════════════════
# Charts sheet
# ══════════════════════════════════════════════════════════════════════════════

def build_charts_sheet(wb: xlsxwriter.Workbook, sty: StyleBook, years: List[int]):
    """Build the Chart Data helper sheet and the Charts display sheet."""
    _build_chart_data(wb, sty, years)

    ws = wb.add_worksheet(SH_CH)
    ws.hide_gridlines(2)
    ws.set_zoom(85)
    ws.write(0, 0, "CHARTS & VISUALISATIONS", sty.col_header)
    ws.merge_range("A1:P1", "CHARTS & VISUALISATIONS", sty.col_header)

    # ── Chart 1: Revenue / EBITDA / PAT Trend ─────────────────────────────
    c1 = _chart_base(wb, "column")
    for key, color in [("rev", COLORS["navy"]),
                       ("ebitda", COLORS["gold"]),
                       ("pat", COLORS["teal"])]:
        s = _series_range(years, key)
        s["fill"] = {"color": color}
        s["gap"] = 150
        c1.add_series(s)
    _style_chart(c1, "Revenue / EBITDA / PAT Trend  (₹ Cr)", "₹ Crores")
    ws.insert_chart("B3", c1, {"x_offset": 0, "y_offset": 0})

    # ── Chart 2: Margin Trends ────────────────────────────────────────────
    c2 = _chart_base(wb, "line")
    for key, color in [("gross_m",  COLORS["navy"]),
                       ("ebitda_m", COLORS["gold"]),
                       ("net_m",    COLORS["teal"])]:
        s = _series_range(years, key)
        s["line"] = {"color": color, "width": 2.5}
        s["marker"] = {"type": "circle", "size": 6, "fill": {"color": color}}
        c2.add_series(s)
    _style_chart(c2, "Margin Trends", "%", percent=True)
    ws.insert_chart("J3", c2, {"x_offset": 0, "y_offset": 0})

    # ── Chart 3: Cash Flow Breakdown ──────────────────────────────────────
    c3 = _chart_base(wb, "column", "clustered")
    for key, color in [("cfo", COLORS["teal"]),
                       ("cfi", COLORS["red"]),
                       ("cff", COLORS["gray"])]:
        s = _series_range(years, key)
        s["fill"] = {"color": color}
        c3.add_series(s)
    _style_chart(c3, "Cash Flow Breakdown  (₹ Cr)", "₹ Crores")
    ws.insert_chart("B22", c3, {"x_offset": 0, "y_offset": 0})

    # ── Chart 4: FCF vs PAT ───────────────────────────────────────────────
    c4 = _chart_base(wb, "column", "clustered")
    for key, color in [("fcf", COLORS["navy"]),
                       ("pat", COLORS["gold"])]:
        s = _series_range(years, key)
        s["fill"] = {"color": color}
        c4.add_series(s)
    _style_chart(c4, "Free Cash Flow vs PAT  (₹ Cr)", "₹ Crores")
    ws.insert_chart("J22", c4, {"x_offset": 0, "y_offset": 0})

    # ── Chart 5: Return Metrics ───────────────────────────────────────────
    c5 = _chart_base(wb, "line")
    for key, color in [("roe",  COLORS["navy"]),
                       ("roa",  COLORS["gold"]),
                       ("roce", COLORS["teal"])]:
        s = _series_range(years, key)
        s["line"] = {"color": color, "width": 2.5}
        s["marker"] = {"type": "diamond", "size": 7,
                        "fill": {"color": color}, "border": {"color": color}}
        c5.add_series(s)
    _style_chart(c5, "Return Metrics — ROE / ROA / ROCE", "%", percent=True)
    ws.insert_chart("B41", c5, {"x_offset": 0, "y_offset": 0})

    # ── Chart 6: Capital Structure — Equity vs Net Debt ───────────────────
    c6 = _chart_base(wb, "bar", "stacked")
    for key, color in [("equity",   COLORS["navy"]),
                       ("net_debt", COLORS["red"])]:
        s = _series_range(years, key)
        s["fill"] = {"color": color}
        c6.add_series(s)
    _style_chart(c6, "Capital Structure — Equity vs Net Debt  (₹ Cr)", "₹ Crores")
    ws.insert_chart("J41", c6, {"x_offset": 0, "y_offset": 0})

    return ws
