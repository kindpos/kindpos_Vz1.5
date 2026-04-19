// ═══════════════════════════════════════════════════
//  KINDpos Terminal — check-overview  (Vz2.0, adaptive)
//  Working layer: full check management with 3 layout modes.
//
//    Mode A  1-4 seats   full-width seat cards
//    Mode B  5 seats     4 full cards + 5th column (shortened card + compact ＋)
//    Mode C  6+ seats    OrderSummary (items-only) + compact seat grid
//
//  Persistent across modes:
//    - Green header (check name tappable to edit)
//    - Bottom-left: totals corner (Subtotal/Tax + Card/Cash)
//    - Bottom-right: 2×3 action grid (PRINT DISC ADD / PAY VOID RESEND)
//
//  Interactions:
//    - Tap seat header  → toggle seat selection
//    - Tap item row     → toggle item selection
//    - Long-press item  → per-item menu
//    - Long-press on selection → bulk menu
//    - Long-press seat header → seat menu (void, merge, split, transfer…)
//
//  SceneManager.mountWorking('check-overview', {
//    checkId, returnLanding, employeeId, employeeName, pin
//  })
// ═══════════════════════════════════════════════════

import { SceneManager, defineScene } from '../scene-manager.js';
import { T } from '../tokens.js';
import {
  buildPillButton,
  hexToRgba,
  darkenHex,
} from '../theme-manager.js';
import { OrderSummary } from '../order-summary.js';
import { buildNumpad } from '../numpad.js';
import { showToast } from '../components.js';
import { setSceneName, setHeaderBack } from '../app.js';
import { showKeyboard, hideKeyboard } from '../keyboard.js';
import { computeTotals } from '../pricing.js';
import './column-editor.js';

var _refreshInFlight = false;

// ── Inject invisible scrollbar style ──
(function() {
  if (document.getElementById('co-scroll-style')) return;
  var s = document.createElement('style');
  s.id = 'co-scroll-style';
  s.textContent = '.co-scroll::-webkit-scrollbar{display:none}';
  document.head.appendChild(s);
})();

// ═══════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════

function fmt(n) { return '$' + (n || 0).toFixed(2); }

function seatTotal(seat) {
  var t = 0;
  for (var i = 0; i < seat.items.length; i++) {
    t += seat.items[i].qty * (seat.items[i].effectivePrice || seat.items[i].price);
  }
  return t;
}

function checkTotals(seats, paidSeats) {
  var subtotal = 0;
  for (var i = 0; i < seats.length; i++) {
    if (paidSeats && paidSeats[seats[i].id]) continue;
    for (var j = 0; j < seats[i].items.length; j++) {
      var it = seats[i].items[j];
      subtotal += it.qty * (it.effectivePrice || it.price);
    }
  }
  return computeTotals(subtotal);
}

function activeSeatCount(seats, paidSeats) {
  var n = 0;
  for (var i = 0; i < seats.length; i++) {
    if (!paidSeats || !paidSeats[seats[i].id]) n++;
  }
  return n;
}

// A = 1-4 active seats · B = 5 · C = 6+
function modeFor(count) {
  if (count <= 4) return 'A';
  if (count === 5) return 'B';
  return 'C';
}

function orderToSeats(order, minSeats) {
  minSeats = minSeats || 1;
  var bySeat = {};
  var allIds = [];

  if (order && Array.isArray(order.items)) {
    for (var i = 0; i < order.items.length; i++) {
      var it = order.items[i];
      var sn = it.seat_number || 1;
      var seatId = 'S-' + String(sn).padStart(3, '0');
      if (!bySeat[seatId]) {
        bySeat[seatId] = { id: seatId, number: sn, items: [] };
        allIds.push(seatId);
      }
      bySeat[seatId].items.push({
        item_id:        it.item_id,
        menu_item_id:   it.menu_item_id,
        name:           it.name,
        qty:            it.qty || 1,
        price:          it.price || 0,
        effectivePrice: it.effective_price != null ? it.effective_price : null,
        mods:           it.mods || [],
        notes:          it.notes || '',
        category:       it.category,
      });
    }
  }

  var maxNum = 0;
  for (var k = 0; k < allIds.length; k++) {
    if (bySeat[allIds[k]].number > maxNum) maxNum = bySeat[allIds[k]].number;
  }
  while (allIds.length < minSeats || maxNum < minSeats) {
    maxNum++;
    var newId = 'S-' + String(maxNum).padStart(3, '0');
    if (!bySeat[newId]) {
      bySeat[newId] = { id: newId, number: maxNum, items: [] };
      allIds.push(newId);
    }
  }

  allIds.sort(function(a, b) { return bySeat[a].number - bySeat[b].number; });
  return allIds.map(function(id) { return bySeat[id]; });
}

function collectSummary(seats, selected, paidSeats) {
  var items = [];
  var subtotal = 0;
  var anySelected = Object.keys(selected).length > 0;
  var visibleSeatCount = 0;
  for (var s = 0; s < seats.length; s++) {
    if (paidSeats && paidSeats[seats[s].id]) continue;
    visibleSeatCount++;
  }
  var showHeaders = visibleSeatCount > 1;
  for (var i = 0; i < seats.length; i++) {
    if (paidSeats && paidSeats[seats[i].id]) continue;
    if (anySelected && !selected[seats[i].id]) continue;
    var seatSub = 0;
    if (showHeaders) {
      for (var k = 0; k < seats[i].items.length; k++) {
        seatSub += seats[i].items[k].qty * (seats[i].items[k].effectivePrice || seats[i].items[k].price);
      }
      items.push({ seatHeader: true, seatId: seats[i].id, seatTotal: seatSub, seatIdx: i });
    }
    for (var j = 0; j < seats[i].items.length; j++) {
      var it = seats[i].items[j];
      var ep = it.effectivePrice || it.price;
      items.push({
        name:      it.name,
        qty:       it.qty,
        unitPrice: ep,
        mods:      it.mods || [],
        seatIdx:   i,
        itemIdx:   j,
        item_id:   it.item_id,
      });
      subtotal += it.qty * ep;
    }
  }
  var totals = computeTotals(subtotal);
  return {
    items:     items,
    subtotal:  totals.subtotal,
    tax:       totals.tax,
    cardTotal: totals.cardTotal,
    cashPrice: totals.cashPrice,
  };
}

var DISCOUNT_OPTIONS = [
  { label: '10% OFF',     pct: 10  },
  { label: '15% OFF',     pct: 15  },
  { label: '20% OFF',     pct: 20  },
  { label: 'COMP (100%)', pct: 100 },
];

// ═══════════════════════════════════════════════════
//  SCENE
// ═══════════════════════════════════════════════════

