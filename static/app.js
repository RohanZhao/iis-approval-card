// Approval-card prototype: page logic.
// All decisions are made on the server (agent.py + validator.py); this file only
// shows the task state and sends the person's actions.

let LISTINGS = [];
let task = null;
let answers = {};          // answers being edited on the "Here's what I understood" card
let changeOpen = false;    // is the Change form open on the approval card

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid);
  return e;
};
const money = (x) => `£${Number(x).toFixed(2)}`;
const PTYPE = { one_time: "One-time", subscription: "Subscribe & Save" };

async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data;
}

async function act(action, body = {}) {
  task = await api(`/api/task/${task.id}/${action}`, body);
  render();
}

// ---------- start ----------

async function init() {
  const data = await api("/api/listings");
  LISTINGS = data.listings;
  for (const [k, v] of Object.entries(data.scenarios)) $("#scenario").append(el("option", { value: k }, v));
  for (const chip of document.querySelectorAll(".chip")) chip.addEventListener("click", () => ($("#request").value = chip.textContent));
  $("#request-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      task = await api("/api/task", {
        text: $("#request").value,
        scenario: $("#scenario").value,
        variant: $("#variant-toggle").checked ? "baseline" : "disclosure",
      });
      answers = {};
      for (const k of ["pack_choice", "quantity", "budget", "purchase_type"]) if (task.spec[k] !== "unknown") answers[k] = task.spec[k];
      changeOpen = false;
      render();
    } catch (e) { alert(e.message); }
  });
  $("#variant-toggle").addEventListener("change", () => {
    if (task) act("variant", { variant: $("#variant-toggle").checked ? "baseline" : "disclosure" });
  });
  renderShop();
}

// ---------- shop (left) ----------

function renderShop() {
  const box = $("#listings");
  box.replaceChildren();
  const sel = task ? task.shop.selected_type : {};
  const chosen = task && task.chosen ? task.chosen.id : null;
  for (const l of LISTINGS) {
    const card = el("article", { class: "listing" + (chosen === l.id ? " chosen" : "") },
      el("h3", {}, `${l.id} · ${l.title}, ${l.pack_size} sheets`, chosen === l.id ? el("span", { class: "tag" }, "Agent chose this") : null),
      el("p", { class: "seller" }, l.seller));
    if (!l.readable) {
      card.append(el("p", { class: "error" }, "⚠ Page did not load (timed out)."));
    } else {
      const current = sel[l.id] || l.default_purchase_type;
      for (const [ptype, price] of Object.entries(l.prices)) {
        const unit = l.unit_labels[ptype];
        const extra = ptype === "subscription" ? ` · ${l.subscription_terms.interval}, ${l.subscription_terms.ends}` : "";
        card.append(el("label", { class: "option" },
          el("input", { type: "radio", name: `opt-${l.id}`, disabled: true, checked: current === ptype }),
          ` ${PTYPE[ptype]}: ${money(price)} (${unit}p/sheet)${extra}`));
      }
    }
    box.append(card);
  }
  const basket = $("#basket");
  basket.replaceChildren();
  const items = task ? [...task.shop.preexisting, ...task.shop.basket] : [{ title: "Washing-up liquid", added_by: "person" }];
  for (const b of items) {
    const name = b.title || `${b.quantity} × ${b.id} (${LISTINGS.find((l) => l.id === b.id).pack_size} sheets)`;
    basket.append(el("li", {}, name, el("span", { class: "tag " + (b.added_by === "agent" ? "agent" : "") }, b.added_by === "agent" ? "added by agent" : "yours")));
  }
  const orders = $("#orders");
  orders.replaceChildren();
  if (task && task.shop.orders.length) {
    orders.append(el("h2", {}, "Mock orders"));
    for (const o of task.shop.orders) orders.append(el("p", {}, `${o.order_id}: ${o.quantity} × ${o.pack_size} sheets, ${money(o.total)}${o.recurring ? ", repeating" : ", once"}`));
  }
}

// ---------- agent panel (right) ----------

