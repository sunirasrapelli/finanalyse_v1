"""
New Excel Sheet Builders — 5 additional sheets for the 19-sheet workbook.

  - Common Size     (Sheet 5)  — IS as % of Revenue; BS as % of Total Assets
  - Forecasting     (Sheet 7)  — WMA 5-year projection (Revenue, EBITDA, EBT, PAT, EPS)
  - Beta Regression (Sheet 8)  — 2-year weekly returns vs NIFTY 50; Blume-adjusted beta
  - VaR & Simulation(Sheet 13) — Historical VaR (4 levels) + Monte Carlo 10,000-path summary
  - DuPont Analysis (Sheet 14) — 3-factor ROE decomposition; all years; Mean/Median columns

Conventions (mirrors excel_builder.py):
  - Row maps use 1-based row numbers; xlsxwriter calls subtract 1.
  - All formulas via formula_registry or inline string construction.
  - All formats from StyleBook — never hardcoded.
  - yfinance-dependent sheets gracefully degrade to N/A placeholders.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional

import numpy as np
import xlsxwriter

from agents.excel_builder import (
    BS, CF, IS,
    SH_BS, SH_CF, SH_IS,
    _data_cols, _write_val,
)
from utils.excel_styles import StyleBook
from utils.formula_registry import col_letter, xref
from utils.logger import get_logger

log = get_logger(__name__)

# ── New sheet name constants ──────────────────────────────────────────────────
SH_CS  = "Common Size"
SH_FC  = "Forecasting"
SH_BR  = "Beta Regression"
SH_VAR = "VaR & Simulation"
SH_DP  = "DuPont Analysis"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _xc(col_idx: int) -> str:
    """0-based column index → Excel column letter."""
    return col_letter(col_idx + 1)


def _get_close(df: Any):
    """Extract closing price series from a yfinance DataFrame (handles multi-index)."""
    for col_name in ("Adj Close", "Close"):
        if col_name in df.columns:
            s = df[col_name]
            if hasattr(s, "squeeze"):
                s = s.squeeze()
            return s
    # Multi-level columns (newer yfinance)
    try:
        return df.xs("Adj Close", axis=1, level=0).squeeze()
    except Exception:
        pass
    try:
        return df.xs("Close", axis=1, level=0).squeeze()
    except Exception:
        pass
    return df.iloc[:, 0].squeeze()


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 5 — Common Size
# ─────────────────────────────────────────────────────────────────────────────

def build_common_size_sheet(
    wb: xlsxwriter.Workbook,
    sty: StyleBook,
    years: List[int],
) -> None:
    """IS every line item as % of Revenue; BS every line item as % of Total Assets."""
    ws = wb.add_worksheet(SH_CS)
    ws.freeze_panes(2, 1)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 36)

    data_cols = _data_cols(years)
    for i, yr in enumerate(years):
        ws.set_column(data_cols[i], data_cols[i], 14)
        ws.write(0, data_cols[i], str(yr), sty.col_header)
    ws.write(0, 0, "COMMON SIZE ANALYSIS", sty.col_header)

    def lbl(row: int, text: str, fmt=None) -> None:
        ws.write(row - 1, 0, text, fmt or sty.line_label)

    def cs_fml(row: int, col_idx: int, src_sheet: str, val_row: int, base_row: int, fmt=None) -> None:
        cx = _xc(col_idx)
        formula = (
            f"=IFERROR('{src_sheet}'!{cx}{val_row}"
            f"/'{src_sheet}'!{cx}${base_row},0)"
        )
        ws.write_formula(row - 1, col_idx, formula, fmt or sty.pct)

    # ── Income Statement section ──────────────────────────────────────────────
    IS_BASE = IS["revenue"]  # denominator: Revenue row

    lbl(2, "INCOME STATEMENT (% of Revenue)", sty.section_label)
    is_items = [
        (IS["revenue"],      "Revenue",                        True),
        (IS["other_income"], "Other Income",                   False),
        (IS["total_income"], "Total Income",                   True),
        (IS["cogs"],         "COGS / Cost of Revenue",         False),
        (IS["employee"],     "Employee Expenses",              False),
        (IS["other_opex"],   "Other Operating Expenses",       False),
        (IS["total_opex"],   "Total Operating Expenses",       True),
        (IS["gross_profit"], "Gross Profit",                   True),
        (IS["ebitda"],       "EBITDA",                         True),
        (IS["da"],           "Depreciation & Amortisation",    False),
        (IS["ebit"],         "EBIT",                           True),
        (IS["interest"],     "Interest / Finance Costs",       False),
        (IS["pbt"],          "PBT",                            True),
        (IS["tax"],          "Tax Expense",                    False),
        (IS["pat"],          "PAT (Net Profit)",               True),
    ]

    for offset, (is_row, label, is_sub) in enumerate(is_items):
        sheet_row = 3 + offset
        lbl(sheet_row, "  " + label,
            sty.subtotal_label if is_sub else sty.line_label)
        for c in data_cols:
            cs_fml(sheet_row, c, SH_IS, is_row, IS_BASE,
                   sty.pct_sub if is_sub else sty.pct)

    # ── Balance Sheet section ─────────────────────────────────────────────────
    BS_BASE = BS["total_assets"]
    bs_start = 3 + len(is_items) + 2

    lbl(bs_start, "BALANCE SHEET (% of Total Assets)", sty.section_label)
    bs_items = [
        (BS["cash"],         "Cash & Cash Equivalents",          False),
        (BS["sti"],          "Short-Term Investments",           False),
        (BS["receivables"],  "Receivables",                      False),
        (BS["inventory"],    "Inventory",                        False),
        (BS["other_ca"],     "Other Current Assets",             False),
        (BS["total_ca"],     "Total Current Assets",             True),
        (BS["net_fa"],       "Net Fixed Assets",                 False),
        (BS["lt_invest"],    "Long-Term Investments",            False),
        (BS["other_nca"],    "Other Non-Current Assets",         False),
        (BS["total_nca"],    "Total Non-Current Assets",         True),
        (BS["total_assets"], "TOTAL ASSETS",                     True),
        (BS["total_cl"],     "Total Current Liabilities",        True),
        (BS["total_ncl"],    "Total Non-Current Liabilities",    True),
        (BS["total_liab"],   "Total Liabilities",                True),
        (BS["total_equity"], "Total Equity",                     True),
        (BS["total_le"],     "Total Liabilities + Equity",       True),
    ]

    for offset, (bs_row, label, is_sub) in enumerate(bs_items):
        sheet_row = bs_start + 1 + offset
        lbl(sheet_row, "  " + label,
            sty.subtotal_label if is_sub else sty.line_label)
        for c in data_cols:
            cs_fml(sheet_row, c, SH_BS, bs_row, BS_BASE,
                   sty.pct_sub if is_sub else sty.pct)


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 7 — Forecasting
# ─────────────────────────────────────────────────────────────────────────────

def _wma_growth(values: List[Optional[float]],
                weights: tuple = (0.5, 0.3, 0.2)) -> float:
    """Weighted moving average of period-over-period growth rates."""
    clean = [v for v in values if v is not None and v > 0]
    if len(clean) < 2:
        return 0.08

    growth_rates = [
        (clean[i] - clean[i - 1]) / clean[i - 1]
        for i in range(1, len(clean))
        if clean[i - 1] > 0
    ]
    if not growth_rates:
        return 0.08

    n = min(len(growth_rates), len(weights))
    recent = growth_rates[-n:]
    w = list(weights[:n])
    total_w = sum(w[:len(recent)])
    if total_w == 0:
        return 0.08

    wma = sum(wt * g for wt, g in zip(w, recent)) / total_w
    return max(min(wma, 0.35), -0.20)


def _project(last_val: Optional[float], growth: float, n: int = 5) -> List[Optional[float]]:
    if last_val is None:
        return [None] * n
    result, v = [], last_val
    for _ in range(n):
        v = v * (1 + growth)
        result.append(round(v, 2))
    return result


def build_forecasting_sheet(
    wb: xlsxwriter.Workbook,
    sty: StyleBook,
    years: List[int],
    income_stmts: list,
) -> None:
    """5-year WMA-based forward projections for Revenue, EBITDA, EBT, PAT, EPS."""
    ws = wb.add_worksheet(SH_FC)
    ws.freeze_panes(2, 1)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 36)

    data_cols = _data_cols(years)
    FORECAST_N = 5
    last_year = years[-1] if years else 2024
    fc_cols = [data_cols[-1] + 1 + i for i in range(FORECAST_N)]

    ws.write(0, 0, "FORECASTING (WMA 5-YEAR PROJECTION)", sty.col_header)
    for i, yr in enumerate(years):
        ws.set_column(data_cols[i], data_cols[i], 14)
        ws.write(0, data_cols[i], str(yr), sty.col_header)
    for i, c in enumerate(fc_cols):
        ws.set_column(c, c, 14)
        ws.write(0, c, f"E{last_year + 1 + i}", sty.col_header_gold)

    # Historical series
    rev_hist    = [s.revenue for s in income_stmts]
    ebitda_hist = [s.ebitda  for s in income_stmts]
    pbt_hist    = [s.pbt     for s in income_stmts]
    pat_hist    = [s.pat     for s in income_stmts]
    eps_hist    = [s.eps_basic or s.eps_diluted for s in income_stmts]

    def last_val(lst):
        return next((v for v in reversed(lst) if v is not None), None)

    rev_g    = _wma_growth(rev_hist)
    ebitda_g = _wma_growth(ebitda_hist)
    pbt_g    = _wma_growth(pbt_hist)
    pat_g    = _wma_growth(pat_hist)
    eps_g    = _wma_growth(eps_hist)

    rev_fc    = _project(last_val(rev_hist),    rev_g)
    ebitda_fc = _project(last_val(ebitda_hist), ebitda_g)
    pbt_fc    = _project(last_val(pbt_hist),    pbt_g)
    pat_fc    = _project(last_val(pat_hist),    pat_g)
    eps_fc    = _project(last_val(eps_hist),    eps_g)

    def write_hist_ref(row: int, is_row: int, fmt) -> None:
        """Write cross-sheet references for historical columns."""
        for c in data_cols:
            cx = _xc(c)
            ws.write_formula(row - 1, c,
                f"=IFERROR('{SH_IS}'!{cx}{is_row},\"\")", fmt)

    def write_fc_vals(row: int, fc_vals: List, fmt) -> None:
        """Write Python-computed forecast values."""
        for i, c in enumerate(fc_cols):
            v = fc_vals[i] if fc_vals and i < len(fc_vals) else None
            if v is not None:
                ws.write_number(row - 1, c, v, fmt)
            else:
                ws.write(row - 1, c, "N/A", sty.line_label)

    def write_margin_row(row: int, num_row: int, den_row: int) -> None:
        """Inline margin % for both historical and forecast."""
        all_cols = data_cols + fc_cols
        for c in all_cols:
            cx = _xc(c)
            ws.write_formula(row - 1, c,
                f"=IFERROR({cx}{num_row}/{cx}{den_row},0)", sty.pct)

    def write_yoy_row(row: int, above_row: int) -> None:
        """YoY growth % across historical + forecast columns."""
        all_cols = data_cols + fc_cols
        for i in range(1, len(all_cols)):
            c    = all_cols[i]
            prev = all_cols[i - 1]
            cx   = _xc(c)
            cxp  = _xc(prev)
            ws.write_formula(row - 1, c,
                f"=IFERROR(({cx}{above_row}-{cxp}{above_row})/ABS({cxp}{above_row}),0)",
                sty.pct_growth_pos)

    r = 2
    R = {}

    # Revenue
    ws.write(r - 1, 0, "REVENUE", sty.section_label); r += 1
    R["rev"] = r
    ws.write(r - 1, 0, "Revenue", sty.subtotal_label)
    write_hist_ref(r, IS["revenue"], sty.num_sub)
    write_fc_vals(r, rev_fc, sty.num_sub); r += 1
    R["rev_yoy"] = r
    ws.write(r - 1, 0, "  YoY Growth %", sty.line_label)
    write_yoy_row(r, R["rev"]); r += 1

    # EBITDA
    ws.write(r - 1, 0, "EBITDA", sty.section_label); r += 1
    R["ebitda"] = r
    ws.write(r - 1, 0, "EBITDA", sty.subtotal_label)
    write_hist_ref(r, IS["ebitda"], sty.num_sub)
    write_fc_vals(r, ebitda_fc, sty.num_sub); r += 1
    R["ebitda_m"] = r
    ws.write(r - 1, 0, "  EBITDA Margin %", sty.line_label)
    write_margin_row(r, R["ebitda"], R["rev"]); r += 1

    # PBT
    ws.write(r - 1, 0, "PBT / EBT", sty.section_label); r += 1
    R["pbt"] = r
    ws.write(r - 1, 0, "Profit Before Tax (EBT)", sty.subtotal_label)
    write_hist_ref(r, IS["pbt"], sty.num_sub)
    write_fc_vals(r, pbt_fc, sty.num_sub); r += 1
    R["pbt_m"] = r
    ws.write(r - 1, 0, "  PBT Margin %", sty.line_label)
    write_margin_row(r, R["pbt"], R["rev"]); r += 1

    # PAT
    ws.write(r - 1, 0, "PAT / NET PROFIT", sty.section_label); r += 1
    R["pat"] = r
    ws.write(r - 1, 0, "Net Profit (PAT)", sty.subtotal_label)
    write_hist_ref(r, IS["pat"], sty.num_sub)
    write_fc_vals(r, pat_fc, sty.num_sub); r += 1
    R["pat_m"] = r
    ws.write(r - 1, 0, "  Net Margin %", sty.line_label)
    write_margin_row(r, R["pat"], R["rev"]); r += 1

    # EPS
    ws.write(r - 1, 0, "EPS", sty.section_label); r += 1
    R["eps"] = r
    ws.write(r - 1, 0, "EPS (Basic)", sty.subtotal_label)
    write_hist_ref(r, IS["eps"], sty.num_sub)
    write_fc_vals(r, eps_fc, sty.num_sub); r += 1

    # WMA assumptions footnote
    r += 1
    ws.write(r - 1, 0, "WMA GROWTH ASSUMPTIONS (Applied)", sty.section_label); r += 1
    for label, g in [
        ("Revenue CAGR (WMA)", rev_g),
        ("EBITDA CAGR (WMA)",  ebitda_g),
        ("PAT CAGR (WMA)",     pat_g),
        ("EPS CAGR (WMA)",     eps_g),
    ]:
        ws.write(r - 1, 0, f"  {label}", sty.line_label)
        ws.write_number(r - 1, 1, g, sty.pct)
        r += 1

    # Revenue bar chart: actuals (navy) vs forecast (gold)
    chart = wb.add_chart({"type": "column"})
    chart.add_series({
        "name": "Historical",
        "categories": [SH_FC, 0, data_cols[0], 0, data_cols[-1]],
        "values":     [SH_FC, R["rev"] - 1, data_cols[0], R["rev"] - 1, data_cols[-1]],
        "fill": {"color": "#1F3864"},
    })
    chart.add_series({
        "name": "Forecast",
        "categories": [SH_FC, 0, fc_cols[0], 0, fc_cols[-1]],
        "values":     [SH_FC, R["rev"] - 1, fc_cols[0], R["rev"] - 1, fc_cols[-1]],
        "fill": {"color": "#C9A84C"},
    })
    chart.set_title({"name": "Revenue — Actuals vs WMA Forecast"})
    chart.set_size({"width": 500, "height": 300})
    chart.set_legend({"position": "bottom"})
    ws.insert_chart(r + 1, 0, chart)


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 8 — Beta Regression
# ─────────────────────────────────────────────────────────────────────────────

def build_beta_regression_sheet(
    wb: xlsxwriter.Workbook,
    sty: StyleBook,
    years: List[int],
    ticker: Optional[str] = None,
    weekly_stock: Optional[Any] = None,
    weekly_nifty: Optional[Any] = None,
) -> None:
    """OLS beta from 2-year weekly returns vs NIFTY 50; Blume adjustment."""
    ws = wb.add_worksheet(SH_BR)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 30)
    ws.set_column(1, 5, 16)

    ws.write(0, 0, "BETA REGRESSION ANALYSIS", sty.col_header)
    ws.merge_range("B1:F1",
        "2-Year Weekly Returns vs NIFTY 50 | OLS Beta | Blume Adjustment",
        sty.subtitle)

    def lbl(row: int, text: str, fmt=None) -> None:
        ws.write(row - 1, 0, text, fmt or sty.line_label)

    def wv(row: int, col: int, value, fmt=None) -> None:
        if value is None:
            ws.write(row - 1, col, "N/A", sty.line_label)
        elif isinstance(value, str):
            ws.write(row - 1, col, value, fmt or sty.line_label)
        else:
            ws.write_number(row - 1, col, value, fmt or sty.num)

    # Parameters
    lbl(3, "PARAMETERS", sty.section_label)
    lbl(4, "  Ticker");    ws.write(3, 1, ticker or "Not provided", sty.line_label)
    lbl(5, "  Index");     ws.write(4, 1, "NIFTY 50 (^NSEI)", sty.line_label)
    lbl(6, "  Frequency"); ws.write(5, 1, "Weekly", sty.line_label)
    lbl(7, "  Period");    ws.write(6, 1, "2 Years", sty.line_label)

    raw_beta: Optional[float] = None
    adj_beta: Optional[float] = None
    r_squared: Optional[float] = None
    n_points: int = 0

    if weekly_stock is not None and weekly_nifty is not None and ticker:
        try:
            s_close = _get_close(weekly_stock).dropna()
            n_close = _get_close(weekly_nifty).dropna()

            common_idx = s_close.index.intersection(n_close.index)
            s_r = s_close.loc[common_idx].pct_change().dropna()
            n_r = n_close.loc[common_idx].pct_change().dropna()

            common2 = s_r.index.intersection(n_r.index)
            s_arr = s_r.loc[common2].values.astype(float)
            n_arr = n_r.loc[common2].values.astype(float)

            if len(s_arr) >= 10:
                n_points = len(s_arr)
                cov_mat = np.cov(s_arr, n_arr)
                raw_beta = float(cov_mat[0, 1] / cov_mat[1, 1])
                adj_beta = 0.67 * raw_beta + 0.33
                corr = float(np.corrcoef(s_arr, n_arr)[0, 1])
                r_squared = corr ** 2

                # Write raw return data (capped at 104 weeks)
                data_row = 17
                ws.write(data_row - 1, 0, "Date",         sty.col_header)
                ws.write(data_row - 1, 1, "Stock Return",  sty.col_header)
                ws.write(data_row - 1, 2, "NIFTY Return",  sty.col_header)

                s_series = s_r.loc[common2]
                n_series = n_r.loc[common2]
                for k, date in enumerate(common2[:104]):
                    ws.write(data_row + k, 0, str(date.date()), sty.line_label)
                    ws.write_number(data_row + k, 1, float(s_series.loc[date]), sty.pct)
                    ws.write_number(data_row + k, 2, float(n_series.loc[date]), sty.pct)

        except Exception as exc:
            log.warning(f"Beta regression computation failed: {exc}")

    # Results
    lbl(9,  "RESULTS",               sty.section_label)
    lbl(10, "  Data Points (weeks)"); ws.write(9,  1, n_points if n_points else "N/A", sty.line_label)
    lbl(11, "  Raw Beta (OLS)");      wv(11, 1, raw_beta,   sty.num)
    lbl(12, "  Blume-Adjusted β");    wv(12, 1, adj_beta,   sty.num)
    lbl(13, "  R-Squared");           wv(13, 1, r_squared,  sty.num)

    # Interpretation row
    lbl(15, "INTERPRETATION", sty.section_label)
    if adj_beta is not None:
        if adj_beta > 1.2:
            interp = f"β = {adj_beta:.2f} — High market sensitivity (aggressive stock; amplifies market moves)"
        elif adj_beta >= 0.8:
            interp = f"β = {adj_beta:.2f} — Market-like risk profile (moves broadly in line with NIFTY 50)"
        else:
            interp = f"β = {adj_beta:.2f} — Defensive stock (lower volatility than the broader market)"
        ws.merge_range("A16:F16", interp, sty.line_label_alt)
    else:
        ws.merge_range("A16:F16",
            "β could not be computed — ticker not provided or data unavailable. "
            "Enter beta manually in the Settings sheet.",
            sty.warn_fmt)

    # Blume formula note
    lbl(18, "BLUME ADJUSTMENT FORMULA", sty.section_label)
    ws.merge_range("A19:F19",
        "β_adj = 0.67 × β_raw  +  0.33 × 1.0   "
        "(Blume 1971: adjusts raw OLS beta toward market mean of 1.0)",
        sty.line_label_alt)
    if adj_beta is not None:
        lbl(20, "  Verification:")
        ws.write_formula(19, 1, "=0.67*B11+0.33", sty.num)
        ws.write(19, 2, "← should match Blume-Adjusted β above", sty.line_label)


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 13 — VaR & Simulation
# ─────────────────────────────────────────────────────────────────────────────

def build_var_simulation_sheet(
    wb: xlsxwriter.Workbook,
    sty: StyleBook,
    years: List[int],
    ticker: Optional[str] = None,
    daily_stock: Optional[Any] = None,
) -> None:
    """Historical VaR (4 confidence levels) + Monte Carlo 10,000-path summary + histogram."""
    ws = wb.add_worksheet(SH_VAR)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 36)
    ws.set_column(1, 4, 18)

    ws.write(0, 0, "VaR & MONTE CARLO SIMULATION", sty.col_header)
    ws.merge_range("B1:E1",
        f"Ticker: {ticker or 'N/A'}  |  2-Year Daily Returns  |  10,000 MC Paths",
        sty.subtitle)

    def lbl(row: int, text: str, fmt=None) -> None:
        ws.write(row - 1, 0, text, fmt or sty.line_label)

    def wn(row: int, col: int, value: Optional[float], fmt=None) -> None:
        if value is not None:
            ws.write_number(row - 1, col, value, fmt or sty.pct)
        else:
            ws.write(row - 1, col, "N/A", sty.line_label)

    mc: dict = {}

    if daily_stock is not None and ticker:
        try:
            prices = _get_close(daily_stock).dropna()
            daily_returns = prices.pct_change().dropna().values.astype(float)

            if len(daily_returns) >= 20:
                mu    = float(np.mean(daily_returns))
                sigma = float(np.std(daily_returns, ddof=1))

                mc = {
                    "n_days":       len(daily_returns),
                    "mu_daily":     mu,
                    "sigma_daily":  sigma,
                    "sigma_annual": sigma * math.sqrt(252),
                    "var90":        float(np.percentile(daily_returns, 10)),
                    "var95":        float(np.percentile(daily_returns, 5)),
                    "var99":        float(np.percentile(daily_returns, 1)),
                    "var995":       float(np.percentile(daily_returns, 0.5)),
                    "_returns":     daily_returns,
                }

                # Monte Carlo GBM
                np.random.seed(42)
                n_sims = 10_000
                log_shocks = np.random.normal(
                    mu - 0.5 * sigma ** 2,
                    sigma,
                    (n_sims, 252),
                )
                final_rets = np.exp(log_shocks.sum(axis=1)) - 1

                below_95 = final_rets[final_rets <= np.percentile(final_rets, 5)]
                mc.update({
                    "mc_mean":   float(np.mean(final_rets)),
                    "mc_median": float(np.median(final_rets)),
                    "mc_var95":  float(np.percentile(final_rets, 5)),
                    "mc_cvar95": float(below_95.mean()) if len(below_95) else None,
                    "mc_p25":    float(np.percentile(final_rets, 25)),
                    "mc_p75":    float(np.percentile(final_rets, 75)),
                })

        except Exception as exc:
            log.warning(f"VaR computation failed: {exc}")

    r = 3

    # Daily return statistics
    lbl(r, "DAILY RETURN STATISTICS", sty.section_label)
    ws.write(r - 1, 1, "Value", sty.col_header); r += 1
    lbl(r, "  Trading Days in Sample")
    ws.write(r - 1, 1, mc.get("n_days", "N/A"), sty.num_int if mc.get("n_days") else sty.line_label); r += 1
    lbl(r, "  Mean Daily Return");      wn(r, 1, mc.get("mu_daily"));    r += 1
    lbl(r, "  Daily Volatility (σ)");   wn(r, 1, mc.get("sigma_daily")); r += 1
    lbl(r, "  Annualised Volatility");  wn(r, 1, mc.get("sigma_annual")); r += 1

    r += 1
    lbl(r, "HISTORICAL VaR (Daily Loss at Confidence Level)", sty.section_label)
    ws.write(r - 1, 1, "Daily VaR", sty.col_header); r += 1
    lbl(r, "  VaR 90%  (10th percentile)");  wn(r, 1, mc.get("var90"));  r += 1
    lbl(r, "  VaR 95%  (5th percentile)");   wn(r, 1, mc.get("var95"));  r += 1
    lbl(r, "  VaR 99%  (1st percentile)");   wn(r, 1, mc.get("var99"));  r += 1
    lbl(r, "  VaR 99.5% (0.5th percentile)"); wn(r, 1, mc.get("var995")); r += 1

    r += 1
    lbl(r, "MONTE CARLO SIMULATION (10,000 paths, 252 trading days)", sty.section_label)
    ws.write(r - 1, 1, "Annual Return", sty.col_header); r += 1
    lbl(r, "  Expected Return (mean)");         wn(r, 1, mc.get("mc_mean"));   r += 1
    lbl(r, "  Median Return");                  wn(r, 1, mc.get("mc_median")); r += 1
    lbl(r, "  VaR 95% — 5th percentile");       wn(r, 1, mc.get("mc_var95")); r += 1
    lbl(r, "  CVaR 95% (Expected Shortfall)");  wn(r, 1, mc.get("mc_cvar95")); r += 1
    lbl(r, "  P25 Outcome");                    wn(r, 1, mc.get("mc_p25"));   r += 1
    lbl(r, "  P75 Outcome");                    wn(r, 1, mc.get("mc_p75"));   r += 1

    # Histogram of daily returns
    r += 2
    lbl(r, "RETURN DISTRIBUTION — Daily Returns Histogram (30 bins)", sty.section_label)
    ws.write(r - 1, 1, "Bin Low",   sty.col_header)
    ws.write(r - 1, 2, "Bin High",  sty.col_header)
    ws.write(r - 1, 3, "Count",     sty.col_header)
    ws.write(r - 1, 4, "Freq %",    sty.col_header)
    r += 1

    hist_start = r
    n_bins = 30

    if "_returns" in mc and len(mc["_returns"]) >= 20:
        counts, edges = np.histogram(mc["_returns"], bins=n_bins)
        total = len(mc["_returns"])
        for i in range(n_bins):
            ws.write_number(r - 1, 1, float(edges[i]),       sty.pct)
            ws.write_number(r - 1, 2, float(edges[i + 1]),   sty.pct)
            ws.write_number(r - 1, 3, int(counts[i]),        sty.num_int)
            ws.write_number(r - 1, 4, float(counts[i]/total), sty.pct)
            r += 1

        chart = wb.add_chart({"type": "column"})
        chart.add_series({
            "name":       "Frequency",
            "categories": [SH_VAR, hist_start - 1, 1, hist_start + n_bins - 2, 1],
            "values":     [SH_VAR, hist_start - 1, 4, hist_start + n_bins - 2, 4],
            "fill":       {"color": "#1F3864"},
            "gap":        10,
        })
        chart.set_title({"name": "Daily Return Distribution"})
        chart.set_x_axis({"name": "Daily Return"})
        chart.set_y_axis({"name": "Frequency (%)"})
        chart.set_size({"width": 500, "height": 300})
        ws.insert_chart(r + 1, 0, chart)
    else:
        ws.merge_range(f"A{r}:E{r}",
            "No price data — provide ticker symbol to compute VaR & run simulation.",
            sty.warn_fmt)


# ─────────────────────────────────────────────────────────────────────────────
# Sheet 14 — DuPont Analysis
# ─────────────────────────────────────────────────────────────────────────────

def build_dupont_sheet(
    wb: xlsxwriter.Workbook,
    sty: StyleBook,
    years: List[int],
) -> None:
    """3-factor ROE decomposition: Net Margin × Asset Turnover × Equity Multiplier."""
    ws = wb.add_worksheet(SH_DP)
    ws.freeze_panes(2, 1)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 40)

    data_cols = _data_cols(years)
    n = len(years)
    mean_col = data_cols[-1] + 1
    med_col  = data_cols[-1] + 2

    for i, yr in enumerate(years):
        ws.set_column(data_cols[i], data_cols[i], 14)
        ws.write(0, data_cols[i], str(yr), sty.col_header)
    ws.set_column(mean_col, med_col, 14)
    ws.write(0, mean_col, "Mean",   sty.col_header_gold)
    ws.write(0, med_col,  "Median", sty.col_header_gold)
    ws.write(0, 0, "DUPONT ANALYSIS", sty.col_header)

    def lbl(row: int, text: str, fmt=None) -> None:
        ws.write(row - 1, 0, text, fmt or sty.line_label)

    def fp(row: int, col_idx: int, formula: str) -> None:
        ws.write_formula(row - 1, col_idx, formula, sty.pct)

    def fn(row: int, col_idx: int, formula: str) -> None:
        ws.write_formula(row - 1, col_idx, formula, sty.num)

    def fp_sub(row: int, col_idx: int, formula: str) -> None:
        ws.write_formula(row - 1, col_idx, formula, sty.pct_sub)

    def fn_sub(row: int, col_idx: int, formula: str) -> None:
        ws.write_formula(row - 1, col_idx, formula, sty.num_sub)

    def agg_pct(row: int) -> None:
        sc = col_letter(data_cols[0] + 1)
        ec = col_letter(data_cols[-1] + 1)
        ws.write_formula(row - 1, mean_col, f"=IFERROR(AVERAGE({sc}{row}:{ec}{row}),0)", sty.pct_sub)
        ws.write_formula(row - 1, med_col,  f"=IFERROR(MEDIAN({sc}{row}:{ec}{row}),0)",  sty.pct_sub)

    def agg_num(row: int) -> None:
        sc = col_letter(data_cols[0] + 1)
        ec = col_letter(data_cols[-1] + 1)
        ws.write_formula(row - 1, mean_col, f"=IFERROR(AVERAGE({sc}{row}:{ec}{row}),0)", sty.num_sub)
        ws.write_formula(row - 1, med_col,  f"=IFERROR(MEDIAN({sc}{row}:{ec}{row}),0)",  sty.num_sub)

    R: dict = {}
    r = 2

    # ── 3-Factor ROE ──────────────────────────────────────────────────────────
    lbl(r, "3-FACTOR ROE DECOMPOSITION", sty.section_label); r += 1
    lbl(r, "ROE  =  Net Margin  ×  Asset Turnover  ×  Equity Multiplier",
        sty.line_label_alt); r += 1

    r += 1
    R["nm"] = r
    lbl(r, "  Net Margin  (PAT / Revenue)")
    for c in data_cols:
        cx = _xc(c)
        fp(r, c, f"=IFERROR('{SH_IS}'!{cx}{IS['pat']}/'{SH_IS}'!{cx}{IS['revenue']},0)")
    agg_pct(r); r += 1

    R["at"] = r
    lbl(r, "  Asset Turnover  (Revenue / Average Total Assets)")
    for i, c in enumerate(data_cols):
        cx = _xc(c)
        if i == 0:
            fn(r, c,
               f"=IFERROR('{SH_IS}'!{cx}{IS['revenue']}"
               f"/'{SH_BS}'!{cx}{BS['total_assets']},0)")
        else:
            prev_c  = data_cols[i - 1]
            prev_cx = _xc(prev_c)
            fn(r, c,
               f"=IFERROR('{SH_IS}'!{cx}{IS['revenue']}"
               f"/(( '{SH_BS}'!{prev_cx}{BS['total_assets']}"
               f"+'{SH_BS}'!{cx}{BS['total_assets']})/2),0)")
    agg_num(r); r += 1

    R["em"] = r
    lbl(r, "  Equity Multiplier  (Total Assets / Total Equity)")
    for c in data_cols:
        cx = _xc(c)
        fn(r, c,
           f"=IFERROR('{SH_BS}'!{cx}{BS['total_assets']}"
           f"/'{SH_BS}'!{cx}{BS['total_equity']},0)")
    agg_num(r); r += 1

    R["roe"] = r
    lbl(r, "ROE  (DuPont 3-Factor)", sty.subtotal_label)
    for c in data_cols:
        cx = _xc(c)
        fp_sub(r, c, f"={cx}{R['nm']}*{cx}{R['at']}*{cx}{R['em']}")
    agg_pct(r); r += 2

    # ── ROA Decomposition ─────────────────────────────────────────────────────
    lbl(r, "ROA DECOMPOSITION", sty.section_label); r += 1
    lbl(r, "ROA  =  Net Margin  ×  Asset Turnover", sty.line_label_alt); r += 1

    r += 1
    R["roa_nm"] = r
    lbl(r, "  Net Margin")
    for c in data_cols:
        cx = _xc(c)
        ws.write_formula(r - 1, c, f"={cx}{R['nm']}", sty.pct)
    agg_pct(r); r += 1

    R["roa_at"] = r
    lbl(r, "  Asset Turnover")
    for c in data_cols:
        cx = _xc(c)
        ws.write_formula(r - 1, c, f"={cx}{R['at']}", sty.num)
    agg_num(r); r += 1

    R["roa"] = r
    lbl(r, "ROA  (DuPont)", sty.subtotal_label)
    for c in data_cols:
        cx = _xc(c)
        fp_sub(r, c, f"={cx}{R['roa_nm']}*{cx}{R['roa_at']}")
    agg_pct(r); r += 2

    # ── Source Metrics ────────────────────────────────────────────────────────
    lbl(r, "SOURCE METRICS (cross-sheet references)", sty.section_label); r += 1
    for label, sheet, row_key, is_num in [
        ("Revenue",         SH_IS, IS["revenue"],       True),
        ("Net Profit (PAT)",SH_IS, IS["pat"],           True),
        ("Total Assets",    SH_BS, BS["total_assets"],  True),
        ("Total Equity",    SH_BS, BS["total_equity"],  True),
    ]:
        lbl(r, f"  {label}")
        for c in data_cols:
            cx = _xc(c)
            ws.write_formula(r - 1, c, f"='{sheet}'!{cx}{row_key}", sty.num)
        r += 1

    r += 1

    # ── YoY Decomposition Changes ─────────────────────────────────────────────
    if n > 1:
        lbl(r, "YoY CHANGES IN DRIVERS", sty.section_label); r += 1
        for metric_row, label, use_pct in [
            (R["nm"],  "Δ Net Margin",           True),
            (R["at"],  "Δ Asset Turnover",        False),
            (R["em"],  "Δ Equity Multiplier",     False),
            (R["roe"], "Δ ROE (DuPont)",          True),
        ]:
            lbl(r, f"  {label}")
            for i in range(1, n):
                c    = data_cols[i]
                prev = data_cols[i - 1]
                cx   = _xc(c)
                cxp  = _xc(prev)
                formula = f"=IFERROR({cx}{metric_row}-{cxp}{metric_row},0)"
                if use_pct:
                    fp(r, c, formula)
                else:
                    fn(r, c, formula)
            r += 1
