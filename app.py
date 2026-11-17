
"""Career Venture Lab — AER-2 Stage 1. Run: streamlit run app.py.

The accounting/math engine uses the standard library. UI dependencies are loaded
only by main(), so python -m unittest discover -s tests needs no extra packages.
No hosted database, paid API, AI service, real payments, or automatic deployment.
"""
from __future__ import annotations

import calendar
import copy
import csv
import hashlib
import io
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

TEAM, COURSE, PATHWAY = "Team1", "Precalculus", "AER-2"
BUILD_ID = "AER2-stage1-startup-2026-11-17"
LEVELS = ("Foundation", "Applied", "Advanced")
SKILLS = ("Rational Average Cost Functions", "Function Composition & Domain Constraints",
          "Seasonal Trigonometric / Growth Modeling")
PAGES = ("Overview", "Inputs and Funding", "Math Skills and Levels",
         "Cross-Course Connections", "Customers", "Operations", "Finance",
         "AI Recommendations", "Marketing Studio", "Report Center", "Assessment",
         "Decisions", "Storefront")
FIXTURE = "month,requested,capacity_override,ad_cost\n2027-01,50,40,0\n2027-02,55,40,100\n2027-03,45,30,0\n"
DEFAULT = {
    "base_price": "35.00", "price": "35.00", "D0": 50, "requested": 50,
    "staff_hours": 80.0, "hours_per_unit": 2.0, "equipment_slots": 40,
    "flight_minutes_per_job": 20.0, "battery_minutes_available": 800.0,
    "working_days": 20, "demand_mode": "Manual", "seasonal_amplitude": 0.20,
    "variable_costs": {"field_labor": "4.00", "travel": "3.00",
                       "maintenance_consumables": "2.00", "report_delivery": "1.00"},
    "fixed_costs": {"insurance_assumption": "150.00", "software": "100.00",
                    "equipment_maintenance": "100.00", "workspace_admin": "150.00"},
    "ad_cost": "0.00", "refund_amount": "0.00", "additional_capex": "0.00",
    "loans_enabled": False, "loan_cash": "0.00", "loan_principal": "0.00",
    "interest": "0.00", "new_owner_cash": "0.00",
}
STARTUP = {"owner": "8000.00", "loan": "0.00", "drone": "3200.00",
           "computer": "1000.00", "setup": "800.00", "inventory": "0.00"}
ASSUMPTIONS = ["Fictional educational simulation; no market forecast or real sales.",
               "No backlog; unfilled requests are lost.",
               "All sales collected and operating expenses paid in the posting month.",
               "No sales tax, income tax, depreciation, asset disposals, or receivables.",
               "Only roof inspections transact; other offerings are future extensions.",
               "Monthly posts use calendar month end; working days are separate.",
               "No random demand in Stage 1. Seeds are saved for reproducibility."]


def money(value):
    """Round UI/computation inputs to cents; never accumulate binary float money."""
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            raise ValueError("Money must be finite.")
        return format(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid money value.") from None


def dec(value):
    return Decimal(str(value))


def money_field(value, label):
    if not isinstance(value, str) or value != money(value) or dec(value) < 0:
        raise ValueError(f"{label}: use a nonnegative money string with two decimals.")


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label}: integer >= {minimum} required.")


def finite(value, label, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{label}: finite {'positive' if positive else 'nonnegative'} number required.")


def validate_config(c):
    if not isinstance(c, dict) or set(c) != set(DEFAULT):
        raise ValueError("Configuration fields differ from the Stage 1 schema.")
    for k in ("base_price", "price", "ad_cost", "refund_amount", "additional_capex",
              "loan_cash", "loan_principal", "interest", "new_owner_cash"):
        money_field(c[k], k)
    if dec(c["base_price"]) == 0:
        raise ValueError("base_price must be positive.")
    for k in ("D0", "requested", "equipment_slots"):
        integer(c[k], k)
    integer(c["working_days"], "working_days", 1)
    if c["working_days"] > 31:




