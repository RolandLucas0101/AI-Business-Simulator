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
        raise ValueError("working_days cannot exceed 31.")
    for k in ("staff_hours", "battery_minutes_available"):
        finite(c[k], k)
    for k in ("hours_per_unit", "flight_minutes_per_job"):
        finite(c[k], k, True)
    finite(c["seasonal_amplitude"], "seasonal_amplitude")
    if c["seasonal_amplitude"] > 1:
        raise ValueError("Seasonal amplitude must be in [0, 1].")
    for group in ("variable_costs", "fixed_costs"):
        if not isinstance(c[group], dict) or set(c[group]) != set(DEFAULT[group]):
            raise ValueError(f"{group}: keep the named cost rows.")
        for k, value in c[group].items():
            money_field(value, k)
    if c["demand_mode"] not in ("Manual", "Price composition", "Seasonal"):
        raise ValueError("Unknown demand model.")
    if c["demand_mode"] == "Price composition" and dec(c["price"]) > 2 * dec(c["base_price"]):
        raise ValueError("Price-composition domain is 0 <= price <= 2 × base_price.")
    if type(c["loans_enabled"]) is not bool:
        raise ValueError("loans_enabled must be boolean.")
    if not c["loans_enabled"] and any(dec(c[k]) for k in ("loan_cash", "loan_principal", "interest")):
        raise ValueError("Enable the optional loan model before using financing fields.")


