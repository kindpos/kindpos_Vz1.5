// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Payment Scene (Vz2.0)
//  2-column: Denominations + Numpad (left recap is persistent OrderSummary)
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { T } from '../tokens.js';
import { chamfer, applySunkenStyle, buildStyledButton, hexToRgba } from '../sm2-shim.js';
import { buildButton, showToast } from '../components.js';
import { SceneManager, defineScene } from '../scene-manager.js';
import { setSceneName, setHeaderBack } from '../app.js';
import { buildNumpad } from '../numpad.js';
import { OrderSummary } from '../order-summary.js';

var PAD     = T.scenePad;
var GAP     = T.colGapSm;
var API     = '/api/v1';

// ── Scene state ───────────────────────────────────
var sceneEl           = null;
var sceneData         = {};
var enteredAmount     = 0;
var denomAccum        = 0;
var numpadStr         = '';
var paymentMode       = 'card';
var confirmProcessing = false;
var payments          = [];
var totalPaid         = 0;
var baseTotal         = 0;
var numpadRef         = null;
var dotTimer          = null;

// DOM refs
var _modeButtons      = {};

// Card processing overlay state
var _procStatusEl     = null;
var _procAnimTimer    = null;

// Change-due timer
var _changeDueTimer   = null;

// Split tap handler (bound to event bus)
function _onSplitTap() { showSplitPopup(); }


// ═══════════════════════════════════════════════════
//  SCENE DEFINITION
// ═══════════════════════════════════════════════════

// ── Return-to-parent helper ──────────────────────
// Payment is mounted as a working scene (replaces check-overview). To go
// back, re-mount the returnTo scene with the returnParams bundle that was
// passed in. Falls back to whatever landing the user came from, or gate
// login as last resort.
function _returnToParent(params) {
  params = params || {};
  var target    = params.returnTo || 'check-overview';
  var retParams = params.returnParams || {
    checkId:       params.checkId || params.orderId,
    returnLanding: params.returnLanding,
    employeeId:    params.employeeId,
    employeeName:  params.employeeName,
    pin:           params.pin,
  };
  try {
    SceneManager.mountWorking(target, retParams);
  } catch (e) {
    // If returnTo scene isn't registered for some reason, fall back to
    // the landing or login gate.
    if (params.returnLanding) {
      SceneManager.mountWorking(params.returnLanding, {
        emp: params.employeeId ? {
          id:   params.employeeId,
          name: params.employeeName,
          pin:  params.pin,
        } : null,
      });
    } else {
      SceneManager.openGate('login');
    }
  }
}

