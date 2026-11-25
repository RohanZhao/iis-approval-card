"""Deterministic validator: rules R1-R8 from SPEC v2.

"Model proposes, system disposes": the simulated model may parse the request
and propose an offer, but it never decides whether a missing or mismatched
field can be ignored. These plain rules decide that, and they can block Buy.

Each check returns a dict:
    {"rule": "R5", "name": "...", "status": "pass" | "fail" | "wait" | "na",
     "message": "..."}
"""

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

UNKNOWN = "unknown"


def unit_label(price, pack_size):
    """Pence per sheet, rounded half-up to 2 places, so the shop page and the card always agree (9.625p -> 9.63p)."""
    if price is None or not pack_size:
        return None
    value = Decimal(str(price)) / Decimal(pack_size) * 100
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _check(rule, name, status, message):
    return {"rule": rule, "name": name, "status": status, "message": message}


# --- R1: confirmed inputs ---------------------------------------------------------

def r1_confirmed_inputs(spec):
    """Every field must be an explicit answer. 'delegated' and 'no limit' count as answers."""
    missing = [k for k in ("item", "pack_choice", "quantity", "budget", "purchase_type")
               if spec.get(k, UNKNOWN) == UNKNOWN]
    if spec.get("quantity") not in (UNKNOWN, None) and (not isinstance(spec["quantity"], int) or spec["quantity"] < 1):
        missing.append("quantity")
    if missing:
        return _check("R1", "Confirmed inputs", "fail",
                      "Waiting for your answer on: " + ", ".join(sorted(set(missing))) + ".")
    return _check("R1", "Confirmed inputs", "pass", "All five task details are confirmed.")


# --- R2: complete offer data ----------------------------------------------------

def r2_offer_data(readings, spec):
    """Keep only readable, in-stock offers that have a price for the confirmed purchase type.

    Returns (check, eligible_offers, excluded). Excluded offers are disclosed,
    never silently dropped.
    """
    ptype = spec["purchase_type"]
    eligible, excluded = [], []
    for r in readings:
        if not r["ok"]:
            excluded.append({"id": r["id"], "reason": r["error"].lower() + ", so it was not compared"})
            continue
        if not r["in_stock"]:
            excluded.append({"id": r["id"], "reason": "out of stock"})
            continue
        if ptype not in r["prices"]:
            excluded.append({"id": r["id"], "reason": f"no {_ptype_word(ptype)} option"})
            continue
        if ptype == "subscription" and not r["subscription_terms"]:
            excluded.append({"id": r["id"], "reason": "subscription terms could not be read"})
            continue
        if isinstance(spec["pack_choice"], int) and r["pack_size"] != spec["pack_choice"]:
            continue  # a different size is not an offer for this request; no need to disclose
        price = r["prices"][ptype]
        total = round(price * spec["quantity"] + r["delivery"], 2)
        eligible.append({
            "id": r["id"],
            "pack_size": r["pack_size"],
            "price": price,
            "delivery": r["delivery"],
            "total": total,
            "unit_price_p": price / r["pack_size"] * 100,
            "unit_label": unit_label(price, r["pack_size"]),
            "default_purchase_type": r["default_purchase_type"],
            "fits_budget": budget_ok(total, spec["budget"]),
        })
    if not eligible:
        status, msg = "fail", "No readable offer matches your request."
    else:
        status, msg = "pass", f"{len(eligible)} readable offer(s) match; {len(excluded)} could not be used."
    return _check("R2", "Complete offer data", status, msg), eligible, excluded


def budget_ok(total, budget):
    if total is None:
        return False
    op = budget["op"]
    if op == "none":
        return True
    if op == "lt":
        return total < budget["amount"]
    if op == "le":
        return total <= budget["amount"]
    raise ValueError(f"Unknown budget op: {op}")


def choose_offer(eligible, spec):
    """Pick the offer: requested size, or lowest unit price if the person delegated the size.

    Only offers within budget are picked; the budget is never relaxed silently.
    """
    fitting = [o for o in eligible if o["fits_budget"]]
    if not fitting:
        return None
    return min(fitting, key=lambda o: (o["unit_price_p"], o["total"]))


# --- R3-R6: checkout read-back --------------------------------------------------