defineScene({
  name: 'check-overview',

  state: {
    listeners:     [],
    orderId:       null,
    order:         null,
    seats:         [],
    checkNumber:   '',
    customerName:  '',
    selected:      {},
    selectedItems: {},
    paidSeats:     {},
    _payingSeats:  [],
    _backConfirmed:false,
    rootEl:        null,
    topAreaEl:     null,
    totalsEl:      null,
    actionGridEl:  null,
    seatEls:       {},
    _lpTimers:     [],
    _mode:         null,
    _summaryItemMap:{},
    _osActive:     false,
  },

  render: function(container, params, state) {
    function track(el, event, handler) {
      el.addEventListener(event, handler);
      state.listeners.push({ el: el, event: event, handler: handler });
    }
    function trackBus(event, handler) {
      SceneManager.on(event, handler);
      state.listeners.push({ bus: true, event: event, handler: handler });
    }

    state.orderId       = params.checkId || null;
    state.checkNumber   = '';
    state.customerName  = '';
    state.selected      = {};
    state.selectedItems = {};
    state.seatEls       = {};
    state.paidSeats     = {};
    state._payingSeats  = [];
    state._backConfirmed= false;
    state._lpTimers     = [];
    state._mode         = null;
    state._osActive     = false;
    state.seats = orderToSeats(null, 1);

    var _landing = params.returnLanding || 'server-landing';
    var _landingParams = { emp: { id: params.employeeId, name: params.employeeName, pin: params.pin } };

    // ── Header ──
    setSceneName(params.checkId ? 'CHECK' : 'NEW CHECK');
    setHeaderBack({
      back:   true,
      onBack: function() {
        var hasContent = state.seats.some(function(s) { return s.items.length > 0; });
        if (!state.orderId && hasContent) {
          if (state._backConfirmed) {
            SceneManager.mountWorking(_landing, _landingParams);
            return;
          }
          showToast('Unsaved items — tap back again to exit', { bg: T.gold });
          state._backConfirmed = true;
          setTimeout(function() { state._backConfirmed = false; }, 3000);
          return;
        }
        SceneManager.mountWorking(_landing, _landingParams);
      },
      x: true,
    });

    // ── Root + body layout ──
    var root = document.createElement('div');
    Object.assign(root.style, {
      position:      'absolute',
      inset:         '0',
      paddingTop:    '44px',
      boxSizing:     'border-box',
      display:       'flex',
      flexDirection: 'column',
    });
    container.appendChild(root);
    state.rootEl = root;

    var body = document.createElement('div');
    Object.assign(body.style, {
      flex:          '1',
      minHeight:     '0',
      padding:       '16px',
      boxSizing:     'border-box',
      display:       'flex',
      flexDirection: 'column',
      gap:           '12px',
    });
    root.appendChild(body);

    var topArea = document.createElement('div');
    Object.assign(topArea.style, {
      flex:      '1',
      minHeight: '0',
      display:   'flex',
      gap:       '12px',
    });
    body.appendChild(topArea);
    state.topAreaEl = topArea;

    var bottomRow = document.createElement('div');
    Object.assign(bottomRow.style, {
      height:     '136px',
      flexShrink: '0',
      display:    'flex',
      gap:        '12px',
    });
    body.appendChild(bottomRow);

    var totalsCorner = document.createElement('div');
    Object.assign(totalsCorner.style, {
      width:         '360px',
      flexShrink:    '0',
      display:       'flex',
      flexDirection: 'column',
      gap:           '8px',
    });
    bottomRow.appendChild(totalsCorner);
    state.totalsEl = totalsCorner;

    var actionGrid = document.createElement('div');
    Object.assign(actionGrid.style, {
      flex:               '1',
      display:            'grid',
      gridTemplateColumns:'repeat(3, minmax(160px, 200px))',
      gridTemplateRows:   '1fr 1fr',
      gap:                '10px',
      justifyContent:     'end',
      alignContent:       'center',
    });
    bottomRow.appendChild(actionGrid);
    state.actionGridEl = actionGrid;

    // ── Wire action buttons ──
    _wireActions(state, params, actionGrid);

    // ── Initial paint ──
    renderTotals(state);
    rerenderTopArea(state);

    // ── Fetch order ──
    if (state.orderId) {
      refreshOrder(state, params);
    }

    trackBus('payment:complete', function(data) {
      if (data && data.orderId === state.orderId) refreshOrder(state, params);
    });

    state._backConfirmed = false;
    return function cleanup() { /* scene-level cleanup in unmount */ };
  },

  unmount: function(state) {
    if (OrderSummary.unlockItemRender) OrderSummary.unlockItemRender();
    OrderSummary.hide();
    state._osActive = false;

    for (var i = 0; i < state.listeners.length; i++) {
      var l = state.listeners[i];
      if (l.bus) SceneManager.off(l.event, l.handler);
      else       l.el.removeEventListener(l.event, l.handler);
    }
    state.listeners = [];

    for (var t = 0; t < state._lpTimers.length; t++) clearTimeout(state._lpTimers[t]);
    state._lpTimers = [];
  },

  interrupts: {

    'co-name-input': {
      render: function(container, params) {
        showKeyboard({
          placeholder:   'Enter name',
          initialValue:  params.currentName || '',
          maxLength:     40,
          onDone:        function(val) { params.onConfirm(val.trim()); },
          onDismiss:     function() { params.onCancel(); },
          dismissOnDone: true,
        });
      },
      unmount: function() { hideKeyboard(); },
    },

    'co-item-menu': {
      render: function(container, params) {
        params = params || {};
        var title   = params.title   || 'Options';
        var options = params.options || [];

        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = [
          'display:flex;flex-direction:column;align-items:stretch;gap:8px;',
          'background:' + T.card + ';',
          'border:3px solid ' + T.green + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'padding:20px 22px;min-width:300px;max-width:420px;',
          'box-shadow:0 8px 32px rgba(0,0,0,0.5);',
        ].join('');

        var lbl = document.createElement('div');
        lbl.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB2 + ';',
          'font-weight:' + T.fwBold + ';',
          'color:' + T.green + ';',
          'letter-spacing:0.2em;',
          'text-transform:uppercase;',
          'text-align:center;margin-bottom:8px;',
        ].join('');
        lbl.textContent = title;
        panel.appendChild(lbl);

        for (var oi = 0; oi < options.length; oi++) {
          (function(opt) {
            var btn = buildPillButton({
              label:    opt.label,
              color:    opt.color || T.card,
              darkBg:   darkenHex(opt.color || T.card, 0.4),
              fontSize: T.fsB2,
              onClick:  function() { params.onConfirm(opt.id); },
            });
            btn.style.width = '100%';
            if ((opt.color || T.card) === T.card) btn.style.color = T.text;
            else                                  btn.style.color = T.well;
            if (opt.color === T.verm) btn.style.color = '#fff';
            panel.appendChild(btn);
          })(options[oi]);
        }

        var cancelBtn = buildPillButton({
          label:    'CANCEL',
          color:    T.card,
          darkBg:   darkenHex(T.card, 0.4),
          fontSize: T.fsB2,
          onClick:  function() { params.onCancel(); },
        });
        cancelBtn.style.width     = '100%';
        cancelBtn.style.color     = T.text;
        cancelBtn.style.marginTop = '6px';
        panel.appendChild(cancelBtn);
        container.appendChild(panel);

        // Tap-outside-to-cancel, gated so the opening long-press release
        // doesn't self-dismiss the modal.
        var _downInside = false;
        container.addEventListener('pointerdown', function(e) {
          _downInside = (e.target === container);
        });
        container.addEventListener('pointerup', function(e) {
          if (_downInside && e.target === container) { params.onCancel(); }
          _downInside = false;
        });
      },
      unmount: function() {},
    },

    'server-picker': {
      render: function(container, params) {
        params = params || {};
        var excludeId = params.excludeId || null;

        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = [
          'background:' + T.card + ';',
          'border:3px solid ' + T.green + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'padding:18px;',
          'min-width:320px;max-width:440px;max-height:460px;',
          'display:flex;flex-direction:column;gap:10px;',
          'box-shadow:0 8px 32px rgba(0,0,0,0.5);',
        ].join('');

        var title = document.createElement('div');
        title.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB2 + ';',
          'font-weight:' + T.fwBold + ';',
          'letter-spacing:0.18em;',
          'color:' + T.green + ';',
          'text-transform:uppercase;',
          'text-align:center;padding:4px 0 10px;',
        ].join('');
        title.textContent = 'TRANSFER TO SERVER';
        panel.appendChild(title);

        var list = document.createElement('div');
        list.style.cssText = 'flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;';

        var loading = document.createElement('div');
        loading.style.cssText = [
          'font-family:' + T.fb + ';',
          'font-size:' + T.fsB3 + ';',
          'color:' + T.text + ';',
          'opacity:0.55;',
          'text-align:center;padding:20px 0;',
        ].join('');
        loading.textContent = 'Loading...';
        list.appendChild(loading);
        panel.appendChild(list);

        var cancelBtn = buildPillButton({
          label:    'CANCEL',
          color:    T.verm,
          darkBg:   T.vermDk,
          fontSize: T.fsB2,
          onClick:  function() { params.onCancel(); },
        });
        cancelBtn.style.alignSelf = 'center';
        panel.appendChild(cancelBtn);
        container.appendChild(panel);

        fetch('/api/v1/servers/clocked-in')
          .then(function(r) { return r.json(); })
          .then(function(data) {
            list.innerHTML = '';
            var staff = (data.staff || []).filter(function(s) { return s.employee_id !== excludeId; });
            if (staff.length === 0) {
              var empty = document.createElement('div');
              empty.style.cssText = [
                'font-family:' + T.fb + ';',
                'font-size:' + T.fsB3 + ';',
                'color:' + T.text + ';',
                'opacity:0.55;',
                'text-align:center;padding:20px 0;',
              ].join('');
              empty.textContent = 'No other servers clocked in';
              list.appendChild(empty);
              return;
            }
            for (var i = 0; i < staff.length; i++) {
              (function(srv) {
                var btn = buildPillButton({
                  label:    srv.employee_name,
                  color:    T.card,
                  darkBg:   darkenHex(T.card, 0.4),
                  fontSize: T.fsB2,
                  onClick:  function() {
                    params.onConfirm({ employee_id: srv.employee_id, employee_name: srv.employee_name });
                  },
                });
                btn.style.width = '100%';
                btn.style.color = T.text;
                list.appendChild(btn);
              })(staff[i]);
            }
          })
          .catch(function() {
            list.innerHTML = '';
            var err = document.createElement('div');
            err.style.cssText = [
              'font-family:' + T.fb + ';',
              'font-size:' + T.fsB3 + ';',
              'color:' + T.verm + ';',
              'text-align:center;padding:20px 0;',
            ].join('');
            err.textContent = 'Failed to load servers';
            list.appendChild(err);
          });
      },
    },

    'disc-pin': {
      render: function(container, params) {
        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = [
          'display:flex;flex-direction:column;align-items:center;gap:14px;',
          'background:' + T.card + ';',
          'border:3px solid ' + T.gold + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'padding:22px 24px;',
          'box-shadow:0 8px 32px rgba(0,0,0,0.5);',
        ].join('');

        var lbl = document.createElement('div');
        lbl.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB2 + ';',
          'font-weight:' + T.fwBold + ';',
          'color:' + T.gold + ';',
          'letter-spacing:0.2em;',
          'text-transform:uppercase;',
          'margin-bottom:2px;',
        ].join('');
        lbl.textContent = 'MANAGER PIN';
        panel.appendChild(lbl);

        var numpad = buildNumpad({
          onSubmit: function(pin) {
            fetch('/api/v1/auth/verify-pin', {
              method:  'POST',
              headers: { 'Content-Type': 'application/json' },
              body:    JSON.stringify({ pin: pin }),
            }).then(function(r) { return r.json(); }).then(function(data) {
              if (data.valid && (data.roles || []).indexOf('manager') !== -1) {
                params.onConfirm(data.employee_id || pin);
              } else if (data.valid) {
                numpad.setError('NOT A MANAGER');
              } else {
                numpad.setError('INVALID PIN');
              }
            }).catch(function() { numpad.setError('NETWORK ERROR'); });
          },
          onCancel: function() { params.onCancel(); },
        });
        panel.appendChild(numpad);
        container.appendChild(panel);

        container.addEventListener('pointerup', function(e) {
          if (e.target === container) { params.onCancel(); }
        });
      },
      unmount: function() {},
    },

    'disc-select': {
      render: function(container, params) {
        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = [
          'display:flex;flex-direction:column;align-items:center;gap:10px;',
          'background:' + T.card + ';',
          'border:3px solid ' + T.gold + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'padding:22px 24px;min-width:300px;',
          'box-shadow:0 8px 32px rgba(0,0,0,0.5);',
        ].join('');

        var lbl = document.createElement('div');
        lbl.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB2 + ';',
          'font-weight:' + T.fwBold + ';',
          'color:' + T.gold + ';',
          'letter-spacing:0.2em;',
          'text-transform:uppercase;',
          'margin-bottom:6px;',
        ].join('');
        lbl.textContent = 'DISCOUNT';
        panel.appendChild(lbl);

        DISCOUNT_OPTIONS.forEach(function(opt) {
          var btn = buildPillButton({
            label:    opt.label,
            color:    T.gold,
            darkBg:   T.goldDk,
            fontSize: T.fsB2,
            onClick:  function() { params.onConfirm(opt); },
          });
          btn.style.width = '240px';
          panel.appendChild(btn);
        });

        var cancelBtn = buildPillButton({
          label:    'CANCEL',
          color:    T.card,
          darkBg:   darkenHex(T.card, 0.4),
          fontSize: T.fsB2,
          onClick:  function() { params.onCancel(); },
        });
        cancelBtn.style.width     = '240px';
        cancelBtn.style.color     = T.text;
        cancelBtn.style.marginTop = '6px';
        panel.appendChild(cancelBtn);
        container.appendChild(panel);
      },
      unmount: function() {},
    },

    'seat-payment': {
      render: function(container, params) {
        params = params || {};
        var seatId   = params.seatId   || '??';
        var payments = params.payments || [];

        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = [
          'display:flex;flex-direction:column;align-items:stretch;gap:10px;',
          'background:' + T.card + ';',
          'border:3px solid ' + T.gold + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'padding:22px 24px;min-width:320px;max-width:440px;',
          'box-shadow:0 8px 32px rgba(0,0,0,0.5);',
        ].join('');

        var title = document.createElement('div');
        title.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB2 + ';',
          'font-weight:' + T.fwBold + ';',
          'color:' + T.gold + ';',
          'letter-spacing:0.2em;',
          'text-transform:uppercase;',
          'text-align:center;margin-bottom:4px;',
        ].join('');
        title.textContent = seatId + ' PAYMENT';
        panel.appendChild(title);

        if (payments.length === 0) {
          var empty = document.createElement('div');
          empty.style.cssText = [
            'font-family:' + T.fb + ';',
            'font-size:' + T.fsB3 + ';',
            'color:' + T.text + ';',
            'opacity:0.55;',
            'padding:8px 0;text-align:center;',
          ].join('');
          empty.textContent = 'No payments found for this seat';
          panel.appendChild(empty);
        } else {
          for (var pi = 0; pi < payments.length; pi++) {
            (function(p) {
              var row = document.createElement('div');
              row.style.cssText = [
                'display:flex;align-items:center;justify-content:space-between;',
                'gap:12px;width:100%;padding:6px 0;',
              ].join('');
              var info = document.createElement('div');
              info.style.cssText = [
                'font-family:' + T.fb + ';',
                'font-size:' + T.fsB2 + ';',
                'color:' + T.text + ';',
              ].join('');
              info.textContent = p.method.toUpperCase() + '  ' + fmt(p.amount);
              row.appendChild(info);
              var delBtn = buildPillButton({
                label:    'DELETE',
                color:    T.verm,
                darkBg:   T.vermDk,
                fontSize: T.fsB3,
                onClick:  function() { params.onConfirm(p.payment_id); },
              });
              delBtn.style.minWidth = '100px';
              row.appendChild(delBtn);
              panel.appendChild(row);
            })(payments[pi]);
          }
        }

        var cancelBtn = buildPillButton({
          label:    'CANCEL',
          color:    T.card,
          darkBg:   darkenHex(T.card, 0.4),
          fontSize: T.fsB2,
          onClick:  function() { params.onCancel(); },
        });
        cancelBtn.style.width     = '100%';
        cancelBtn.style.color     = T.text;
        cancelBtn.style.marginTop = '4px';
        panel.appendChild(cancelBtn);
        container.appendChild(panel);

        var _downInside = false;
        container.addEventListener('pointerdown', function(e) {
          _downInside = (e.target === container);
        });
        container.addEventListener('pointerup', function(e) {
          if (_downInside && e.target === container) { params.onCancel(); }
          _downInside = false;
        });
      },
      unmount: function() {},
    },
  },
});