defineScene({
  name: 'payment',

  state: {
    enteredAmount: 0,
    paymentMode: 'card',
  },

  render: function(container, params) {
    params = params || {};
    sceneEl           = container;
    sceneData         = params;
    enteredAmount     = 0;
    denomAccum        = 0;
    numpadStr         = '';
    paymentMode       = params.paymentMode || 'card';
    confirmProcessing = false;
    payments          = [];
    totalPaid         = 0;
    baseTotal         = params.cardTotal || 0;
    numpadRef         = null;
    dotTimer          = null;
    _modeButtons      = {};
    _procStatusEl     = null;
    _procAnimTimer    = null;

    setSceneName(params.checkId || 'ORDER');
    setHeaderBack({
      back: true,
      onBack: function() { _returnToParent(params); },
      x: true,
    });

    container.style.cssText = [
      'width:100%;height:100%;',
      'display:flex;gap:' + GAP + 'px;',
      'padding:' + (PAD + 12) + 'px ' + PAD + 'px ' + PAD + 'px ' + PAD + 'px;',
      'box-sizing:border-box;overflow:hidden;',
      'background:' + T.bg + ';',
    ].join('');

    container.appendChild(buildCenterColumn(params));
    container.appendChild(buildRightColumn(params));

    // ── Left recap + baseTotal source-of-truth ──
    // Payment is a working scene (replaces check-overview). Fetch the order
    // once: populate the OrderSummary recap on the left AND ensure baseTotal
    // is the authoritative backend value (check-overview doesn't always
    // pass cardTotal in params, so we can't trust params.cardTotal alone).
    if (params.orderId) {
      fetch('/api/v1/orders/' + encodeURIComponent(params.orderId))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(order) {
          if (!order) return;
          var items = [];
          var subtotal = 0;
          if (Array.isArray(order.items)) {
            order.items.forEach(function(it) {
              if (it.voided) return;
              var qty   = it.qty || 1;
              var price = (typeof it.price === 'number' ? it.price : 0);
              var line  = qty * price;
              subtotal += line;
              items.push({
                name:  it.name || it.menu_item_name || 'Item',
                qty:   qty,
                price: line,
              });
            });
          }
          var tax       = (typeof order.tax === 'number') ? order.tax : 0;
          var cardTotal = (typeof order.balance_due === 'number')
            ? order.balance_due : (subtotal + tax);
          var cashPrice = cardTotal; // cash-discount logic lives upstream; pass through

          // Set baseTotal from the backend. Only inflate (not shrink) if
          // the upstream passed a higher cardTotal — avoids a re-fetch
          // race where an outdated cardTotal would overwrite the correct
          // fresh value.
          if (!baseTotal || cardTotal > 0) {
            baseTotal = cardTotal;
            updateSplitDisplay();
          }

          OrderSummary.show({
            checkLabel:   order.check_number || order.order_id || 'ORDER',
            customerName: order.customer_name || '',
            items:        items,
            subtotal:     subtotal,
            tax:          tax,
            cardTotal:    cardTotal,
            cashPrice:    cashPrice,
          });
        })
        .catch(function() { /* silently skip — scene still works */ });
    }
  },

  unmount: function() {
    SceneManager.off('split:tap', _onSplitTap);
    if (dotTimer) { clearInterval(dotTimer); dotTimer = null; }
    if (_procAnimTimer) { clearInterval(_procAnimTimer); _procAnimTimer = null; }
    if (OrderSummary && OrderSummary.hide) OrderSummary.hide();
  },

  events: {
    'split:tap': function() { showSplitPopup(); },
  },

  interrupts: {
    'split-select': {
      render: function(container, params) {
        params = params || {};
        var remaining = params.remaining || 0;

        // Vz2.0 card: left accent bar + rounded corners + drop shadow
        container.style.cssText = [
          'display:flex;flex-direction:column;align-items:center;gap:18px;',
          'padding:32px 44px;',
          'background:' + T.card + ';',
          'border-left:4px solid ' + T.gold + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'box-shadow:0 10px 30px rgba(0,0,0,0.45);',
          'min-width:420px;',
          'pointer-events:auto;',
        ].join('');

        var title = document.createElement('div');
        title.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB1 + ';',
          'font-weight:' + T.fwBold + ';',
          'color:' + T.gold + ';',
          'letter-spacing:0.14em;',
          'text-transform:uppercase;',
        ].join('');
        title.textContent = 'Split Payment';
        container.appendChild(title);

        var sub = document.createElement('div');
        sub.style.cssText = [
          'font-family:' + T.fb + ';',
          'font-size:' + T.fsB2 + ';',
          'color:' + T.green + ';',
        ].join('');
        sub.textContent = 'Remaining: $' + remaining.toFixed(2);
        container.appendChild(sub);

        var btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:14px;margin-top:4px;';

        [2, 3, 4].forEach(function(divisor) {
          var amt = Math.ceil(remaining / divisor * 100) / 100;
          var btn = _buildSplitOption('1/' + divisor, '$' + amt.toFixed(2), function() {
            params.onConfirm(amt);
          });
          btnRow.appendChild(btn);
        });
        container.appendChild(btnRow);

        var cancel = _buildActionBtn('Cancel', T.verm, function() { params.onCancel(); });
        cancel.style.flex = '0 0 auto';
        cancel.style.width = '160px';
        cancel.style.height = '48px';
        container.appendChild(cancel);
      },
    },
  },

  transactionals: {
    'pc-card-processing': {
      render: function(container, params) {
        params = params || {};
        var amount = params.amount || 0;
        var TOTAL_SEGS = 22;
        var segments = [];
        var segIdx = 0;
        var msgIdx = 0;

        var statusMessages = [
          'Connecting to terminal...',
          'Waiting for card...',
          'Reading card data...',
          'Contacting processor...',
          'Awaiting authorization...',
        ];

        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        // Vz2.0 modal card: left accent bar + rounded + drop shadow.
        var card = document.createElement('div');
        card.style.cssText = [
          'background:' + T.card + ';',
          'border-left:4px solid ' + T.gold + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'width:460px;',
          'box-shadow:0 12px 36px rgba(0,0,0,0.55);',
          'font-family:' + T.fb + ';',
          'overflow:hidden;',
        ].join('');

        // Header strip
        var titleBar = document.createElement('div');
        titleBar.style.cssText = [
          'padding:14px 20px;',
          'background:' + T.well + ';',
          'display:flex;align-items:center;gap:12px;',
          'border-bottom:1px solid ' + T.border + ';',
        ].join('');

        var icon = document.createElement('div');
        icon.style.cssText = [
          'width:32px;height:32px;flex-shrink:0;',
          'background:' + T.gold + ';',
          'display:flex;align-items:center;justify-content:center;',
          'font-size:18px;font-weight:' + T.fwBold + ';',
          'color:' + T.well + ';',
          'border-radius:8px;',
        ].join('');
        icon.textContent = '\u25C8';

        var titleText = document.createElement('span');
        titleText.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB2 + ';',
          'font-weight:' + T.fwBold + ';',
          'color:' + T.green + ';',
          'letter-spacing:0.08em;',
          'text-transform:uppercase;',
        ].join('');
        titleText.textContent = 'Card Payment \u2014 $' + amount.toFixed(2);

        titleBar.appendChild(icon);
        titleBar.appendChild(titleText);
        card.appendChild(titleBar);

        // Body
        var body = document.createElement('div');
        body.style.cssText = 'padding:24px 24px 22px;display:flex;flex-direction:column;gap:14px;';

        _procStatusEl = document.createElement('div');
        _procStatusEl.style.cssText = [
          'font-family:' + T.fb + ';',
          'font-size:' + T.fsB2 + ';',
          'color:' + T.text + ';',
          'min-height:28px;',
        ].join('');
        _procStatusEl.textContent = statusMessages[0];
        body.appendChild(_procStatusEl);

        // Progress bar: rounded well with gold segments inside.
        var progContainer = document.createElement('div');
        progContainer.style.cssText = [
          'height:28px;padding:3px;',
          'background:' + T.well + ';',
          'border:1px solid ' + T.border + ';',
          'border-radius:8px;',
          'overflow:hidden;',
          'box-shadow:inset 0 2px 4px rgba(0,0,0,0.4);',
        ].join('');
        var progFill = document.createElement('div');
        progFill.style.cssText = 'height:100%;display:flex;gap:2px;align-items:stretch;';

        for (var i = 0; i < TOTAL_SEGS; i++) {
          var seg = document.createElement('div');
          seg.style.cssText = [
            'width:14px;flex-shrink:0;',
            'background:' + T.gold + ';',
            'border-radius:2px;',
            'opacity:0;transition:opacity 0.05s;',
          ].join('');
          progFill.appendChild(seg);
          segments.push(seg);
        }
        progContainer.appendChild(progFill);
        body.appendChild(progContainer);

        var hint = document.createElement('div');
        hint.style.cssText = [
          'font-family:' + T.fb + ';',
          'font-size:' + T.fsB3 + ';',
          'color:' + T.mutedText + ';',
          'text-align:center;',
          'letter-spacing:0.05em;',
        ].join('');
        hint.textContent = 'Present card on terminal...';
        body.appendChild(hint);

        card.appendChild(body);
        container.appendChild(card);

        _procAnimTimer = setInterval(function() {
          if (segIdx < TOTAL_SEGS) {
            segments[segIdx].style.opacity = '1';
            segIdx++;
          }
          if (segIdx % 4 === 0 && msgIdx < statusMessages.length - 1) {
            msgIdx++;
            if (_procStatusEl) _procStatusEl.textContent = statusMessages[msgIdx];
          }
          if (segIdx >= TOTAL_SEGS) {
            segIdx = 0;
            segments.forEach(function(s) { s.style.opacity = '0'; });
          }
        }, 200);
      },
      unmount: function() {
        if (_procAnimTimer) clearInterval(_procAnimTimer);
        _procAnimTimer = null;
        _procStatusEl = null;
      },
    },

    'pc-change-due': {
      render: function(container, params) {
        params = params || {};
        var returned = false;
        _changeDueTimer = null;

        setSceneName(null);
        setHeaderBack({});

        container.style.cssText = [
          'width:100%;height:100%;',
          'display:flex;flex-direction:column;align-items:center;justify-content:center;',
          'gap:24px;background:' + T.scrimInterrupt + ';',
        ].join('');

        var isCash    = params.paymentMode === 'cash';
        var hasChange = isCash && params.change > 0;

        // Vz2.0 card with accent bar (gold for change-due celebration)
        var card = document.createElement('div');
        card.style.cssText = [
          'display:flex;flex-direction:column;align-items:center;',
          'padding:40px 72px 36px;',
          'background:' + T.card + ';',
          'border-left:4px solid ' + T.gold + ';',
          'border-radius:' + T.chamferCard + 'px;',
          'box-shadow:0 16px 48px rgba(0,0,0,0.55);',
          'min-width:520px;',
        ].join('');

        var topLabel = document.createElement('div');
        topLabel.style.cssText = [
          'font-family:' + T.fh + ';',
          'font-size:' + T.fsB1 + ';',
          'font-weight:' + T.fwBold + ';',
          'letter-spacing:0.22em;',
          'color:' + T.green + ';',
          'margin-bottom:24px;',
          'text-transform:uppercase;',
        ].join('');
        topLabel.textContent = isCash ? 'Cash Payment' : 'Card Payment';
        card.appendChild(topLabel);

        if (hasChange) {
          var changeLabel = document.createElement('div');
          changeLabel.style.cssText = [
            'font-family:' + T.fh + ';',
            'font-size:' + T.fsB2 + ';',
            'font-weight:' + T.fwBold + ';',
            'letter-spacing:0.18em;',
            'color:' + T.green + ';',
            'margin-bottom:8px;',
            'text-transform:uppercase;',
          ].join('');
          changeLabel.textContent = 'Change Due';
          card.appendChild(changeLabel);

          var changeAmount = document.createElement('div');
          changeAmount.style.cssText = [
            'font-family:' + T.fh + ';',
            'font-size:108px;font-weight:' + T.fwBold + ';',
            'color:' + T.gold + ';',
            'line-height:1;letter-spacing:0.02em;',
            'text-shadow:0 0 24px ' + hexToRgba(T.gold, 0.35) + ';',
          ].join('');
          changeAmount.textContent = '$' + params.change.toFixed(2);
          card.appendChild(changeAmount);
        } else {
          var paidLabel = document.createElement('div');
          paidLabel.style.cssText = [
            'font-family:' + T.fh + ';',
            'font-size:44px;font-weight:' + T.fwBold + ';',
            'letter-spacing:0.14em;',
            'color:' + T.green + ';',
            'margin-bottom:8px;',
            'text-transform:uppercase;',
          ].join('');
          paidLabel.textContent = isCash ? 'Exact Change' : 'Payment Approved';
          card.appendChild(paidLabel);
        }

        var chargedLine = document.createElement('div');
        chargedLine.style.cssText = [
          'font-family:' + T.fb + ';',
          'font-size:' + T.fsB2 + ';',
          'color:' + T.mutedText + ';',
          'margin-top:14px;',
          'letter-spacing:0.06em;',
        ].join('');
        chargedLine.textContent = (isCash ? 'Cash price: ' : 'Charged: ') + '$' + params.total.toFixed(2);
        card.appendChild(chargedLine);

        var printLine = document.createElement('div');
        printLine.style.cssText = [
          'font-family:' + T.fb + ';',
          'font-size:' + T.fsB3 + ';',
          'color:' + T.mutedText + ';',
          'letter-spacing:0.14em;',
          'margin-top:18px;',
          'text-transform:uppercase;',
        ].join('');
        printLine.textContent = 'Receipt Printing...';
        card.appendChild(printLine);

        container.appendChild(card);

        var btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:20px;';

        var newOrderBtn = _buildActionBtn('NEW ORDER', T.green, function() { doReturn('order-entry'); });
        newOrderBtn.style.flex = '0 0 auto';
        newOrderBtn.style.width  = '240px';
        newOrderBtn.style.height = '72px';
        btnRow.appendChild(newOrderBtn);

        var logoutBtn = _buildActionBtn('LOGOUT', T.green, function() { doReturn('login'); });
        logoutBtn.style.flex = '0 0 auto';
        logoutBtn.style.width  = '240px';
        logoutBtn.style.height = '72px';
        btnRow.appendChild(logoutBtn);

        container.appendChild(btnRow);

        var postAction = (window.KINDpos && window.KINDpos.postPaymentAction) || 'quick-service';
        if (postAction === 'logout') {
          var autoHint = document.createElement('div');
          autoHint.style.cssText = [
            'font-family:' + T.fb + ';',
            'font-size:' + T.fsB3 + ';',
            'color:' + T.mutedText + ';',
            'letter-spacing:0.12em;',
            'margin-top:4px;',
          ].join('');
          autoHint.textContent = 'auto-logout in 8s...';
          container.appendChild(autoHint);

          var countdown = 8;
          _changeDueTimer = setInterval(function() {
            countdown--;
            if (countdown <= 0) {
              clearInterval(_changeDueTimer);
              _changeDueTimer = null;
              doReturn('login');
            } else {
              autoHint.textContent = 'auto-logout in ' + countdown + 's...';
            }
          }, 1000);
        }

        function doReturn(target) {
          if (returned) return;
          returned = true;
          if (_changeDueTimer) { clearInterval(_changeDueTimer); _changeDueTimer = null; }
          var activeScene = SceneManager.getActiveWorking();
          SceneManager.closeAllTransactional();
          if (target === 'login') {
            OrderSummary.hide();
            SceneManager.unmountWorking(activeScene);
            SceneManager.openGate('login');
          } else if (activeScene === 'check-overview') {
            SceneManager.emit('payment:complete');
          } else {
            OrderSummary.hide();
            SceneManager.mountWorking('order-entry', {});
          }
        }
      },
      unmount: function() {
        if (_changeDueTimer) { clearInterval(_changeDueTimer); _changeDueTimer = null; }
      },
    },
  },
});


// ═══════════════════════════════════════════════════
//  CENTER COLUMN — Denominations + Actions + Toggle
// ═══════════════════════════════════════════════════

function buildCenterColumn(params) {
  var col = document.createElement('div');
  col.style.cssText = 'flex:1;display:flex;flex-direction:column;gap:10px;overflow:hidden;justify-content:center;padding:8px 0;';

  // ── Denomination grid (2 cols × 2 rows, fixed rows) ──
  // 2x2 squares for $5/$10/$20/$50 — tall enough to feel tappable but
  // not stretching to fill the whole column.
  var grid = document.createElement('div');
  grid.style.cssText = [
    'display:grid;',
    'grid-template-columns:1fr 1fr;',
    'grid-template-rows:140px 140px;',
    'gap:10px;flex-shrink:0;',
  ].join('');

  grid.appendChild(buildDenomBtn(5));
  grid.appendChild(buildDenomBtn(10));
  grid.appendChild(buildDenomBtn(20));
  grid.appendChild(buildDenomBtn(50));
  col.appendChild(grid);

  // ── $100 (full-width, same bevel/style as denoms but smaller row) ──
  var btn100 = buildDenomBtn(100);
  btn100.style.height = '70px';
  btn100.style.flexShrink = '0';
  col.appendChild(btn100);

  // ── Exact + Split row (two buttons, equal width) ──
  var actionRow = document.createElement('div');
  actionRow.style.cssText = 'flex-shrink:0;display:flex;gap:10px;';

  actionRow.appendChild(_buildActionBtn('Exact', T.yellow, handleExact));
  actionRow.appendChild(_buildActionBtn('Split', T.elec,   _onSplitTap));

  col.appendChild(actionRow);

  // ── Method toggle: Cash | Card | GC — bigger pill buttons ──
  var toggle = document.createElement('div');
  toggle.style.cssText = 'flex-shrink:0;display:flex;gap:12px;padding-top:8px;';

  toggle.appendChild(buildModeBtn('Cash', 'cash', T.green));
  toggle.appendChild(buildModeBtn('Card', 'card', T.elec));
  toggle.appendChild(buildModeBtn('GC',   'gc',   T.gold));

  col.appendChild(toggle);

  setTimeout(function() { setPaymentMode(paymentMode); }, 0);

  return col;
}

