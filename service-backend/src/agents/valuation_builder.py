"""
Phase 2 — Valuation Sheets

Adds four sheets to the workbook:
  Sheet 8  — WACC & Cost of Capital
  Sheet 9  — DCF Valuation  (5-year FCF forecast + Terminal Value + Sensitivity)
  Sheet 10 — DDM Valuation  (Dividend Discount Model)
  Sheet 11 — Comparable Company Analysis (Comps template)

All inputs flow through the Settings sheet so the user only changes one place.
All computed cells use LIVE Excel formulas.
"""
from typing import List

import xlsxwriter

from config.settings import (
    CORPORATE_TAX_RATE,
    DEFAULT_BETA,
    EQUITY_RISK_PREMIUM,
    RISK_FREE_RATE,
    TERMINAL_GROWTH_RATE,
)
from utils.excel_styles import StyleBook
from utils.formula_registry import col_letter

# ── Sheet names ────────────────────────────────────────────────────────────────
SH_IS  = "Income Statement"
SH_BS  = "Balance Sheet"
SH_CF  = "Cash Flow"
SH_ST  = "Settings"
SH_WC  = "WACC"
SH_DCF = "DCF Valuation"
SH_DDM = "DDM Valuation"
SH_CMP = "Comps"

# ── Settings sheet row references (1-based, col B = index 1) ──────────────────
# These match the rows written by _build_settings() in excel_builder.py
ST_RF    = 2   # Risk-Free Rate
ST_ERP   = 3   # Equity Risk Premium
ST_BETA  = 4   # Beta
ST_TAX   = 5   # Tax Rate
ST_G     = 6   # Terminal Growth Rate
ST_KD    = 7   # Pre-Tax Cost of Debt
ST_KE    = 8   # Cost of Equity (formula)
ST_KD_AT = 9   # After-Tax Cost of Debt (formula)
ST_MCAP  = 11  # Market Cap input
ST_PRICE = 12  # Current Share Price input
ST_SH    = 13  # Shares Outstanding

# ── Income Statement row references (from excel_builder.IS dict) ───────────────
IS_REV    = 3
IS_EBITDA = 16
IS_EBIT   = 19
IS_PAT    = 25
IS_SHARES = 29
IS_DPS    = 31

# ── Balance Sheet row references (from excel_builder.BS dict) ─────────────────
BS_CASH  = 3
BS_STI   = 4
BS_TCA   = 8
BS_TA    = 20
BS_STB   = 23
BS_TCL   = 26
BS_LTD   = 29
BS_TE    = 39
BS_ND    = 44   # Net Debt (computed row)

# ── Cash Flow row references (from excel_builder.CF dict) ─────────────────────
CF_CFO  = 7
CF_FCF  = 28


def _xr(sheet: str, col: str, row: int) -> str:
    """Cross-sheet reference."""
    return f"'{sheet}'!{col}{row}"


def _latest_col(years: List[int]) -> str:
    """Excel column letter for the most-recent year (last data column)."""
    return col_letter(len(years) + 1)   # col A=labels, B=yr1, C=yr2, ...


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 8 — WACC & Cost of Capital
# ══════════════════════════════════════════════════════════════════════════════

