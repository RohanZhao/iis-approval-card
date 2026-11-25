"""Simulated model.

Stands in for the LLM in SPEC v2. It is deterministic on purpose, so every
run of the prototype and every test gives the same result.

What a real LLM would do here:
  1. parse_request: turn a free-text request into the five task fields.
  2. explain_choice: write the one-line reason shown on the card.

Rule from SPEC v2: anything the person did not say stays "unknown".
The model never fills a gap with a guess. Gaps are asked about in the
"Here's what I understood" card instead.
"""

import re

UNKNOWN = "unknown"
FIELDS = ("item", "pack_choice", "quantity", "budget", "purchase_type")

_NUMBER_WORDS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def parse_request(text):
    """Return the five task fields. Unstated fields are UNKNOWN."""
    t = " " + text.lower().replace("colour catchers", "colour catcher sheets") + " "
    return {
        "item": _item(t),
        "pack_choice": _pack(t),
        "quantity": _quantity(t),
        "budget": _budget(t),
        "purchase_type": _purchase_type(t),
    }


def _item(t):
    if re.search(r"colou?r[\s-]*catcher", t):
        return "colour catcher sheets"
    return UNKNOWN


def _pack(t):
    # "40 sheets", "40-sheet", "pack of 40", "40 colour catcher sheets"
    m = (
        re.search(r"(\d+)[\s-]*sheets?", t)
        or re.search(r"packs? of (\d+)", t)
        or re.search(r"(\d+)\s+colou?r\s*catcher", t)
    )
    if m:
        return int(m.group(1))
    if re.search(r"(you choose|any size|whichever (size|pack))", t):
        return "delegated"
    return UNKNOWN


def _quantity(t):
    m = re.search(r"\b(\d+|one|a|an|two|three|four|five)\s+packs?\b", t)
    if m:
        word = m.group(1)
        return int(word) if word.isdigit() else _NUMBER_WORDS[word]
    return UNKNOWN


def _budget(t):
    m = re.search(r"(under|below|less than)\s*£\s*(\d+(?:\.\d+)?)", t)
    if m:
        return {"op": "lt", "amount": float(m.group(2))}
    m = re.search(r"(max(?:imum)?|up to|at most|no more than)\s*£\s*(\d+(?:\.\d+)?)", t)
    if m:
        return {"op": "le", "amount": float(m.group(2))}
    if re.search(r"no (price |budget )?limit", t):
        return {"op": "none"}
    return UNKNOWN


def _purchase_type(t):
    if re.search(r"(one[\s-]*time|one[\s-]*off|just once|buy once|no subscri|not? (a )?subscri|don'?t subscribe)", t):
        return "one_time"
    if re.search(r"subscri", t):
        return "subscription"
    return UNKNOWN


def explain_choice(spec, chosen, candidates):
    """One-line reason for the chosen offer (an LLM would write this)."""
    ptype = spec["purchase_type"]
    unit = chosen["unit_price_p"]
    label = chosen["unit_label"]
    if spec["pack_choice"] == "delegated":
        reason = (
            f"You let me choose the pack: {chosen['pack_size']} sheets has the lowest "
            f"{_ptype_word(ptype)} price per sheet among the readable offers that fit your limit "
            f"({label}p)."
        )
        cheaper_over_limit = [c for c in candidates if c["unit_price_p"] < unit and not c["fits_budget"]]
        if cheaper_over_limit:
            c = min(cheaper_over_limit, key=lambda x: x["unit_price_p"])
            reason += f" The {c['pack_size']}-sheet pack is cheaper per sheet but goes over your limit."
        return reason
    return (
        f"You asked for {chosen['pack_size']} sheets: this is the cheapest readable "
        f"{_ptype_word(ptype)} offer of that size ({label}p per sheet)."
    )


def _ptype_word(ptype):
    return "one-time" if ptype == "one_time" else "subscription"