function _buildSplitOption(topLine, bottomLine, onTap) {
  var btn = document.createElement('div');
  btn.style.cssText = [
    'width:120px;height:88px;',
    'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;',
    'background:' + T.card + ';',
    'border:2px solid ' + T.green + ';',
    'border-radius:' + T.chamferCard + 'px;',
    'font-family:' + T.fh + ';',
    'color:' + T.green + ';',
    'cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'box-shadow:0 4px 0 ' + T.well + ';',
    'transition:transform 80ms, box-shadow 80ms;',
  ].join('');

  var top = document.createElement('div');
  top.style.cssText = 'font-size:' + T.fsB2 + ';font-weight:' + T.fwBold + ';letter-spacing:0.08em;';
  top.textContent = topLine;
  btn.appendChild(top);

  var bot = document.createElement('div');
  bot.style.cssText = 'font-size:' + T.fsB3 + ';font-weight:' + T.fwBold + ';color:' + T.gold + ';';
  bot.textContent = bottomLine;
  btn.appendChild(bot);

  btn.addEventListener('pointerdown', function() {
    btn.style.transform = 'translateY(2px)';
    btn.style.boxShadow = '0 2px 0 ' + T.well;
  });
  function resetPress() {
    btn.style.transform = '';
    btn.style.boxShadow = '0 4px 0 ' + T.well;
  }
  btn.addEventListener('pointerup',     resetPress);
  btn.addEventListener('pointercancel', resetPress);
  btn.addEventListener('pointerleave',  resetPress);
  btn.addEventListener('click', function() { if (onTap) onTap(); });

  return btn;
}