def build_wacc_sheet(wb: xlsxwriter.Workbook, sty: StyleBook, years: List[int]):
    ws = wb.add_worksheet(SH_WC)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 40)
    ws.set_column(1, 1, 18)
    ws.set_column(2, 2, 42)

    lc = _latest_col(years)   # latest-year data column on IS/BS/CF sheets

    def lbl(r, text, fmt=None): ws.write(r - 1, 0, text, fmt or sty.line_label)
    def note(r, text):          ws.write(r - 1, 2, text, sty.line_label)
    def fml(r, formula, fmt=None): ws.write_formula(r - 1, 1, formula, fmt or sty.num)
    def inp(r, val, fmt=None):  ws.write_number(r - 1, 1, val, fmt or sty.input_cell)
    def sep(r): ws.set_row(r - 1, 6)

    ws.write(0, 0, "WACC & COST OF CAPITAL", sty.col_header)
    ws.write(0, 1, "Value", sty.col_header)
    ws.write(0, 2, "Notes", sty.col_header)

    # ── A. Cost of Equity ─────────────────────────────────────────────────────
    lbl(2, "A.  COST OF EQUITY  (CAPM)", sty.section_label)
    lbl(3, "Risk-Free Rate (Rf)")
    fml(3, f"='{SH_ST}'!B{ST_RF}", sty.pct)
    note(3, "Indian 10Y G-Sec — edit in Settings")

    lbl(4, "Equity Risk Premium (ERP)")
    fml(4, f"='{SH_ST}'!B{ST_ERP}", sty.pct)
    note(4, "Damodaran India ERP — edit in Settings")

    lbl(5, "Beta (β)")
    fml(5, f"='{SH_ST}'!B{ST_BETA}", sty.num)
    note(5, "Levered beta vs Nifty 50 — edit in Settings")

    lbl(6, "Cost of Equity  [Ke = Rf + β × ERP]", sty.subtotal_label)
    fml(6, f"=B3+B5*B4", sty.pct)
    note(6, "CAPM formula")
    sep(7)

    # ── B. Cost of Debt ───────────────────────────────────────────────────────
    lbl(8, "B.  COST OF DEBT", sty.section_label)

    lbl(9, "Total Debt (latest year)")
    fml(9, f"=('{SH_BS}'!{lc}{BS_LTD}+'{SH_BS}'!{lc}{BS_STB})", sty.num)
    note(9, "Long-term Debt + Short-term Borrowings")

    lbl(10, "Interest Expense (latest year)")
    fml(10, f"='{SH_IS}'!{lc}{IS_EBIT}-'{SH_IS}'!{lc}{IS_PAT}"
            f"-IFERROR('{SH_IS}'!{lc}22,0)", sty.num)  # rough proxy
    fml(10, f"='{SH_ST}'!B{ST_KD}*B9", sty.num)
    note(10, "Estimated: Pre-Tax Kd × Total Debt")

    lbl(11, "Pre-Tax Cost of Debt (Kd)")
    fml(11, f"='{SH_ST}'!B{ST_KD}", sty.pct)
    note(11, "Edit in Settings  (= Interest / Avg Debt)")

    lbl(12, "Corporate Tax Rate")
    fml(12, f"='{SH_ST}'!B{ST_TAX}", sty.pct)
    note(12, "Edit in Settings")

    lbl(13, "After-Tax Cost of Debt  [Kd × (1-t)]", sty.subtotal_label)
    fml(13, "=B11*(1-B12)", sty.pct)
    note(13, "Tax shield on interest")
    sep(14)

    # ── C. Capital Structure ──────────────────────────────────────────────────
    lbl(15, "C.  CAPITAL STRUCTURE", sty.section_label)

    lbl(16, "Market Capitalisation  (₹ Cr)")
    fml(16, f"='{SH_ST}'!B{ST_MCAP}", sty.num_int)
    note(16, "Enter in Settings → Market Cap cell")

    lbl(17, "Total Debt  (₹ Cr)")
    fml(17, "=B9", sty.num_int)

    lbl(18, "Cash & Short-Term Investments  (₹ Cr)")
    fml(18, f"=('{SH_BS}'!{lc}{BS_CASH}+'{SH_BS}'!{lc}{BS_STI})", sty.num_int)

    lbl(19, "Net Debt  (₹ Cr)")
    fml(19, "=B17-B18", sty.num_int)

    lbl(20, "Enterprise Value  [Market Cap + Net Debt]")
    fml(20, "=B16+B19", sty.num_int)
    note(20, "EV = Market Cap + Net Debt")

    lbl(21, "Equity Weight  [E / (E + D)]", sty.subtotal_label)
    fml(21, "=IFERROR(B16/(B16+B17),1)", sty.pct)

    lbl(22, "Debt Weight  [D / (E + D)]", sty.subtotal_label)
    fml(22, "=IFERROR(B17/(B16+B17),0)", sty.pct)
    sep(23)

    # ── D. WACC ───────────────────────────────────────────────────────────────
    lbl(24, "D.  WACC CALCULATION", sty.section_label)

    lbl(25, "WACC  =  Ke × (E/V)  +  Kd(1-t) × (D/V)", sty.subtotal_label)
    fml(25, "=B6*B21 + B13*B22", sty.pct)
    note(25, "Weighted Average Cost of Capital")
    sep(26)

    # ── E. Sanity Checks ──────────────────────────────────────────────────────
    lbl(27, "E.  SANITY CHECKS", sty.section_label)

    lbl(28, "WACC < Cost of Equity?  (must be TRUE)")
    fml(28, '=IF(B25<B6,"✓ TRUE — leverage reduces WACC","✗ FALSE — check inputs")',
        sty.pass_fmt)

    lbl(29, "WACC > Terminal Growth Rate?  (must be TRUE for DCF to work)")
    fml(29, f'=IF(B25>\'{SH_ST}\'!B{ST_G},'
            f'"✓ TRUE — DCF is valid","✗ FALSE — DCF will give negative value")',
        sty.pass_fmt)

    lbl(30, "EV / EBITDA  (market-implied multiple)")
    fml(30, f"=IFERROR(B20/'{SH_IS}'!{lc}{IS_EBITDA},0)", sty.num)
    note(30, "Cross-check against industry peers")

    return ws


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 9 — DCF Valuation
# ══════════════════════════════════════════════════════════════════════════════

