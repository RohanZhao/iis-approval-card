"""Simulated shopping agent: one delegated task from request to outcome.

Flow (SPEC v2):
  request -> parse (simulated model) -> "Here's what I understood" card (R1)
  -> plan -> read listings (R2) -> choose offer -> set purchase option
  -> add to basket -> read back checkout (R3-R6) -> approval card
  -> Buy (R7, then R8) / Change (approval invalidated, re-run) / Cancel

Every step is written to the run log (logs/run-log.jsonl) so a session can be
inspected or replayed later, e.g. for the A3 comparison.
"""

import json
import time
import uuid
from pathlib import Path

import mock_model
import validator
from mock_shop import MockShop

LOG_DIR = Path(__file__).parent / "logs"
UNKNOWN = mock_model.UNKNOWN
VARIANTS = ("disclosure", "baseline")


def _ptype_word(p):
    return {"one_time": "one-time", "subscription": "subscription"}.get(p, p)


class Task:
    def __init__(self, request, scenario="normal", variant="disclosure", shop_overrides=None, log=True):
        if variant not in VARIANTS:
            raise ValueError(f"Unknown card variant: {variant}")
        self.id = uuid.uuid4().hex[:8]
        self.request = request
        self.scenario = scenario
        self.variant = variant
        self.shop = MockShop(scenario, overrides=shop_overrides)
        self.parsed = mock_model.parse_request(request)
        self.spec = dict(self.parsed)
        self.status = "clarifying"
        self.steps = []
        self.chosen = None
        self.eligible = []
        self.excluded = []
        self.readback = None
        self.checks = []
        self.snapshot = None
        self.acknowledged = False
        self.purchase_option_note = None
        self.r2 = None
        self.notice = None
        self.retry_count = 0
        self._check_step = None
        self.outcome = None
        self.events = []
        self._log_enabled = log
        self.log("task_created", {"request": request, "parsed": self.parsed,
                                  "scenario": scenario, "variant": variant})

    # --- logging ------------------------------------------------------------------

    def log(self, event, data=None):
        entry = {"t": round(time.time(), 3), "task": self.id, "event": event, "data": data or {}}
        self.events.append(entry)
        if self._log_enabled:
            LOG_DIR.mkdir(exist_ok=True)
            with open(LOG_DIR / "run-log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    def step(self, text, status="done"):
        self.steps.append({"text": text, "status": status})

    # --- clarification (R1) ------------------------------------------------------

    def close_clarification(self):
        self.status = "waiting"
        self.log("clarification_closed", {"missing": self.missing_fields()})

    def resume(self):
        self.status = "clarifying"
        self.log("clarification_resumed")

    def missing_fields(self):
        return [k for k in mock_model.FIELDS if self.spec.get(k) == UNKNOWN]

    def confirm(self, answers):
        """Apply the person's answers, then run only if R1 passes."""
        for k, v in (answers or {}).items():
            if k in mock_model.FIELDS and k != "item":
                self.spec[k] = v
        r1 = validator.r1_confirmed_inputs(self.spec)
        self.log("clarification_answered", {"answers": answers, "spec": self.spec, "R1": r1["status"]})
        if r1["status"] != "pass":
            self.status = "clarifying"
            return r1
        self.status = "running"
        self._run()
        return r1

    # --- main run ----------------------------------------------------------------

    def plan(self):
        return [
            {"text": "Search the shop for colour catcher sheets", "consequential": False},
            {"text": f"Compare readable {_ptype_word(self.spec['purchase_type'])} offers", "consequential": False},
            {"text": "Set the purchase option and add to basket", "consequential": False},
            {"text": "Re-read the checkout and check it against your answers", "consequential": False},
            {"text": "Ask you before paying", "consequential": True},
        ]

    def _run(self):
        self.steps = []
        self.acknowledged = False
        self.step("Searched the shop: 4 listings found")
        readings = [self.shop.read_listing(i) for i in self.shop.listings]
        for r in readings:
            if not r["ok"]:
                self.step(f"Could not read {r['id']} ({r['error'].lower()})", "warn")
        r2, self.eligible, self.excluded = validator.r2_offer_data(readings, self.spec)
        self.r2 = r2
        self.notice = None
        self.retry_count = 0
        self.log("offers_read", {"eligible": self.eligible, "excluded": self.excluded, "R2": r2})
        self.chosen = validator.choose_offer(self.eligible, self.spec)
        if r2["status"] == "fail" or self.chosen is None:
            self.status = "no_offer"
            msg = r2["message"] if r2["status"] == "fail" else "No readable offer fits your limit."
            self.step(msg, "fail")
            self.checks = [r2]
            self.log("no_offer", {"message": msg})
            return
        self.step(f"Compared {len(self.eligible)} offer(s); chose {self.chosen['id']} "
                  f"({self.chosen['pack_size']} sheets)")
        self._prepare_basket()

    def _prepare_basket(self):
        lid = self.chosen["id"]
        want = self.spec["purchase_type"]
        default = self.shop.selected_type[lid]
        if default != want:
            self.shop.set_purchase_type(lid, want)
            self.purchase_option_note = {"default": default, "requested": want, "changed_by_agent": True}
            self.step(f"{lid} defaulted to {self._option_label(default)}; clicked {self._option_label(want)}")
        else:
            self.purchase_option_note = {"default": default, "requested": want, "changed_by_agent": False}
        self.shop.add_to_basket(lid, self.spec["quantity"])
        self.step(f"Added {self.spec['quantity']} × {lid} to the basket")
        self._read_back()

    def _read_back(self):
        self.readback = self.shop.read_checkout()
        self._validate()
        self.snapshot = validator.snapshot_id(self.readback) if self.readback.get("ok") else None
        ok = validator.buy_allowed(self.checks)
        waiting = any(c["status"] == "wait" for c in self.checks) and not any(c["status"] == "fail" for c in self.checks)
        self.status = "awaiting_approval" if ok else ("awaiting_terms" if waiting else "blocked")
        self.step("Re-read checkout and checked it against your answers",
                  {"awaiting_approval": "done", "awaiting_terms": "wait"}.get(self.status, "fail"))
        self._check_step = len(self.steps) - 1
        self.log("checkout_validated", {"readback": self.readback, "checks": self.checks,
                                        "snapshot": self.snapshot, "status": self.status})
        self.log("card_shown", {"variant": self.variant, "snapshot": self.snapshot,
                                "buy_enabled": self.buy_enabled()})

    def _validate(self):
        """R1 and R3-R6 on the checkout, with R2 (offer data) kept in the list so every rule is shown."""
        checks = validator.validate_checkout(self.readback, self.chosen["id"], self.spec, self.acknowledged)
        self.checks = checks[:1] + ([self.r2] if self.r2 else []) + checks[1:]

    @staticmethod
    def _option_label(p):
        return {"one_time": "one-time purchase", "subscription": "Subscribe & Save"}.get(p, str(p))

    # --- controls on the approval card --------------------------------------

    def buy_enabled(self):
        if self.variant == "baseline":
            # Comparison condition: generic summary card, Buy always available (SPEC v1 card).
            return self.status in ("awaiting_approval", "blocked", "awaiting_terms") and bool(self.readback and self.readback.get("ok"))
        return self.status == "awaiting_approval"

    def acknowledge_terms(self, value=True):
        """Tick or untick "I understand this repeats". Unticking takes Buy away again."""
        self.acknowledged = bool(value)
        self._validate()
        if validator.buy_allowed(self.checks):
            self.status = "awaiting_approval"
        elif any(c["status"] == "wait" for c in self.checks):
            self.status = "awaiting_terms"
        else:
            self.status = "blocked"
        if self._check_step is not None:
            self.steps[self._check_step]["status"] = "done" if self.status == "awaiting_approval" else "wait"
        self.step("You confirmed the repeat terms" if self.acknowledged else "You withdrew the confirmation",
                  "done" if self.acknowledged else "wait")
        self.log("terms_acknowledged" if self.acknowledged else "terms_unacknowledged", {"snapshot": self.snapshot})

    def retry(self):
        self.retry_count += 1
        self.log("retry", {"attempt": self.retry_count + 1})
        self.step(f"Retry {self.retry_count}: set the purchase option again", "done")
        self._prepare_basket()
        failed = [c for c in self.checks if c["status"] == "fail"]
        if failed:
            self.notice = f"Tried again (attempt {self.retry_count + 1}): still blocked. {failed[0]['message']}"
        else:
            self.notice = f"Tried again (attempt {self.retry_count + 1}): the checkout now matches your answers."

    def change(self, field, value):
        """Change one answer. Any earlier approval is void; the order is rebuilt and re-checked."""
        old = self.spec.get(field)
        self.spec[field] = value
        self.log("change", {"field": field, "from": old, "to": value, "invalidated_snapshot": self.snapshot})
        self.snapshot = None
        self.outcome = None
        self.status = "running"
        self._run()

    def set_variant(self, variant):
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.variant = variant
        self.log("variant_switched", {"variant": variant})

    def buy(self, approved_snapshot):
        if not self.buy_enabled():
            return {"error": "Buy is not available for this order."}
        current = self.shop.read_checkout()   # final check right before paying
        r7 = validator.r7_approval(approved_snapshot, current)
        self.log("buy_pressed", {"approved_snapshot": approved_snapshot, "R7": r7})
        if r7["status"] != "pass":
            self.readback = current
            self._read_back()
            self.step(r7["message"], "fail")
            return {"R7": r7}
        order = self.shop.place_order(current)
        r8 = validator.r8_outcome(order, current)
        self.outcome = {"order": order, "R8": r8, "summary": self._summary(order, r8)}
        self.status = "done" if r8["status"] == "pass" else "outcome_unknown"
        self.log("order_result", self.outcome)
        return self.outcome

    def cancel(self):
        self.shop.clear_task_items()
        self.status = "cancelled"
        self.log("cancelled", {"basket_after": self.shop.basket + self.shop.preexisting})

    def _summary(self, order, r8):
        if r8["status"] != "pass":
            return r8["message"]
        rec = "; repeats " + self.readback["subscription_terms"]["interval"] + " until you cancel" \
            if order["recurring"] else " once; no subscription"
        return (f"Ordered {order['quantity']} × {order['pack_size']}-sheet pack for "
                f"£{order['total']:.2f}{rec}. (Mock order {order['order_id']}; nothing was really bought.)")

    # --- what the page shows ------------------------------------------------------

    def understood(self):
        """Rows of the "Here's what I understood" card: what you said vs. what is missing."""
        rows = []
        for k in mock_model.FIELDS:
            v = self.parsed[k]
            rows.append({"field": k, "said": v != UNKNOWN, "value": v})
        return rows

    def disclosure(self):
        """Choices made on the person's behalf, each with its origin and consequence (A1 idea)."""
        if not self.chosen:
            return []
        items = []
        if self.spec["pack_choice"] == "delegated":
            items.append({"origin": "You let me choose",
                          "text": mock_model.explain_choice(self.spec, self.chosen, self.eligible)})
        else:
            items.append({"origin": "You asked",
                          "text": mock_model.explain_choice(self.spec, self.chosen, self.eligible)})
        note = self.purchase_option_note
        rb = self.readback or {}
        if note and note["changed_by_agent"]:
            if rb.get("purchase_type") == note["requested"]:
                items.append({"origin": "Shop default — I changed it",
                              "text": f"This listing defaulted to {self._option_label(note['default'])}. "
                                      f"I switched it to {self._option_label(note['requested'])} and re-read checkout to verify."})
            else:
                items.append({"origin": "Shop default — still on",
                              "text": f"This listing defaulted to {self._option_label(note['default'])}. "
                                      f"I tried to switch it off, but checkout still shows {self._option_label(rb.get('purchase_type'))}."})
        elif note:
            items.append({"origin": "Shop default — matches you",
                          "text": f"The listing's default was {self._option_label(note['default'])}, which is what you asked for; checked at checkout."})
        for e in self.excluded:
            items.append({"origin": "Not compared", "text": f"{e['id']}: {e['reason']}."})
        return items

    def visible_steps(self):
        """The baseline condition must not reveal validator results anywhere, including the step log."""
        if self.variant != "baseline":
            return self.steps
        out = []
        for i, st in enumerate(self.steps):
            if i == self._check_step:
                out.append({"text": "Prepared the checkout", "status": "neutral"})
            else:
                out.append(st)
        return out

    def view(self):
        rb = self.readback if self.readback and self.readback.get("ok") else None
        if rb:
            rb = dict(rb, unit_label=validator.unit_label(rb["unit_pack_price"], rb["pack_size"]))
        return {
            "id": self.id,
            "request": self.request,
            "scenario": self.scenario,
            "variant": self.variant,
            "status": self.status,
            "understood": self.understood(),
            "spec": self.spec,
            "missing": self.missing_fields(),
            "plan": self.plan() if self.status not in ("clarifying", "waiting") else None,
            "steps": self.visible_steps(),
            "notice": self.notice,
            "chosen": self.chosen,
            "readback": rb,
            "checks": self.checks,
            "disclosure": self.disclosure(),
            "snapshot": self.snapshot,
            "buy_enabled": self.buy_enabled(),
            "acknowledged": self.acknowledged,
            "outcome": self.outcome,
            "shop": {
                "selected_type": self.shop.selected_type,
                "basket": self.shop.basket,
                "preexisting": self.shop.preexisting,
                "orders": self.shop.orders,
            },
            "events": self.events[-30:],
        }