function render() {
  renderShop();
  $("#variant-toggle").checked = task.variant === "baseline";
  const flow = $("#flow");
  flow.replaceChildren();
  flow.append(el("p", { class: "you" }, el("strong", {}, "You: "), task.request));

  if (task.status === "clarifying") flow.append(understoodCard());
  else if (task.status === "waiting") flow.append(waitingCard());
  else {
    flow.append(planBox(), stepLog());
    if (task.status === "no_offer") flow.append(noOfferCard());
    else if (["awaiting_approval", "blocked", "awaiting_terms"].includes(task.status)) {
      flow.append(task.variant === "baseline" ? baselineCard() : disclosureCard());
    } else if (task.status === "done" || task.status === "outcome_unknown") flow.append(outcomeCard());
    else if (task.status === "cancelled") flow.append(el("div", { class: "card" }, el("h2", {}, "Cancelled"),
      el("p", {}, "No order was placed. I removed only the item I added; your own basket items are untouched.")));
  }
  renderLog();
}

function statusTag(said, answered) {
  if (said) return el("span", { class: "tag said" }, "from your request");
  return answered ? el("span", { class: "tag" }, "your answer") : el("span", { class: "tag ask" }, "Please choose");
}

// "Here's what I understood" (R1)
function understoodCard() {
  const rows = [
    ["pack_choice", "Pack size", [[20, "20"], [40, "40"], [80, "80"], ["delegated", "You choose: cheapest per sheet"]]],
    ["quantity", "Quantity", [[1, "1 pack"], [2, "2 packs"], [3, "3 packs"]]],
    ["purchase_type", "Purchase type", [["one_time", "One-time"], ["subscription", "Subscription — review repeat terms before buying"]]],
  ];
  const said = Object.fromEntries(task.understood.map((r) => [r.field, r.said]));
  const card = el("div", { class: "card understood" },
    el("h2", {}, "Here's what I understood"),
    el("p", { class: "row" }, el("span", { class: "label" }, "Item"), "colour catcher sheets", el("span", { class: "tag said" }, "from your request")));
  for (const [field, label, opts] of rows) {
    const row = el("div", { class: "row" }, el("span", { class: "label" }, label),
      statusTag(said[field], answers[field] !== undefined));
    const group = el("div", { class: "choices", role: "group", "aria-label": label });
    for (const [value, text] of opts) {
      group.append(el("button", { type: "button", class: "choice" + (JSON.stringify(answers[field]) === JSON.stringify(value) ? " on" : ""), "aria-pressed": String(JSON.stringify(answers[field]) === JSON.stringify(value)),
        onclick: () => { answers[field] = value; render(); } }, text));
    }
    row.append(group);
    card.append(row);
  }
  // budget
  const b = answers.budget;
  const budgetRow = el("div", { class: "row" }, el("span", { class: "label" }, "Budget"),
    statusTag(said.budget, answers.budget !== undefined));
  const group = el("div", { class: "choices" });
  if (b && b.op === "lt") group.append(el("button", { type: "button", class: "choice on" }, `Total under ${money(b.amount)}`));
  const input = el("input", { type: "number", min: "0.01", step: "0.01", placeholder: "e.g. 5", "aria-label": "Maximum total in pounds",
    value: b && b.op === "le" ? b.amount : "" });
  group.append(el("span", { class: "inline" }, "Maximum total £", input,
    el("button", { type: "button", class: "choice" + (b && b.op === "le" ? " on" : ""), onclick: () => {
      const v = parseFloat(input.value);
      if (v > 0) { answers.budget = { op: "le", amount: v }; render(); }
    } }, "Set")));
  group.append(el("button", { type: "button", class: "choice" + (b && b.op === "none" ? " on" : ""), onclick: () => { answers.budget = { op: "none" }; render(); } }, "No limit"));
  budgetRow.append(group);
  card.append(budgetRow);

  const missing = ["pack_choice", "quantity", "purchase_type", "budget"].filter((k) => answers[k] === undefined);
  if (missing.length) card.append(el("p", { class: "note" }, "I won't search or touch the basket until these are answered."));
  card.append(
    el("div", { class: "actions" },
      el("button", { type: "button", class: "primary", disabled: missing.length > 0, onclick: () => act("confirm", { answers }) }, "Confirm and start"),
      el("button", { type: "button", onclick: () => act("close") }, "Close")));
  return card;
}