def build_dcf_sheet(wb: xlsxwriter.Workbook, sty: StyleBook, years: List[int]):
    ws = wb.add_worksheet(SH_DCF)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 36)
    for c in range(1, 9):
        ws.set_column(c, c, 14)

    lc = _latest_col(years)
    n_hist = len(years)

    # Forecast columns: B=Yr1, C=Yr2, ..., F=Yr5, G=Terminal
    FCOLS = [col_letter(i + 2) for i in range(5)]   # B,C,D,E,F  (forecast years 1-5)
    TCOL  = col_letter(7)                             # G = Terminal

    def lbl(r, text, fmt=None):  ws.write(r - 1, 0, text, fmt or sty.line_label)
    def fml(r, c_idx, formula, fmt=None):
        ws.write_formula(r - 1, c_idx, formula, fmt or sty.num)
    def inp(r, c_idx, val, fmt=None):
        ws.write_number(r - 1, c_idx, val, fmt or sty.input_cell)
    def txt(r, c_idx, text, fmt=None):
        ws.write(r - 1, c_idx, text, fmt or sty.line_label)

    ws.write(0, 0, "DCF VALUATION — DISCOUNTED CASH FLOW MODEL", sty.col_header)
    for i, label in enumerate(["Year 1", "Year 2", "Year 3", "Year 4", "Year 5", "Terminal"]):
        ws.write(0, i + 1, label, sty.col_header)

    # ── A. Historical FCF (anchor) ─────────────────────────────────────────
    lbl(2, "A.  HISTORICAL FREE CASH FLOW  (₹ Cr)", sty.section_label)
    for i, yr in enumerate(years):
        col_i = col_letter(i + 2)   # B, C, D for years
        ws.write(1, i + 1, str(yr), sty.col_header_gold)
        fml(3, i + 1,
            f"='{SH_CF}'!{col_i}{CF_FCF}", sty.num)
    lbl(3, "Free Cash Flow (Historical)")
    ws.set_row(3, 6)   # small gap

    # ── B. Forecast Assumptions ────────────────────────────────────────────
    lbl(5, "B.  FORECAST ASSUMPTIONS  (edit yellow cells)", sty.section_label)
    lbl(6, "FCF Growth Rate — Year 1")
    lbl(7, "FCF Growth Rate — Year 2")
    lbl(8, "FCF Growth Rate — Year 3")
    lbl(9, "FCF Growth Rate — Year 4")
    lbl(10, "FCF Growth Rate — Year 5")
    lbl(11, "Terminal Growth Rate (g)")
    lbl(12, "WACC (from WACC sheet)")

    # Default growth rates (user edits)
    for row_i, rate in enumerate([0.12, 0.10, 0.09, 0.08, 0.07], start=6):
        inp(row_i, 1, rate, sty.input_cell)
    fml(11, 1, f"='{SH_ST}'!B{ST_G}", sty.pct)
    fml(12, 1, f"='{SH_WC}'!B25", sty.pct)
    ws.set_row(12, 6)

    # ── C. FCF Projections ─────────────────────────────────────────────────
    lbl(14, "C.  PROJECTED FREE CASH FLOW  (₹ Cr)", sty.section_label)
    lbl(15, "Base FCF (most recent year)")
    lbl(16, "Projected FCF")
    lbl(17, "FCF Growth Rate Applied")

    # Base FCF = most recent historical year
    base_col = col_letter(n_hist + 1)   # last historical year column on DCF sheet
    for fi, fc in enumerate(FCOLS):
        # Growth rate for this year is in B6, B7, ..., B10
        gr_ref = f"B{6 + fi}"
        if fi == 0:
            # Year 1: base = last historical FCF
            prev_fcf = f"='{SH_CF}'!{lc}{CF_FCF}"
            fml(15, fi + 1, prev_fcf, sty.num)
            fml(16, fi + 1, f"={fc}15*(1+{gr_ref})", sty.num_sub)
        else:
            prev_fc = FCOLS[fi - 1]
            fml(16, fi + 1, f"={prev_fc}16*(1+{gr_ref})", sty.num_sub)
        fml(17, fi + 1, f"={gr_ref}", sty.pct)

    # Terminal FCF = FCF(Year5) × (1 + g)
    fml(16, 6, f"=F16*(1+B11)", sty.num_sub)   # col G = index 6
    txt(17, 6, "Terminal year", sty.line_label)
    ws.set_row(17, 6)

    # ── D. Discounting & Valuation ─────────────────────────────────────────
    lbl(19, "D.  DISCOUNTING  (WACC = B12)", sty.section_label)
    lbl(20, "Discount Period (t)")
    lbl(21, "Discount Factor  [1/(1+WACC)^t]")
    lbl(22, "Present Value of FCF")
    lbl(23, "Terminal Value  [FCF(t+1) / (WACC - g)]")
    lbl(24, "PV of Terminal Value")

    for fi, fc in enumerate(FCOLS):
        t = fi + 1
        fml(20, fi + 1, f"={t}", sty.num_int)
        fml(21, fi + 1, f"=1/(1+$B$12)^{t}", sty.num)
        fml(22, fi + 1, f"={fc}16*{fc}21", sty.num)

    # Terminal Value in col G
    fml(23, 6, "=G16/(B12-B11)", sty.num_int)
    fml(21, 6, f"=1/(1+$B$12)^5", sty.num)   # TV discounted at year-5 factor
    fml(24, 6, "=G23*F21", sty.num_int)
    ws.set_row(24, 6)

    # Summary valuation
    lbl(26, "E.  INTRINSIC VALUATION  (₹ Cr)", sty.section_label)
    lbl(27, "Sum of PV of FCFs  (Years 1–5)")
    fml(27, 1, "=SUM(B22:F22)", sty.num_int)

    lbl(28, "PV of Terminal Value")
    fml(28, 1, "=G24", sty.num_int)

    lbl(29, "ENTERPRISE VALUE  (EV)", sty.subtotal_label)
    fml(29, 1, "=B27+B28", sty.num_int)

    lbl(30, "Less: Net Debt")
    fml(30, 1, f"='{SH_WC}'!B19", sty.num_int)

    lbl(31, "EQUITY VALUE", sty.subtotal_label)
    fml(31, 1, "=B29-B30", sty.num_int)

    lbl(32, "Shares Outstanding  (Mn)")
    fml(32, 1, f"='{SH_ST}'!B{ST_SH}", sty.num_int)

    lbl(33, "INTRINSIC VALUE PER SHARE  (₹)", sty.subtotal_label)
    fml(33, 1, "=IFERROR(B31/B32*100,0)", sty.num_int)
    ws.write(32, 2, "× 100 to convert Crores to per-share (shares in Mn)", sty.line_label)

    lbl(34, "Current Market Price  (₹)")
    fml(34, 1, f"='{SH_ST}'!B{ST_PRICE}", sty.num_int)

    lbl(35, "Implied Upside / (Downside)", sty.subtotal_label)
    fml(35, 1, "=IFERROR((B33-B34)/B34,0)", sty.pct)
    ws.set_row(35, 8)

    # ── E. Sensitivity Table ───────────────────────────────────────────────
    lbl(37, "F.  SENSITIVITY — Intrinsic Value per Share  (₹)", sty.section_label)
    ws.write(37, 0, "WACC →", sty.col_header)

    # WACC axis: WACC ± 2% in 1% steps → 5 columns
    wacc_offsets = [-0.02, -0.01, 0.00, 0.01, 0.02]
    g_offsets    = [-0.01, -0.005, 0.00, 0.005, 0.01]

    # Column headers = WACC values
    for ci, wo in enumerate(wacc_offsets):
        fml(38, ci + 1, f"='{SH_WC}'!B25+({wo})", sty.col_header_gold)

    # Row headers = g values
    ws.write(37, 0, "g ↓ \\ WACC →", sty.section_label)
    for ri, go in enumerate(g_offsets):
        fml(38 + ri + 1, 0, f"='{SH_ST}'!B{ST_G}+({go})", sty.pct)

        for ci, wo in enumerate(wacc_offsets):
            # Formula: FCF(Yr5+1) / (WACC_variant - g_variant) × PV factor / shares
            wacc_var = f"({col_letter(ci+2)}38)"
            g_var    = f"($A{38 + ri + 1})"
            fml(38 + ri + 1, ci + 1,
                f"=IFERROR("
                f"  (B27 + F16*(1+{g_var})/({wacc_var}-{g_var})/(1+{wacc_var})^5 - B30)"
                f"  / B32 * 100"
                f", 0)",
                sty.num_int)

    return ws


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 10 — DDM Valuation
# ══════════════════════════════════════════════════════════════════════════════

