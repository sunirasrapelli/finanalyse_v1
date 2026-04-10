"""
Centralised Excel formula generator.
All formula strings are built here — nothing is hardcoded in the builder.

Notation:
  col  — Excel column letter(s), e.g. "B", "C", "AA"
  row  — 1-based Excel row number (int)
  sheet — sheet name string (used for cross-sheet references)

Cross-sheet reference helper:  xref(sheet, col, row) → "'Sheet Name'!B5"
"""


def xref(sheet: str, col: str, row: int) -> str:
    """Cross-sheet reference: 'Sheet Name'!B5"""
    return f"'{sheet}'!{col}{row}"


def col_letter(n: int) -> str:
    """Convert 1-based column index to Excel column letter (1→A, 26→Z, 27→AA)."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ── Income Statement Formulas ─────────────────────────────────────────────────

def total_income(rev_col: str, other_col: str, row: int) -> str:
    return f"={rev_col}{row}+{other_col}{row}"

def total_opex(cogs_row: int, emp_row: int, other_row: int, col: str) -> str:
    return f"=SUM({col}{cogs_row},{col}{emp_row},{col}{other_row})"

def gross_profit(rev_row: int, cogs_row: int, col: str) -> str:
    return f"={col}{rev_row}-{col}{cogs_row}"

def gross_margin(gp_row: int, rev_row: int, col: str) -> str:
    return f"=IFERROR({col}{gp_row}/{col}{rev_row},0)"

def ebit(ebitda_row: int, da_row: int, col: str) -> str:
    return f"={col}{ebitda_row}-{col}{da_row}"

def ebit_margin(ebit_row: int, rev_row: int, col: str) -> str:
    return f"=IFERROR({col}{ebit_row}/{col}{rev_row},0)"

def ebitda_margin(ebitda_row: int, rev_row: int, col: str) -> str:
    return f"=IFERROR({col}{ebitda_row}/{col}{rev_row},0)"

def pbt(ebit_row: int, int_row: int, col: str) -> str:
    return f"={col}{ebit_row}-{col}{int_row}"

def pat(pbt_row: int, tax_row: int, col: str) -> str:
    return f"={col}{pbt_row}-{col}{tax_row}"

def net_margin(pat_row: int, rev_row: int, col: str) -> str:
    return f"=IFERROR({col}{pat_row}/{col}{rev_row},0)"

def effective_tax_rate(tax_row: int, pbt_row: int, col: str) -> str:
    return f"=IFERROR({col}{tax_row}/{col}{pbt_row},0)"

def eps(pat_row: int, shares_row: int, col: str) -> str:
    return f"=IFERROR({col}{pat_row}/{col}{shares_row},0)"

def payout_ratio(dps_row: int, eps_row: int, col: str) -> str:
    return f"=IFERROR({col}{dps_row}/{col}{eps_row},0)"

def yoy_growth(curr_col: str, prev_col: str, row: int) -> str:
    return f"=IFERROR(({curr_col}{row}-{prev_col}{row})/ABS({prev_col}{row}),0)"

def cagr(end_col: str, start_col: str, row: int, periods: int) -> str:
    return f"=IFERROR(({end_col}{row}/{start_col}{row})^(1/{periods})-1,0)"


# ── Balance Sheet Formulas ────────────────────────────────────────────────────

def sum_range(col: str, start_row: int, end_row: int) -> str:
    return f"=SUM({col}{start_row}:{col}{end_row})"

def net_fixed_assets(gross_row: int, dep_row: int, col: str) -> str:
    return f"={col}{gross_row}-{col}{dep_row}"

def total_assets(ca_row: int, nca_row: int, col: str) -> str:
    return f"={col}{ca_row}+{col}{nca_row}"

def total_liabilities(cl_row: int, ncl_row: int, col: str) -> str:
    return f"={col}{cl_row}+{col}{ncl_row}"

def total_liabilities_and_equity(liab_row: int, eq_row: int, col: str) -> str:
    return f"={col}{liab_row}+{col}{eq_row}"

def balance_check(ta_row: int, tle_row: int, col: str) -> str:
    return (
        f'=IF(ABS({col}{ta_row}-{col}{tle_row})<1,'
        f'"BALANCED",'
        f'"ERROR: Diff = "&TEXT({col}{ta_row}-{col}{tle_row},"#,##0.00"))'
    )

def working_capital(ca_row: int, cl_row: int, col: str) -> str:
    return f"={col}{ca_row}-{col}{cl_row}"

def net_debt(ltd_row: int, stb_row: int, cash_row: int, sti_row: int, col: str) -> str:
    return f"={col}{ltd_row}+{col}{stb_row}-{col}{cash_row}-{col}{sti_row}"


# ── Cash Flow Formulas ────────────────────────────────────────────────────────

def cfo_total(start_row: int, end_row: int, col: str) -> str:
    return f"=SUM({col}{start_row}:{col}{end_row})"

def cfi_total(start_row: int, end_row: int, col: str) -> str:
    return f"=SUM({col}{start_row}:{col}{end_row})"

def cff_total(start_row: int, end_row: int, col: str) -> str:
    return f"=SUM({col}{start_row}:{col}{end_row})"

def net_change_in_cash(cfo_row: int, cfi_row: int, cff_row: int, col: str) -> str:
    return f"={col}{cfo_row}+{col}{cfi_row}+{col}{cff_row}"

def closing_cash(opening_row: int, net_change_row: int, col: str) -> str:
    return f"={col}{opening_row}+{col}{net_change_row}"

def free_cash_flow(cfo_row: int, capex_row: int, col: str) -> str:
    return f"={col}{cfo_row}+{col}{capex_row}"  # capex is negative

def cf_reconciliation(closing_row: int, bs_cash_row: int, col: str,
                      bs_sheet: str = "Balance Sheet") -> str:
    return (
        f'=IF(ABS({col}{closing_row}-{xref(bs_sheet,"B",bs_cash_row)})<1,'
        f'"OK",'
        f'"CF RECONCILIATION ERROR")'
    )


# ── Ratio Formulas (cross-sheet) ──────────────────────────────────────────────

def ratio_formula(numerator_ref: str, denominator_ref: str) -> str:
    return f"=IFERROR({numerator_ref}/{denominator_ref},0)"

def dupont_roe(net_margin_ref: str, asset_turnover_ref: str, equity_mult_ref: str) -> str:
    return f"={net_margin_ref}*{asset_turnover_ref}*{equity_mult_ref}"

def days_formula(balance_ref: str, flow_ref: str) -> str:
    return f"=IFERROR({balance_ref}/{flow_ref}*365,0)"

def cash_conversion_cycle(dio_ref: str, dso_ref: str, dpo_ref: str) -> str:
    return f"={dio_ref}+{dso_ref}-{dpo_ref}"


# ── Settings / Valuation ──────────────────────────────────────────────────────

SETTINGS_SHEET = "Settings"

def wacc_formula(
    rf_ref: str, erp_ref: str, beta_ref: str,
    tax_ref: str, cost_debt_ref: str,
    eq_weight_ref: str, debt_weight_ref: str
) -> str:
    cost_equity = f"({rf_ref}+{beta_ref}*{erp_ref})"
    after_tax_debt = f"({cost_debt_ref}*(1-{tax_ref}))"
    return f"={eq_weight_ref}*{cost_equity}+{debt_weight_ref}*{after_tax_debt}"
