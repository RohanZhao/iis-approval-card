"""Tests for the SPEC v2 cases (Lab 3), run against the real agent and validator code.

Run from the project folder:   python3 -m unittest -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mock_model                     # noqa: E402
import validator                      # noqa: E402
from agent import Task                # noqa: E402

VAGUE = "Get me some colour catchers, compare prices."
FULL = "Buy one pack of 40 colour catcher sheets on Amazon UK. One-time purchase, under £5. Compare prices first."
DELEGATE = {"pack_choice": "delegated", "quantity": 1, "purchase_type": "one_time", "budget": {"op": "none"}}


def task(text=VAGUE, **kw):
    return Task(text, log=False, **kw)


class ParseTests(unittest.TestCase):
    def test_full_request_parses_all_five_fields(self):
        p = mock_model.parse_request(FULL)
        self.assertEqual(p, {"item": "colour catcher sheets", "pack_choice": 40, "quantity": 1,
                             "budget": {"op": "lt", "amount": 5.0}, "purchase_type": "one_time"})

    def test_vague_request_leaves_four_unknowns(self):
        p = mock_model.parse_request(VAGUE)
        self.assertEqual([k for k, v in p.items() if v == "unknown"],
                         ["pack_choice", "quantity", "budget", "purchase_type"])


class SpecCaseTests(unittest.TestCase):
    def test_A_standard_input_gives_verified_40_sheet_card(self):
        t = task(FULL)
        t.confirm({})
        self.assertEqual(t.status, "awaiting_approval")
        self.assertEqual((t.chosen["id"], t.readback["final_total"], t.readback["recurring"]), ("O2", 3.85, False))

    def test_B_revised_delegated_choice_picks_O3_one_time(self):
        t = task()
        t.confirm(DELEGATE)
        self.assertEqual(t.chosen["id"], "O3")
        self.assertEqual(t.readback["purchase_type"], "one_time")
        self.assertEqual(t.readback["final_total"], 7.20)
        origins = [d["origin"] for d in t.disclosure()]
        self.assertIn("Shop default — I changed it", origins)
        self.assertIn("Not compared", origins)            # O4 timed out and is disclosed
        out = t.buy(t.snapshot)
        self.assertEqual(out["R8"]["status"], "pass")
        self.assertFalse(out["order"]["recurring"])

    def test_C_unanswered_card_waits_and_touches_nothing(self):
        t = task()
        t.close_clarification()
        self.assertEqual(t.status, "waiting")
        r1 = t.confirm({"quantity": 1})                     # still three unknowns
        self.assertEqual(r1["status"], "fail")
        self.assertEqual(t.shop.basket, [])
        self.assertIsNone(t.chosen)
        self.assertFalse(t.buy_enabled())

    def test_D_subscription_that_stays_on_blocks_buy(self):
        t = task(scenario="subscription_sticks")
        t.confirm(DELEGATE)
        self.assertEqual(t.status, "blocked")
        r3 = next(c for c in t.checks if c["rule"] == "R3")
        self.assertIn("Purchase type does not match", r3["message"])
        self.assertFalse(t.buy_enabled())
        self.assertIn("error", t.buy(t.snapshot))
        t.retry()                                           # the shop still ignores the click
        self.assertEqual(t.status, "blocked")
        t.change("pack_choice", 40)                         # person changes to 40 sheets
        self.assertEqual((t.status, t.chosen["id"], t.readback["final_total"]), ("awaiting_approval", "O2", 3.85))

    def test_E_test_A_replay_one_time_backed_by_read_back(self):
        t = task(FULL)
        t.confirm({})
        r3 = next(c for c in t.checks if c["rule"] == "R3")
        self.assertEqual(r3["status"], "pass")
        self.assertEqual(t.readback["purchase_type"], "one_time")

    def test_F_total_becomes_exactly_5_after_approval(self):
        t = task(FULL)
        t.confirm({})
        approved = t.snapshot
        t.shop.overrides["readback"] = {"unit_pack_price": 5.00, "final_total": 5.00}   # price rises at checkout
        out = t.buy(approved)
        self.assertEqual(out["R7"]["status"], "fail")      # old approval no longer applies
        self.assertEqual(t.shop.orders, [])
        self.assertEqual(t.status, "blocked")
        r5 = next(c for c in t.checks if c["rule"] == "R5")
        self.assertEqual(r5["status"], "fail")              # £5 is not under £5

    def test_G_explicit_subscription_needs_acknowledgement(self):
        t = task()
        t.confirm({**DELEGATE, "pack_choice": 40, "purchase_type": "subscription"})
        self.assertEqual(t.status, "awaiting_terms")
        self.assertFalse(t.buy_enabled())
        t.acknowledge_terms()
        self.assertEqual(t.status, "awaiting_approval")
        out = t.buy(t.snapshot)
        self.assertTrue(out["order"]["recurring"])
        self.assertEqual(out["order"]["total"], 3.66)

    def test_H_unreadable_checkout_blocks_without_inventing_values(self):
        t = task(FULL, shop_overrides={"readback": {"purchase_type": None}})
        t.confirm({})
        self.assertEqual(t.status, "blocked")
        r3 = next(c for c in t.checks if c["rule"] == "R3")
        self.assertIn("cannot read", r3["message"])
        self.assertFalse(t.buy_enabled())


class OtherBehaviourTests(unittest.TestCase):
    def test_cancel_removes_only_the_agents_item(self):
        t = task(FULL)
        t.confirm({})
        t.cancel()
        self.assertEqual(t.shop.basket, [])
        self.assertEqual(t.shop.preexisting[0]["added_by"], "person")
        self.assertEqual(t.shop.orders, [])

    def test_budget_is_never_relaxed(self):
        t = task()
        t.confirm({**DELEGATE, "budget": {"op": "lt", "amount": 2}})   # nothing costs under £2
        self.assertEqual(t.status, "no_offer")
        self.assertEqual(t.shop.basket, [])

    def test_delegated_choice_respects_budget_and_says_so(self):
        t = task()
        t.confirm({**DELEGATE, "budget": {"op": "lt", "amount": 5}})
        self.assertEqual(t.chosen["id"], "O2")
        self.assertIn("cheaper per sheet but goes over your limit", t.disclosure()[0]["text"])

    def test_change_invalidates_earlier_approval(self):
        t = task()
        t.confirm(DELEGATE)
        old = t.snapshot
        t.change("quantity", 2)
        self.assertEqual(t.status, "awaiting_approval")
        self.assertNotEqual(old, t.snapshot)
        out = t.buy(old)
        self.assertEqual(out["R7"]["status"], "fail")

    def test_unknown_order_result_is_reported_not_retried(self):
        t = task(FULL, shop_overrides={"order_fails": True})
        t.confirm({})
        out = t.buy(t.snapshot)
        self.assertEqual(out["R8"]["status"], "fail")
        self.assertEqual(t.status, "outcome_unknown")

    def test_baseline_card_shows_same_order_but_does_not_block(self):
        t = task(scenario="subscription_sticks", variant="baseline")
        t.confirm(DELEGATE)
        self.assertEqual(t.status, "blocked")              # validator still runs and logs
        self.assertTrue(t.buy_enabled())                    # but the baseline card does not use it


class ManualCheckFixTests(unittest.TestCase):
    """Problems Renhan found by running the page on 25 Nov."""

    def test_checks_list_includes_R2(self):
        t = task(FULL)
        t.confirm({})
        self.assertEqual([c["rule"] for c in t.checks], ["R1", "R2", "R3", "R4", "R5", "R6"])

    def test_unit_price_rounding_matches_shop_page(self):
        self.assertEqual(validator.unit_label(3.85, 40), "9.63")   # 9.625p rounds half up
        t = task(FULL)
        t.confirm({})
        self.assertIn("9.63p", t.disclosure()[0]["text"])

    def test_baseline_unit_price_comes_from_checkout_not_chosen_offer(self):
        t = task(scenario="subscription_sticks", variant="baseline")
        t.confirm(DELEGATE)
        self.assertEqual(t.view()["readback"]["unit_label"], "8.55")      # £6.84 / 80, not the one-time 9.00p

    def test_baseline_step_log_hides_validator_result(self):
        t = task(scenario="subscription_sticks", variant="baseline")
        t.confirm(DELEGATE)
        self.assertNotIn("fail", [s["status"] for s in t.view()["steps"]])

    def test_retry_gives_feedback(self):
        t = task(scenario="subscription_sticks")
        t.confirm(DELEGATE)
        t.retry()
        self.assertIn("attempt 2", t.view()["notice"])

    def test_subscription_acknowledgement_can_be_withdrawn(self):
        t = task()
        t.confirm({**DELEGATE, "pack_choice": 40, "purchase_type": "subscription"})
        t.acknowledge_terms(True)
        self.assertTrue(t.buy_enabled())
        self.assertEqual(t.steps[t._check_step]["status"], "done")
        t.acknowledge_terms(False)
        self.assertFalse(t.buy_enabled())
        self.assertEqual(t.status, "awaiting_terms")


class ValidatorUnitTests(unittest.TestCase):
    def test_under_means_strictly_less(self):
        self.assertFalse(validator.budget_ok(5.00, {"op": "lt", "amount": 5}))
        self.assertTrue(validator.budget_ok(4.99, {"op": "lt", "amount": 5}))
        self.assertTrue(validator.budget_ok(5.00, {"op": "le", "amount": 5}))

    def test_no_limit_and_delegation_count_as_answers(self):
        spec = {"item": "x", "pack_choice": "delegated", "quantity": 1, "budget": {"op": "none"}, "purchase_type": "one_time"}
        self.assertEqual(validator.r1_confirmed_inputs(spec)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