function _buildActionBtn(label, accent, onTap) {
  // Plain div, colored outline, text stays in the accent color through
  // all states. Shares the depress visual language with denom buttons.
  var btn = document.createElement('div');
  btn.style.cssText = [
    'flex:1;height:56px;',
    'display:flex;align-items:center;justify-content:center;',
    'background:' + T.card + ';',
    'border:2px solid ' + accent + ';',
    'border-radius:999px;',
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsB2 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + accent + ';',
    'letter-spacing:0.1em;',
    'cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'box-shadow:0 4px 0 ' + T.well + ';',
    'transition:transform 80ms, box-shadow 80ms;',
  ].join('');
  btn.textContent = label;

  btn.addEventListener('pointerdown', function() {
    btn.style.transform = 'translateY(2px)';
    btn.style.boxShadow = '0 2px 0 ' + T.well;
  });
  function resetPress() {
    btn.style.transform = '';
    btn.style.boxShadow = '0 4px 0 ' + T.well;
  }
  btn.addEventListener('pointerup',     resetPress);
  btn.addEventListener('pointercancel', resetPress);
  btn.addEventListener('pointerleave',  resetPress);
  btn.addEventListener('click', function() { if (onTap) onTap(); });

  return btn;
}

function buildDenomBtn(val) {
  // Plain div (not a pill) so we control the press state and the text
  // never flips to dark on hover/press. Matches the mode-toggle approach.
  var btn = document.createElement('div');
  btn.style.cssText = [
    'width:100%;height:100%;',
    'display:flex;align-items:center;justify-content:center;',
    'background:' + T.card + ';',
    'border:2px solid ' + T.border + ';',
    'border-radius:14px;',
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsDenom + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.green + ';',
    'letter-spacing:0.06em;',
    'cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'box-shadow:0 6px 0 ' + T.well + ';',
    'transition:background 140ms, transform 80ms, box-shadow 80ms;',
  ].join('');
  btn.textContent = '$' + val;

  // Subtle depress on press — text stays mint the whole time.
  btn.addEventListener('pointerdown', function() {
    btn.style.transform = 'translateY(3px)';
    btn.style.boxShadow = '0 3px 0 ' + T.well;
  });
  function resetPress() {
    btn.style.transform = '';
    btn.style.boxShadow = '0 6px 0 ' + T.well;
  }
  btn.addEventListener('pointerup',     resetPress);
  btn.addEventListener('pointercancel', resetPress);
  btn.addEventListener('pointerleave',  resetPress);

  // Tap: brief confirmation flash (bg flips to mint, text goes dark for
  // 180ms so the user sees the denomination was accepted), then back.
  btn.addEventListener('click', function() {
    handleDenomination(val);
    btn.style.background = T.green;
    btn.style.color      = T.well;
    setTimeout(function() {
      btn.style.background = T.card;
      btn.style.color      = T.green;
    }, 180);
  });

  return btn;
}

