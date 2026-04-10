"""
Claude tool_use schema for financial statement extraction.
This JSON Schema mirrors the Pydantic models exactly, forcing Claude
to always return structured data via tool_use (never prose).
"""

# Reusable float-or-null definition
_FLOAT_OR_NULL = {"type": ["number", "null"]}

_INCOME_STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "fiscal_year": {"type": "integer", "description": "e.g. 2024"},
        "currency": {"type": "string", "default": "INR"},
        "unit": {"type": "string", "description": "Crores or Millions", "default": "Crores"},
        "revenue": {**_FLOAT_OR_NULL, "description": "Net Revenue / Net Sales"},
        "other_income": {**_FLOAT_OR_NULL, "description": "Non-operating / other income"},
        "total_income": {**_FLOAT_OR_NULL, "description": "Revenue + Other Income"},
        "cogs": {**_FLOAT_OR_NULL, "description": "Cost of Goods Sold / Cost of Revenue"},
        "employee_expenses": {**_FLOAT_OR_NULL, "description": "Staff / employee costs"},
        "other_operating_expenses": {**_FLOAT_OR_NULL, "description": "All other opex"},
        "total_operating_expenses": {**_FLOAT_OR_NULL, "description": "Sum of all operating expenses"},
        "gross_profit": {**_FLOAT_OR_NULL, "description": "Revenue minus COGS"},
        "ebitda": {**_FLOAT_OR_NULL, "description": "Earnings Before Interest Tax DA"},
        "depreciation_amortization": {**_FLOAT_OR_NULL, "description": "D&A — always positive"},
        "ebit": {**_FLOAT_OR_NULL, "description": "EBITDA minus D&A"},
        "interest_expense": {**_FLOAT_OR_NULL, "description": "Finance costs — positive"},
        "pbt": {**_FLOAT_OR_NULL, "description": "Profit Before Tax"},
        "tax_expense": {**_FLOAT_OR_NULL, "description": "Tax charge — positive"},
        "effective_tax_rate": {**_FLOAT_OR_NULL, "description": "Tax / PBT as decimal e.g. 0.25"},
        "pat": {**_FLOAT_OR_NULL, "description": "Profit After Tax / Net Income"},
        "minority_interest": {**_FLOAT_OR_NULL, "description": "Minority / non-controlling interest"},
        "pat_attributable": {**_FLOAT_OR_NULL, "description": "PAT attributable to parent shareholders"},
        "shares_outstanding": {**_FLOAT_OR_NULL, "description": "Shares in millions or lakhs (match unit)"},
        "eps_basic": {**_FLOAT_OR_NULL, "description": "Basic EPS in currency per share"},
        "eps_diluted": {**_FLOAT_OR_NULL, "description": "Diluted EPS"},
        "dividends_per_share": {**_FLOAT_OR_NULL, "description": "DPS"},
        "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1,
                                  "description": "0-1 confidence in extracted values"},
        "extraction_notes": {"type": ["string", "null"],
                             "description": "Any caveats, restatements or ambiguities"},
    },
    "required": ["fiscal_year"],
}

_BALANCE_SHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "fiscal_year": {"type": "integer"},
        "currency": {"type": "string", "default": "INR"},
        "unit": {"type": "string", "default": "Crores"},
        # Current Assets
        "cash_and_equivalents": {**_FLOAT_OR_NULL, "description": "Cash & bank balances"},
        "short_term_investments": {**_FLOAT_OR_NULL, "description": "Short-term / liquid investments"},
        "accounts_receivable": {**_FLOAT_OR_NULL, "description": "Trade receivables / debtors"},
        "inventory": {**_FLOAT_OR_NULL, "description": "Inventories / stock"},
        "other_current_assets": _FLOAT_OR_NULL,
        "total_current_assets": _FLOAT_OR_NULL,
        # Non-Current Assets
        "gross_fixed_assets": {**_FLOAT_OR_NULL, "description": "Gross block / PP&E at cost"},
        "accumulated_depreciation": {**_FLOAT_OR_NULL, "description": "Accumulated dep — positive"},
        "net_fixed_assets": {**_FLOAT_OR_NULL, "description": "Net block / PP&E net"},
        "capital_wip": {**_FLOAT_OR_NULL, "description": "Capital work-in-progress"},
        "intangible_assets": _FLOAT_OR_NULL,
        "goodwill": _FLOAT_OR_NULL,
        "long_term_investments": _FLOAT_OR_NULL,
        "deferred_tax_assets": _FLOAT_OR_NULL,
        "other_non_current_assets": _FLOAT_OR_NULL,
        "total_non_current_assets": _FLOAT_OR_NULL,
        "total_assets": _FLOAT_OR_NULL,
        # Current Liabilities
        "short_term_borrowings": {**_FLOAT_OR_NULL, "description": "Short-term loans / current portion of LT debt"},
        "accounts_payable": {**_FLOAT_OR_NULL, "description": "Trade payables / creditors"},
        "other_current_liabilities": _FLOAT_OR_NULL,
        "total_current_liabilities": _FLOAT_OR_NULL,
        # Non-Current Liabilities
        "long_term_debt": {**_FLOAT_OR_NULL, "description": "Long-term borrowings / bonds"},
        "deferred_tax_liabilities": _FLOAT_OR_NULL,
        "other_non_current_liabilities": _FLOAT_OR_NULL,
        "total_non_current_liabilities": _FLOAT_OR_NULL,
        "total_liabilities": _FLOAT_OR_NULL,
        # Equity
        "share_capital": {**_FLOAT_OR_NULL, "description": "Paid-up equity capital"},
        "reserves_and_surplus": {**_FLOAT_OR_NULL, "description": "Retained earnings + reserves"},
        "minority_interest": {**_FLOAT_OR_NULL, "description": "Non-controlling interest in equity"},
        "total_equity": {**_FLOAT_OR_NULL, "description": "Total shareholders' equity"},
        "total_liabilities_and_equity": {**_FLOAT_OR_NULL, "description": "Must equal Total Assets"},
        "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "extraction_notes": {"type": ["string", "null"]},
    },
    "required": ["fiscal_year"],
}