def build_ddm_sheet(wb: xlsxwriter.Workbook, sty: StyleBook, years: List[int]):
    ws = wb.add_worksheet(SH_DDM)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 36)
    for c in range(1, 9):
        ws.set_column(c, c, 14)

    lc = _latest_col(years)
    FCOLS = [col_letter(i + 2) for i in range(5)]

    def lbl(r, text, fmt=None):  ws.write(r - 1, 0, text, fmt or sty.line_label)
    def fml(r, c_idx, formula, fmt=None):
        ws.write_formula(r - 1, c_idx, formula, fmt or sty.num)
    def inp(r, c_idx, val, fmt=None):
        ws.write_number(r - 1, c_idx, val, fmt or sty.input_cell)

    ws.write(0, 0, "DDM VALUATION — DIVIDEND DISCOUNT MODEL", sty.col_header)
    for i, label in enumerate(["Year 1", "Year 2", "Year 3", "Year 4", "Year 5", "Terminal"]):
        ws.write(0, i + 1, label, sty.col_header)

    # ── A. Historical Dividends ─────────────────────────────────────────────
    lbl(2, "A.  HISTORICAL DIVIDENDS PER SHARE  (₹)", sty.section_label)
    for i, yr in enumerate(years):
        ws.write(1, i + 1, str(yr), sty.col_header_gold)
        fml(3, i + 1, f"='{SH_IS}'!{col_letter(i+2)}{IS_DPS}", sty.num)
    lbl(3, "Dividends Per Share (DPS)  — Historical")
    ws.set_row(3, 6)

    # ── B. Assumptions ─────────────────────────────────────────────────────
    lbl(5, "B.  ASSUMPTIONS  (edit yellow cells)", sty.section_label)
    lbl(6, "DPS Growth Rate — Years 1–3  (high growth)")
    lbl(7, "DPS Growth Rate — Years 4–5  (stable growth)")
    lbl(8, "Terminal Dividend Growth Rate (g)")
    lbl(9, "Cost of Equity  (Ke — required return)")

    inp(6, 1, 0.12, sty.input_cell)
    inp(7, 1, 0.08, sty.input_cell)
    fml(8, 1, f"='{SH_ST}'!B{ST_G}", sty.pct)
    fml(9, 1, f"='{SH_WC}'!B6", sty.pct)
    ws.set_row(9, 6)

    # ── C. DPS Projections ─────────────────────────────────────────────────
    lbl(11, "C.  PROJECTED DIVIDENDS PER SHARE  (₹)", sty.section_label)
    lbl(12, "Projected DPS")
    lbl(13, "Growth Rate Applied")

    for fi, fc in enumerate(FCOLS):
        gr_ref = "B6" if fi < 3 else "B7"
        if fi == 0:
            fml(12, fi + 1, f"='{SH_IS}'!{lc}{IS_DPS}*(1+{gr_ref})", sty.num_sub)
        else:
            prev_fc = FCOLS[fi - 1]
            fml(12, fi + 1, f"={prev_fc}12*(1+{gr_ref})", sty.num_sub)
        fml(13, fi + 1, f"={gr_ref}", sty.pct)

    # Terminal DPS
    fml(12, 6, "=F12*(1+B8)", sty.num_sub)
    ws.set_row(13, 6)

    # ── D. Discounting ─────────────────────────────────────────────────────
    lbl(15, "D.  DISCOUNTING  (Ke = B9)", sty.section_label)
    lbl(16, "Discount Factor  [1/(1+Ke)^t]")
    lbl(17, "PV of DPS")
    lbl(18, "Terminal Value  [DPS(t+1) / (Ke - g)]")
    lbl(19, "PV of Terminal Value")

    for fi, fc in enumerate(FCOLS):
        t = fi + 1
        fml(16, fi + 1, f"=1/(1+$B$9)^{t}", sty.num)
        fml(17, fi + 1, f"={fc}12*{fc}16", sty.num)

    fml(18, 6, "=G12/(B9-B8)", sty.num_int)
    fml(19, 6, "=G18*F16", sty.num_int)
    ws.set_row(19, 6)

    # ── E. DDM Intrinsic Value ──────────────────────────────────────────────
    lbl(21, "E.  DDM INTRINSIC VALUE", sty.section_label)
    lbl(22, "Sum of PV of Dividends  (Years 1–5)")
    fml(22, 1, "=SUM(B17:F17)", sty.num)

    lbl(23, "PV of Terminal Value")
    fml(23, 1, "=G19", sty.num_int)

    lbl(24, "INTRINSIC VALUE PER SHARE  (DDM)  (₹)", sty.subtotal_label)
    fml(24, 1, "=B22+B23", sty.num_int)

    lbl(25, "Current Market Price  (₹)")
    fml(25, 1, f"='{SH_ST}'!B{ST_PRICE}", sty.num_int)

    lbl(26, "Implied Upside / (Downside)", sty.subtotal_label)
    fml(26, 1, "=IFERROR((B24-B25)/B25,0)", sty.pct)

    lbl(27, "NOTE", sty.section_label)
    ws.write(26, 0, "NOTE", sty.section_label)
    ws.write(26, 1,
             "DDM is most reliable for mature, high-dividend companies. "
             "If DPS history is 0 or thin, use DCF instead.",
             sty.line_label)

    return ws


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 11 — Comparable Company Analysis (Comps)
# ══════════════════════════════════════════════════════════════════════════════

