"""Mock shop and simulated browser tool.

Stands in for the real shop website and the browser-automation tool
(e.g. Playwright or computer use) in SPEC v2. Nothing here touches a real
shop, account or payment.

The shop behaves like the Week 2 experience:
  * O3 (80 sheets) defaults to Subscribe & Save.
  * O4 times out, so it can never be read.

Demo scenario "subscription_sticks" (SPEC v2 case D): the shop ignores the
agent's attempt to switch Subscribe & Save off, so the checkout still says
subscription. The validator must catch this at read-back.
"""

import copy
import json
from pathlib import Path

DATA = Path(__file__).parent / "data" / "listings.json"

SCENARIOS = {
    "normal": "Normal shop",
    "subscription_sticks": "D: shop keeps Subscribe & Save on after the agent switches it off",
}


def load_listings():
    return json.loads(DATA.read_text(encoding="utf-8"))["listings"]


class MockShop:
    """One shop session: page state, basket and orders for a single task."""

    def __init__(self, scenario="normal", overrides=None):
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")
        self.scenario = scenario
        self.listings = {l["id"]: copy.deepcopy(l) for l in load_listings()}
        # Page state: which purchase option is selected on each listing.
        self.selected_type = {i: l["default_purchase_type"] for i, l in self.listings.items()}
        self.basket = []            # items this task added
        self.preexisting = [{"id": "X9", "title": "Washing-up liquid", "added_by": "person"}]
        self.orders = []
        # Test hooks for SPEC cases F and H (not exposed in the demo UI).
        self.overrides = overrides or {}

    # --- reading pages ------------------------------------------------------

    def read_listing(self, listing_id):
        """Return what can be read from a listing page, or an error."""
        l = self.listings[listing_id]
        if not l["readable"]:
            return {"id": listing_id, "ok": False, "error": "Page timed out"}
        return {
            "id": listing_id,
            "ok": True,
            "title": l["title"],
            "seller": l["seller"],
            "pack_size": l["pack_size"],
            "prices": dict(l["prices"]),
            "default_purchase_type": l["default_purchase_type"],
            "subscription_terms": copy.deepcopy(l["subscription_terms"]),
            "delivery": l["delivery"],
            "in_stock": l["in_stock"],
        }

    # --- acting on pages ------------------------------------------------------

    def set_purchase_type(self, listing_id, purchase_type):
        """Click the purchase option. In scenario D the click on O3 does nothing."""
        if (
            self.scenario == "subscription_sticks"
            and purchase_type == "one_time"
            and self.listings[listing_id]["default_purchase_type"] == "subscription"
        ):
            return {"clicked": True}  # the agent thinks it worked; the page did not change
        self.selected_type[listing_id] = purchase_type
        return {"clicked": True}

    def add_to_basket(self, listing_id, quantity):
        self.clear_task_items()
        self.basket.append({"id": listing_id, "quantity": quantity, "added_by": "agent"})

    def clear_task_items(self):
        """Remove only the items this task added; leave the person's own items alone."""
        self.basket = [b for b in self.basket if b["added_by"] != "agent"]

    # --- checkout ----------------------------------------------------------------

    def read_checkout(self):
        """Read back what the checkout page actually shows."""
        if not self.basket:
            return {"ok": False, "error": "Basket is empty"}
        line = self.basket[0]
        l = self.listings[line["id"]]
        ptype = self.selected_type[line["id"]]
        price = l["prices"].get(ptype)
        readback = {
            "ok": True,
            "listing_id": l["id"],
            "item": l["title"].lower(),
            "pack_size": l["pack_size"],
            "quantity": line["quantity"],
            "purchase_type": ptype,
            "unit_pack_price": price,
            "delivery": l["delivery"],
            "final_total": round(price * line["quantity"] + l["delivery"], 2) if price is not None else None,
            "recurring": ptype == "subscription",
            "subscription_terms": copy.deepcopy(l["subscription_terms"]) if ptype == "subscription" else None,
        }
        readback.update(self.overrides.get("readback", {}))
        return readback

    def place_order(self, readback):
        if self.overrides.get("order_fails"):
            return {"status": "unknown"}
        order = {
            "status": "order_confirmed",
            "order_id": f"MOCK-{len(self.orders) + 1:03d}",
            "pack_size": readback["pack_size"],
            "quantity": readback["quantity"],
            "total": readback["final_total"],
            "recurring": readback["recurring"],
        }
        self.orders.append(order)
        self.clear_task_items()
        return order