function buildModeBtn(label, mode, activeColor) {
  // Plain div (not a pill button) so we fully control the press/active
  // visual states and keep the text mint regardless of interaction.
  var wrap = document.createElement('div');
  wrap.style.cssText = [
    'flex:1;height:80px;',
    'display:flex;align-items:center;justify-content:center;',
    'background:' + T.card + ';',
    'border:2px solid ' + T.border + ';',
    'border-radius:999px;',
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsB2 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.green + ';',
    'letter-spacing:0.14em;',
    'cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'transition:background 120ms, border-color 120ms, transform 80ms;',
    'box-shadow:0 4px 0 ' + T.well + ';',
  ].join('');
  wrap.textContent = label;

  // Tap visual: subtle depress — NO color flip (text stays mint always).
  wrap.addEventListener('pointerdown', function() {
    wrap.style.transform = 'translateY(2px)';
    wrap.style.boxShadow = '0 2px 0 ' + T.well;
  });
  function resetPress() {
    wrap.style.transform = '';
    wrap.style.boxShadow = '0 4px 0 ' + T.well;
  }
  wrap.addEventListener('pointerup',     resetPress);
  wrap.addEventListener('pointercancel', resetPress);
  wrap.addEventListener('pointerleave',  resetPress);
  wrap.addEventListener('click', function() {
    setPaymentMode(mode);
  });

  // Expose refs for setPaymentMode to toggle the active visual.
  _modeButtons[mode] = { wrap: wrap, inner: wrap, color: activeColor };
  return wrap;
}


// ═══════════════════════════════════════════════════
//  RIGHT COLUMN — Numpad
// ═══════════════════════════════════════════════════

function buildRightColumn() {
  var col = document.createElement('div');
  col.style.cssText = 'flex-shrink:0;display:flex;flex-direction:column;justify-content:stretch;';

  numpadRef = buildNumpad({
    masked:         false,
    maxDigits:      7,
    displayH:       68,
    cardPad:        18,
    keyH:           96,
    keyGap:         12,
    gap:            16,
    submitLabel:    'ent',
    chassisColor:   T.card,
    chassisChamfer: 6,
    chassisBevel:   5,
    digitColor:     T.digitColor,
    clearColor:     T.clrColor,
    submitColor:    T.submitColor,
    displayColor:   T.pinDot,
    displayBg:      T.pinFieldBg,
    digitFont:      T.fhr,
    canSubmit:      function() { return enteredAmount > 0; },
    displayFormat:  function(digits) {
      if (digits && digits.length > 0) {
        var n = parseInt(digits, 10) || 0;
        return '$' + (n / 100).toFixed(2);
      }
      if (denomAccum > 0) return '$' + denomAccum.toFixed(2);
      return '$0.00';
    },
    onChange: function(digits) {
      denomAccum = 0;
      numpadStr = digits;
      enteredAmount = (parseInt(digits, 10) || 0) / 100;
      updateSplitDisplay();
    },
    onSubmit: function() {
      handleConfirm();
    },
  });

  col.appendChild(numpadRef);
  return col;
}


