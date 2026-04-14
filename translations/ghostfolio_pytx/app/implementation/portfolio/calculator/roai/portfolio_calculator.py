"""Stub ROAI calculator — returns zero/empty values for all metrics.

This is the example skeleton: it has the correct interface but no real
calculation logic. Tests will fail on value assertions but all endpoints
will run without errors. Replace this file with a real implementation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from app.implementation._support.bigjs import Big
from app.implementation._support.datefns import _date_format
from app.implementation._support.ghostfolio_helper import _DATE_FORMAT
from app.implementation._support.nest_logger import Logger

from app.wrapper.portfolio.calculator.portfolio_calculator import PortfolioCalculator

class RoaiPortfolioCalculator(PortfolioCalculator):
    """Stub ROAI calculator — no real implementation."""

    def get_performance(self) -> dict:
        sorted_acts = self.sorted_activities()
        symbols: set[str] = set()
        for act in sorted_acts:
            sym = act.get("symbol", "")
            if sym and act.get("type", "") not in ("DIVIDEND", "FEE", "LIABILITY"):
                symbols.add(sym)

        first_date = min((a["date"] for a in sorted_acts), default=None)
        return {
            "chart": [],
            "firstOrderDate": first_date,
            "performance": {
                "currentNetWorth": 0,
                "currentValue": 0,
                "currentValueInBaseCurrency": 0,
                "netPerformance": 0,
                "netPerformancePercentage": 0,
                "netPerformancePercentageWithCurrencyEffect": 0,
                "netPerformanceWithCurrencyEffect": 0,
                "totalFees": 0,
                "totalInvestment": 0,
                "totalLiabilities": 0.0,
                "totalValueables": 0.0,
            },
        }

    def get_investments(self, group_by: str | None = None) -> dict:
        return {"investments": []}

    def get_holdings(self) -> dict:
        return {"holdings": {}}

    def get_details(self, base_currency: str = "USD") -> dict:
        return {
            "accounts": {
                "default": {
                    "balance": 0.0,
                    "currency": base_currency,
                    "name": "Default Account",
                    "valueInBaseCurrency": 0.0,
                }
            },
            "createdAt": min((a["date"] for a in self.activities), default=None),
            "holdings": {},
            "platforms": {
                "default": {
                    "balance": 0.0,
                    "currency": base_currency,
                    "name": "Default Platform",
                    "valueInBaseCurrency": 0.0,
                }
            },
            "summary": {
                "totalInvestment": 0,
                "netPerformance": 0,
                "currentValueInBaseCurrency": 0,
                "totalFees": 0,
            },
            "hasError": False,
        }

    def get_dividends(self, group_by: str | None = None) -> dict:
        return {"dividends": []}

    def evaluate_report(self) -> dict:
        return {
            "xRay": {
                "categories": [
                    {"key": "accounts", "name": "Accounts", "rules": []},
                    {"key": "currencies", "name": "Currencies", "rules": []},
                    {"key": "fees", "name": "Fees", "rules": []},
                ],
                "statistics": {"rulesActiveCount": 0, "rulesFulfilledCount": 0},
            }
        }