// ═══════════════════════════════════════════════════
//  TOTALS CORNER (universal across modes)
// ═══════════════════════════════════════════════════

function renderTotals(state) {
  var el = state.totalsEl;
  el.innerHTML = '';
  var totals = checkTotals(state.seats, state.paidSeats);

  el.appendChild(_buildTotalsBox([
    { lbl: 'Subtotal:', val: fmt(totals.subtotal), color: T.gold },
    { lbl: 'Tax:',      val: fmt(totals.tax),      color: T.gold },
  ]));
  el.appendChild(_buildTotalsBox([
    { lbl: 'Card Price:', val: fmt(totals.cardTotal), color: T.elec },
    { lbl: 'Cash Price:', val: fmt(totals.cashPrice), color: T.gold },
  ]));
}

function _buildTotalsBox(rows) {
  var box = document.createElement('div');
  Object.assign(box.style, {
    background:   T.well,
    borderLeft:   T.accentBarW + ' solid ' + T.green,
    borderRadius: '8px',
    padding:      '8px 12px',
    fontSize:     T.fsB3,
    fontFamily:   T.fb,
    display:      'flex',
    flexDirection:'column',
    gap:          '3px',
  });
  for (var i = 0; i < rows.length; i++) {
    var r = document.createElement('div');
    Object.assign(r.style, {
      display:        'flex',
      justifyContent: 'space-between',
      alignItems:     'baseline',
      gap:            '8px',
    });
    var l = document.createElement('span');
    l.style.cssText = 'color:' + T.text + ';opacity:0.85;';
    l.textContent = rows[i].lbl;
    r.appendChild(l);
    var v = document.createElement('span');
    v.style.cssText = 'color:' + rows[i].color + ';font-weight:' + T.fwBold + ';';
    v.textContent = rows[i].val;
    r.appendChild(v);
    box.appendChild(r);
  }
  return box;
}

// ═══════════════════════════════════════════════════
//  TOP-AREA DISPATCHER
// ═══════════════════════════════════════════════════

function rerenderTopArea(state) {
  var count = activeSeatCount(state.seats, state.paidSeats);
  var mode = modeFor(count);
  state._mode = mode;

  if (state._osActive && mode !== 'C') {
    OrderSummary.hide();
    state._osActive = false;
  }

  // In Mode C, OrderSummary renders its own totals at the bottom of its
  // panel — hide our bottom-left totals corner to avoid duplication.
  if (state.totalsEl) {
    state.totalsEl.style.display = (mode === 'C') ? 'none' : 'flex';
  }

  var top = state.topAreaEl;
  top.innerHTML = '';
  state.seatEls = {};

  for (var t = 0; t < state._lpTimers.length; t++) clearTimeout(state._lpTimers[t]);
  state._lpTimers = [];

  if (mode === 'A')      renderModeA(state, top);
  else if (mode === 'B') renderModeB(state, top);
  else                   renderModeC(state, top);

  renderTotals(state);
}

// ═══════════════════════════════════════════════════
//  MODE A — 1 to 4 seats, full-width cards
// ═══════════════════════════════════════════════════