def r3_readback(readback, expected_listing, spec):
    if not readback.get("ok"):
        return _check("R3", "Checkout read-back", "fail", "I cannot read the checkout, so I cannot verify the order.")
    unreadable = [k for k in ("pack_size", "quantity", "purchase_type", "final_total")
                  if readback.get(k) in (None, UNKNOWN)]
    if unreadable:
        return _check("R3", "Checkout read-back", "fail",
                      "I cannot read " + ", ".join(unreadable).replace("_", " ") + " at checkout, so I cannot verify the order.")
    if readback["listing_id"] != expected_listing:
        return _check("R3", "Checkout read-back", "fail", "The checkout shows a different product from the one I chose.")
    if readback["purchase_type"] != spec["purchase_type"]:
        return _check("R3", "Checkout read-back", "fail",
                      f"Purchase type does not match: you asked for {_ptype_word(spec['purchase_type'])}, "
                      f"but checkout shows {_ptype_word(readback['purchase_type'])}.")
    return _check("R3", "Checkout read-back", "pass",
                  f"Checkout re-read: {readback['quantity']} × {readback['pack_size']} sheets, "
                  f"{_ptype_word(readback['purchase_type'])}.")


def r4_quantity_pack(readback, spec):
    if readback.get("quantity") != spec["quantity"]:
        return _check("R4", "Quantity and pack", "fail",
                      f"Quantity does not match: you asked for {spec['quantity']}, checkout shows {readback.get('quantity')}.")
    if isinstance(spec["pack_choice"], int) and readback.get("pack_size") != spec["pack_choice"]:
        return _check("R4", "Quantity and pack", "fail",
                      f"Pack size does not match: you asked for {spec['pack_choice']} sheets.")
    how = "you let me choose the size" if spec["pack_choice"] == "delegated" else "it is the size you asked for"
    return _check("R4", "Quantity and pack", "pass", f"Quantity {spec['quantity']} as asked; pack allowed because {how}.")


def r5_budget(readback, spec):
    total = readback.get("final_total")
    if total is None or readback.get("delivery") is None:
        return _check("R5", "Total within budget", "fail", "The total or delivery cost cannot be read.")
    b = spec["budget"]
    if b["op"] == "none":
        return _check("R5", "Total within budget", "pass", f"You chose no limit; total is £{total:.2f}.")
    limit = ("under" if b["op"] == "lt" else "at most") + f" £{b['amount']:.2f}"
    if budget_ok(total, b):
        return _check("R5", "Total within budget", "pass", f"£{total:.2f} is {limit}.")
    return _check("R5", "Total within budget", "fail", f"£{total:.2f} is not {limit}.")


def r6_subscription(readback, spec, acknowledged=False):
    if not readback.get("recurring"):
        return _check("R6", "Subscription terms", "na", "One-time purchase; no repeat charge.")
    if spec["purchase_type"] != "subscription":
        return _check("R6", "Subscription terms", "fail", "This would start a subscription you did not ask for.")
    terms = readback.get("subscription_terms") or {}
    if not terms.get("interval") or not terms.get("ends"):
        return _check("R6", "Subscription terms", "fail", "Subscription terms cannot be read.")
    if not acknowledged:
        return _check("R6", "Subscription terms", "wait", "Please confirm the repeat-delivery terms first.")
    return _check("R6", "Subscription terms", "pass", "You confirmed the repeat-delivery terms.")


def validate_checkout(readback, expected_listing, spec, acknowledged=False):
    checks = [
        r1_confirmed_inputs(spec),
        r3_readback(readback, expected_listing, spec),
    ]
    if checks[1]["status"] == "pass":
        checks += [r4_quantity_pack(readback, spec), r5_budget(readback, spec),
                   r6_subscription(readback, spec, acknowledged)]
    return checks


def buy_allowed(checks):
    return all(c["status"] in ("pass", "na") for c in checks)


# --- R7: approval is tied to one snapshot ---------------------------------------

SNAPSHOT_FIELDS = ("listing_id", "pack_size", "quantity", "purchase_type", "unit_pack_price",
                   "delivery", "final_total", "recurring")


def snapshot_id(readback):
    """Fingerprint of the exact order shown on the card."""
    data = {k: readback.get(k) for k in SNAPSHOT_FIELDS}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


def r7_approval(approved_snapshot, current_readback):
    if approved_snapshot != snapshot_id(current_readback):
        return _check("R7", "Approval matches order", "fail",
                      "The order changed after you approved it, so your approval no longer applies.")
    return _check("R7", "Approval matches order", "pass", "Your approval is for exactly this order.")


# --- R8: outcome ----------------------------------------------------------------

def r8_outcome(order, readback):
    if order.get("status") != "order_confirmed":
        return _check("R8", "Order outcome", "fail",
                      "I could not confirm whether the order went through. I will not retry payment automatically.")
    if order["total"] != readback["final_total"] or order["recurring"] != readback["recurring"]:
        return _check("R8", "Order outcome", "fail", "The confirmed order differs from what you approved.")
    return _check("R8", "Order outcome", "pass", "Order confirmed as approved.")


def _ptype_word(ptype):
    return {"one_time": "one-time", "subscription": "subscription"}.get(ptype, str(ptype))