// ═══════════════════════════════════════════════════
//  PAYMENT MODE TOGGLE
// ═══════════════════════════════════════════════════

function setPaymentMode(mode) {
  paymentMode = mode;
  Object.keys(_modeButtons).forEach(function(m) {
    var b = _modeButtons[m];
    if (!b) return;
    var isActive = (m === mode);
    if (isActive) {
      // Active: filled with the mode color, dark text.
      b.wrap.style.background   = b.color;
      b.wrap.style.borderColor  = b.color;
      b.wrap.style.boxShadow    = '0 0 14px ' + hexToRgba(b.color, 0.55) + ', 0 4px 0 ' + T.well;
      b.wrap.style.color        = T.well;
    } else {
      // Inactive: plain card bg, mint text.
      b.wrap.style.background   = T.card;
      b.wrap.style.borderColor  = T.border;
      b.wrap.style.boxShadow    = '0 4px 0 ' + T.well;
      b.wrap.style.color        = T.green;
    }
  });
}


// ═══════════════════════════════════════════════════
//  DENOMINATION + EXACT HANDLERS
// ═══════════════════════════════════════════════════

function handleDenomination(val) {
  denomAccum += val;
  numpadStr = '';
  enteredAmount = denomAccum;
  if (numpadRef) {
    numpadRef.setPin('');
    numpadRef.setHint('$' + denomAccum.toFixed(2), T.gold);
  }
  updateSplitDisplay();
}

function handleExact() {
  var remaining = getRemainingBalance();
  if (remaining <= 0) {
    showToast('Nothing due', { bg: T.gold, duration: 1500 });
    return;
  }
  enteredAmount = remaining;
  denomAccum = 0;
  // Populate the numpad's digit buffer with the remaining amount in cents
  // so the display reads the same as if the user typed it manually — then
  // pressing `ent` submits via the normal path.
  var cents = Math.round(remaining * 100).toString();
  numpadStr = cents;
  if (numpadRef) {
    numpadRef.setPin(cents);
  }
  updateSplitDisplay();
}


// ═══════════════════════════════════════════════════
//  BALANCE TRACKING
// ═══════════════════════════════════════════════════

function getRemainingBalance() {
  return Math.max(0, baseTotal - totalPaid);
}

function updateSplitDisplay() {
  if (OrderSummary && OrderSummary.updateSplit) {
    OrderSummary.updateSplit({ totalPaid: totalPaid, remaining: getRemainingBalance() });
  }
}


// ═══════════════════════════════════════════════════
//  CONFIRM — API Calls
// ═══════════════════════════════════════════════════