function renderModeA(state, container) {
  var count = activeSeatCount(state.seats, state.paidSeats);
  var cellCount = count + 1; // seats + add tile
  var grid = document.createElement('div');
  Object.assign(grid.style, {
    flex:               '1',
    minHeight:          '0',
    display:            'grid',
    gridTemplateColumns:'repeat(' + cellCount + ', 1fr)',
    gap:                '12px',
  });
  container.appendChild(grid);

  for (var i = 0; i < state.seats.length; i++) {
    if (state.paidSeats[state.seats[i].id]) continue;
    grid.appendChild(buildSeatCard(state, i, { compact: false }));
  }
  grid.appendChild(buildAddTile(state, { compact: false }));
}

// ═══════════════════════════════════════════════════
//  MODE B — 5 seats, all equal width, 5th col = stack
// ═══════════════════════════════════════════════════

function renderModeB(state, container) {
  var grid = document.createElement('div');
  Object.assign(grid.style, {
    flex:               '1',
    minHeight:          '0',
    display:            'grid',
    gridTemplateColumns:'repeat(5, 1fr)',
    gap:                '10px',
  });
  container.appendChild(grid);

  // Filter to just the active (non-paid) seats
  var active = [];
  for (var i = 0; i < state.seats.length; i++) {
    if (!state.paidSeats[state.seats[i].id]) active.push(i);
  }
  // First 4 seats: full cards
  for (var a = 0; a < 4 && a < active.length; a++) {
    grid.appendChild(buildSeatCard(state, active[a], { compact: false }));
  }
  // 5th column: stack with shortened S-005 card on top, + tile on bottom
  var stack = document.createElement('div');
  Object.assign(stack.style, {
    display:       'flex',
    flexDirection: 'column',
    gap:           '10px',
    minHeight:     '0',
  });
  if (active.length >= 5) {
    var card = buildSeatCard(state, active[4], { compact: false });
    card.style.flex      = '1';
    card.style.minHeight = '0';
    stack.appendChild(card);
  }
  var addTile = buildAddTile(state, { compact: false });
  addTile.style.height     = '80px';
  addTile.style.flexShrink = '0';
  stack.appendChild(addTile);
  grid.appendChild(stack);
}

// ═══════════════════════════════════════════════════
//  MODE C — 6+ seats, OrderSummary + compact grid
// ═══════════════════════════════════════════════════

function renderModeC(state, container) {
  var wrap = document.createElement('div');
  Object.assign(wrap.style, {
    flex:               '1',
    minHeight:          '0',
    display:            'grid',
    gridTemplateColumns:'360px 1fr',
    gap:                '12px',
  });
  container.appendChild(wrap);

  // LEFT — OrderSummary as a floating panel (managed by order-summary.js).
  // We just reserve the left column; OrderSummary positions itself.
  var osSlot = document.createElement('div');
  osSlot.style.cssText = 'min-height:0;';
  wrap.appendChild(osSlot);

  // RIGHT — compact seat grid card
  var grid = document.createElement('div');
  Object.assign(grid.style, {
    background:   T.card,
    borderLeft:   T.accentBarW + ' solid ' + T.green,
    borderRadius: T.chamferCard + 'px',
    display:      'flex',
    flexDirection:'column',
    overflow:     'hidden',
    boxShadow:    '0 4px 16px rgba(0,0,0,0.28)',
    minHeight:    '0',
  });

  var hdr = document.createElement('div');
  Object.assign(hdr.style, {
    background:   T.green,
    height:       '32px',
    display:      'flex',
    alignItems:   'center',
    justifyContent:'space-between',
    padding:      '0 14px',
    fontFamily:   T.fh,
    fontWeight:   T.fwBold,
    fontSize:     T.fsB3,
    color:        T.well,
    letterSpacing:'0.18em',
    textTransform:'uppercase',
  });
  var hL = document.createElement('span');
  hL.textContent = 'SEATS';
  hdr.appendChild(hL);
  var allBtn = document.createElement('span');
  allBtn.style.cssText = 'cursor:pointer;font-size:' + T.fsB4 + ';letter-spacing:0.2em;';
  allBtn.textContent = 'ALL';
  allBtn.addEventListener('pointerup', function() { forceSelectAll(state); });
  hdr.appendChild(allBtn);
  grid.appendChild(hdr);

  var cg = document.createElement('div');
  Object.assign(cg.style, {
    flex:               '1',
    padding:            '10px',
    display:            'grid',
    gridTemplateColumns:'repeat(3, 1fr)',
    gap:                '10px',
    alignContent:       'start',
    overflowY:          'auto',
  });
  cg.className = 'co-scroll';

  for (var i = 0; i < state.seats.length; i++) {
    if (state.paidSeats[state.seats[i].id]) continue;
    cg.appendChild(buildCompactTile(state, i));
  }
  cg.appendChild(buildAddTile(state, { compact: true }));
  grid.appendChild(cg);
  wrap.appendChild(grid);

  // Fire OrderSummary
  renderOrderSummary(state);
}

// ═══════════════════════════════════════════════════
//  SEAT CARD (used in Mode A and B for first 4 + the shortened 5th)
// ═══════════════════════════════════════════════════

function buildSeatCard(state, seatIdx, opts) {
  opts = opts || {};
  var seat = state.seats[seatIdx];
  var selected = !!state.selected[seat.id];
  var canDelete = seat.items.length === 0
    && activeSeatCount(state.seats, state.paidSeats) > 1;

  var card = document.createElement('div');
  Object.assign(card.style, {
    position:     'relative',
    background:   T.card,
    borderLeft:   T.accentBarW + ' solid ' + (selected ? T.gold : T.green),
    borderRadius: T.chamferCard + 'px',
    boxShadow:    selected
      ? '0 0 0 2px ' + T.gold + ', 0 4px 16px rgba(0,0,0,0.4)'
      : '0 4px 16px rgba(0,0,0,0.28)',
    display:      'flex',
    flexDirection:'column',
    overflow:     'hidden',
    minHeight:    '0',
  });

  // (X button appended at the end so it's DOM-above the header)

  // Header (tap = toggle seat, long-press = seat menu)
  var hdr = document.createElement('div');
  Object.assign(hdr.style, {
    background:    selected ? T.gold : T.green,
    height:        '32px',
    display:       'flex',
    alignItems:    'center',
    justifyContent:'flex-start',
    gap:           '10px',
    padding:       '0 12px',
    fontFamily:    T.fh,
    fontWeight:    T.fwBold,
    color:         T.well,
    letterSpacing: '0.18em',
    fontSize:      T.fsB3,
    cursor:        'pointer',
    userSelect:    'none',
    pointerEvents: 'auto',
    touchAction:   'manipulation',
  });
  var hL = document.createElement('span');
  hL.textContent = seat.id;
  hdr.appendChild(hL);
  var hR = document.createElement('span');
  hR.style.cssText = 'color:' + T.well + ';opacity:0.85;font-size:' + T.fsB3 + ';letter-spacing:0.05em;';
  hR.textContent = fmt(seatTotal(seat));
  hdr.appendChild(hR);
  card.appendChild(hdr);

  _wireHeaderTaps(state, seat.id, hdr);

  // Item list
  var itemsEl = document.createElement('div');
  itemsEl.className = 'co-scroll';
  Object.assign(itemsEl.style, {
    flex:            '1',
    overflowY:       'auto',
    padding:         '6px 10px',
    display:         'flex',
    flexDirection:   'column',
    gap:             '2px',
    minHeight:       '0',
  });

  if (seat.items.length === 0) {
    var empty = document.createElement('div');
    Object.assign(empty.style, {
      fontFamily: T.fb,
      fontSize:   T.fsB3,
      color:      hexToRgba(T.text, 0.45),
      textAlign:  'center',
      padding:    '16px 0',
      fontStyle:  'italic',
    });
    empty.textContent = 'No items';
    itemsEl.appendChild(empty);
  } else {
    for (var j = 0; j < seat.items.length; j++) {
      itemsEl.appendChild(buildItemRow(state, seatIdx, j));
    }
  }

  card.appendChild(itemsEl);
  if (canDelete) card.appendChild(_buildDeleteSeatX(state, seat.id));
  state.seatEls[seat.id] = { wrap: card, hdr: hdr, itemsEl: itemsEl };
  return card;
}

function buildItemRow(state, seatIdx, itemIdx) {
  var item = state.seats[seatIdx].items[itemIdx];
  var key = seatIdx + ':' + itemIdx;
  var isSel = !!state.selectedItems[key];

  var row = document.createElement('div');
  Object.assign(row.style, {
    display:            'grid',
    gridTemplateColumns:'1fr 32px 58px',
    alignItems:         'center',
    padding:            '4px 6px',
    fontFamily:         T.fb,
    fontSize:           T.fsB3,
    color:              isSel ? T.well : T.text,
    background:         isSel ? T.gold : 'transparent',
    borderBottom:       '1px solid ' + hexToRgba(T.border, 0.3),
    borderRadius:       '4px',
    cursor:             'pointer',
    userSelect:         'none',
    pointerEvents:      'auto',
    touchAction:        'manipulation',
  });

  var name = document.createElement('span');
  name.textContent = item.name;
  name.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  row.appendChild(name);

  var qty = document.createElement('span');
  qty.textContent = item.qty;
  qty.style.cssText = 'text-align:right;color:' + (isSel ? T.well : T.text) + ';';
  row.appendChild(qty);

  var px = document.createElement('span');
  px.textContent = fmt(item.qty * (item.effectivePrice || item.price));
  px.style.cssText = 'text-align:right;color:' + (isSel ? T.well : T.gold) + ';font-weight:' + T.fwBold + ';';
  row.appendChild(px);

  _wireItemTaps(state, seatIdx, itemIdx, row);

  // Render modifiers below the row
  var wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;';
  wrap.appendChild(row);
  if (Array.isArray(item.mods) && item.mods.length) {
    for (var mi = 0; mi < item.mods.length; mi++) {
      wrap.appendChild(_modRow(item.mods[mi]));
    }
  }
  return wrap;
}