def build_comps_sheet(wb: xlsxwriter.Workbook, sty: StyleBook, years: List[int]):
    ws = wb.add_worksheet(SH_CMP)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 28)
    for c in range(1, 10):
        ws.set_column(c, c, 13)

    lc = _latest_col(years)

    def lbl(r, text, fmt=None):  ws.write(r - 1, 0, text, fmt or sty.line_label)
    def fml(r, c_idx, formula, fmt=None):
        ws.write_formula(r - 1, c_idx, formula, fmt or sty.num)
    def inp(r, c_idx, fmt=None):
        ws.write_blank(r - 1, c_idx, fmt or sty.input_cell_num)
    def hdr(r, c_idx, text):
        ws.write(r - 1, c_idx, text, sty.col_header)

    ws.write(0, 0, "COMPARABLE COMPANY ANALYSIS  (COMPS)", sty.col_header)

    # ── A. Our Company Metrics ─────────────────────────────────────────────
    lbl(2, "A.  OUR COMPANY METRICS  (auto-filled)", sty.section_label)

    metrics = [
        (3, "Revenue  (₹ Cr, LTM)",      f"='{SH_IS}'!{lc}{IS_REV}"),
        (4, "EBITDA  (₹ Cr, LTM)",        f"='{SH_IS}'!{lc}{IS_EBITDA}"),
        (5, "EBIT  (₹ Cr, LTM)",          f"='{SH_IS}'!{lc}19"),
        (6, "Net Income / PAT  (₹ Cr)",   f"='{SH_IS}'!{lc}{IS_PAT}"),
        (7, "EPS  (₹)",                   f"='{SH_IS}'!{lc}30"),
        (8, "Total Debt  (₹ Cr)",         f"=('{SH_BS}'!{lc}{BS_LTD}+'{SH_BS}'!{lc}{BS_STB})"),
        (9, "Cash  (₹ Cr)",               f"='{SH_BS}'!{lc}{BS_CASH}"),
        (10,"Market Cap  (₹ Cr)",         f"='{SH_ST}'!B{ST_MCAP}"),
        (11,"Enterprise Value  (₹ Cr)",   f"='{SH_WC}'!B20"),
        (12,"Shares Outstanding  (Mn)",   f"='{SH_ST}'!B{ST_SH}"),
    ]
    hdr(2, 1, "Value")
    for row, label, formula in metrics:
        lbl(row, label)
        fml(row, 1, formula, sty.num)

    ws.set_row(12, 8)

    # ── B. Peer Company Multiples ──────────────────────────────────────────
    lbl(14, "B.  PEER COMPANY MULTIPLES  (enter manually)", sty.section_label)
    peer_cols = range(1, 6)   # B through F = Peer 1-5
    peer_headers = [f"Peer {i}" for i in range(1, 6)] + ["Median", "Mean"]
    for i, ph in enumerate(peer_headers):
        ws.write(13, i + 1, ph, sty.col_header if i < 5 else sty.col_header_gold)

    multiple_rows = [
        (15, "EV / Revenue  (x)"),
        (16, "EV / EBITDA  (x)"),
        (17, "EV / EBIT  (x)"),
        (18, "Price / Earnings  (P/E)  (x)"),
        (19, "Price / Book  (P/B)  (x)"),
        (20, "Price / FCF  (x)"),
    ]
    for row, label in multiple_rows:
        lbl(row, label)
        for c in peer_cols:
            inp(row, c)
        # Median (col F = index 6) and Mean (col G = index 7)
        r_range = f"B{row}:F{row}"
        fml(row, 6, f"=MEDIAN({r_range})", sty.num)
        fml(row, 7, f"=AVERAGE({r_range})", sty.num)

    ws.set_row(20, 8)

    # ── C. Implied Valuations ──────────────────────────────────────────────
    lbl(22, "C.  IMPLIED VALUATION  (using Median multiples)", sty.section_label)
    hdr(22, 1, "Median Multiple")
    hdr(22, 2, "Our Metric")
    hdr(22, 3, "Implied EV / Price")
    hdr(22, 4, "Implied Share Price  (₹)")

    implied_rows = [
        (23, "EV / Revenue",  15, f"='{SH_IS}'!{lc}{IS_REV}",   True),
        (24, "EV / EBITDA",   16, f"='{SH_IS}'!{lc}{IS_EBITDA}", True),
        (25, "EV / EBIT",     17, f"='{SH_IS}'!{lc}19",           True),
        (26, "P / E  →  Price",18, f"='{SH_IS}'!{lc}30",          False),  # EPS-based
        (27, "P / FCF →  Price",20, f"='{SH_CF}'!{lc}{CF_FCF}",   False),
    ]

    for row, label, mult_row, metric_formula, is_ev_based in implied_rows:
        lbl(row, label)
        fml(row, 1, f"=G{mult_row}", sty.num)  # Median column
        fml(row, 2, metric_formula, sty.num)
        if is_ev_based:
            # Implied EV = Median × Our Metric
            fml(row, 3, f"=B{row}*C{row}", sty.num)
            # Implied Share Price = (Implied EV - Net Debt) / Shares × 100
            fml(row, 4,
                f"=IFERROR((D{row}-'{SH_WC}'!B19)/'{SH_ST}'!B{ST_SH}*100,0)",
                sty.num)
        else:
            # Price-based multiple: Implied Price = Multiple × EPS or FCF/share
            fml(row, 3, "—", sty.line_label)
            fml(row, 4, f"=IFERROR(B{row}*C{row},0)", sty.num)

    ws.set_row(27, 8)

    # ── D. Valuation Summary ───────────────────────────────────────────────
    lbl(29, "D.  VALUATION SUMMARY  (₹ per share)", sty.section_label)
    hdr(29, 1, "Method")
    hdr(29, 2, "Intrinsic Value  (₹)")

    summary = [
        (30, "DCF Valuation",    f"='{SH_DCF}'!B33"),
        (31, "DDM Valuation",    f"='{SH_DDM}'!B24"),
        (32, "EV/Revenue Comps", f"=D23"),
        (33, "EV/EBITDA Comps",  f"=D24"),
        (34, "P/E Comps",        f"=D26"),
    ]
    for row, label, formula in summary:
        ws.write(row - 1, 1, label, sty.line_label)
        fml(row, 2, formula, sty.num)

    lbl(35, "Low  (Min across methods)")
    fml(35, 2, "=MIN(C30:C34)", sty.num_sub)
    lbl(36, "High  (Max across methods)")
    fml(36, 2, "=MAX(C30:C34)", sty.num_sub)
    lbl(37, "Central Estimate  (Median)")
    fml(37, 2, "=MEDIAN(C30:C34)", sty.num_sub)
    lbl(38, "Current Market Price  (₹)")
    fml(38, 2, f"='{SH_ST}'!B{ST_PRICE}", sty.num)
    lbl(39, "Implied Upside to Central  (%)", sty.subtotal_label)
    fml(39, 2, "=IFERROR((C37-C38)/C38,0)", sty.pct)

    return ws