async function handleConfirm() {
  if (confirmProcessing) return;
  confirmProcessing = true;

  var remaining = getRemainingBalance();
  var isCash = paymentMode === 'cash';
  var paymentAmount = Math.min(enteredAmount, remaining);
  var change = isCash ? Math.max(0, enteredAmount - paymentAmount) : 0;
  var proc = null;

  if (paymentAmount <= 0) {
    confirmProcessing = false;
    return;
  }

  try {
    // Resolve seat_numbers for the backend. Two param shapes are supported:
    //  1) Legacy SM2: sceneData.seatNumbers = [1, 2, 3]
    //  2) Vz2.0 check-overview: sceneData.seats = [{seatId, number, items}, ...]
    // Without seat_numbers the backend can't tag the payment to specific
    // seats, so check-overview wouldn't render them as paid (gold) on return.
    var seatNumbers = null;
    if (Array.isArray(sceneData.seatNumbers) && sceneData.seatNumbers.length) {
      seatNumbers = sceneData.seatNumbers.slice();
    } else if (Array.isArray(sceneData.seats) && sceneData.seats.length) {
      seatNumbers = sceneData.seats
        .map(function(s) { return s && typeof s.number === 'number' ? s.number : null; })
        .filter(function(n) { return n !== null; });
      if (seatNumbers.length === 0) seatNumbers = null;
    }

    if (isCash) {
      var cashBody = {
          order_id:       sceneData.orderId,
          amount:         paymentAmount,
          tip:            0.0,
          payment_method: 'cash',
      };
      if (seatNumbers) cashBody.seat_numbers = seatNumbers;
      var res = await fetch(API + '/payments/cash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cashBody),
      });
      if (!res.ok) {
        var err = await res.json().catch(function() { return {}; });
        confirmProcessing = false;
        showToast(err.detail || 'Cash payment failed', { bg: T.verm });
        return;
      }
    } else {
      proc = showProcessingOverlay(paymentAmount);

      var controller = new AbortController();
      var cardTimeout = setTimeout(function() { controller.abort(); }, 95000);

      var saleBody = {
          order_id:    sceneData.orderId,
          amount:      paymentAmount,
          terminal_id: 'terminal_01',
      };
      if (seatNumbers) saleBody.seat_numbers = seatNumbers;
      var res = await fetch(API + '/payments/sale', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(saleBody),
        signal: controller.signal,
      });

      clearTimeout(cardTimeout);
      if (proc) proc.dismiss();

      if (!res.ok) {
        var err = await res.json().catch(function() { return {}; });
        var errType = res.status === 402 ? 'DECLINED'
                    : res.status === 400 ? 'CANCELLED'
                    : 'ERROR';
        confirmProcessing = false;
        showToast(err.detail || 'Payment failed \u2014 ' + errType, { bg: T.verm });
        return;
      }
    }

    // ── Success — queue receipts ──
    queueReceipt('customer');
    if (!isCash) queueReceipt('merchant');

    payments.push({ method: paymentMode, amount: paymentAmount });
    totalPaid += paymentAmount;

    var newRemaining = getRemainingBalance();
    confirmProcessing = false;

    if (newRemaining < 0.005) {
      activateResult(change);
    } else {
      enteredAmount = 0;
      denomAccum = 0;
      numpadStr = '';
      if (numpadRef) numpadRef.clear();
      updateSplitDisplay();
      showToast(
        '$' + paymentAmount.toFixed(2) + ' ' + paymentMode +
        ' \u2014 $' + newRemaining.toFixed(2) + ' remaining',
        { bg: T.greenWarm, duration: 3000 }
      );
    }

  } catch (err) {
    if (proc) proc.dismiss();
    confirmProcessing = false;
    showToast('Connection error \u2014 check terminal', { bg: T.verm });
  }
}

function queueReceipt(copyType) {
  fetch(API + '/print/receipt/' + sceneData.orderId + '?copy_type=' + copyType, { method: 'POST' })
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); })
    .catch(function(err) {
      console.warn('[KINDpos] Receipt print failed (' + copyType + '):', err);
      showToast('Receipt print failed \u2014 check printer');
    });
}


// ═══════════════════════════════════════════════════
//  RESULT — Open Change Due
// ═══════════════════════════════════════════════════

function activateResult(change) {
  var lastPayment = payments[payments.length - 1] || {};
  var isCash = lastPayment.method === 'cash';
  var remaining = getRemainingBalance();
  var isFullyPaid = remaining < 0.005;

  SceneManager.closeAllTransactional();
  SceneManager.emit('payment:complete', { orderId: sceneData.orderId });

  // Show change due toast if applicable (cash only, any flow).
  if (isCash && change > 0) {
    showToast('Change: $' + change.toFixed(2), { bg: T.gold, duration: 4000 });
  }

  if (isFullyPaid) {
    // Whole check settled → return to landing page. Determine which
    // landing from the returnParams bundle passed in.
    var landing = sceneData.returnLanding
      || (sceneData.returnParams && sceneData.returnParams.returnLanding)
      || 'server-landing';
    SceneManager.mountWorking(landing, {
      emp: sceneData.employeeId ? {
        id:   sceneData.employeeId,
        name: sceneData.employeeName,
        pin:  sceneData.pin,
      } : null,
    });
  } else {
    // Partial payment (more seats / amount remaining) → return to
    // check-overview so operator can continue paying. Gold-headered
    // paid seats will show their settled state.
    _returnToParent(sceneData);
  }
}


// ═══════════════════════════════════════════════════
//  SPLIT POPUP
// ═══════════════════════════════════════════════════

function showSplitPopup() {
  var remaining = getRemainingBalance();
  if (remaining <= 0) return;

  SceneManager.interrupt('split-select', {
    params: { remaining: remaining },
    onConfirm: function(amount) {
      denomAccum = 0;
      enteredAmount = amount;
      numpadStr = '';
      if (numpadRef && numpadRef.clear) numpadRef.clear();
    },
  });
}


// ═══════════════════════════════════════════════════
//  CARD PROCESSING OVERLAY HELPERS
// ═══════════════════════════════════════════════════

function showProcessingOverlay(amount) {
  SceneManager.openTransactional('pc-card-processing', { amount: amount });
  return {
    updateStatus: function(msg) { if (_procStatusEl) _procStatusEl.textContent = msg; },
    dismiss: function() {
      if (_procAnimTimer) clearInterval(_procAnimTimer);
      _procAnimTimer = null;
      _procStatusEl = null;
      SceneManager.closeTransactional('pc-card-processing');
    },
  };
}