function _modRow(mod) {
  var isSecondary = mod.prefix === 'NO' || mod.prefix === 'ON SIDE';
  var r = document.createElement('div');
  Object.assign(r.style, {
    display:            'grid',
    gridTemplateColumns:'1fr 58px',
    padding:            '0 0 1px ' + (isSecondary ? '28px' : '20px'),
    fontFamily:         T.fb,
    fontSize:           T.fsB4,
    color:              isSecondary ? T.verm : T.green,
    fontStyle:          isSecondary ? 'italic' : 'normal',
  });
  var nm = document.createElement('span');
  var pre = mod.prefix && mod.prefix !== 'ADD' ? mod.prefix + ' ' : '';
  nm.textContent = pre + (mod.name || '');
  r.appendChild(nm);
  var p = document.createElement('span');
  p.style.cssText = 'text-align:right;color:' + T.gold + ';';
  if (mod.price && mod.price > 0) p.textContent = '+' + fmt(mod.price);
  r.appendChild(p);
  return r;
}

// ═══════════════════════════════════════════════════
//  COMPACT SEAT TILE (Mode C)
// ═══════════════════════════════════════════════════

function buildCompactTile(state, seatIdx) {
  var seat = state.seats[seatIdx];
  var selected = !!state.selected[seat.id];
  var canDelete = seat.items.length === 0
    && activeSeatCount(state.seats, state.paidSeats) > 1;

  var tile = document.createElement('div');
  Object.assign(tile.style, {
    position:       'relative',
    background:     selected ? T.green : T.card,
    borderRadius:   T.chamferCard + 'px',
    minHeight:      '72px',
    padding:        '8px 10px',
    display:        'flex',
    flexDirection:  'column',
    alignItems:     'center',
    justifyContent: 'center',
    gap:            '2px',
    cursor:         'pointer',
    boxShadow:      '0 3px 0 rgba(0,0,0,0.4)',
    userSelect:     'none',
    pointerEvents:  'auto',
    touchAction:    'manipulation',
  });

  // (X button appended after content)

  var cid = document.createElement('span');
  Object.assign(cid.style, {
    fontFamily:   T.fh,
    fontWeight:   T.fwBold,
    fontSize:     T.fsH4,
    color:        selected ? T.well : T.text,
    letterSpacing:'0.06em',
    lineHeight:   '1',
  });
  cid.textContent = seat.id;
  tile.appendChild(cid);

  var ctot = document.createElement('span');
  Object.assign(ctot.style, {
    fontFamily: T.fb,
    fontSize:   T.fsB3,
    color:      selected ? T.well : T.gold,
    lineHeight: '1',
  });
  ctot.textContent = fmt(seatTotal(seat));
  tile.appendChild(ctot);

  _wireHeaderTaps(state, seat.id, tile);
  if (canDelete) tile.appendChild(_buildDeleteSeatX(state, seat.id));
  state.seatEls[seat.id] = { wrap: tile, hdr: tile, itemsEl: null };
  return tile;
}

// ═══════════════════════════════════════════════════
//  ADD TILE (dashed +)
// ═══════════════════════════════════════════════════

function buildAddTile(state, opts) {
  opts = opts || {};
  var tile = document.createElement('div');
  Object.assign(tile.style, {
    background:     'transparent',
    border:         '2px dashed ' + hexToRgba(T.green, 0.5),
    borderRadius:   T.chamferCard + 'px',
    display:        'flex',
    alignItems:     'center',
    justifyContent: 'center',
    cursor:         'pointer',
    minHeight:      opts.compact ? '72px' : '0',
    pointerEvents:  'auto',
  });
  var plus = document.createElement('div');
  Object.assign(plus.style, {
    fontFamily: T.fh,
    fontWeight: T.fwBold,
    fontSize:   opts.compact ? '32px' : '56px',
    color:      hexToRgba(T.green, 0.6),
  });
  plus.textContent = '+';
  tile.appendChild(plus);

  tile.addEventListener('pointerdown', function() {
    tile.style.background = hexToRgba(T.green, 0.08);
  });
  tile.addEventListener('pointerup', function() {
    tile.style.background = 'transparent';
    addSeat(state);
  });
  tile.addEventListener('pointerleave', function() {
    tile.style.background = 'transparent';
  });
  return tile;
}

// ═══════════════════════════════════════════════════
//  TAP + LONG-PRESS WIRING
// ═══════════════════════════════════════════════════

function _wireHeaderTaps(state, seatId, el) {
  var lpTimer = null;
  var didLongPress = false;

  el.addEventListener('pointerdown', function() {
    didLongPress = false;
    lpTimer = setTimeout(function() {
      didLongPress = true;
      openSeatMenu(state, seatId);
    }, 550);
    state._lpTimers.push(lpTimer);
  });
  el.addEventListener('pointerup', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    if (didLongPress) { didLongPress = false; return; }
    // Tap = toggle selection (but paid seats go to reopen flow)
    if (state.paidSeats[seatId]) {
      reopenSeat(state, seatId);
    } else {
      toggleSeat(state, seatId);
    }
  });
  el.addEventListener('pointerleave', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    didLongPress = false;
  });
  el.addEventListener('pointercancel', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    didLongPress = false;
  });
}

function _wireItemTaps(state, seatIdx, itemIdx, el) {
  var lpTimer = null;
  var didLongPress = false;
  var key = seatIdx + ':' + itemIdx;

  el.addEventListener('pointerdown', function() {
    didLongPress = false;
    lpTimer = setTimeout(function() {
      didLongPress = true;
      // If something is already selected → bulk menu
      if (Object.keys(state.selectedItems).length > 0) {
        openBulkMenu(state);
      } else {
        openItemMenu(state, seatIdx, itemIdx);
      }
    }, 500);
    state._lpTimers.push(lpTimer);
  });
  el.addEventListener('pointerup', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    if (didLongPress) { didLongPress = false; return; }
    toggleItem(state, seatIdx, itemIdx);
  });
  el.addEventListener('pointerleave', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    didLongPress = false;
  });
  el.addEventListener('pointercancel', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    didLongPress = false;
  });
}

// ═══════════════════════════════════════════════════
//  SELECTION OPERATIONS
// ═══════════════════════════════════════════════════

function toggleSeat(state, seatId) {
  if (state.paidSeats[seatId]) return;
  if (state.selected[seatId]) delete state.selected[seatId];
  else                        state.selected[seatId] = true;
  rerenderTopArea(state);
}

function toggleItem(state, seatIdx, itemIdx) {
  var key = seatIdx + ':' + itemIdx;
  if (state.selectedItems[key]) delete state.selectedItems[key];
  else                          state.selectedItems[key] = true;
  rerenderTopArea(state);
}

function forceSelectAll(state) {
  for (var i = 0; i < state.seats.length; i++) {
    if (state.paidSeats[state.seats[i].id]) continue;
    state.selected[state.seats[i].id] = true;
  }
  rerenderTopArea(state);
}

function clearAllSelection(state) {
  state.selected = {};
  state.selectedItems = {};
  rerenderTopArea(state);
}

function getSelectedItemRefs(state) {
  var out = [];
  var keys = Object.keys(state.selectedItems);
  for (var i = 0; i < keys.length; i++) {
    var p = keys[i].split(':');
    out.push({ seatIdx: +p[0], itemIdx: +p[1] });
  }
  return out;
}

function getSelectedSeatIds(state) {
  return Object.keys(state.selected);
}

function addSeat(state) {
  var maxNum = 0;
  for (var i = 0; i < state.seats.length; i++) {
    if (state.seats[i].number > maxNum) maxNum = state.seats[i].number;
  }
  var num = maxNum + 1;
  state.seats.push({
    id:     'S-' + String(num).padStart(3, '0'),
    number: num,
    items:  [],
  });

  if (state.orderId) {
    fetch('/api/v1/orders/' + state.orderId, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        guest_count: Math.max.apply(null, state.seats.map(function(s) { return s.number; })),
      }),
    });
  }
  rerenderTopArea(state);
}

function deleteSeat(state, seatId) {
  var seatIdx = -1;
  for (var i = 0; i < state.seats.length; i++) {
    if (state.seats[i].id === seatId) { seatIdx = i; break; }
  }
  if (seatIdx < 0) return;
  if (state.seats[seatIdx].items.length > 0) {
    showToast('Seat has items — void them first', { bg: T.verm });
    return;
  }
  if (activeSeatCount(state.seats, state.paidSeats) <= 1) {
    showToast('Can’t remove the only seat', { bg: T.gold });
    return;
  }
  state.seats.splice(seatIdx, 1);
  delete state.selected[seatId];
  rerenderTopArea(state);
}

