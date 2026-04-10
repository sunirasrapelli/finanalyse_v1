"""
Top-level container model that groups all three financial statements
for a company, plus extraction metadata.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from models.financial_statements import BalanceSheet, CashFlowStatement, IncomeStatement


class ExtractionMetadata(BaseModel):
    source_type:           Literal["pdf", "pdf_local", "manual", "url"] = "pdf"
    extraction_timestamp:  datetime = Field(default_factory=datetime.now)
    model_used:            str      = "claude-sonnet-4-6"
    overall_confidence:    float    = 1.0
    warnings:              List[str] = Field(default_factory=list)


class FinancialData(BaseModel):
    company_name: str
    ticker:       Optional[str] = None
    exchange:     Optional[str] = None
    currency:     str           = "INR"
    unit:         str           = "Crores"
    fiscal_years: List[int]     = Field(default_factory=list)

    income_statements:    List[IncomeStatement]    = Field(default_factory=list)
    balance_sheets:       List[BalanceSheet]        = Field(default_factory=list)
    cash_flow_statements: List[CashFlowStatement]  = Field(default_factory=list)

    metadata: ExtractionMetadata = Field(default_factory=ExtractionMetadata)

    def get_income_statement(self, year: int) -> Optional[IncomeStatement]:
        return next((s for s in self.income_statements if s.fiscal_year == year), None)

    def get_balance_sheet(self, year: int) -> Optional[BalanceSheet]:
        return next((s for s in self.balance_sheets if s.fiscal_year == year), None)

    def get_cash_flow(self, year: int) -> Optional[CashFlowStatement]:
        return next((s for s in self.cash_flow_statements if s.fiscal_year == year), None)

    def sorted_years(self) -> List[int]:
        return sorted(self.fiscal_years)
