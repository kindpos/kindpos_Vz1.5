// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Pricing source of truth
//
//  One place to hold TAX_RATE and CASH_DISCOUNT plus the
//  helper that turns a subtotal into the per-tender totals
//  the checkout UI displays. Previously every scene
//  (check-overview, order-entry, manager-landing,
//  server-landing) kept its own copy, and four copies
//  meant four opportunities for a stale rate to drift
//  past a payment. Use `getRates()` or `computeTotals()`
//  from this module; never re-declare TAX_RATE.
//
//  `totalsForOrder(order, fallbackSubtotal)` should be
//  preferred whenever a backend Order projection is on
//  hand — it routes through `order.balance_due` /
//  `order.total` so the number on screen matches what
//  the backend will charge, even if /config/pricing
//  hasn't yet loaded.
//
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

// Defaults kick in when the browser hasn't yet heard back from
// /api/v1/config/pricing. They match the long-standing POS defaults
// so a first render before the fetch completes looks sane.
var _taxRate = 0.07;
var _cashDiscount = 0.04;
var _loaded = false;
var _loadPromise = null;

function _roundCents(n) {
  return Math.round((n || 0) * 100) / 100;
}

function _loadRates() {
  if (_loadPromise) return _loadPromise;
  _loadPromise = fetch('/api/v1/config/pricing')
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(d) {
      if (d) {
        if (d.tax_rate != null) _taxRate = d.tax_rate;
        if (d.cash_discount_rate != null) _cashDiscount = d.cash_discount_rate;
      }
      _loaded = true;
    })
    .catch(function() { _loaded = true; /* keep defaults */ });
  return _loadPromise;
}

// Kick the fetch off at module-import time so scenes that render
// synchronously still get the latest rates as soon as possible.
_loadRates();

// ── Public accessors ────────────────────────────────

export function getTaxRate()       { return _taxRate; }
export function getCashDiscount()  { return _cashDiscount; }

// Returns { taxRate, cashDiscount } — keep reading it, don't cache;
// the value updates once /api/v1/config/pricing resolves.
export function getRates() {
  return { taxRate: _taxRate, cashDiscount: _cashDiscount };
}

// Useful for callers that want to block until the canonical rates
// are in hand (e.g. a first-paint spinner).
export function ratesReady() { return _loadRates(); }

// ── Computation helpers ─────────────────────────────

// Compute all per-tender totals from a raw subtotal (items only, no
// discounts). Every scene that builds a preview total should use this
// exactly once so a future tax change touches one line of code.
export function computeTotals(subtotal) {
  var sub = _roundCents(subtotal);
  var tax = _roundCents(sub * _taxRate);
  var cardTotal = _roundCents(sub + tax);
  var cashPrice = _roundCents(cardTotal * (1 - _cashDiscount));
  return { subtotal: sub, tax: tax, cardTotal: cardTotal, cashPrice: cashPrice };
}

// Prefer backend-computed totals when we have an Order projection.
// `order.total` already reflects discounts, refunds, captured tax, and
// event-sourced tax at payment time; `order.balance_due` reflects
// what's still owed. Falls back to `computeTotals(fallbackSubtotal)`
// when the order hasn't been persisted yet (new-order preview).
export function totalsForOrder(order, fallbackSubtotal) {
  if (order && typeof order.total === 'number') {
    var cardTotal = _roundCents(order.total);
    var subtotal = typeof order.subtotal === 'number'
      ? _roundCents(order.subtotal)
      : _roundCents(cardTotal / (1 + _taxRate));
    var tax = _roundCents(cardTotal - subtotal);
    var cashPrice = _roundCents(cardTotal * (1 - _cashDiscount));
    return {
      subtotal: subtotal,
      tax: tax,
      cardTotal: cardTotal,
      cashPrice: cashPrice,
      balanceDue: typeof order.balance_due === 'number'
        ? _roundCents(order.balance_due)
        : cardTotal,
    };
  }
  return computeTotals(fallbackSubtotal || 0);
}