// Tiny × button overlay for empty seats. Tapping removes the seat.
function _buildDeleteSeatX(state, seatId) {
  var x = document.createElement('div');
  Object.assign(x.style, {
    position:       'absolute',
    top:            '5px',
    right:          '6px',
    width:          '24px',
    height:         '24px',
    borderRadius:   '50%',
    background:     T.verm,
    color:          '#fff',
    fontFamily:     T.fh,
    fontWeight:     T.fwBold,
    fontSize:       '16px',
    display:        'flex',
    alignItems:     'center',
    justifyContent: 'center',
    cursor:         'pointer',
    userSelect:     'none',
    zIndex:         '5',
    lineHeight:     '1',
    boxShadow:      '0 2px 6px rgba(0,0,0,0.5)',
    pointerEvents:  'auto',
    touchAction:    'manipulation',
  });
  x.textContent = '\u00d7';
  // Capture-phase handlers so we win against the header's listeners.
  x.addEventListener('pointerdown', function(e) {
    e.stopPropagation();
    e.preventDefault();
  });
  x.addEventListener('pointerup',   function(e) {
    e.stopPropagation();
    e.preventDefault();
    deleteSeat(state, seatId);
  });
  x.addEventListener('click', function(e) {
    // Fallback for platforms where click still fires
    e.stopPropagation();
    e.preventDefault();
    deleteSeat(state, seatId);
  });
  return x;
}

// ═══════════════════════════════════════════════════
//  ACTION BUTTONS (bottom-right grid)
// ═══════════════════════════════════════════════════

function _wireActions(state, params, grid) {
  var btns = [
    { label: 'PRINT',     color: T.green,     dark: T.greenDk,     onClick: function() { handlePrint(state);     } },
    { label: 'DISC',      color: T.gold,      dark: T.goldDk,      onClick: function() { handleDiscount(state);  } },
    { label: 'ADD ITEMS', color: T.green,     dark: T.greenDk,     onClick: function() { handleAddItems(state, params); } },
    { label: 'PAY',       color: T.gold,      dark: T.goldDk,      onClick: function() { handlePay(state, params); } },
    { label: 'VOID',      color: T.verm,      dark: T.vermDk,      onClick: function() { handleVoid(state);      } },
    { label: 'RESEND',    color: T.greenWarm, dark: T.greenWarmDk, onClick: function() { handleResend(state);    } },
  ];
  for (var i = 0; i < btns.length; i++) {
    var b = btns[i];
    var pill = buildPillButton({
      label:    b.label,
      color:    b.color,
      darkBg:   b.dark,
      fontSize: T.fsB2,
      onClick:  b.onClick,
    });
    if (b.label === 'VOID') pill.style.color = '#fff';
    pill.style.pointerEvents = 'auto';
    grid.appendChild(pill);
  }
}

// ═══════════════════════════════════════════════════
//  PRINT
// ═══════════════════════════════════════════════════

function handlePrint(state) {
  if (!state.orderId) { showToast('Save items first', { bg: T.gold }); return; }
  showToast('Printing receipt…', { bg: T.green });
  fetch('/api/v1/orders/' + state.orderId + '/print/receipt', { method: 'POST' })
    .then(function(r) {
      if (r.ok) showToast('Receipt printed', { bg: T.greenWarm });
      else      showToast('Print failed', { bg: T.verm });
    })
    .catch(function() { showToast('Print failed', { bg: T.verm }); });
}

// ═══════════════════════════════════════════════════
//  RESEND (re-fire kitchen tickets)
// ═══════════════════════════════════════════════════

function handleResend(state) {
  if (!state.orderId) { showToast('Nothing to resend', { bg: T.gold }); return; }
  showToast('Resending to kitchen…', { bg: T.green });
  fetch('/api/v1/orders/' + state.orderId + '/resend', { method: 'POST' })
    .then(function(r) {
      if (r.ok) showToast('Kitchen ticket sent', { bg: T.greenWarm });
      else      showToast('Resend failed', { bg: T.verm });
    })
    .catch(function() { showToast('Resend failed', { bg: T.verm }); });
}

// ═══════════════════════════════════════════════════
//  ADD ITEMS (push to order-entry)
// ═══════════════════════════════════════════════════

function handleAddItems(state, params) {
  if (!state.orderId) {
    // No order yet (NEW CHECK path). Create one first so order-entry has
    // something to attach items to.
    fetch('/api/v1/orders', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        server_id:    params.employeeId,
        server_name:  params.employeeName,
        guest_count:  Math.max(1, activeSeatCount(state.seats, state.paidSeats)),
      }),
    })
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(order) {
        if (!order) { showToast('Could not create order', { bg: T.verm }); return; }
        state.orderId = order.order_id || order.id;
        _gotoOrderEntry(state, params);
      })
      .catch(function() { showToast('Could not create order', { bg: T.verm }); });
  } else {
    _gotoOrderEntry(state, params);
  }
}

function _gotoOrderEntry(state, params) {
  SceneManager.mountWorking('order-entry', {
    orderId:      state.orderId,
    returnTo:     'check-overview',
    returnParams: {
      checkId:       state.orderId,
      returnLanding: params.returnLanding,
      employeeId:    params.employeeId,
      employeeName:  params.employeeName,
      pin:           params.pin,
    },
    employeeId:   params.employeeId,
    employeeName: params.employeeName,
    pin:          params.pin,
    seats:        state.seats,
  });
}

// ═══════════════════════════════════════════════════
//  PAY (push to payment scene for selected seat(s))
// ═══════════════════════════════════════════════════

function handlePay(state, params) {
  if (!state.orderId) {
    showToast('Save items first', { bg: T.gold });
    return;
  }

  var selectedIds = getSelectedSeatIds(state);
  if (selectedIds.length === 0) {
    // No seats selected — default to "pay whole check" (all non-paid seats
    // with items on them).
    for (var i = 0; i < state.seats.length; i++) {
      if (!state.paidSeats[state.seats[i].id] && state.seats[i].items.length > 0) {
        selectedIds.push(state.seats[i].id);
      }
    }
  }
  if (selectedIds.length === 0) {
    showToast('No items to pay', { bg: T.gold });
    return;
  }

  // Build the seat-totals summary the payment scene needs — seat IDs,
  // per-seat subtotals, and their items (so payment can display what it's
  // charging for per seat).
  var seatSummary = [];
  for (var s = 0; s < state.seats.length; s++) {
    if (selectedIds.indexOf(state.seats[s].id) === -1) continue;
    if (state.paidSeats[state.seats[s].id]) continue;
    seatSummary.push({
      seatId:  state.seats[s].id,
      number:  state.seats[s].number,
      items:   state.seats[s].items,
    });
  }

  SceneManager.mountWorking('payment', {
    orderId:      state.orderId,
    seatIds:      selectedIds,
    seats:        seatSummary,
    returnTo:     'check-overview',
    returnParams: {
      checkId:       state.orderId,
      returnLanding: params.returnLanding,
      employeeId:    params.employeeId,
      employeeName:  params.employeeName,
      pin:           params.pin,
    },
    employeeId:   params.employeeId,
    employeeName: params.employeeName,
    pin:          params.pin,
  });
}

// ═══════════════════════════════════════════════════
//  VOID  (items / seats with undo window)
// ═══════════════════════════════════════════════════

function handleVoid(state) {
  var itemRefs = getSelectedItemRefs(state);
  var seatIds  = getSelectedSeatIds(state);

  if (itemRefs.length === 0 && seatIds.length === 0) {
    showToast('Select items or seats to void', { bg: T.gold });
    return;
  }

  // Expand seat selections into item refs
  if (itemRefs.length === 0 && seatIds.length > 0) {
    for (var s = 0; s < seatIds.length; s++) {
      var sIdx = _seatIdxById(state, seatIds[s]);
      if (sIdx < 0) continue;
      for (var j = 0; j < state.seats[sIdx].items.length; j++) {
        itemRefs.push({ seatIdx: sIdx, itemIdx: j });
      }
    }
  }

  if (itemRefs.length === 0) {
    showToast('Nothing to void', { bg: T.gold });
    return;
  }

  _voidItems(state, itemRefs);
}