_CASH_FLOW_SCHEMA = {
    "type": "object",
    "properties": {
        "fiscal_year": {"type": "integer"},
        "currency": {"type": "string", "default": "INR"},
        "unit": {"type": "string", "default": "Crores"},
        # Operating
        "net_income": {**_FLOAT_OR_NULL, "description": "Starting net income / PAT"},
        "depreciation_amortization": {**_FLOAT_OR_NULL, "description": "D&A add-back — positive"},
        "changes_in_working_capital": {**_FLOAT_OR_NULL, "description": "Net WC movement — can be negative"},
        "other_operating_adjustments": _FLOAT_OR_NULL,
        "cash_from_operations": {**_FLOAT_OR_NULL, "description": "CFO total"},
        # Investing
        "capex": {**_FLOAT_OR_NULL, "description": "Capital expenditure — NEGATIVE number"},
        "proceeds_from_asset_sales": {**_FLOAT_OR_NULL, "description": "Positive"},
        "acquisitions": {**_FLOAT_OR_NULL, "description": "Negative"},
        "investments_net": {**_FLOAT_OR_NULL, "description": "Net purchase/sale of investments"},
        "cash_from_investing": {**_FLOAT_OR_NULL, "description": "CFI total — usually negative"},
        # Financing
        "debt_raised": {**_FLOAT_OR_NULL, "description": "Positive"},
        "debt_repaid": {**_FLOAT_OR_NULL, "description": "Negative"},
        "dividends_paid": {**_FLOAT_OR_NULL, "description": "Negative"},
        "share_issuance": {**_FLOAT_OR_NULL, "description": "Positive"},
        "share_buyback": {**_FLOAT_OR_NULL, "description": "Negative"},
        "cash_from_financing": {**_FLOAT_OR_NULL, "description": "CFF total"},
        # Summary
        "net_change_in_cash": {**_FLOAT_OR_NULL, "description": "CFO + CFI + CFF"},
        "opening_cash": _FLOAT_OR_NULL,
        "closing_cash": {**_FLOAT_OR_NULL, "description": "opening + net_change"},
        "free_cash_flow": {**_FLOAT_OR_NULL, "description": "CFO + Capex (capex is negative)"},
        "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "extraction_notes": {"type": ["string", "null"]},
    },
    "required": ["fiscal_year"],
}

# ── Main Tool Schema ──────────────────────────────────────────────────────────

EXTRACTION_TOOL = {
    "name": "extract_financial_statements",
    "description": (
        "Extract all three financial statements from the provided annual report. "
        "Return data for every fiscal year present in the document. "
        "Use null for any field not explicitly stated in the document."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {"type": "string"},
            "ticker": {"type": ["string", "null"]},
            "exchange": {"type": ["string", "null"]},
            "currency": {"type": "string", "default": "INR"},
            "unit": {"type": "string", "description": "Crores or Millions", "default": "Crores"},
            "fiscal_years": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of fiscal years extracted e.g. [2022, 2023, 2024]",
            },
            "income_statements": {
                "type": "array",
                "items": _INCOME_STATEMENT_SCHEMA,
                "description": "One entry per fiscal year",
            },
            "balance_sheets": {
                "type": "array",
                "items": _BALANCE_SHEET_SCHEMA,
                "description": "One entry per fiscal year",
            },
            "cash_flow_statements": {
                "type": "array",
                "items": _CASH_FLOW_SCHEMA,
                "description": "One entry per fiscal year",
            },
        },
        "required": ["company_name", "fiscal_years", "income_statements",
                     "balance_sheets", "cash_flow_statements"],
    },
}

# tool_choice to force Claude to always call this tool (never return prose)
TOOL_CHOICE = {"type": "tool", "name": "extract_financial_statements"}