function waitingCard() {
  return el("div", { class: "card waiting" },
    el("h2", {}, "⏸ Waiting for clarification"),
    el("p", {}, "I have not chosen an offer, changed the basket or prepared any payment. Still needed: " +
      task.missing.map((f) => f.replace("_", " ")).join(", ") + "."),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "primary", onclick: () => act("resume") }, "Resume"),
      el("button", { type: "button", onclick: () => act("cancel") }, "Cancel task")));
}

function planBox() {
  return el("div", { class: "plan" }, el("h3", {}, "Plan"),
    el("ol", {}, task.plan.map((p) => el("li", {}, p.text, p.consequential ? el("span", { class: "tag ask" }, "⚠ will ask you first") : null))));
}

function stepLog() {
  return el("div", { class: "steps" }, el("h3", {}, "What I did"),
    el("ul", {}, task.steps.map((s) => el("li", { class: s.status }, { done: "✓ ", warn: "⚠ ", fail: "✗ ", wait: "⏸ ", neutral: "• " }[s.status] || "", s.text))));
}

function orderLines(rb) {
  return el("div", { class: "order" },
    el("p", {}, `${rb.quantity} pack × ${rb.pack_size} colour catcher sheets`),
    el("p", {}, `Item ${money(rb.unit_pack_price * rb.quantity)} + delivery ${money(rb.delivery)} = `, el("strong", {}, `${money(rb.final_total)} total`)),
    el("p", { class: "ptype" }, el("strong", {}, rb.recurring
      ? `Subscription: ${money(rb.unit_pack_price)} ${rb.subscription_terms.interval}, ${rb.subscription_terms.ends}.`
      : "One-time purchase; no subscription or repeat charge.")));
}

// Revised card (SPEC v2): verified order + choices made on your behalf + checks
function disclosureCard() {
  const rb = task.readback;
  const failed = task.checks.filter((c) => c.status === "fail");
  const card = el("div", { class: "card approval" + (failed.length ? " blocked" : "") },
    el("h2", {}, failed.length ? "I can't let you buy this yet" : "Before you buy — verified mock checkout"));
  if (rb) card.append(orderLines(rb));
  for (const c of failed) card.append(el("p", { class: "problem", role: "alert" }, el("strong", {}, "⚠ Problem: "), c.message));
  if (task.notice) card.append(el("p", { class: "notice", role: "status" }, task.notice));
  card.append(el("h3", {}, "Choices made for you"),
    el("ul", { class: "disclosure" }, task.disclosure.map((d) => el("li", {}, el("span", { class: "origin" }, d.origin), " ", d.text))));
  if (task.status === "awaiting_terms" || (rb && rb.recurring && task.acknowledged)) {
    card.append(el("div", { class: "terms" },
      el("p", {}, `A new ${rb.pack_size}-sheet pack ${rb.subscription_terms.interval}, ${money(rb.unit_pack_price)} each time, ${rb.subscription_terms.ends}. You can cancel in the subscription settings.`),
      el("label", {}, el("input", { type: "checkbox", checked: task.acknowledged, onchange: (ev) => act("acknowledge", { value: ev.target.checked }) }), " I understand this repeats until I cancel")));
  }
  card.append(el("details", {}, el("summary", {}, "What I checked"),
    el("ul", { class: "checks" }, task.checks.map((c) => el("li", { class: c.status }, `${c.rule} ${c.name}: ${c.status.toUpperCase()} — ${c.message}`)))));
  const actions = el("div", { class: "actions" });
  if (task.buy_enabled) {
    const label = rb.recurring ? `Buy: ${money(rb.final_total)} now, then ${rb.subscription_terms.interval}` : `Buy once for ${money(rb.final_total)}`;
    actions.append(el("button", { type: "button", class: "primary", onclick: () => act("buy", { snapshot: task.snapshot }) }, label));
  } else if (failed.some((c) => c.rule === "R3")) {
    actions.append(el("button", { type: "button", onclick: () => act("retry") }, "Retry"));
  }
  actions.append(el("button", { type: "button", onclick: () => { changeOpen = !changeOpen; render(); } }, "Change…"),
    el("button", { type: "button", onclick: () => act("cancel") }, "Cancel"));
  card.append(actions);
  if (changeOpen) card.append(changeForm());
  return card;
}