function _voidItems(state, refs) {
  // Sort descending within each seat so splice doesn't shift indices
  refs.sort(function(a, b) {
    if (a.seatIdx !== b.seatIdx) return b.seatIdx - a.seatIdx;
    return b.itemIdx - a.itemIdx;
  });

  var snapshot = [];
  for (var i = 0; i < refs.length; i++) {
    var r = refs[i];
    snapshot.push({
      seatIdx: r.seatIdx,
      itemIdx: r.itemIdx,
      item:    state.seats[r.seatIdx].items[r.itemIdx],
    });
    state.seats[r.seatIdx].items.splice(r.itemIdx, 1);
  }

  state.selectedItems = {};
  rerenderTopArea(state);

  showToast('Voided ' + refs.length + ' item(s) — tap to undo', {
    bg: T.verm,
    duration: 4000,
    onClick: function() {
      // Reinsert in ascending order
      snapshot.sort(function(a, b) {
        if (a.seatIdx !== b.seatIdx) return a.seatIdx - b.seatIdx;
        return a.itemIdx - b.itemIdx;
      });
      for (var j = 0; j < snapshot.length; j++) {
        var s = snapshot[j];
        state.seats[s.seatIdx].items.splice(s.itemIdx, 0, s.item);
      }
      rerenderTopArea(state);
      showToast('Void undone', { bg: T.greenWarm });
    },
  });

  // After the undo window, commit to backend
  if (state.orderId) {
    setTimeout(function() {
      for (var k = 0; k < snapshot.length; k++) {
        var iid = snapshot[k].item.item_id;
        if (!iid) continue;
        fetch('/api/v1/orders/' + state.orderId + '/items/' + iid, { method: 'DELETE' });
      }
    }, 4200);
  }
}

function _seatIdxById(state, seatId) {
  for (var i = 0; i < state.seats.length; i++) {
    if (state.seats[i].id === seatId) return i;
  }
  return -1;
}

// ═══════════════════════════════════════════════════
//  DISCOUNT (manager PIN → % picker → apply)
// ═══════════════════════════════════════════════════

function handleDiscount(state) {
  var itemRefs = getSelectedItemRefs(state);
  var seatIds  = getSelectedSeatIds(state);

  if (itemRefs.length === 0 && seatIds.length === 0) {
    showToast('Select items or seats to discount', { bg: T.gold });
    return;
  }

  SceneManager.interrupt('disc-pin', {
    onConfirm: function() {
      SceneManager.interrupt('disc-select', {
        onConfirm: function(opt) {
          _applyDiscount(state, opt.pct, itemRefs, seatIds);
        },
        onCancel: function() {},
      });
    },
    onCancel: function() {},
  });
}

function _applyDiscount(state, pct, itemRefs, seatIds) {
  // Expand seat selections into item refs
  if (itemRefs.length === 0 && seatIds.length > 0) {
    for (var s = 0; s < seatIds.length; s++) {
      var sIdx = _seatIdxById(state, seatIds[s]);
      if (sIdx < 0) continue;
      for (var j = 0; j < state.seats[sIdx].items.length; j++) {
        itemRefs.push({ seatIdx: sIdx, itemIdx: j });
      }
    }
  }

  for (var i = 0; i < itemRefs.length; i++) {
    var r = itemRefs[i];
    var it = state.seats[r.seatIdx].items[r.itemIdx];
    var base = it.price || 0;
    var modSum = 0;
    if (Array.isArray(it.mods)) {
      for (var m = 0; m < it.mods.length; m++) modSum += (it.mods[m].price || 0);
    }
    var effective = base + modSum;
    it.effectivePrice = effective * (1 - pct / 100);
  }

  state.selectedItems = {};
  state.selected = {};
  rerenderTopArea(state);
  showToast(pct + '% discount applied', { bg: T.greenWarm });

  // TODO: persist to backend (needs discount endpoint)
}

// ═══════════════════════════════════════════════════
//  LONG-PRESS MENUS
// ═══════════════════════════════════════════════════

function openItemMenu(state, seatIdx, itemIdx) {
  // When long-pressed on an unselected item, select it first so the
  // menu acts on a clear single target.
  state.selectedItems = {};
  state.selectedItems[seatIdx + ':' + itemIdx] = true;
  rerenderTopArea(state);

  SceneManager.interrupt('co-item-menu', {
    title:   'Item Options',
    options: [
      { id: 'void',     label: 'Void this item',      color: T.verm      },
      { id: 'disc',     label: 'Discount this item',  color: T.gold      },
      { id: 'move',     label: 'Move to seat…',       color: T.green     },
      { id: 'qty',      label: 'Change quantity',     color: T.green     },
      { id: 'note',     label: 'Add note',            color: T.green     },
      { id: 'reprint',  label: 'Reprint to kitchen',  color: T.greenWarm },
    ],
    onConfirm: function(optId) { handleItemAction(state, optId, seatIdx, itemIdx); },
    onCancel:  function() { state.selectedItems = {}; rerenderTopArea(state); },
  });
}

function openBulkMenu(state) {
  SceneManager.interrupt('co-item-menu', {
    title:   Object.keys(state.selectedItems).length + ' Items Selected',
    options: [
      { id: 'void',     label: 'Void selected',            color: T.verm      },
      { id: 'disc',     label: 'Discount selected',        color: T.gold      },
      { id: 'move',     label: 'Move selected to seat…',   color: T.green     },
      { id: 'reprint',  label: 'Reprint selected',         color: T.greenWarm },
    ],
    onConfirm: function(optId) { handleBulkAction(state, optId); },
    onCancel:  function() {},
  });
}

function openSeatMenu(state, seatId) {
  var sIdx = _seatIdxById(state, seatId);
  var seat = state.seats[sIdx];
  var empty = seat && seat.items.length === 0;
  var options = [
    { id: 'void',     label: 'Void seat',            color: T.verm      },
    { id: 'disc',     label: 'Discount seat',        color: T.gold      },
    { id: 'rename',   label: 'Rename seat',          color: T.green     },
    { id: 'merge',    label: 'Merge with seat…',     color: T.green     },
    { id: 'split',    label: 'Split items across…',  color: T.green     },
    { id: 'transfer', label: 'Transfer to server…',  color: T.green     },
  ];
  if (empty) options.push({ id: 'delete', label: 'Delete seat', color: T.verm });

  SceneManager.interrupt('co-item-menu', {
    title:   seatId + ' Options',
    options: options,
    onConfirm: function(optId) { handleSeatAction(state, optId, seatId); },
    onCancel:  function() {},
  });
}

// ═══════════════════════════════════════════════════
//  MENU ACTION HANDLERS
// ═══════════════════════════════════════════════════

function handleItemAction(state, optId, seatIdx, itemIdx) {
  if (optId === 'void') {
    _voidItems(state, [{ seatIdx: seatIdx, itemIdx: itemIdx }]);
  } else if (optId === 'disc') {
    handleDiscount(state);
  } else if (optId === 'move') {
    _pickMoveTarget(state, [{ seatIdx: seatIdx, itemIdx: itemIdx }]);
  } else if (optId === 'qty') {
    _promptQty(state, seatIdx, itemIdx);
  } else if (optId === 'note') {
    _promptNote(state, seatIdx, itemIdx);
  } else if (optId === 'reprint') {
    showToast('Reprint — coming soon', { bg: T.gold });
  }
}

function handleBulkAction(state, optId) {
  var refs = getSelectedItemRefs(state);
  if (optId === 'void') {
    _voidItems(state, refs);
  } else if (optId === 'disc') {
    handleDiscount(state);
  } else if (optId === 'move') {
    _pickMoveTarget(state, refs);
  } else if (optId === 'reprint') {
    showToast('Reprint — coming soon', { bg: T.gold });
  }
}

function handleSeatAction(state, optId, seatId) {
  var sIdx = _seatIdxById(state, seatId);
  if (sIdx < 0) return;

  if (optId === 'void') {
    var refs = [];
    for (var i = 0; i < state.seats[sIdx].items.length; i++) {
      refs.push({ seatIdx: sIdx, itemIdx: i });
    }
    if (refs.length === 0) { showToast('Seat is already empty', { bg: T.gold }); return; }
    _voidItems(state, refs);
  } else if (optId === 'disc') {
    state.selected = {};
    state.selected[seatId] = true;
    handleDiscount(state);
  } else if (optId === 'rename') {
    showToast('Rename seat — coming soon', { bg: T.gold });
  } else if (optId === 'merge') {
    _pickMergeTarget(state, seatId);
  } else if (optId === 'split') {
    openEditSeats(state);
  } else if (optId === 'transfer') {
    _openTransfer(state);
  } else if (optId === 'delete') {
    deleteSeat(state, seatId);
  }
}

function _pickMoveTarget(state, refs) {
  // Build seat list excluding paid + source seat (if all refs share one)
  var options = [];
  for (var i = 0; i < state.seats.length; i++) {
    if (state.paidSeats[state.seats[i].id]) continue;
    options.push({ id: state.seats[i].id, label: state.seats[i].id, color: T.green });
  }
  options.push({ id: '__new__', label: '+ New seat', color: T.greenWarm });

  SceneManager.interrupt('co-item-menu', {
    title:   'Move to Seat',
    options: options,
    onConfirm: function(optId) {
      var targetIdx;
      if (optId === '__new__') {
        addSeat(state);
        targetIdx = state.seats.length - 1;
      } else {
        targetIdx = _seatIdxById(state, optId);
      }
      if (targetIdx < 0) return;
      // Move in descending order
      refs.sort(function(a, b) {
        if (a.seatIdx !== b.seatIdx) return b.seatIdx - a.seatIdx;
        return b.itemIdx - a.itemIdx;
      });
      for (var r = 0; r < refs.length; r++) {
        var rr = refs[r];
        var it = state.seats[rr.seatIdx].items.splice(rr.itemIdx, 1)[0];
        state.seats[targetIdx].items.push(it);
      }
      state.selectedItems = {};
      rerenderTopArea(state);
      showToast('Moved ' + refs.length + ' item(s)', { bg: T.greenWarm });
    },
    onCancel: function() {},
  });
}