def capacity(c):
    # Decimal avoids 0.3/0.1 floating-point undercounts.
    return min(int(dec(c["staff_hours"]) // dec(c["hours_per_unit"])), c["equipment_slots"],
               int(dec(c["battery_minutes_available"]) // dec(c["flight_minutes_per_job"])))


def costs(c):
    return sum(map(dec, c["fixed_costs"].values()), Decimal(0)), sum(map(dec, c["variable_costs"].values()), Decimal(0))


def average_cost(s, c):
    if s <= 0:
        return None
    f, v = costs(c)
    return float(f) / s + float(v)


def demand_at_price(p, c):
    return max(0.0, 2 * c["D0"] - c["D0"] / float(c["base_price"]) * p)


def seasonal_demand(t, c):
    return c["D0"] * (1 + c["seasonal_amplitude"] * math.sin(2 * math.pi * (t - 1) / 12))


def demand(c, month):
    if c["demand_mode"] == "Price composition":
        # floor exact demand for integer transactions
        d = max(Decimal(0), dec(c["D0"]) * (2 * dec(c["base_price"]) - dec(c["price"])) / dec(c["base_price"]))
        return int(d.to_integral_value(rounding=ROUND_FLOOR))
    if c["demand_mode"] == "Seasonal":
        return max(0, math.floor(seasonal_demand(date.fromisoformat(month + "-01").month, c) + 1e-10))
    return c["requested"]


def month_end(month):
    try:
        first = date.fromisoformat(month + "-01")
        if first.strftime("%Y-%m") != month:
            raise ValueError
        return first.replace(day=calendar.monthrange(first.year, first.month)[1]).isoformat()
    except (ValueError, TypeError):
        raise ValueError("Use a valid month YYYY-MM.") from None


def next_month(state):
    d = date.fromisoformat(state["simulation_date"])
    return f"{d.year + (d.month == 12):04d}-{d.month % 12 + 1:02d}"


def opening_rows(startup):
    out = []
    for k, event, category in (("owner", "OwnerContribution", "startup_owner"),
                               ("loan", "LoanDraw", "startup_loan"),
                               ("drone", "Capex", "drone_sensor_kit"),
                               ("computer", "Capex", "computer"),
                               ("setup", "Expense", "preopening_setup")):
        out.append({"transaction_id": "opening-" + k, "date": "2026-12-31", "event_type": event,
                    "category": category, "amount": startup[k], "quantity": 1, "unit_price": startup[k],
                    "offering_id": None, "campaign_id": None, "financing_type": "loan" if "loan" in k else "owner" if k == "owner" else None,
                    "state_version": 1, "run_id": "opening", "seed": 0})
    return out


def new_snapshot(startup=None, mode="Normal"):
    start = copy.deepcopy(STARTUP if startup is None else startup)
    validate_startup(start)
    if mode not in ("Normal", "Fixture-test"):
        raise ValueError("Unknown run mode.")
    return {"schema_version": 1, "team_id": TEAM, "course": COURSE, "pathway_id": PATHWAY,
            "snapshot_id": str(uuid4()), "state_version": 1, "simulation_date": "2026-12-31",
            "base_period": "monthly", "working_days": 20, "currency": "USD",
            "level_by_skill": dict.fromkeys(SKILLS, "Advanced"), "assumptions": ASSUMPTIONS[:],
            "sources": [{"title": "Teacher-provided AER-2 build specification", "type": "fictional_classroom_fixture"}],
            "offerings": [{"offering_id": "roof", "name": "Roof inspection", "unit": "inspection",
                           "price": "35.00", "demand_rule": "Manual", "capacity_rule": "minimum of staff, equipment, battery"}],
            "funding": [{"type": "owner", "amount": start["owner"]}, {"type": "loan", "amount": start["loan"]}],
            "cost_lines": cost_lines(DEFAULT), "capacity": capacity_record(DEFAULT),
            "ledger": opening_rows(start), "campaigns": [], "decisions": [], "runs": [],
            "startup": start, "config": copy.deepcopy(DEFAULT), "mode": mode}


def validate_startup(s):
    if not isinstance(s, dict) or set(s) != set(STARTUP):
        raise ValueError("Invalid startup schema.")
    for k, v in s.items():
        money_field(v, k)
    if dec(s["inventory"]) != 0:
        raise ValueError("Inventory is zero for the Stage 1 drone service.")
    if dec(s["owner"]) + dec(s["loan"]) < dec(s["drone"]) + dec(s["computer"]) + dec(s["setup"]):
        raise ValueError("Startup sources cannot be less than startup spending.")


def cost_lines(c):
    return [{"name": k, "basis": basis, "amount": v} for group, basis in
            (("variable_costs", "per_delivered_unit"), ("fixed_costs", "monthly")) for k, v in c[group].items()]


def capacity_record(c):
    keys = ("staff_hours", "hours_per_unit", "equipment_slots", "battery_minutes_available", "flight_minutes_per_job")
    return {**{k: c[k] for k in keys}, "derived_units": capacity(c)}


def balances(state, through=None):
    cash = debt = equipment = revenue = expenses = owner = Decimal(0)
    for r in state["ledger"]:
        if through is not None and r["date"] > through:
            continue
        a, e = dec(r["amount"]), r["event_type"]
        cash += a if e in ("Revenue", "OwnerContribution", "LoanDraw") else -a
        if e == "Revenue": revenue += a
        elif e == "Refund": revenue -= a
        elif e == "Expense": expenses += a
        elif e == "LoanDraw": debt += a
        elif e == "PrincipalPayment": debt -= a
        elif e == "OwnerContribution": owner += a
        elif e == "Capex": equipment += a
    retained = revenue - expenses
    return {k: money(v) for k, v in {"cash": cash, "debt": debt, "equipment": equipment,
            "owner_equity": owner, "retained_earnings": retained,
            "assets": cash + equipment, "liabilities_and_equity": debt + owner + retained}.items()}


def calculate(c, month, capacity_override=None):
    validate_config(c)
    month_end(month)
    if c["working_days"] > calendar.monthrange(int(month[:4]), int(month[5:]))[1]:
        raise ValueError("Working days exceed calendar days in the selected month.")
    cap = capacity(c) if capacity_override is None else capacity_override
    integer(cap, "capacity")
    requested, f_v = demand(c, month), costs(c)
    sold = min(requested, cap)
    f, v = f_v
    gross = dec(c["price"]) * sold
    if dec(c["refund_amount"]) > gross:
        raise ValueError("Refund cannot exceed this month's gross sales.")
    revenue = gross - dec(c["refund_amount"])
    var = sold * v
    total = var + f + dec(c["ad_cost"]) + dec(c["interest"])
    profit = revenue - total
    flow = profit - dec(c["additional_capex"]) - dec(c["loan_principal"]) + dec(c["new_owner_cash"]) + dec(c["loan_cash"])
    return {"month": month, "requested": requested, "capacity": cap, "sold": sold,
            "lost_demand": requested - sold, "revenue": money(revenue),
            "gross_revenue": money(gross), "variable_expense": money(var),
            "fixed_expense": money(f), "total_expense": money(total), "profit": money(profit),
            "cash_change": money(flow), "campaign": c["ad_cost"]}


def post_month(state, c, month, run_id, seed=2027, memo=None, capacity_override=None):
    """Return a new snapshot; do not mutate the caller on success or failure."""
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 100:
        raise ValueError("A run_id of 1–100 characters is required.")
    integer(seed, "seed")
    if any(r["run_id"] == run_id for r in state["runs"]) or run_id == "opening":
        raise ValueError("Duplicate run_id rejected: no transactions posted.")
    if month != next_month(state):
        raise ValueError("Post exactly the next month; backdating and duplicate months are rejected.")
    if state["mode"] == "Normal" and capacity_override is not None:
        raise ValueError("Capacity overrides are allowed only in Fixture-test mode.")
    if state["mode"] == "Fixture-test":
        expected = list(csv.DictReader(io.StringIO(FIXTURE)))
        idx = len(state["runs"])
        if idx >= len(expected):
            raise ValueError("Fixture mode contains exactly three supplied rows.")
        row = expected[idx]
        fixture_c = copy.deepcopy(DEFAULT)
        fixture_c.update(requested=int(row["requested"]), ad_cost=money(row["ad_cost"]))
        if c != fixture_c or month != row["month"] or capacity_override != int(row["capacity_override"]) or state["startup"] != STARTUP:
            raise ValueError("Fixture mode accepts only the exact supplied fixture rows and baseline startup.")
    result = calculate(c, month, capacity_override)
    debt = dec(balances(state)["debt"])
    if dec(c["loan_principal"]) > debt + dec(c["loan_cash"]):
        raise ValueError("Principal repayment exceeds outstanding debt plus this month's draw.")
    if dec(c["interest"]) and debt + dec(c["loan_cash"]) == 0:
        raise ValueError("Interest requires outstanding debt.")
    if not isinstance(memo, dict) or not all(isinstance(memo.get(k), str) and memo[k].strip()
            for k in ("owner", "checker", "student_prediction", "calculation", "reflection")):
        raise ValueError("Complete owner, checker, prediction, calculation and decision memo.")
    if memo["owner"].strip().casefold() == memo["checker"].strip().casefold():
        raise ValueError("Use a different teammate as checker.")
    out = copy.deepcopy(state)
    version = state["state_version"] + 1
    when = month_end(month)
    def add(event, category, amount, quantity=1, offering=None, campaign=None, financing=None):
        value = money(amount)
        # Keep zero revenue/expenses as explicit auditable rows.
        unit = money(dec(value) / quantity) if quantity else "0.00"
        out["ledger"].append({"transaction_id": f"{run_id}:{len(out['ledger'])}",
            "date": when, "event_type": event, "category": category, "amount": value,
            "quantity": quantity, "unit_price": unit, "offering_id": offering,
            "campaign_id": campaign, "financing_type": financing,
            "state_version": version, "run_id": run_id, "seed": seed})
    add("Revenue", "roof_sales", result["gross_revenue"], result["sold"], "roof")
    for k, v in c["variable_costs"].items():
        add("Expense", k, dec(v) * result["sold"], result["sold"], "roof")
    for k, v in c["fixed_costs"].items():
        add("Expense", k, v)
    if dec(c["ad_cost"]):
        cid = run_id + ":campaign"
        add("Expense", "own_marketing", c["ad_cost"], campaign=cid)
        out["campaigns"].append({"campaign_id": cid, "date": when, "cost": c["ad_cost"], "status": "approved_simulated"})
    for key, event, cat, finance in (("refund_amount", "Refund", "customer_refund", None),
            ("additional_capex", "Capex", "replacement_equipment", None),
            ("interest", "Expense", "interest", "loan"),
            ("loan_principal", "PrincipalPayment", "principal", "loan"),
            ("loan_cash", "LoanDraw", "loan_receipt", "loan"),
            ("new_owner_cash", "OwnerContribution", "additional_owner", "owner")):
        if dec(c[key]): add(event, cat, c[key], financing=finance)
    out.update(state_version=version, simulation_date=when, working_days=c["working_days"],
               config=copy.deepcopy(c), cost_lines=cost_lines(c), capacity=capacity_record(c))
    out["offerings"][0].update(price=c["price"], demand_rule=c["demand_mode"])
    result["closing_cash"] = balances(out)["cash"]
    run = {"run_id": run_id, "seed": seed, "month": month, "config": copy.deepcopy(c),
           "capacity_override": capacity_override, "result": result}
    out["runs"].append(run)
    out["decisions"].append({"decision_id": run_id + ":decision", "snapshot_id": state["snapshot_id"],
        "alternatives": ["Keep baseline", "Accept this scenario", "Revise and recalculate"],
        "report_ids": [run_id + ":preview"], "student_prediction": memo["student_prediction"],
        "calculation": memo["calculation"], "visual_id": memo.get("visual_id", "preview"),
        "chosen_action": "Post this simulated month", "owner": memo["owner"], "checker": memo["checker"],
        "approval": "student_approved", "expected_outcome": memo["student_prediction"],
        "actual_outcome": result, "reflection": memo["reflection"],
        "before_state_version": state["state_version"], "after_state_version": version,
        "before_balances": balances(state), "after_balances": balances(out)})
    return out


def default_memo():
    # Used by classroom fixtures/tests only, never auto-approves a normal UI run.
    return dict(owner="Fixture operator", checker="Fixture reviewer", student_prediction="Replay supplied fixture",
                calculation="Reference monthly algorithm", reflection="Fictional fixture acceptance run")


def run_fixtures():
    s = new_snapshot(mode="Fixture-test")
    for row in csv.DictReader(io.StringIO(FIXTURE)):
        c = copy.deepcopy(DEFAULT)
        c.update(requested=int(row["requested"]), ad_cost=money(row["ad_cost"]))
        s = post_month(s, c, row["month"], "fixture-" + row["month"], 2027,
                       default_memo(), int(row["capacity_override"]))
    return s


def validate_snapshot(s):
    """Replay all transactions to validate imported state atomically.

    This catches edited totals, omitted transactions, duplicate IDs, invalid money,
    nonfinite data, inconsistent versions, and schema/identity violations.
    It is not cryptographic authentication of a student's claims.
    """
    if not isinstance(s, dict) or set(s) != set(new_snapshot()):
        raise ValueError("Snapshot has missing or unknown fields.")
    integer(s["schema_version"], "schema_version", 1)
    if (s["schema_version"], s["team_id"], s["course"], s["pathway_id"], s["currency"], s["base_period"]) != (1, TEAM, COURSE, PATHWAY, "USD", "monthly"):
        raise ValueError("Wrong schema, team_id, course, pathway, currency or base period.")
    if not isinstance(s["snapshot_id"], str) or not s["snapshot_id"].strip():
        raise ValueError("Missing snapshot_id.")
    integer(s["state_version"], "state_version", 1)
    if not isinstance(s["level_by_skill"], dict) or set(s["level_by_skill"]) != set(SKILLS) or any(x not in LEVELS for x in s["level_by_skill"].values()):
        raise ValueError("Invalid course skill levels.")
    for k in ("assumptions", "sources", "offerings", "funding", "cost_lines", "ledger", "campaigns", "decisions", "runs"):
        if not isinstance(s[k], list): raise ValueError(f"{k} must be a list.")
    if len(s["runs"]) > 240:
        raise ValueError("Maximum snapshot length is 240 monthly runs.")
    replay = new_snapshot(s["startup"], s["mode"])
    replay["snapshot_id"] = s["snapshot_id"]
    replay["level_by_skill"] = s["level_by_skill"]
    if len(s["runs"]) != len(s["decisions"]):
        raise ValueError("Each run needs exactly one approved decision.")
    for run, decision in zip(s["runs"], s["decisions"]):
        replay = post_month(replay, run["config"], run["month"], run["run_id"], run["seed"],
                            decision, run["capacity_override"])
    if s != replay:
        raise ValueError("Snapshot does not match its replayed ledger, inputs, decisions or version.")
    b = balances(s)
    if b["assets"] != b["liabilities_and_equity"]:
        raise ValueError("Balance sheet does not reconcile.")
    return s


def dump_snapshot(state):
    validate_snapshot(state)
    return json.dumps(state, indent=2, allow_nan=False)


def restore_snapshot(raw, current, expected_version, fresh_session=False):
    if expected_version != current["state_version"]:
        raise ValueError("The active state advanced; retry from its current version.")
    if len(raw) > 5_000_000:
        raise ValueError("Snapshot exceeds 5 MB.")
    try:
        s = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON number rejected.")))
        validate_snapshot(s)
    except (KeyError, TypeError, IndexError, json.JSONDecodeError, RecursionError, AttributeError) as e:
        raise ValueError("Malformed snapshot: " + str(e)) from None
    if not fresh_session:
        if s["snapshot_id"] != current["snapshot_id"]:
            raise ValueError("Different snapshot lineage. Open a fresh session to restore another plan.")
        if s["state_version"] < current["state_version"]:
            raise ValueError("Stale state_version rejected; the active business has advanced.")
        if s["ledger"][:len(current["ledger"])] != current["ledger"]:
            raise ValueError("Import would overwrite the active ledger; rejected.")
        if s["decisions"][:len(current["decisions"])] != current["decisions"]:
            raise ValueError("Import would overwrite approved decisions; rejected.")
    return s


def validate_recommendation(r, state):
    required = {"role", "snapshot_id", "state_version", "question", "evidence", "method", "results",
                "alternatives", "uncertainty", "proposed_changes", "checks_needed", "approval_status"}
    if not isinstance(r, dict) or not required <= set(r):
        raise ValueError("Recommendation schema is incomplete.")
    if r["snapshot_id"] != state["snapshot_id"] or type(r["state_version"]) is not int or r["state_version"] != state["state_version"]:
        raise ValueError("Stale or wrong-snapshot recommendation rejected.")
    for k in ("role", "question", "method", "uncertainty"):
        if not isinstance(r[k], str): raise ValueError(k + " must be text.")
    for k in ("evidence", "alternatives", "checks_needed"):
        if not isinstance(r[k], list): raise ValueError(k + " must be a list.")
    if not isinstance(r["results"], dict) or not isinstance(r["proposed_changes"], dict) or r["approval_status"] != "pending":
        raise ValueError("Recommendation must contain result/change objects and remain pending.")
    return r


def rows_csv(rows):
    if not rows: return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def ledger_report(state, grain="monthly"):
    groups = {}
    for r in state["ledger"]:
        key = r["date"] if grain == "daily" else r["date"][:4] if grain == "yearly" else r["date"][:7]
        x = groups.setdefault(key, {"period": key, "revenue": Decimal(0), "expenses": Decimal(0), "cash_flow": Decimal(0)})
        a, e = dec(r["amount"]), r["event_type"]
        x["cash_flow"] += a if e in ("Revenue", "OwnerContribution", "LoanDraw") else -a
        if e == "Revenue": x["revenue"] += a
        elif e == "Refund": x["revenue"] -= a
        elif e == "Expense": x["expenses"] += a
    return [{**{k: money(v) if isinstance(v, Decimal) else v for k, v in x.items()},
             "profit": money(x["revenue"] - x["expenses"])} for x in groups.values()]


def main():
    import streamlit as st
    st.set_page_config(page_title="Career Venture Lab • Drone Inspection", page_icon="🛩️", layout="wide")
    # Render visible content before potentially slow scientific-library imports.
    # The build stamp also identifies a stale/wrong file in the deployed repository.
    st.title("Drone Inspection Venture")
    st.caption(f"Fictional business • Stage 1 • Build: {BUILD_ID}")
    print(f"CVL_STARTUP {BUILD_ID}: dashboard entry reached", flush=True)
    with st.spinner("Loading dashboard libraries…"):
        import pandas as pd
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    print(f"CVL_STARTUP {BUILD_ID}: libraries ready", flush=True)
    st.markdown("""<style>
      .block-container{padding-top:1.5rem;max-width:1450px}
      [data-testid="stMetric"]{background:#eef5f7;border-left:4px solid #007d87;padding:14px;border-radius:6px}
      h1,h2,h3{color:#153448} .stCaption{line-height:1.5}
      @media print{[data-testid="stSidebar"],button{display:none!important}.block-container{padding:0}}
    </style>""", unsafe_allow_html=True)
    if "business" not in st.session_state:
        st.session_state.business = new_snapshot()
        st.session_state.fresh = True
        st.session_state.pending = None
        st.session_state.editor_epoch = 0
    state = st.session_state.business
    c0 = state["config"]
    st.sidebar.title("CAREER VENTURE LAB")
    st.sidebar.caption("Team1 / AER-2 / Precalculus")
    page = st.sidebar.radio("Workspace", PAGES)
    st.sidebar.divider()
    st.sidebar.write(f"State v{state['state_version']} · {state['mode']}")
    st.sidebar.caption(f"Ledger through {state['simulation_date']}")
    st.sidebar.info("Save JSON after every approved month. Browser refresh can reset this session; upload your latest file to resume.")
    if state["mode"] == "Fixture-test":
        st.warning("FIXTURE-TEST MODE — capacity overrides are active. This isolated replay is not a normal business run.")
    st.caption("Fictional business • Stage 1 • Manual approval • No live AI or real payments")
    b = balances(state)
    pending = st.session_state.pending
    c = pending["config"] if pending else c0
    horizon = pending["month"] if pending else next_month(state)

    def skill_card(level=None):
        lv = level or state["level_by_skill"][SKILLS[0]]
        f, v = costs(c)
        equations = {"Foundation": "A(s)=F/s+v", "Applied": "P(p)=p·min(K,q(p))−[F+v·min(K,q(p))]",
                     "Advanced": "D(t)=D₀[1+a·sin(2π(t−1)/12)]; s(t)=min(K,⌊D(t)⌋)"}
        st.info(f"Precalculus · {lv} · {equations[lv]} · F=${f}/month, v=${v}/inspection, K={capacity(c)} inspections/month.")
        st.caption("Domains: 0<s≤K for average cost; 0≤p≤2p₀ for price composition; month index 1…12 for seasonality. Assumptions are fictional; capacity is a minimum of resources. Interpretation: explain which constraint changes your decision and why.")

    def table(rows):
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    def plot_export(frame, x, ys, title, equation, units, kind="line", label="PROJECTED SCENARIO", assumptions=None):
        chart_horizon = (f"months 1–12 of {horizon[:4]} (fictional seasonal cycle)"
                         if x == "month index t" else
                         f"{frame[x].iloc[0]} through {frame[x].iloc[-1]}"
                         if x == "month" and len(frame) else horizon)
        signature = json.dumps({"config": c, "title": title, "equation": equation,
            "data": frame.to_json(orient="split"), "snapshot": state["snapshot_id"],
            "state_version": state["state_version"], "label": label}, sort_keys=True)
        sid = "scenario-" + hashlib.sha256(signature.encode()).hexdigest()[:12]
        metadata = {"scenario_id": sid, "snapshot_id": state["snapshot_id"], "state_version": state["state_version"],
                    "label": label, "equation": equation, "units": units, "horizon": chart_horizon,
                    "created_utc": datetime.now(timezone.utc).isoformat(), "assumptions": assumptions or ASSUMPTIONS}
        fig, ax = plt.subplots(figsize=(9.2, 4.3))
        styles = ("-", "--", ":", "-.")
        if kind == "bar":
            width = .8 / len(ys)
            xx = np.arange(len(frame))
            for i, y in enumerate(ys):
                ax.bar(xx + i * width, frame[y], width=width, label=y, hatch=("/", "\\", ".", "x")[i % 4])
            ax.set_xticks(xx + (len(ys)-1)*width/2, frame[x], rotation=20)
            vals = frame[ys].to_numpy(dtype=float)
            ax.set_ylim(bottom=min(0.0, float(vals.min()) * 1.15))
        else:
            for i, y in enumerate(ys):
                ax.plot(frame[x], frame[y], styles[i % 4], label=y, linewidth=2,
                        marker="o" if len(frame) <= 15 else None)
            if title.startswith("Average cost"):
                ax.axvline(0, color="#9b4e00", linestyle="-.", label="vertical asymptote s=0 (undefined)")
        ax.axhline(0, color="#4b5563", linewidth=.8)
        ax.set(title=title, xlabel=x, ylabel=units)
        ax.grid(alpha=.18)
        ax.legend(loc="best")
        fig.text(.01, .01, f"{label} | {sid} | snapshot v{state['state_version']} | {chart_horizon}", fontsize=6.5)
        fig.tight_layout(rect=(0, .04, 1, 1))
        st.pyplot(fig)
        st.caption(f"{equation} · {units} · {label} · {chart_horizon}. {metadata['scenario_id']}. Download the metadata with the chart.")
        table(frame.to_dict("records"))
        cols = st.columns(4)
        key = page + title
        for col, fmt in zip(cols[:2], ("png", "svg")):
            data = io.BytesIO()
            fig.savefig(data, format=fmt, dpi=160, metadata={"Description": json.dumps(metadata)} if fmt == "svg" else {"Description": json.dumps(metadata)})
            col.download_button(fmt.upper(), data.getvalue(), sid + "." + fmt,
                                mime="image/svg+xml" if fmt == "svg" else "image/png", key=key+fmt)
        cols[2].download_button("Chart CSV", frame.to_csv(index=False), sid + ".csv", "text/csv", key=key+"csv")
        cols[3].download_button("Chart metadata", json.dumps(metadata, indent=2), sid + "_metadata.json", "application/json", key=key+"meta")
        plt.close(fig)

    if page == "Overview":
        cols = st.columns(4)
        for col, title, value in zip(cols, ("Cash available", "Equipment assets", "Debt", "Retained earnings"),
                                      (b["cash"], b["equipment"], b["debt"], b["retained_earnings"])):
            col.metric(title, "$" + value)
        skill_card()
        st.subheader("Your next operating cycle")
        st.write("1. Set inputs → 2. inspect the projected scenario → 3. record your reasoning and obtain a teammate check → 4. approve one month → 5. download the updated JSON.")
        if dec(b["cash"]) < 0:
            st.error("Cash is negative. This simulation does not create automatic financing; revise future plans and document the shortfall.")
        if state["runs"]:
            df = pd.DataFrame([r["result"] for r in state["runs"]])
            plot_export(df.assign(profit=df.profit.astype(float), closing_cash=df.closing_cash.astype(float)), "month",
                        ["profit", "closing_cash"], "Approved profit and cash", "Profit=net revenue−expenses; cash includes financing/capex", "USD", label="ACTUAL SIMULATED")
        else:
            st.write("No operating months posted yet. Opening ledger: $8,000 owner funding − $4,200 equipment − $800 setup = $3,000 cash (baseline).")
        st.subheader("Implementation status")
        table([{"Stage": "1 • available", "Scope": "Inputs, math, projections, approvals, ledger, JSON, fixture replay, basic CSV/graph exports"},
               {"Stage": "2 • not implemented", "Scope": "Automated department/AI workflows, full report suite, customer CRM, flyer generation"},
               {"Stage": "3 • not implemented", "Scope": "Snapshot-based assessments, grading, cross-course evidence automation"},
               {"Stage": "4 • optional, not implemented", "Scope": "Storefront, simulated cart/checkout, agent/API orchestration"}])

    elif page == "Inputs and Funding":
        skill_card()
        st.subheader("Opening capital plan")
        st.caption("Change startup only before accepting an operating month. Approving a new startup creates a new plan; export any previous plan first. Inventory remains zero.")
        start = state["startup"]
        with st.form("startup"):
            cols = st.columns(3)
            ns = {}
            for i, (key, label) in enumerate((("owner", "Owner contribution"), ("loan", "Optional opening loan"),
                    ("drone", "Drone and sensor kit"), ("computer", "Computer asset"), ("setup", "Pre-opening training/setup"))):
                ns[key] = money(cols[i % 3].number_input(label + " (USD)", min_value=0.0, value=float(start[key]), step=50.0))
            ns["inventory"] = "0.00"
            confirm_start = st.checkbox("I approve these opening sources and uses as a new plan.")
            startup_submit = st.form_submit_button("Approve opening plan", disabled=bool(state["runs"]) or state["mode"] != "Normal")
        if startup_submit:
            try:
                if not confirm_start: raise ValueError("Check the opening-plan approval first.")
                st.session_state.business = new_snapshot(ns)
                st.session_state.pending = None
                st.session_state.fresh = False
                st.session_state.editor_epoch += 1
                st.rerun()
            except ValueError as e: st.error(str(e))
        table([{"Account": k, "USD": v} for k, v in b.items()])
        st.subheader("Draft the next month")
        st.caption("Editing and previewing do not change the ledger. Default posting month is the next unposted month.")
        if state["mode"] != "Normal":
            st.warning("Fixture replay is read-only here. Use a fresh browser session for a normal plan.")
        else:
            with st.form("scenario-" + str(st.session_state.editor_epoch)):
                cols = st.columns(3)
                nc = copy.deepcopy(c0)
                month = cols[0].text_input("Posting month (YYYY-MM)", next_month(state))
                run_id = cols[1].text_input("Unique run ID", "team1-" + next_month(state))
                seed = int(cols[2].number_input("Recorded seed (no randomness in Stage 1)", min_value=0, value=2027, step=1))
                for i, (key, label) in enumerate((("base_price", "Demand-model base price p₀"), ("price", "Selling price per inspection"),
                                                ("ad_cost", "Own-business advertising"))):
                    nc[key] = money(cols[i].number_input(label + " (USD)", min_value=0.01 if key == "base_price" else 0.0, value=float(c0[key]), step=1.0))
                nc["demand_mode"] = cols[0].selectbox("Demand model", ["Manual", "Price composition", "Seasonal"], index=["Manual", "Price composition", "Seasonal"].index(c0["demand_mode"]))
                nc["D0"] = int(cols[1].number_input("D₀: requests/month at p₀", min_value=0, value=c0["D0"], step=1))
                nc["requested"] = int(cols[2].number_input("Requested inspections (Manual mode only)", min_value=0, value=c0["requested"], step=1))
                nc["seasonal_amplitude"] = cols[0].slider("Fictional seasonal amplitude", 0.0, 1.0, float(c0["seasonal_amplitude"]), .05)
                nc["working_days"] = int(cols[1].number_input("Productive working days in month", 1, 31, c0["working_days"]))
                st.markdown("**Staff, equipment and battery limits**")
                for i, (key, label) in enumerate((("staff_hours", "Productive staff hours/month"), ("hours_per_unit", "Staff hours/inspection"),
                        ("equipment_slots", "Equipment inspections/month"), ("flight_minutes_per_job", "Battery minutes/inspection"),
                        ("battery_minutes_available", "Battery minutes/month"))):
                    if key == "equipment_slots":
                        nc[key] = int(cols[i%3].number_input(label, 0, value=c0[key], step=1))
                    else:
                        nc[key] = cols[i%3].number_input(label, min_value=.01 if key in ("hours_per_unit", "flight_minutes_per_job") else 0.0,
                                                       value=float(c0[key]), step=1.0)
                for group, heading in (("variable_costs", "Variable expense per delivered inspection (USD)"), ("fixed_costs", "Fixed monthly expenses (USD)")):
                    st.markdown("**" + heading + "**")
                    for i, (key, val) in enumerate(c0[group].items()):
                        nc[group][key] = money(cols[i%3].number_input(key.replace("_", " "), min_value=0.0, value=float(val), step=1.0))
                st.markdown("**Explicit cash adjustments (USD)**")
                nc["loans_enabled"] = st.checkbox("Enable optional loan transactions (explicit amounts, no assumed rate)", value=c0["loans_enabled"])
                for i, (key, label) in enumerate((("refund_amount", "Refund (reduces revenue once)"),
                        ("additional_capex", "Additional equipment purchase"), ("new_owner_cash", "Additional owner funding"),
                        ("loan_cash", "New loan receipt"), ("loan_principal", "Principal repayment"), ("interest", "Interest expense"))):
                    nc[key] = money(cols[i%3].number_input(label, min_value=0.0, value=0.0, step=10.0))
                submitted = st.form_submit_button("Create pending scenario preview")
            if submitted:
                try:
                    if month != next_month(state): raise ValueError("Select the next unposted month: " + next_month(state))
                    if nc["working_days"] > calendar.monthrange(int(month[:4]), int(month[5:]))[1]:
                        raise ValueError("Working days exceed calendar days.")
                    result = calculate(nc, month)
                    st.session_state.pending = {"config": nc, "month": month, "run_id": run_id, "seed": seed,
                        "snapshot_id": state["snapshot_id"], "state_version": state["state_version"], "result": result}
                    st.success("Preview created. Review the scenario in Decisions; the ledger is unchanged.")
                    table([result])
                except (ValueError, OverflowError) as e: st.error(str(e))

    elif page == "Math Skills and Levels":
        st.subheader("Select your mathematical evidence")
        level = st.selectbox("Complexity level", LEVELS, index=LEVELS.index(state["level_by_skill"][SKILLS[0]]))
        if st.button("Save course skill levels to this snapshot"):
            st.session_state.business["level_by_skill"] = dict.fromkeys(SKILLS, level)
            st.session_state.fresh = False
            st.rerun()
        skill_card(level)
        st.caption("Chart controls change analysis only. They never post ledger transactions. Seasonal controls for the operating model are in Inputs and Funding.")
        f, v = costs(c)
        cap = capacity(c)
        if level == "Foundation":
            st.latex(r"A(s)=\frac{F}{s}+v,\quad 0<s\leq K")
            if cap:
                s = st.slider("Completed inspections s", 1, cap, min(40, cap)) if cap > 1 else 1
                st.metric("Average cost", f"${average_cost(s,c):.2f}/inspection")
                xs = np.linspace(.2, cap, 180)
                frame = pd.DataFrame({"inspections s": xs, "average cost": [average_cost(x,c) for x in xs], "horizontal asymptote v": float(v)})
                plot_export(frame, "inspections s", ["average cost", "horizontal asymptote v"], "Average cost within practical capacity", "A(s)=F/s+v; vertical asymptote s=0; horizontal y=v", "USD/inspection")
            else: st.warning("Capacity is zero: the practical average-cost domain is empty.")
            st.write("A(0) is undefined. Evidence: annotate both asymptotes, compute one valid average cost, and explain why a mathematical asymptote may lie outside practical business operation.")
        elif level == "Applied":
            st.latex(r"q(p)=\max(0,2D_0-(D_0/p_0)p),\quad s(p)=\min(K,q(p))")
            p0 = float(c["base_price"])
            p = st.slider("Analysis price p (USD/inspection)", 0.0, 2*p0, min(float(c["price"]),2*p0), .5)
            q = demand_at_price(p,c)
            s = min(cap,q)
            st.write(f"p=${p:.2f} → q={q:.3f} requests → s={s:.3f} continuous sales → R=${p*s:.2f} → C=${float(f)+float(v)*s:.2f}. Integer transaction sales: {math.floor(s+1e-10)}.")
            xs = np.linspace(0,2*p0,220)
            ss = np.minimum(cap,[demand_at_price(x,c) for x in xs])
            frame = pd.DataFrame({"price p": xs, "revenue": xs*ss, "cost": float(f)+float(v)*ss,
                                  "profit": xs*ss-float(f)-float(v)*ss})
            plot_export(frame,"price p",["revenue","cost","profit"],"Composition with feasible capacity", "R=p·s(p); C=F+v·s(p); P=R−C (continuous relaxation)","USD/month")
            bp = p0*(2-cap/c["D0"]) if c["D0"] else None
            st.write(f"Capacity breakpoint: ${bp:.2f}." if bp is not None and 0 <= bp <= 2*p0 else "No interior capacity breakpoint in this price domain.")
            st.write("Evidence: explain p→q→s→R,C,P; identify the active constraint and domain; compare two prices, then justify the integer/continuous difference.")
        else:
            a = st.slider("Analysis-only seasonal amplitude a", 0.0, 1.0, float(c["seasonal_amplitude"]), .05)
            model = copy.deepcopy(c); model["seasonal_amplitude"] = a
            frame = pd.DataFrame({"month index t": list(range(1,13)), "baseline demand D₀": c["D0"],
                "seasonal demand D(t)": [seasonal_demand(t,model) for t in range(1,13)],
                "integer realized sales": [min(cap,math.floor(seasonal_demand(t,model)+1e-10)) for t in range(1,13)],
                "capacity boundary K": cap})
            plot_export(frame,"month index t",list(frame.columns[1:]),"Seasonality and clipped sales",f"D(t)=D₀[1+{a:.2f}sin(2π(t−1)/12)]; s=min(K,floor(D))", "inspections/month", assumptions=ASSUMPTIONS+[f"Analysis amplitude={a}; not a ledger input."])
            st.write("Period: 12 months. For a>0: peak month 4, minimum month 10. Capacity can conceal demand seasonality in realized sales.")
            st.write("Evidence: identify amplitude, midline, period and phase; explain peak/trough and clipping; compare a=0 with a chosen nonzero value; defend an extrapolation limit.")
            st.caption("Exponential/logarithmic growth is not enabled in Stage 1; teacher approval here covers the seasonal trigonometric model.")

    elif page in ("Operations", "Customers"):
        skill_card()
        result = calculate(c, horizon)
        st.subheader("Resource bottlenecks" if page == "Operations" else "Requests versus delivered inspections")
        if page == "Operations":
            caps = {"Staff": int(dec(c["staff_hours"])//dec(c["hours_per_unit"])), "Equipment": c["equipment_slots"],
                    "Battery": int(dec(c["battery_minutes_available"])//dec(c["flight_minutes_per_job"]))}
            frame = pd.DataFrame({"Resource": list(caps), "Inspections/month": list(caps.values())})
            plot_export(frame,"Resource",["Inspections/month"],"Feasible monthly throughput","K=min(floor(H/h),equipment,floor(B/b))","inspections/month",kind="bar")
            used = result["sold"]*c["flight_minutes_per_job"]
            st.write(f"Flight utilization: {used:.1f}/{c['battery_minutes_available']:.1f} battery minutes = " +
                     (f"{100*used/c['battery_minutes_available']:.1f}%." if c["battery_minutes_available"] else "undefined (zero battery minutes)."))
            st.write(f"Turnaround proxy: {c['hours_per_unit']:.2f} productive staff-hours/inspection. This is processing time, not measured client elapsed time; no queue or travel calendar is modeled.")
            st.caption(f"Working days={c['working_days']}; calendar days={calendar.monthrange(int(horizon[:4]),int(horizon[5:]))[1]}. Monthly staff hours/working day={c['staff_hours']/c['working_days']:.2f}. Fixed-cost allocation/working day=${float(costs(c)[0])/c['working_days']:.2f}; allocation only, not extra ledger entries.")
        else:
            frame = pd.DataFrame({"Status": ["Requested", "Completed", "Lost demand"],
                                  "Inspections": [result["requested"],result["sold"],result["lost_demand"]]})
            plot_export(frame,"Status",["Inspections"],"Demand fulfillment preview","sold=min(requested,K); lost=requested−sold","inspections/month",kind="bar")
            st.caption("No customer identities are collected. CRM and additional offerings are Stage 2; roof inspections are the only revenue source.")

    elif page in ("Finance", "Report Center"):
        skill_card()
        st.subheader("Ledger-reconciled reports")
        grain = st.selectbox("Report time grouping", ["monthly", "daily", "yearly"])
        report = ledger_report(state,grain)
        table(report)
        st.caption("Daily reports show actual posting dates (monthly transactions occur on calendar month end), not fabricated daily sales. Opening setup is included in lifetime profit; monthly operating profit excludes that December startup expense.")
        table([{"Balance-sheet account": k, "USD": val} for k,val in b.items()])
        st.success("Assets = liabilities + owner contribution + retained earnings: " + b["assets"] + " = " + b["liabilities_and_equity"])
        st.download_button("Download grouped report CSV",rows_csv(report),"business_report.csv","text/csv")
        st.download_button("Download complete dated ledger CSV",rows_csv(state["ledger"]),"ledger.csv","text/csv")
        with st.expander("Inspect every transaction"):
            table(state["ledger"])
        st.subheader("Forecast scenarios — never posted as sales")
        scenarios = []
        for name, multiplier in (("Downside",.90),("Baseline",1.00),("Upside",1.10)):
            base_requested = demand(c,horizon)
            sc = copy.deepcopy(c)
            sc.update(demand_mode="Manual", requested=math.floor(base_requested*multiplier+1e-10))
            rr = calculate(sc,horizon)
            scenarios.append({"Scenario":name, "requested":rr["requested"], "completed":rr["sold"],
                              "projected profit":float(rr["profit"]), "multiplier":multiplier})
        plot_export(pd.DataFrame(scenarios),"Scenario",["projected profit"],"Projected profit or loss","(price−v)·min(requested,K)−F−marketing−interest−refunds","USD/month",kind="bar",
                    assumptions=ASSUMPTIONS+["Demand multipliers 0.90/1.00/1.10; other draft inputs fixed. Scenarios, not confidence intervals."])
        if state["runs"]:
            actual = []
            for run in state["runs"]:
                rc=copy.deepcopy(run["config"]); rc.update(demand_mode="Manual",requested=rc["D0"])
                rr=calculate(rc,run["month"],run["capacity_override"])
                actual.append({"month":run["month"],"baseline projected profit":float(rr["profit"]),"actual simulated profit":float(run["result"]["profit"])})
            plot_export(pd.DataFrame(actual),"month",["baseline projected profit","actual simulated profit"],"Baseline comparison against approved months","baseline uses D₀; actual uses each recorded request rule and cost inputs","USD/month",label="PROJECTED BASELINE / ACTUAL SIMULATED")

    elif page == "Decisions":
        skill_card()
        st.subheader("Approve one operating month")
        if pending is None:
            st.info("Create a scenario in Inputs and Funding first.")
        else:
            st.write(f"Pending run: {pending['run_id']} · month {pending['month']} · based on v{pending['state_version']}")
            table([pending["result"]])
            st.write("Expected closing cash: $" + money(dec(b["cash"])+dec(pending["result"]["cash_change"])))
            with st.expander("Before/after draft inputs"):
                table([{"Input": k,"Before":str(c0[k]),"Draft":str(pending["config"][k])} for k in DEFAULT if c0[k] != pending["config"][k]])
            with st.form("approve"):
                owner=st.text_input("Student owner")
                checker=st.text_input("Different teammate checker")
                prediction=st.text_area("Your prediction, including expected profit and cash")
                calculation=st.text_area("Independent calculation and visual evidence used")
                reflection=st.text_area("Decision memo: why this choice, assumptions and alternatives")
                approved=st.checkbox("We checked the calculations and approve posting this simulated month.")
                commit=st.form_submit_button("Approve and post once")
            if commit:
                try:
                    if not approved: raise ValueError("Approval is required.")
                    if pending["snapshot_id"] != state["snapshot_id"] or pending["state_version"] != state["state_version"]:
                        raise ValueError("Stale preview rejected. Create a new preview from current state.")
                    st.session_state.business=post_month(state,pending["config"],pending["month"],pending["run_id"],pending["seed"],
                        dict(owner=owner,checker=checker,student_prediction=prediction,calculation=calculation,reflection=reflection))
                    st.session_state.pending=None
                    st.session_state.fresh=False
                    st.session_state.editor_epoch+=1
                    st.rerun()
                except ValueError as e: st.error(str(e))
        if state["decisions"]:
            with st.expander("Approved decision log and before/after balances"):
                st.json(state["decisions"])

    elif page == "Cross-Course Connections":
        skill_card()
        st.subheader("Engineering and technical writing")
        st.write("Physics task: use battery minutes per job to identify the throughput limit. Compare 800 and 600 available battery minutes while holding staff and equipment fixed. Explain whether adding staff would change throughput.")
        st.write("Writing task: draft a fictional client roof-inspection report with purpose, observations, units, limitations of aerial measurement, and a justified recommendation. Do not claim this simulation performs a real inspection.")
        st.caption("Cross-course automated evidence collection and assessment generation are Stage 3, not implemented.")

    elif page == "AI Recommendations":
        skill_card()
        st.subheader("Manual recommendation handoff")
        st.write("No AI service is connected. Export the snapshot below for an approved Gem, Claude skill or ChatGPT conversation. A manually pasted recommendation can be checked here; applying it automatically is a later-stage feature.")
        raw = st.text_area("Paste recommendation JSON (optional)",height=180)
        if st.button("Validate recommendation against current state"):
            try:
                r=validate_recommendation(json.loads(raw),state)
                st.json(r)
                st.success("Current snapshot/version; remains PENDING. Re-enter proposed changes as a scenario and obtain student approval.")
            except (ValueError,TypeError) as e: st.error(str(e))
        with st.expander("Recommendation schema"):
            st.json(dict(role="Finance",snapshot_id=state["snapshot_id"],state_version=state["state_version"],
                question="Question here",evidence=[],method="Method here",results={},alternatives=[],uncertainty="State assumptions",
                proposed_changes={},checks_needed=[],approval_status="pending"))

    else:
        skill_card()
        st.subheader(page + " — planned feature")
        msg={"Marketing Studio":"Stage 2: flyer and advertising asset generation are not implemented. Own advertising spend is already an editable operating expense in Stage 1.",
             "Assessment":"Stage 3: snapshot-based math and subject assessments and grading are not implemented. Math-page interpretation prompts are available; no teacher assessment keys are included.",
             "Storefront":"Stage 4 (optional, lower priority): product catalog, simulated cart and checkout are not implemented. No payments or public sales."}
        st.info(msg[page])

    st.divider()
    st.subheader("Save, restore and acceptance fixtures")
    with st.expander("Download the durable JSON snapshot / import a saved state",expanded=False):
        st.caption("The JSON file on your computer is the durable save. Downloading does not save to a server. Treat an imported file as the authoritative plan only after checking its team, version and ledger.")
        st.download_button("Save business JSON",dump_snapshot(state),f"Team1_AER2_v{state['state_version']}.json","application/json")
        upload=st.file_uploader("Load JSON snapshot (maximum 5 MB)",type=["json"])
        confirm=st.checkbox("I reviewed the file and approve importing its validated ledger.")
        if st.button("Validate and restore JSON",disabled=upload is None):
            try:
                if not confirm: raise ValueError("Review and approve the restore first.")
                restored=restore_snapshot(upload.getvalue().decode("utf-8"),state,state["state_version"],st.session_state.fresh)
                st.session_state.business=restored
                st.session_state.pending=None
                st.session_state.fresh=False
                st.session_state.editor_epoch+=1
                st.rerun()
            except (ValueError,UnicodeDecodeError) as e: st.error(str(e))
    with st.expander("Run isolated sample fixtures"):
        st.caption("Runs in a separate snapshot; your active ledger is not changed. To inspect fixture reports in a fresh session, export the fixture JSON and restore it there.")
        if st.button("Replay three sample months"):
            fixture_state=run_fixtures()
            st.session_state.fixture_preview=fixture_state
        if "fixture_preview" in st.session_state:
            fs=st.session_state.fixture_preview
            st.warning("FIXTURE-TEST PREVIEW ONLY: capacity_override = 40, 40, 30.")
            table([r["result"] for r in fs["runs"]])
            st.download_button("Save fixture snapshot",dump_snapshot(fs),"fixture_snapshot.json","application/json")
        st.download_button("Download exact fixture CSV",FIXTURE,"monthly_fixture.csv","text/csv")
    st.caption("No taxes or depreciation are modeled. Loans, refunds and capex use explicit entries only. Render storage and browser session state are not a durable multi-user database. Save the JSON before a restart.")


def launch():
    """Show ordinary startup failures explicitly; preserve Streamlit rerun/stop signals."""
    import traceback
    print(f"CVL_STARTUP {BUILD_ID}: launching", flush=True)
    try:
        main()
    except Exception as exc:
        # Streamlit's control-flow signals inherit BaseException, not Exception.
        # Do not replace or swallow those rerun/stop signals.
        traceback.print_exc()
        import streamlit as st
        st.error("The business dashboard could not finish loading. Copy the error below for troubleshooting.")
        st.caption(f"Build: {BUILD_ID}")
        st.exception(exc)
        print(f"CVL_STARTUP {BUILD_ID}: failed ({type(exc).__name__})", flush=True)


if __name__ == "__main__":
    launch()