// Baseline card (SPEC v1): order summary only, generic Buy / Change / Cancel
function baselineCard() {
  const rb = task.readback;
  const card = el("div", { class: "card approval baseline" },
    el("p", { class: "variant-note" }, "Baseline card (A3 comparison condition): order summary only. Validator results are logged but not shown and do not block Buy."),
    el("h2", {}, "Before you buy"));
  if (rb) {
    card.append(el("p", {}, `${rb.quantity} × ${rb.pack_size} colour catcher sheets — ${money(rb.final_total)}`));
    card.append(el("p", {}, `Best value per sheet (${rb.unit_label}p).`));
  }
  const actions = el("div", { class: "actions" },
    el("button", { type: "button", class: "primary", disabled: !task.buy_enabled, onclick: () => act("buy", { snapshot: task.snapshot }) }, "Buy"),
    el("button", { type: "button", onclick: () => { changeOpen = !changeOpen; render(); } }, "Change…"),
    el("button", { type: "button", onclick: () => act("cancel") }, "Cancel"));
  card.append(actions);
  if (changeOpen) card.append(changeForm());
  return card;
}

function changeForm() {
  const f = el("div", { class: "change" }, el("p", {}, "Change one answer. Any earlier approval is cancelled and I check the new order again."));
  const opt = (field, value, text) => el("button", { type: "button", class: "choice", onclick: () => { changeOpen = false; act("change", { field, value }); } }, text);
  f.append(
    el("div", {}, "Pack: ", opt("pack_choice", 20, "20"), opt("pack_choice", 40, "40"), opt("pack_choice", 80, "80"), opt("pack_choice", "delegated", "You choose")),
    el("div", {}, "Quantity: ", opt("quantity", 1, "1"), opt("quantity", 2, "2"), opt("quantity", 3, "3")),
    el("div", {}, "Type: ", opt("purchase_type", "one_time", "One-time"), opt("purchase_type", "subscription", "Subscription")),
    el("div", {}, "Budget: ", opt("budget", { op: "lt", amount: 5 }, "Under £5"), opt("budget", { op: "le", amount: 10 }, "Max £10"), opt("budget", { op: "none" }, "No limit")));
  return f;
}

function noOfferCard() {
  return el("div", { class: "card blocked" }, el("h2", {}, "No order prepared"),
    el("p", {}, task.steps[task.steps.length - 1].text + " I did not relax any of your answers."),
    el("ul", { class: "disclosure" }, task.disclosure.map((d) => el("li", {}, el("span", { class: "origin" }, d.origin), " ", d.text))),
    el("div", { class: "actions" },
      el("button", { type: "button", onclick: () => { changeOpen = !changeOpen; render(); } }, "Change…"),
      el("button", { type: "button", onclick: () => act("cancel") }, "Cancel")),
    changeOpen ? changeForm() : null);
}

function outcomeCard() {
  const ok = task.status === "done";
  return el("div", { class: "card " + (ok ? "done" : "blocked") }, el("h2", {}, ok ? "✓ Order placed (mock)" : "Outcome unknown"),
    el("p", {}, task.outcome.summary));
}

function renderLog() {
  const log = $("#log");
  log.replaceChildren();
  for (const e of task.events) {
    log.append(el("li", {}, el("details", {},
      el("summary", {}, el("code", {}, e.event), " ", new Date(e.t * 1000).toLocaleTimeString()),
      el("pre", {}, JSON.stringify(e.data, null, 2)))));
  }
}

init();