function _pickMergeTarget(state, sourceSeatId) {
  var options = [];
  for (var i = 0; i < state.seats.length; i++) {
    if (state.paidSeats[state.seats[i].id]) continue;
    if (state.seats[i].id === sourceSeatId) continue;
    options.push({ id: state.seats[i].id, label: state.seats[i].id, color: T.green });
  }
  if (options.length === 0) { showToast('No other seats to merge with', { bg: T.gold }); return; }

  SceneManager.interrupt('co-item-menu', {
    title:   'Merge ' + sourceSeatId + ' Into…',
    options: options,
    onConfirm: function(targetId) {
      var sIdx = _seatIdxById(state, sourceSeatId);
      var tIdx = _seatIdxById(state, targetId);
      if (sIdx < 0 || tIdx < 0) return;
      state.seats[tIdx].items = state.seats[tIdx].items.concat(state.seats[sIdx].items);
      state.seats.splice(sIdx, 1);
      delete state.selected[sourceSeatId];
      rerenderTopArea(state);
      showToast('Merged into ' + targetId, { bg: T.greenWarm });
    },
    onCancel: function() {},
  });
}

function _promptQty(state, seatIdx, itemIdx) {
  showToast('Change qty — coming soon', { bg: T.gold });
  // TODO: numpad interrupt to set new quantity, patch backend.
}

function _promptNote(state, seatIdx, itemIdx) {
  showToast('Add note — coming soon', { bg: T.gold });
  // TODO: showKeyboard interrupt, update item.notes, patch backend.
}

function _openTransfer(state) {
  if (!state.orderId) { showToast('Save items first', { bg: T.gold }); return; }
  SceneManager.interrupt('server-picker', {
    onConfirm: function(server) {
      fetch('/api/v1/orders/' + state.orderId, {
        method:  'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          server_id:   server.employee_id,
          server_name: server.employee_name,
        }),
      }).then(function(r) {
        if (r.ok) showToast('Transferred to ' + server.employee_name, { bg: T.greenWarm });
        else      showToast('Transfer failed',                         { bg: T.verm });
      });
    },
    onCancel: function() {},
    excludeId: null,
  });
}

// ═══════════════════════════════════════════════════
//  EDIT SEATS (column-editor for split/merge/move)
// ═══════════════════════════════════════════════════

function openEditSeats(state) {
  var columns = [];
  for (var i = 0; i < state.seats.length; i++) {
    if (state.paidSeats[state.seats[i].id]) continue;
    columns.push({
      id:    state.seats[i].id,
      label: state.seats[i].id,
      items: state.seats[i].items.map(function(it) {
        return {
          name:         it.name,
          qty:          it.qty,
          price:        it.price,
          item_id:      it.item_id,
          menu_item_id: it.menu_item_id,
          category:     it.category,
          mods:         it.mods,
          notes:        it.notes,
        };
      }),
    });
  }
  SceneManager.openTransactional('column-editor', {
    columns:    columns,
    operations: ['MERGE', 'MOVE', 'SPLIT'],
    orderId:    state.orderId,
    onSave: function(newColumns) {
      // Rebuild seats from columns
      var newSeats = [];
      for (var c = 0; c < newColumns.length; c++) {
        var oldNumber = parseInt(newColumns[c].id.replace(/^S-|^NEW-/, ''), 10) || (c + 1);
        newSeats.push({
          id:     'S-' + String(c + 1).padStart(3, '0'),
          number: c + 1,
          items:  newColumns[c].items,
        });
      }
      // Preserve any paid seats at the front unchanged
      var paid = [];
      for (var p = 0; p < state.seats.length; p++) {
        if (state.paidSeats[state.seats[p].id]) paid.push(state.seats[p]);
      }
      state.seats = paid.concat(newSeats);
      state.selectedItems = {};
      state.selected = {};
      rerenderTopArea(state);
      // TODO: diff against backend and POST new / PATCH changed / DELETE removed.
    },
  });
}

// ═══════════════════════════════════════════════════
//  ORDER SUMMARY (Mode C only)
// ═══════════════════════════════════════════════════

function renderOrderSummary(state) {
  var s = collectSummary(state.seats, state.selected, state.paidSeats);
  state._summaryItemMap = {};

  if (!state._osActive) {
    OrderSummary.show({
      checkLabel:   state.checkNumber || state.orderId || 'check',
      customerName: state.customerName || '',
      items:        s.items,
      subtotal:     s.subtotal,
      tax:          s.tax,
      cardTotal:    s.cardTotal,
      cashPrice:    s.cashPrice,
      onNameTap:    function() { openNameEditor(state); },
      onItemTap:    function(idx) { _onOSItemTap(state, idx); },
    });
    state._osActive = true;
  } else {
    OrderSummary.update({
      checkLabel:   state.checkNumber || state.orderId || 'check',
      customerName: state.customerName || '',
      items:        s.items,
      subtotal:     s.subtotal,
      tax:          s.tax,
      cardTotal:    s.cardTotal,
      cashPrice:    s.cashPrice,
    });
  }
}

function _onOSItemTap(state, idx) {
  // TODO: when OrderSummary fires an item tap, translate back to (seatIdx, itemIdx)
  // and toggle selection, then rerender. Since collectSummary already includes
  // seatIdx/itemIdx on item entries, we can use that.
  // For now stubbed — selection in Mode C is driven by compact tiles.
}

// ═══════════════════════════════════════════════════
//  CUSTOMER NAME EDITOR
// ═══════════════════════════════════════════════════

function openNameEditor(state) {
  SceneManager.interrupt('co-name-input', {
    currentName: state.customerName,
    onConfirm:   function(name) {
      state.customerName = name;
      if (state.orderId) {
        fetch('/api/v1/orders/' + state.orderId, {
          method:  'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ customer_name: name }),
        });
      }
      if (state._osActive) renderOrderSummary(state);
    },
    onCancel: function() {},
  });
}

// ═══════════════════════════════════════════════════
//  REOPEN PAID SEAT (void payment flow)
// ═══════════════════════════════════════════════════

function reopenSeat(state, seatId) {
  if (!state.orderId) return;
  fetch('/api/v1/orders/' + state.orderId, { cache: 'no-store' })
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(order) {
      if (order) state.order = order;
      var source = (order && order.payments) || (state.order && state.order.payments) || [];
      var matches = source.filter(function(p) { return p.seat_id === seatId; });
      if (matches.length === 0) {
        showToast('No payment found for this seat', { bg: T.gold });
        return;
      }
      openSeatPaymentInterrupt(state, seatId, matches);
    });
}

function openSeatPaymentInterrupt(state, seatId, payments) {
  SceneManager.interrupt('seat-payment', {
    seatId:   seatId,
    payments: payments,
    onConfirm: function(paymentId) {
      fetch('/api/v1/orders/' + state.orderId + '/payments/' + paymentId, {
        method:  'DELETE',
      }).then(function(r) {
        if (r.ok) {
          delete state.paidSeats[seatId];
          showToast('Payment voided', { bg: T.greenWarm });
          refreshOrder(state, {});
        } else {
          showToast('Void failed', { bg: T.verm });
        }
      });
    },
    onCancel: function() {},
  });
}

// ═══════════════════════════════════════════════════
//  REFRESH ORDER (fetch + re-render)
// ═══════════════════════════════════════════════════

function refreshOrder(state, params) {
  if (!state.orderId) return;
  if (_refreshInFlight) return;
  _refreshInFlight = true;

  fetch('/api/v1/orders/' + state.orderId, { cache: 'no-store' })
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(order) {
      _refreshInFlight = false;
      if (!order) return;
      state.order = order;
      state.checkNumber  = order.check_number || '';
      state.customerName = order.customer_name || '';

      if (state.checkNumber) setSceneName(state.checkNumber);

      state.seats = orderToSeats(order, 1);

      // Recompute paid seats
      state.paidSeats = {};
      if (Array.isArray(order.payments)) {
        for (var p = 0; p < order.payments.length; p++) {
          if (order.payments[p].seat_id) {
            state.paidSeats[order.payments[p].seat_id] = true;
          }
        }
      }

      rerenderTopArea(state);

      // Deep-link: if caller passed autoSplit (e.g. from a landing page's
      // Split button), fire the edit-seats flow once the check data has
      // loaded. One-shot — clear the flag so subsequent refreshes don't
      // re-trigger the column-editor.
      if (params && params.autoSplit) {
        params.autoSplit = false;
        openEditSeats(state);
      }
    })
    .catch(function() {
      _refreshInFlight = false;
    });
}