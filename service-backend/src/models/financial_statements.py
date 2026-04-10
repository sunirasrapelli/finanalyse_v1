"""
Core Pydantic models for the three financial statements.
All monetary fields are Optional[float] — real annual reports are inconsistent;
missing data is represented as None rather than 0 so we can distinguish
'not reported' from 'zero'.
"""
from typing import Optional
from pydantic import BaseModel, model_validator


class IncomeStatement(BaseModel):
    fiscal_year: int
    currency: str = "INR"
    unit: str = "Crores"

    # Revenue
    revenue: Optional[float] = None                     # Net Revenue / Net Sales
    other_income: Optional[float] = None                # Non-operating income
    total_income: Optional[float] = None                # Revenue + Other Income

    # Cost Structure
    cogs: Optional[float] = None                        # Cost of Goods Sold / Cost of Revenue
    employee_expenses: Optional[float] = None
    other_operating_expenses: Optional[float] = None
    total_operating_expenses: Optional[float] = None

    # Profitability
    gross_profit: Optional[float] = None
    ebitda: Optional[float] = None
    depreciation_amortization: Optional[float] = None
    ebit: Optional[float] = None
    interest_expense: Optional[float] = None
    pbt: Optional[float] = None                         # Profit Before Tax
    tax_expense: Optional[float] = None
    effective_tax_rate: Optional[float] = None
    pat: Optional[float] = None                         # Profit After Tax (Net Income)
    minority_interest: Optional[float] = None
    pat_attributable: Optional[float] = None            # PAT after minority interest

    # Per Share
    shares_outstanding: Optional[float] = None         # In millions / lakhs
    eps_basic: Optional[float] = None
    eps_diluted: Optional[float] = None
    dividends_per_share: Optional[float] = None

    # Extraction metadata
    extraction_confidence: float = 1.0
    extraction_notes: Optional[str] = None


class BalanceSheet(BaseModel):
    fiscal_year: int
    currency: str = "INR"
    unit: str = "Crores"

    # Current Assets
    cash_and_equivalents: Optional[float] = None
    short_term_investments: Optional[float] = None
    accounts_receivable: Optional[float] = None
    inventory: Optional[float] = None
    other_current_assets: Optional[float] = None
    total_current_assets: Optional[float] = None

    # Non-Current Assets
    gross_fixed_assets: Optional[float] = None
    accumulated_depreciation: Optional[float] = None
    net_fixed_assets: Optional[float] = None           # PP&E net
    capital_wip: Optional[float] = None
    intangible_assets: Optional[float] = None
    goodwill: Optional[float] = None
    long_term_investments: Optional[float] = None
    deferred_tax_assets: Optional[float] = None
    other_non_current_assets: Optional[float] = None
    total_non_current_assets: Optional[float] = None

    total_assets: Optional[float] = None

    # Current Liabilities
    short_term_borrowings: Optional[float] = None
    accounts_payable: Optional[float] = None
    other_current_liabilities: Optional[float] = None
    total_current_liabilities: Optional[float] = None

    # Non-Current Liabilities
    long_term_debt: Optional[float] = None
    deferred_tax_liabilities: Optional[float] = None
    other_non_current_liabilities: Optional[float] = None
    total_non_current_liabilities: Optional[float] = None

    total_liabilities: Optional[float] = None

    # Equity
    share_capital: Optional[float] = None
    reserves_and_surplus: Optional[float] = None
    minority_interest: Optional[float] = None
    total_equity: Optional[float] = None

    total_liabilities_and_equity: Optional[float] = None

    # Extraction metadata
    extraction_confidence: float = 1.0
    extraction_notes: Optional[str] = None

    @model_validator(mode="after")
    def check_balance_sheet_equation(self):
        """Total Assets should ≈ Total Liabilities + Equity (within 1%)."""
        ta = self.total_assets
        tle = self.total_liabilities_and_equity
        if ta is not None and tle is not None and ta != 0:
            diff_pct = abs(ta - tle) / abs(ta)
            if diff_pct > 0.01:
                # Reduce confidence rather than raise; extractor will flag this
                self.extraction_confidence = min(self.extraction_confidence, 0.6)
                self.extraction_notes = (
                    (self.extraction_notes or "") +
                    f" [BS imbalance: Assets={ta}, L+E={tle}, diff={diff_pct:.1%}]"
                )
        return self


class CashFlowStatement(BaseModel):
    fiscal_year: int
    currency: str = "INR"
    unit: str = "Crores"

    # Operating Activities
    net_income: Optional[float] = None
    depreciation_amortization: Optional[float] = None
    changes_in_working_capital: Optional[float] = None
    other_operating_adjustments: Optional[float] = None
    cash_from_operations: Optional[float] = None       # CFO

    # Investing Activities
    capex: Optional[float] = None                      # Capital Expenditures (negative value)
    proceeds_from_asset_sales: Optional[float] = None
    acquisitions: Optional[float] = None
    investments_net: Optional[float] = None
    cash_from_investing: Optional[float] = None        # CFI

    # Financing Activities
    debt_raised: Optional[float] = None
    debt_repaid: Optional[float] = None
    dividends_paid: Optional[float] = None
    share_issuance: Optional[float] = None
    share_buyback: Optional[float] = None
    cash_from_financing: Optional[float] = None        # CFF

    # Summary
    net_change_in_cash: Optional[float] = None
    opening_cash: Optional[float] = None
    closing_cash: Optional[float] = None
    free_cash_flow: Optional[float] = None             # CFO + Capex (capex is negative)

    # Extraction metadata
    extraction_confidence: float = 1.0
    extraction_notes: Optional[str] = None

    @model_validator(mode="after")
    def check_cf_reconciliation(self):
        """Net change in cash should ≈ CFO + CFI + CFF."""
        cfo = self.cash_from_operations
        cfi = self.cash_from_investing
        cff = self.cash_from_financing
        net = self.net_change_in_cash
        if all(v is not None for v in [cfo, cfi, cff, net]):
            computed = cfo + cfi + cff
            if abs(computed) > 0.01 and abs(net - computed) / abs(computed) > 0.02:
                self.extraction_confidence = min(self.extraction_confidence, 0.6)
                self.extraction_notes = (
                    (self.extraction_notes or "") +
                    f" [CF mismatch: CFO+CFI+CFF={computed:.1f}, net_change={net:.1f}]"
                )
        return self
