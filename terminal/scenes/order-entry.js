// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Order Entry Scene (Vz2.0)
//  Item entry tool — child of check-overview
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { SceneManager, defineScene } from '../scene-manager.js';
import { T } from '../tokens.js';
import { buildPillButton, hexToRgba, darkenHex } from '../theme-manager.js';
import {
  buildStyledButton,
  applySunkenStyle,
  chamfer,
  bevelEdges,
  applyCardBevel as _applyCardBevel,
} from '../sm2-shim.js';
import { buildButton, showToast } from '../components.js';
import { setSceneName, setHeaderBack } from '../app.js';
import { OrderSummary } from '../order-summary.js';
import { showKeyboard, hideKeyboard } from '../keyboard.js';
import { showHalfPlacementOverlay } from '../half-placement-overlay.js';
import { showPizzaBuilderOverlay } from '../pizza-builder-overlay.js';
import { PREFIXES as UNI_PREFIXES, getModHexData, hasPizzaCategory, PIZZA_PLACEMENTS, MOD_COLORS } from '../menu-data/universal-modifiers.js';
import { computeTotals } from '../pricing.js';

// Local bevel colors kept for any call sites that still reference them.
var _bevelL = T.green;
var _bevelD = T.greenDk;

var PAD      = 16;
var GAP      = 16;
var BTN_H    = 50;
var OVERLAP  = 18;

// Pricing rates come from frontend/js/pricing.js — one source of truth
// for TAX_RATE / CASH_DISCOUNT across every scene, so a stale copy can't
// leak into a payment amount.

// ── API ───────────────────────────────────────────
var API = '/api/v1';

// ── Order ID — one per transaction, reset on fresh enter ──
var currentOrderId = null;
var isSending = false;   // guard against concurrent handleSend calls

function _idemKey() {
  return 'ik_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}
var currentCheckNumber = null;
var currentCustomerName = null;

function _handleNameTap() {
  if (!currentOrderId) {
    showToast('Send items first to name this check', { bg: T.gold, duration: 2000 });
    return;
  }
  SceneManager.interrupt('oe-name-input', {
    onConfirm: function(name) {
      fetch(API + '/orders/' + currentOrderId, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customer_name: name }),
      }).then(function(r) {
        if (r.ok) {
          currentCustomerName = name;
          OrderSummary.update({ customerName: name });
          showToast(name ? 'Named: ' + name : 'Name cleared', { bg: T.greenWarm, duration: 1500 });
        } else { showToast('Name update failed', { bg: T.verm }); }
      }).catch(function() { showToast('Name update failed', { bg: T.verm }); });
    },
    onCancel: function() {},
    checkLabel: currentCheckNumber || 'check',
    currentName: currentCustomerName || '',
  });
}

// ── Pizza builder data (populated by API or fallback) ──
var PIZZA_BUILDER_DATA = null;

// ── Menu data (loaded from API on scene entry) ──
var MENU_DATA = [];

var MOD_DATA = [];

// ── Per-item included-modifier lookup (from hidden "included_<item_id>" groups) ──
var INCLUDED_BY_ITEM = {};

// ── Overseer-authored modifier wiring (source of truth when present) ──
var MODIFIER_GROUPS = [];          // raw groups (non-hidden) keyed by group_id
var MANDATORY_ASSIGNMENTS = [];    // [{ assignment_id, label, target_type, target_id, modifier_ids, select_mode }]
var UNIVERSAL_ASSIGNMENTS = [];    // [{ assignment_id, category_id, group_ids }]
var MODIFIER_MASTER = {};          // modifier_id → { name, price }
var ITEM_TO_CATEGORY = {};         // item_id → category_id

// ── Fetch menu from API and transform to HexNav format ──
var _menuFetched = false;

function fetchMenuFromAPI() {
  return Promise.all([
    fetch(API + '/menu').then(function(r) { return r.json(); }),
    fetch(API + '/config/mandatory-assignments').then(function(r) { return r.ok ? r.json() : []; }).catch(function() { return []; }),
    fetch(API + '/config/universal-assignments').then(function(r) { return r.ok ? r.json() : []; }).catch(function() { return []; }),
  ]).then(function(results) {
    var menu = results[0];
    MANDATORY_ASSIGNMENTS = results[1] || [];
    UNIVERSAL_ASSIGNMENTS = results[2] || [];
    if (!menu.categories || !menu.items) return;

    // Build items_by_category keyed by category_id (lowercase)
    var itemsByCatId = {};
    ITEM_TO_CATEGORY = {};
    menu.categories.forEach(function(cat) { itemsByCatId[cat.category_id] = []; });
    menu.items.forEach(function(item) {
      // Match item.category (name like "Pizza") to category
      var cat = menu.categories.find(function(c) {
        return c.name === item.category || c.category_id === item.category;
      });
      if (cat) {
        if (!itemsByCatId[cat.category_id]) itemsByCatId[cat.category_id] = [];
        itemsByCatId[cat.category_id].push(item);
        var iid = item.item_id || item.id;
        if (iid) ITEM_TO_CATEGORY[iid] = cat.category_id;
      }
    });

    // Transform categories + items into HexNav MENU_DATA
    MENU_DATA = menu.categories.map(function(cat) {
      var catItems = (itemsByCatId[cat.category_id] || [])
        .sort(function(a, b) { return (a.display_order || 999) - (b.display_order || 999); })
        .map(function(item) {
          var hexItem = { label: item.name, price: item.price, id: item.item_id || item.id };
          if (item.pizza_size) hexItem.pizzaSize = true;
          if (item.mods) hexItem.requiredMods = item.mods;
          return hexItem;
        });
      // Prefer the user-set color from the Overseer; fall back to theme token
      var catColor = cat.color || cat.hex_color || T.catColor(cat.label || cat.name.toUpperCase()) || T.mutedText;
      var textColor = _textColorForHex(catColor);
      return {
        id: cat.category_id,
        label: cat.label || cat.name.toUpperCase(),
        color: catColor,
        textColor: textColor,
        pizzaBuilder: cat.pizza_builder || false,
        enablePlacement: cat.enable_placement === true,
        subcats: [{ id: cat.category_id + '-items', label: cat.name, items: catItems }],
      };
    });

    // Build per-item included-modifier lookup from hidden "included_<item_id>" groups.
    // Each entry is shape { id, label } — matches ModifierPanel's includedItems contract.
    INCLUDED_BY_ITEM = {};
    MODIFIER_GROUPS = [];
    MODIFIER_MASTER = {};
    (menu.modifier_groups || []).forEach(function(g) {
      // Always index modifiers into MODIFIER_MASTER so mandatory-assignment
      // lookups resolve names for modifiers that live in hidden groups too.
      (g.modifiers || []).forEach(function(m) {
        if (m.modifier_id && !MODIFIER_MASTER[m.modifier_id]) {
          MODIFIER_MASTER[m.modifier_id] = { name: m.name, price: parseFloat(m.price) || 0 };
        }
      });
      if (g.hidden) {
        if (g.owner_item_id) {
          var mods = (g.modifiers || []).map(function(m) { return { id: m.modifier_id, label: m.name }; });
          if (mods.length > 0) INCLUDED_BY_ITEM[g.owner_item_id] = mods;
        }
        return;
      }
      MODIFIER_GROUPS.push(g);
    });

    // Extract pizza builder modifier groups
    if (menu.modifier_groups) {
      var builderGroups = menu.modifier_groups
        .filter(function(g) { return g.builder; })
        .sort(function(a, b) { return (a.display_order || 999) - (b.display_order || 999); });

      if (builderGroups.length > 0) {
        PIZZA_BUILDER_DATA = builderGroups.map(function(g) {
          var subcats;
          if (g.subcats && g.subcats.length > 0) {
            // Group has explicit subcategories (e.g. Prep → Crust, Temp, Sauce, Cut)
            subcats = g.subcats.map(function(sc) {
              return {
                id: sc.id,
                label: sc.name,
                items: (sc.modifiers || []).map(function(m) {
                  return { label: m.name, id: m.modifier_id, price: m.price || 0 };
                }),
              };
            });
          } else {
            // Flat modifiers → single subcat
            subcats = [{ id: g.group_id + '-items', label: g.name, items:
              (g.modifiers || []).map(function(m) {
                return { label: m.name, id: m.modifier_id, price: m.price || 0 };
              }),
            }];
          }
          return {
            id: g.group_id,
            label: g.name.toUpperCase(),
            color: g.color || T.green,
            textColor: g.text_color || T.well,
            subcats: subcats,
          };
        });
      }
    }

    _menuFetched = true;
    // Refresh snake grid if already mounted
    if (_gridEl) renderSnakeGrid();
  }).catch(function(err) {
    console.warn('[KINDpos] Menu fetch failed, using fallback:', err);
  });
}

function _textColorForHex(hex) {
  // Simple luminance check to pick dark or light text
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  var lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.5 ? T.well : T.text;
}

// ── Combo flow state ─────────────────────────────
var comboFlow    = null;  // { step: 'side'|'drink', ticketItem: ref }

// ── Scene state ───────────────────────────────────
var ticket       = [];    // [{ id, name, unitPrice, mods:[{name,price,charged}], selected, sent }]
var ticketSeq    = 0;     // monotonic ID counter
var sceneParams  = {};
var modHistory   = [];    // [{inst, mod}] — undo stack for modifier additions
var _bottomBar   = null;  // DOM ref for bottom action bar
var _mainArea    = null;  // DOM ref for right panel
var _activeSeat  = 1;     // current seat number for new items

// ── Snake nav state ───────────────────────────────
var snakeState = {
  view:   'cats',  // 'personal'|'cats'|'subcats'|'items'
  crumbs: [],      // [{ id, label, color }]
  catId:  null,
  subId:  null,
};
var favorites    = [];   // item ids for personal tab
var _gridEl      = null; // inner grid DOM container
var _gridWrap    = null; // collapsible grid wrapper
var _snakeStrip  = null; // crumb-only strip shown when mod panel open
var _snakeTabBar = null; // ★ PERSONAL tab strip
var _expandedItems = {}; // item id → true when mod rows are expanded

// ── Modifier Panel (slide-up) ─────────────────────
var _modPanel      = null;   // ModifierPanel instance
var _modPanelItem  = null;   // ticket preview item for active panel
var _modPanelOpen  = false;  // drives grid collapse animation

// ── Batch Modifier Session ───────────────────────
var modifierSession = {
  active: false,
  selectedItems: [],
  activePrefix: null,
  activePlacement: null,
  appliedMods: [],
  panelEl: null,
  hasPizza: false,
};

// ── Prefix definitions ────────────────────────────
var PREFIXES = [
  { id: 'add',     label: 'ADD',     color: T.greenWarm, textColor: T.well },
  { id: 'extra',   label: 'EXTRA',   color: T.elec,      textColor: T.well },
  { id: 'no',      label: 'NO',      color: T.verm,      textColor: T.text },
  { id: 'on-side', label: 'ON SIDE', color: T.gold,      textColor: T.well },
  { id: 'lite',    label: 'LITE',    color: T.gold,      textColor: T.well },
];

defineScene({
  name: 'order-entry',

  state: {},

  render: function(container, params) {
    params = params || {};
    setSceneName(params.recallOrderId ? 'ADD ITEMS' : 'NEW ORDER');
    setHeaderBack({
      back: true,
      onBack: function() { handleClose(); },
      x: true,
    });
    ticket         = [];
    ticketSeq      = 0;
    sceneParams    = params;
    currentOrderId = null;
    isSending      = false;
    currentCheckNumber = null;
    currentCustomerName = null;
    modHistory     = [];
    modifierSession = { active: false, selectedItems: [], activePrefix: null, activePlacement: null, appliedMods: [], panelEl: null, hasPizza: false };
    _bottomBar     = null;
    _mainArea      = null;
    _modPanel      = null;
    _modPanelItem  = null;
    _modPanelOpen  = false;
    _gridEl        = null;
    _gridWrap      = null;
    _snakeStrip    = null;
    _snakeTabBar   = null;
    _expandedItems = {};
    snakeState     = { view:'cats', crumbs:[], catId:null, subId:null };
    favorites      = [];
    _activeSeat    = (params.seatNumbers && params.seatNumbers[0]) || 1;

    container.style.cssText = [
      'width:100%;height:100%;',
      'display:flex;gap:' + GAP + 'px;',
      'padding:' + PAD + 'px;',
      'box-sizing:border-box;',
    ].join('');

    // Show persistent order summary panel (left column)
    // Lock _renderItems so stale check-overview updates can't write into our ticket list
    OrderSummary.show({ title: 'ITEM RECAP', checkId: params.recallCheckNumber || '', customerName: '', items: [], subtotal: 0, tax: 0, cardTotal: 0, cashPrice: 0, onNameTap: _handleNameTap });
    OrderSummary.lockItemRender();

    var mainArea = buildMain(container, params);
    container.appendChild(mainArea);

    if (!_menuFetched) fetchMenuFromAPI();

    if (params.recallOrderId) {
      currentOrderId = params.recallOrderId;
      currentCheckNumber = params.recallCheckNumber || null;
      recallFromBackend(params.recallOrderId);
    }
  },

  unmount: function() {
    OrderSummary.unlockItemRender();
    OrderSummary.hide();
    if (_modPanel) { _modPanel.destroy(); _modPanel = null; }
    _modPanelItem  = null;
    _modPanelOpen  = false;
    ticket         = [];
    ticketSeq      = 0;
    modHistory     = [];
    modifierSession = { active: false, selectedItems: [], activePrefix: null, activePlacement: null, appliedMods: [], panelEl: null, hasPizza: false };
    comboFlow      = null;
    currentOrderId = null;
    isSending      = false;
    currentCheckNumber = null;
    currentCustomerName = null;
    _bottomBar     = null;
    _mainArea      = null;
    _gridEl        = null;
    _gridWrap      = null;
    _snakeStrip    = null;
    _snakeTabBar   = null;
    _expandedItems = {};
    snakeState     = { view:'cats', crumbs:[], catId:null, subId:null };
    favorites      = [];
    _activeSeat    = 1;
  },

  interrupts: {
    'seat-assign': {
      render: function(container, params) {
        var items = params.items || [];       // [ { id, name, mods } ]
        var seatNumbers = params.seatNumbers || [1]; // available seats [1, 2, 3, ...]
        var assignments = {};                 // { itemId: [seatNumber, ...] }

        container.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = [
          'display:flex;flex-direction:column;gap:10px;',
          'background:' + T.well + ';',
          'border:4px solid ' + T.green + ';clip-path:polygon(5px 0%,calc(100% - 5px) 0%,100% 5px,100% calc(100% - 5px),calc(100% - 5px) 100%,5px 100%,0% calc(100% - 5px),0% 5px);',
          'padding:20px 24px;min-width:500px;max-width:620px;',
          'max-height:520px;overflow:hidden;',
        ].join('');

        // Title
        var title = document.createElement('div');
        title.style.cssText = 'font-family:' + T.fh + ';font-size:' + T.fsB3 + ';color:' + T.green + ';letter-spacing:2px;text-align:center;margin-bottom:4px;text-transform:uppercase;';
        title.textContent = '// ASSIGN SEATS //';
        panel.appendChild(title);

        // Scrollable item list
        var list = document.createElement('div');
        list.className = 'co-scroll';
        list.style.cssText = 'flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;max-height:380px;';

        var seatBtnRefs = {}; // { itemId: [ { wrap, inner, seatNum } ] }

        for (var i = 0; i < items.length; i++) {
          (function(item) {
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:10px;';

            // Item label
            var label = document.createElement('div');
            label.style.cssText = [
              'flex:1;min-width:0;',
              'font-family:' + T.fb + ';font-size:' + T.fsB3 + ';color:' + T.text + ';',
              'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
            ].join('');
            var displayName = item.name;
            if (item.mods && item.mods.length > 0) {
              displayName += ' (' + item.mods.map(function(m) { return m.name; }).join(', ') + ')';
            }
            label.textContent = displayName;
            row.appendChild(label);

            // Seat tile buttons — styled to match check-overview
            var btnGroup = document.createElement('div');
            btnGroup.style.cssText = 'display:flex;gap:6px;';
            assignments[item.id] = [];
            seatBtnRefs[item.id] = [];

            for (var si = 0; si < seatNumbers.length; si++) {
              (function(sn) {
                var btn = buildStyledButton({ variant: 'dark' });
                var wrap = btn.wrap;
                var inner = btn.inner;

                wrap.style.clipPath = chamfer(6);
                wrap.style.width = '64px';
                wrap.style.height = '52px';
                wrap.style.minWidth = '0';

                inner.innerHTML = '';
                inner.style.flexDirection = 'column';
                inner.style.gap = '0';
                inner.style.padding = '4px 6px';
                inner.style.fontFamily = T.fh;
                inner.style.lineHeight = '1.2';

                var idEl = document.createElement('div');
                idEl.style.cssText = 'font-family:' + T.fh + ';font-size:' + T.fsB3 + ';letter-spacing:2px;text-transform:uppercase;';
                idEl.textContent = 'S' + sn;
                inner.appendChild(idEl);

                seatBtnRefs[item.id].push({ wrap: wrap, inner: inner, seatNum: sn });

                wrap.addEventListener('pointerup', function(e) {
                  e.stopPropagation();
                  var arr = assignments[item.id];
                  var idx = arr.indexOf(sn);
                  if (idx >= 0) {
                    arr.splice(idx, 1);
                  } else {
                    arr.push(sn);
                  }
                  // Update visuals for this item's seat buttons
                  var refs = seatBtnRefs[item.id];
                  var sel = assignments[item.id];
                  for (var ri = 0; ri < refs.length; ri++) {
                    var isOn = sel.indexOf(refs[ri].seatNum) >= 0;
                    refs[ri].wrap.style.background = isOn ? T.green : refs[ri].wrap._embV.bg;
                    refs[ri].wrap.style.boxShadow = isOn ? refs[ri].wrap._embV.shadowActive : refs[ri].wrap._embV.shadow;
                    refs[ri].inner.style.color = isOn ? T.well : refs[ri].wrap._embV.label;
                  }
                  updateConfirmState();
                });
                btnGroup.appendChild(wrap);
              })(seatNumbers[si]);
            }
            row.appendChild(btnGroup);
            list.appendChild(row);
          })(items[i]);
        }
        panel.appendChild(list);

        // Helper: refresh visual state for all seat buttons
        function refreshAllBtnVisuals() {
          for (var ii = 0; ii < items.length; ii++) {
            var refs = seatBtnRefs[items[ii].id];
            var sel = assignments[items[ii].id];
            for (var ri = 0; ri < refs.length; ri++) {
              var isOn = sel.indexOf(refs[ri].seatNum) >= 0;
              refs[ri].wrap.style.background = isOn ? T.green : refs[ri].wrap._embV.bg;
              refs[ri].wrap.style.boxShadow = isOn ? refs[ri].wrap._embV.shadowActive : refs[ri].wrap._embV.shadow;
              refs[ri].inner.style.color = isOn ? T.well : refs[ri].wrap._embV.label;
            }
          }
        }

        // Bottom bar: select-all + confirm + cancel
        var bottomBar = document.createElement('div');
        bottomBar.style.cssText = 'display:flex;gap:10px;margin-top:8px;';

        var cancelBtn = buildButton('CANCEL', {
          fill: T.card, color: T.text, fontSize: T.fsB2, height: 48,
          onTap: function() { params.onCancel(); },
        });
        cancelBtn.style.flex = '1';
        bottomBar.appendChild(cancelBtn);

        var selectAllBtn = buildButton('SELECT ALL', {
          fill: T.card, color: T.gold, fontSize: T.fsB2, height: 48,
          onTap: function() {
            for (var ai = 0; ai < items.length; ai++) {
              assignments[items[ai].id] = seatNumbers.slice();
            }
            refreshAllBtnVisuals();
            updateConfirmState();
          },
        });
        selectAllBtn.style.flex = '1';
        bottomBar.appendChild(selectAllBtn);

        var confirmBtn = buildButton('CONFIRM', {
          fill: T.card, color: T.dimText, fontSize: T.fsB2, height: 48,
          onTap: function() {
            // Only proceed if all items have at least one seat
            var ready = true;
            for (var k = 0; k < items.length; k++) {
              if (!assignments[items[k].id] || assignments[items[k].id].length === 0) { ready = false; break; }
            }
            if (!ready) return;
            params.onConfirm(assignments);
          },
        });
        confirmBtn.style.flex = '1';
        bottomBar.appendChild(confirmBtn);
        panel.appendChild(bottomBar);
        container.appendChild(panel);

        function updateConfirmState() {
          var allAssigned = true;
          for (var k = 0; k < items.length; k++) {
            if (!assignments[items[k].id] || assignments[items[k].id].length === 0) { allAssigned = false; break; }
          }
          confirmBtn.style.color = allAssigned ? T.green : T.dimText;
          confirmBtn.style.borderColor = allAssigned ? T.green : T.card;
        }
        updateConfirmState();

        // Tap scrim to cancel
        container.addEventListener('pointerup', function(e) {
          if (e.target === container) { params.onCancel(); }
        });
      },
      unmount: function() {},
    },
    'oe-name-input': {
      render: function(container, params) {
        showKeyboard({
          placeholder: 'Enter name',
          initialValue: params.currentName || '',
          maxLength: 40,
          onDone: function(val) {
            params.onConfirm(val.trim());
          },
          onDismiss: function() {
            params.onCancel();
          },
          dismissOnDone: true,
        });
      },
      unmount: function() { hideKeyboard(); },
    },
  },
});

// ── TOTALS HELPER ─────────────────────────────────
function computeTicketTotals() {
  var subtotal = 0;
  var counts = {};
  var summaryItems = [];  // item summary for ORDER RECAP
  ticket.forEach(function(inst) {
    var modTotal = inst.mods.reduce(function(s, m) { return s + m.price; }, 0);
    var lineTotal = inst.unitPrice + modTotal;
    counts[inst.name] = counts[inst.name] || { unitPrice: inst.unitPrice, qty: 0 };
    counts[inst.name].qty += 1;
    subtotal += lineTotal;
    summaryItems.push({
      name: inst.name,
      unitPrice: lineTotal,
      qty: 1,
      sent: inst.sent,
      mods: inst.mods.filter(function(m) { return m.charged || m.name; }),
    });
  });
  var t = computeTotals(subtotal);
  return { counts: counts, summaryItems: summaryItems, subtotal: t.subtotal, tax: t.tax, cardTotal: t.cardTotal, cashPrice: t.cashPrice };
}


// ── FAVORITES API ─────────────────────────────────
function loadFavorites() {
  var empId = sceneParams.employeeId;
  if (!empId) return;
  fetch(API + '/favorites?employee_id=' + empId)
    .then(function(r) { return r.ok ? r.json() : { item_ids: [] }; })
    .then(function(data) {
      favorites = data.item_ids || [];
      if (snakeState.view === 'personal') renderSnakeGrid();
    })
    .catch(function() { favorites = []; });
}

function saveFavorites() {
  var empId = sceneParams.employeeId;
  if (!empId) return;
  fetch(API + '/favorites', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ employee_id: empId, item_ids: favorites }),
  }).catch(function() {});
}

function toggleFavorite(itemId) {
  var idx = favorites.indexOf(itemId);
  if (idx >= 0) {
    favorites.splice(idx, 1);
    showToast('Removed from Personal', { bg: T.card, duration: 1200 });
  } else {
    favorites.push(itemId);
    showToast('★ Added to Personal', { bg: T.gold, duration: 1200 });
  }
  saveFavorites();
  renderSnakeGrid();
}

// ── SNAKE NAV TILE BUILDERS ────────────────────────

function _tileStyle(color, filled, extraCss) {
  return [
    'display:flex;flex-direction:column;justify-content:center;align-items:center;',
    'min-height:95px;padding:12px 10px;box-sizing:border-box;',
    'border-radius:10px;cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'border-left:4px solid ' + color + ';',
    'background:' + (filled ? color : T.card) + ';',
    'box-shadow:0 4px 0 ' + (filled ? hexToRgba(color, 0.55) : '#111') + ';',
    'transition:transform 80ms,box-shadow 80ms;',
    extraCss || '',
  ].join('');
}

function _applyPress(el, color, filled) {
  el.addEventListener('pointerdown', function() {
    el.style.transform = 'translateY(3px)';
    el.style.boxShadow = 'none';
  });
  el.addEventListener('pointerup', function() {
    el.style.transform = '';
    el.style.boxShadow = '0 4px 0 ' + (filled ? hexToRgba(color, 0.55) : '#111');
  });
  el.addEventListener('pointerleave', function() {
    el.style.transform = '';
    el.style.boxShadow = '0 4px 0 ' + (filled ? hexToRgba(color, 0.55) : '#111');
  });
}

function buildCrumbTile(crumb, isLast) {
  var el = document.createElement('div');
  el.style.cssText = _tileStyle(crumb.color, true);
  el.style.position = 'relative';

  if (!isLast) {
    var back = document.createElement('div');
    back.style.cssText = 'position:absolute;top:6px;right:8px;font-size:10px;color:rgba(0,0,0,0.4);font-family:' + T.fb + ';pointer-events:none;';
    back.textContent = '◂';
    el.appendChild(back);
  }

  var lbl = document.createElement('span');
  lbl.style.cssText = 'font-family:' + T.fh + ';font-weight:700;font-size:22px;color:' + (isLast ? '#fff' : 'rgba(0,0,0,0.75)') + ';letter-spacing:1px;text-align:center;pointer-events:none;';
  lbl.textContent = crumb.label;
  el.appendChild(lbl);

  _applyPress(el, crumb.color, true);
  return el;
}

function buildCatTile(cat) {
  var el = document.createElement('div');
  el.style.cssText = _tileStyle(cat.color, false);

  var lbl = document.createElement('span');
  lbl.style.cssText = 'font-family:' + T.fh + ';font-weight:700;font-size:24px;color:' + cat.color + ';letter-spacing:1.5px;text-align:center;pointer-events:none;';
  lbl.textContent = cat.label;
  el.appendChild(lbl);

  _applyPress(el, cat.color, false);
  return el;
}

function buildSubcatTile(sub, color) {
  var el = document.createElement('div');
  el.style.cssText = _tileStyle(color, false, 'opacity:0.9;');

  var lbl = document.createElement('span');
  lbl.style.cssText = 'font-family:' + T.fh + ';font-weight:700;font-size:21px;color:' + color + ';letter-spacing:1px;text-align:center;pointer-events:none;';
  lbl.textContent = sub.label;
  el.appendChild(lbl);

  _applyPress(el, color, false);
  return el;
}

function buildItemTile(item, catColor, isFav) {
  var el = document.createElement('div');
  el.style.cssText = _tileStyle(catColor, false, 'justify-content:space-between;align-items:flex-start;position:relative;');

  if (isFav) {
    var star = document.createElement('div');
    star.style.cssText = 'position:absolute;top:7px;right:8px;color:' + T.gold + ';font-size:14px;pointer-events:none;';
    star.textContent = '★';
    el.appendChild(star);
  }

  var name = document.createElement('span');
  name.style.cssText = 'font-family:' + T.fh + ';font-weight:700;font-size:14px;color:' + T.text + ';letter-spacing:0.3px;line-height:1.3;padding-right:' + (isFav ? '18px' : '0') + ';pointer-events:none;';
  name.textContent = item.label;
  el.appendChild(name);

  var price = document.createElement('span');
  price.style.cssText = 'font-family:' + T.fb + ';font-size:15px;color:' + T.gold + ';font-weight:700;margin-top:6px;pointer-events:none;';
  price.textContent = '$' + (typeof item.price === 'number' ? item.price.toFixed(2) : item.price);
  el.appendChild(price);

  _applyPress(el, catColor, false);
  return el;
}

// ── SNAKE NAV GRID RENDERER ────────────────────────

function renderSnakeGrid() {
  if (!_gridEl) return;
  _gridEl.innerHTML = '';

  var view   = snakeState.view;
  var crumbs = snakeState.crumbs;
  var catId  = snakeState.catId;
  var subId  = snakeState.subId;

  // ── PERSONAL TAB ──
  if (view === 'personal') {
    _renderPersonalGrid();
    return;
  }

  // ── Crumb tiles (inline, same grid) ──
  if (view !== 'cats') {
    crumbs.forEach(function(crumb, i) {
      var tile = buildCrumbTile(crumb, i === crumbs.length - 1);
      tile.addEventListener('pointerup', function() { _crumbTap(i); });
      _gridEl.appendChild(tile);
    });
  }

  // ── Category home ──
  if (view === 'cats') {
    MENU_DATA.forEach(function(cat) {
      var tile = buildCatTile(cat);
      tile.addEventListener('pointerup', function() { _selectCat(cat); });
      _gridEl.appendChild(tile);
    });
    return;
  }

  // ── Subcategory ──
  var menuCat = MENU_DATA.find(function(c) { return c.id === catId; });
  if (!menuCat) return;
  var subcats = menuCat.subcats;

  if (view === 'subcats' && subcats && subcats.length > 1) {
    subcats.forEach(function(sub) {
      var tile = buildSubcatTile(sub, menuCat.color);
      tile.addEventListener('pointerup', function() { _selectSubcat(sub, menuCat); });
      _gridEl.appendChild(tile);
    });
    return;
  }

  // ── Items ──
  var itemList = [];
  if (subId) {
    var sub = (subcats || []).find(function(s) { return s.id === subId; });
    if (sub) itemList = sub.items || [];
  } else {
    (subcats || []).forEach(function(s) { itemList = itemList.concat(s.items || []); });
  }

  itemList.forEach(function(item) {
    var isFav = favorites.indexOf(item.id) >= 0;
    var tile = buildItemTile(item, menuCat.color, isFav);
    _bindItemTile(tile, item, menuCat);
    _gridEl.appendChild(tile);
  });
}

function _bindItemTile(tile, item, menuCat) {
  var longPressTimer = null;
  var didLong = false;

  tile.addEventListener('pointerdown', function() {
    didLong = false;
    longPressTimer = setTimeout(function() {
      didLong = true;
      if (item.id) toggleFavorite(item.id);
    }, 600);
  });

  tile.addEventListener('pointerup', function() {
    clearTimeout(longPressTimer);
    if (!didLong) handleItemSelect(item);
  });

  tile.addEventListener('pointerleave', function() {
    clearTimeout(longPressTimer);
  });
}

function _renderPersonalGrid() {
  if (favorites.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = [
      'grid-column:1/-1;display:flex;flex-direction:column;',
      'align-items:center;justify-content:center;height:200px;gap:10px;',
      'font-family:' + T.fh + ';font-size:13px;color:' + T.mutedText + ';text-align:center;',
    ].join('');
    empty.innerHTML = '<div style="font-size:35px;color:' + T.gold + ';opacity:0.5;pointer-events:none;">★</div><span style="pointer-events:none;">Hold any item to add it here</span>';
    _gridEl.appendChild(empty);
    return;
  }

  // Group by category, preserving MENU_DATA order
  MENU_DATA.forEach(function(cat) {
    var catItems = [];
    favorites.forEach(function(favId) {
      (cat.subcats || []).forEach(function(sub) {
        (sub.items || []).forEach(function(item) {
          if (item.id === favId) catItems.push(item);
        });
      });
    });
    if (catItems.length === 0) return;

    // Category header spanning full grid
    var hdr = document.createElement('div');
    hdr.style.cssText = [
      'grid-column:1/-1;display:flex;align-items:center;gap:8px;',
      'margin-top:4px;margin-bottom:2px;',
    ].join('');
    var hdrLabel = document.createElement('span');
    hdrLabel.style.cssText = 'font-family:' + T.fh + ';font-weight:700;font-size:10px;color:' + cat.color + ';letter-spacing:2px;pointer-events:none;';
    hdrLabel.textContent = cat.label;
    var hdrLine = document.createElement('div');
    hdrLine.style.cssText = 'height:1px;flex:1;background:linear-gradient(to right,' + cat.color + '44,transparent);pointer-events:none;';
    hdr.appendChild(hdrLabel);
    hdr.appendChild(hdrLine);
    _gridEl.appendChild(hdr);

    catItems.forEach(function(item) {
      var tile = buildItemTile(item, cat.color, true);
      _bindItemTile(tile, item, cat);
      _gridEl.appendChild(tile);
    });
  });
}

// ── SNAKE NAV ACTIONS ──────────────────────────────

function _selectCat(cat) {
  var hasSubs = cat.subcats && cat.subcats.length > 1;
  snakeState.crumbs = [{ id: cat.id, label: cat.label, color: cat.color }];
  snakeState.catId  = cat.id;
  snakeState.subId  = null;
  snakeState.view   = hasSubs ? 'subcats' : 'items';
  renderSnakeGrid();
  _refreshSnakeTabBar();
}

function _selectSubcat(sub, menuCat) {
  snakeState.crumbs.push({ id: sub.id, label: sub.label, color: menuCat.color });
  snakeState.subId = sub.id;
  snakeState.view  = 'items';
  renderSnakeGrid();
}

function _crumbTap(idx) {
  if (idx === 0 && snakeState.crumbs.length === 1) {
    // Back to category home
    snakeState.view   = 'cats';
    snakeState.crumbs = [];
    snakeState.catId  = null;
    snakeState.subId  = null;
  } else if (idx === 0) {
    // Back to subcats
    snakeState.crumbs = snakeState.crumbs.slice(0, 1);
    snakeState.subId  = null;
    snakeState.view   = 'subcats';
  }
  renderSnakeGrid();
  _refreshSnakeTabBar();
}

function _refreshSnakeTabBar() {
  if (!_snakeTabBar) return;
  var homeBtn = _snakeTabBar._homeBtn;
  var personalBtn = _snakeTabBar._personalBtn;
  if (!homeBtn || !personalBtn) return;

  var isPersonal = snakeState.view === 'personal';
  var isDrilling = !isPersonal && snakeState.view !== 'cats';

  // Personal tab active state
  personalBtn.style.borderBottom = isPersonal ? '2px solid ' + T.gold : '2px solid transparent';
  personalBtn.style.color = isPersonal ? T.gold : T.mutedText;

  // Show/hide ⌂ CATEGORIES back button
  homeBtn.style.display = isDrilling ? '' : 'none';
}

// ── MAIN AREA ─────────────────────────────────────
function buildMain(parentEl, params) {
  var main = document.createElement('div');
  main.style.cssText = 'flex:1;display:flex;flex-direction:column;min-height:0;';
  _mainArea = main;

  // ── Tab bar (★ PERSONAL + ⌂ CATEGORIES) ──────────
  var tabBar = document.createElement('div');
  tabBar.style.cssText = [
    'display:flex;background:' + T.well + ';',
    'border-bottom:1px solid rgba(255,255,255,0.06);',
    'padding:4px 8px 0;flex-shrink:0;',
  ].join('');
  _snakeTabBar = tabBar;

  var personalBtn = document.createElement('div');
  personalBtn.style.cssText = [
    'padding:6px 14px;cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'font-family:' + T.fh + ';font-weight:700;font-size:11px;letter-spacing:1px;',
    'color:' + T.mutedText + ';border-bottom:2px solid transparent;',
    'transition:color 120ms;',
  ].join('');
  personalBtn.textContent = '★ PERSONAL';
  personalBtn.addEventListener('pointerup', function() {
    snakeState.view   = 'personal';
    snakeState.crumbs = [];
    snakeState.catId  = null;
    snakeState.subId  = null;
    renderSnakeGrid();
    _refreshSnakeTabBar();
  });
  tabBar._personalBtn = personalBtn;

  var homeBtn = document.createElement('div');
  homeBtn.style.cssText = [
    'padding:6px 12px;cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'font-family:' + T.fh + ';font-size:11px;letter-spacing:1px;',
    'color:' + T.mutedText + ';border-bottom:2px solid transparent;',
    'display:none;opacity:0.6;',
  ].join('');
  homeBtn.textContent = '⌂ CATEGORIES';
  homeBtn.addEventListener('pointerup', function() {
    snakeState.view   = 'cats';
    snakeState.crumbs = [];
    snakeState.catId  = null;
    snakeState.subId  = null;
    renderSnakeGrid();
    _refreshSnakeTabBar();
  });
  tabBar._homeBtn = homeBtn;

  tabBar.appendChild(personalBtn);
  tabBar.appendChild(homeBtn);
  main.appendChild(tabBar);

  // ── Collapsible grid wrapper ──────────────────────
  var gridWrap = document.createElement('div');
  gridWrap.style.cssText = 'flex:1;overflow-y:auto;';
  _gridWrap = gridWrap;

  var grid = document.createElement('div');
  grid.style.cssText = [
    'display:grid;',
    'grid-template-columns:repeat(auto-fill,minmax(120px,1fr));',
    'gap:6px;padding:10px;',
  ].join('');
  _gridEl = grid;
  gridWrap.appendChild(grid);
  main.appendChild(gridWrap);

  // ── Snake strip (crumbs only, shown when mod panel open) ──
  var snakeStrip = document.createElement('div');
  snakeStrip.style.cssText = [
    'display:none;flex-wrap:wrap;gap:6px;align-items:center;',
    'padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06);',
    'flex-shrink:0;position:relative;z-index:10;',
  ].join('');
  _snakeStrip = snakeStrip;
  main.appendChild(snakeStrip);

  // Note: ModifierPanel mounts directly onto _mainArea as an absolute overlay
  // (position:relative is set on main to contain it)

  // ── Bottom action bar ─────────────────────────────
  _bottomBar = document.createElement('div');
  _bottomBar.style.cssText = 'display:grid;grid-template-columns:repeat(5,1fr);grid-auto-rows:auto;gap:4px;flex-shrink:0;margin-top:4px;';
  main.appendChild(_bottomBar);

  // Load menu data + favorites, then render grid
  requestAnimationFrame(function() {
    if (!_menuFetched) {
      fetchMenuFromAPI().then(function() { renderSnakeGrid(); });
    } else {
      renderSnakeGrid();
    }
    loadFavorites();
  });

  return main;
}



// ── SEAT ASSIGNMENT AT COMMIT TIME ───────────────
function assignSeatsIfNeeded(callback) {
  var unsent = ticket.filter(function(i) { return !i.sent; });
  if (unsent.length === 0) { callback(); return; }

  var seats = (sceneParams.seatNumbers && sceneParams.seatNumbers.length > 0)
    ? sceneParams.seatNumbers : [1];

  // 1 seat → auto-assign all pending items
  if (seats.length === 1) {
    for (var i = 0; i < unsent.length; i++) unsent[i].seat_number = seats[0];
    callback();
    return;
  }

  // If exactly one seat is selected in check-overview, auto-assign to it
  var selSeats = sceneParams.selectedSeatNumbers;
  if (selSeats && selSeats.length === 1) {
    for (var i = 0; i < unsent.length; i++) unsent[i].seat_number = selSeats[0];
    callback();
    return;
  }

  // 2+ seats → open seat assignment interrupt
  var itemsForAssign = unsent.map(function(inst) {
    return { id: inst.id, name: inst.name, mods: inst.mods };
  });

  SceneManager.interrupt('seat-assign', {
    params: { items: itemsForAssign, seatNumbers: seats },
    onConfirm: function(assignments) {
      // Apply assignments: { itemId: [seatNumber, ...] }
      // Items assigned to multiple seats get duplicated (one per extra seat)
      var dupes = [];
      for (var j = 0; j < unsent.length; j++) {
        var seatList = assignments[unsent[j].id];
        if (!seatList || seatList.length === 0) continue;
        // First seat goes on the original item
        unsent[j].seat_number = seatList[0];
        // Additional seats → duplicate the item
        for (var s = 1; s < seatList.length; s++) {
          var clone = Object.assign({}, unsent[j]);
          clone.id = unsent[j].id + '_s' + seatList[s];
          clone.idemKey = _idemKey();
          clone.seat_number = seatList[s];
          clone.sent = false;
          clone.mods = (unsent[j].mods || []).slice();
          dupes.push(clone);
        }
      }
      // Add duplicated items to the ticket
      for (var d = 0; d < dupes.length; d++) ticket.push(dupes[d]);
      callback();
    },
    onCancel: function() { /* do nothing — stay on order scene */ },
  });
}

// ── BOTTOM BAR — Three States ────────────────────
function rebuildBottomBar() {
  if (!_bottomBar) return;
  _bottomBar.innerHTML = '';
  _bottomBar.style.cssText = 'display:grid;grid-template-columns:repeat(5,1fr);grid-auto-rows:auto;gap:4px;flex-shrink:0;margin-top:4px;';

  var hasUnsent = ticket.some(function(i) { return !i.sent; });

  // ── Active modifier session: CANCEL / UNDO / DONE ──
  if (modifierSession.active) {
    var cancelBtn = buildButton('CANCEL', { fill: T.card, color: T.verm, fontSize: '26px', fontFamily: T.fh,
      onTap: function() { cancelSession(); },
    });
    var undoBtn = buildButton('UNDO', { fill: T.card, color: T.gold, fontSize: '26px', fontFamily: T.fh,
      onTap: function() {
        if (modifierSession.appliedMods.length === 0) return;
        var last = modifierSession.appliedMods.pop();
        last.modRefs.forEach(function(ref) {
          var idx = ref.inst.mods.indexOf(ref.mod);
          if (idx !== -1) ref.inst.mods.splice(idx, 1);
        });
        renderTicket();
        refreshModifierPanel();
      },
    });
    var doneBtn = buildButton('DONE', { fill: T.card, color: T.greenWarm, fontSize: '26px', fontFamily: T.fh,
      onTap: function() { finalizeSession(); },
    });
    cancelBtn.style.gridColumn = '1 / 2'; cancelBtn.style.gridRow = '1'; cancelBtn.style.height = '100%';
    undoBtn.style.gridColumn = '2 / 4'; undoBtn.style.gridRow = '1'; undoBtn.style.height = '100%';
    doneBtn.style.gridColumn = '4 / 6'; doneBtn.style.gridRow = '1'; doneBtn.style.height = '100%';
    _bottomBar.appendChild(cancelBtn);
    _bottomBar.appendChild(undoBtn);
    _bottomBar.appendChild(doneBtn);
    return;
  }

  // ── Items selected (not in session): DESELECT / MODIFY / SEND ──
  var hasSelected = modifierSession.selectedItems.length > 0;
  if (hasSelected) {
    var deselectBtn = buildButton('DESELECT', { fill: T.card, color: T.dimText, fontSize: '22px', fontFamily: T.fh,
      onTap: function() { clearModifierSelection(); },
    });
    var modifyBtn = buildButton('MODIFY', { fill: T.card, color: T.gold, fontSize: '26px', fontFamily: T.fh,
      onTap: function() { openModifierSession(); },
    });
    modifyBtn.style.outline = '3px solid ' + T.gold;
    modifyBtn.style.outlineOffset = '-1px';
    var sendBtn2 = buildButton('SEND', { fill: T.card, color: T.green, fontSize: '26px', fontFamily: T.fh,
      onTap: function() {
        clearModifierSelection();
        if (!hasUnsent) { handleClose(); return; }
        assignSeatsIfNeeded(async function() {
          try { await handleSend(); } catch (e) { return; }
          handleClose();
        });
      },
    });
    deselectBtn.style.gridColumn = '1 / 2'; deselectBtn.style.gridRow = '1'; deselectBtn.style.height = '100%';
    modifyBtn.style.gridColumn = '2 / 4'; modifyBtn.style.gridRow = '1'; modifyBtn.style.height = '100%';
    sendBtn2.style.gridColumn = '4 / 6'; sendBtn2.style.gridRow = '1'; sendBtn2.style.height = '100%';
    _bottomBar.appendChild(deselectBtn);
    _bottomBar.appendChild(modifyBtn);
    _bottomBar.appendChild(sendBtn2);
    return;
  }

  // ── Default: SAVE / SEND ──
  // Switch bottomBar to flex centered layout
  _bottomBar.style.cssText = 'display:flex;gap:12px;justify-content:center;align-items:center;flex-shrink:0;margin-top:6px;padding:0 4px;';

  var saveColor = hasUnsent ? T.greenWarm : T.mutedText;
  var sendColor = hasUnsent ? T.gold      : T.mutedText;

  var finalizeBtn = buildPillButton({ label: 'SAVE', color: saveColor, textColor: T.well });
  finalizeBtn.style.flex        = '1';
  finalizeBtn.style.height      = '58px';
  finalizeBtn.style.fontSize    = '22px';
  finalizeBtn.style.touchAction = 'manipulation';
  finalizeBtn.addEventListener('pointerenter', function() {
    if (hasUnsent) finalizeBtn.style.filter = 'brightness(1.15)';
  });
  finalizeBtn.addEventListener('pointerleave', function() {
    finalizeBtn.style.filter = '';
  });
  finalizeBtn.addEventListener('pointerup', function() {
    finalizeBtn.style.filter = '';
    if (!hasUnsent) { handleClose(); return; }
    assignSeatsIfNeeded(async function() {
      try { await handleSaveOnly(); } catch (e) { return; }
      handleClose();
    });
  });

  var sendBtn = buildPillButton({ label: 'SEND', color: sendColor, textColor: T.well });
  sendBtn.style.flex        = '1';
  sendBtn.style.height      = '58px';
  sendBtn.style.fontSize    = '22px';
  sendBtn.style.touchAction = 'manipulation';
  sendBtn.addEventListener('pointerenter', function() {
    if (hasUnsent) sendBtn.style.filter = 'brightness(1.15)';
  });
  sendBtn.addEventListener('pointerleave', function() {
    sendBtn.style.filter = '';
  });
  sendBtn.addEventListener('pointerup', function() {
    sendBtn.style.filter = '';
    if (!hasUnsent) { handleClose(); return; }
    assignSeatsIfNeeded(async function() {
      try { await handleSend(); } catch (e) { return; }
      handleClose();
    });
  });

  _bottomBar.appendChild(finalizeBtn);
  _bottomBar.appendChild(sendBtn);
}

function clearModifierSelection() {
  modifierSession.selectedItems = [];
  ticket.forEach(function(i) { i.selected = false; });
  renderTicket();
  rebuildBottomBar();
}

// ── MODIFIER SESSION ─────────────────────────────
function openModifierSession() {
  if (modifierSession.active) return;
  // Filter to unsent items only
  var ids = modifierSession.selectedItems;
  var items = ticket.filter(function(i) { return ids.indexOf(i.id) !== -1 && !i.sent; });
  if (items.length === 0) {
    showToast('No unsent items selected', { bg: T.dimText, duration: 2000 });
    return;
  }
  modifierSession.active = true;
  modifierSession.selectedItems = items.map(function(i) { return i.id; });
  modifierSession.activePrefix = null;
  modifierSession.activePlacement = null;
  modifierSession.appliedMods = [];

  // Detect pizza items for placement
  var catIds = [];
  items.forEach(function(i) {
    if (i.category && catIds.indexOf(i.category) === -1) catIds.push(i.category);
  });
  modifierSession.hasPizza = hasPizzaCategory(catIds);
  modifierSession._catIds = catIds;

  // Collapse snake grid, show modifier panel
  if (_gridWrap) _gridWrap.style.display = 'none';

  var panel = buildModifierPanel(catIds);
  modifierSession.panelEl = panel;
  if (_mainArea && _bottomBar) {
    _mainArea.insertBefore(panel, _bottomBar);
  }

  // Init HexNav after panel is in the DOM so it gets correct dimensions
  if (panel._initHexNav) panel._initHexNav();

  rebuildBottomBar();
  renderTicket();
}

function buildPlacementBar() {
  var plColor = MOD_COLORS.pizza.color;
  var plText  = MOD_COLORS.pizza.textColor;
  var dimText = T.mutedText;

  var styled = buildStyledButton(T.card);
  styled.wrap.style.flexShrink = '0';
  styled.inner.style.height = '38px';
  styled.inner.style.display = 'flex';
  styled.inner.style.alignItems = 'stretch';
  styled.inner.style.justifyContent = 'stretch';
  styled.inner.style.padding = '0';

  var segments = {};
  var order = ['left', 'whole', 'right'];

  order.forEach(function(id, i) {
    var pl = PIZZA_PLACEMENTS.find(function(p) { return p.id === id; });
    if (!pl) return;
    var isActive = modifierSession.activePlacement === id;

    if (i > 0) {
      var div = document.createElement('div');
      div.style.cssText = 'width:2px;background:' + T.border + ';flex-shrink:0;align-self:stretch;';
      styled.inner.appendChild(div);
    }

    var seg = document.createElement('div');
    seg.style.cssText = [
      'flex:' + (id === 'whole' ? '2' : '1') + ';',
      'display:flex;align-items:center;justify-content:center;',
      'font-family:' + T.fh + ';font-size:22px;',
      'background:' + (isActive ? plColor : 'transparent') + ';',
      'color:' + (isActive ? plText : dimText) + ';',
      'cursor:pointer;transition:background 80ms,color 80ms;',
    ].join('');
    seg.textContent = pl.label;

    seg.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      modifierSession.activePlacement = id;
      refreshPlacementBar();
    });

    styled.inner.appendChild(seg);
    segments[id] = seg;
  });

  return { wrap: styled.wrap, segments: segments, plColor: plColor, plText: plText, dimText: dimText };
}

function refreshPlacementBar() {
  var panel = modifierSession.panelEl;
  if (!panel || !panel._placeBar) return;
  var bar = panel._placeBar;

  ['left', 'whole', 'right'].forEach(function(id) {
    var seg = bar.segments[id];
    if (!seg) return;
    var isActive = modifierSession.activePlacement === id;
    seg.style.background = isActive ? bar.plColor : 'transparent';
    seg.style.color = isActive ? bar.plText : bar.dimText;
  });
}

function buildModifierPanel(catIds) {
  var panel = document.createElement('div');
  panel.style.cssText = [
    'flex:1;display:flex;flex-direction:column;gap:4px;',
    'background:' + T.card + ';',
    'border:7px solid ' + T.gold + ';',
    'padding:6px;overflow:hidden;',
    'margin-bottom:0;padding-bottom:' + OVERLAP + 'px;',
  ].join('');

  // ── PREFIX ROW ──
  var prefixRow = document.createElement('div');
  prefixRow.style.cssText = 'display:flex;gap:6px;flex-shrink:0;';
  panel._prefixBtns = {};

  UNI_PREFIXES.forEach(function(p) {
    var isActive = modifierSession.activePrefix === p.id;
    var pDef = PREFIXES.find(function(x) { return x.id === p.id; }) || {};
    var pColor = pDef.color || T.card;
    var pTextColor = pDef.textColor || T.text;

    var btn = buildButton(p.label, {
      fill: isActive ? pColor : T.card,
      color: isActive ? pTextColor : pColor,
      fontSize: '26px',
      fontFamily: T.fh,
    });
    btn.style.flex = '1';
    btn.style.height = '44px';

    btn.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      modifierSession.activePrefix = (modifierSession.activePrefix === p.id) ? null : p.id;
      refreshModifierPanel();
    });

    panel._prefixBtns[p.id] = btn;
    prefixRow.appendChild(btn);
  });
  panel.appendChild(prefixRow);

  // ── PIZZA PLACEMENT CARD — wide chamfered bar with 3 segments ──
  if (modifierSession.hasPizza) {
    if (!modifierSession.activePlacement) modifierSession.activePlacement = 'whole';
    var placeBar = buildPlacementBar();
    panel._placeBar = placeBar;
    panel.appendChild(placeBar.wrap);
  }

  // ── MODIFIER BUTTON GRID (replaces HexNav) ──
  var modData = getModHexData(catIds || []);
  panel._modData = modData;

  // Category tab bar
  var catTabBar = document.createElement('div');
  catTabBar.style.cssText = 'display:flex;gap:4px;flex-shrink:0;';
  panel._catTabBtns = {};
  var activeCatId = modData.length > 0 ? modData[0].id : null;
  panel._activeCatId = activeCatId;

  modData.forEach(function(cat) {
    var isActive = cat.id === activeCatId;
    var catBtn = document.createElement('div');
    catBtn.style.cssText = [
      'flex:1;height:34px;display:flex;align-items:center;justify-content:center;',
      'font-family:' + T.fh + ';font-size:20px;cursor:pointer;',
      'border:2px solid ' + cat.color + ';',
      'background:' + (isActive ? cat.color : T.card) + ';',
      'color:' + (isActive ? cat.textColor : cat.color) + ';',
      'transition:background 80ms,color 80ms;',
    ].join('');
    catBtn.textContent = cat.label;
    catBtn.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      panel._activeCatId = cat.id;
      refreshModCatTabs(panel);
      renderModButtonGrid(panel);
    });
    panel._catTabBtns[cat.id] = catBtn;
    catTabBar.appendChild(catBtn);
  });
  panel.appendChild(catTabBar);

  // Scrollable button grid
  var gridWrap = document.createElement('div');
  gridWrap.style.cssText = 'flex:1;overflow-y:auto;overflow-x:hidden;scrollbar-width:none;-ms-overflow-style:none;';
  var grid = document.createElement('div');
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:4px;';
  gridWrap.appendChild(grid);
  panel._modGrid = grid;
  panel.appendChild(gridWrap);

  // Init: no deferred HexNav needed
  panel._initHexNav = function() {
    renderModButtonGrid(panel);
  };

  // ── APPLIED MODS LOG ──
  var logWrap = document.createElement('div');
  logWrap.style.cssText = [
    'max-height:100px;overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none;',
    'background:' + T.well + ';padding:4px 8px;flex-shrink:0;',
  ].join('');
  applySunkenStyle(logWrap);
  panel._log = logWrap;
  panel.appendChild(logWrap);

  // Init log
  renderAppliedModsLog(panel);

  return panel;
}

function applyModifier(mod) {
  if (!modifierSession.activePrefix) {
    showToast('Select a prefix first', { bg: T.dimText, duration: 2000 });
    return;
  }
  var prefix = UNI_PREFIXES.find(function(p) { return p.id === modifierSession.activePrefix; });
  if (!prefix) return;

  var placement = modifierSession.hasPizza ? (modifierSession.activePlacement || 'whole') : null;
  var modName = prefix.label + ' ' + mod.label;
  var modRefs = [];

  // Determine price based on prefix: ADD/EXTRA use modifier price, others are free
  var chargesPrice = prefix.id === 'add' || prefix.id === 'extra';
  var modPrice = chargesPrice ? (mod.price || 0) : 0;
  var charged = chargesPrice && modPrice > 0;

  modifierSession.selectedItems.forEach(function(id) {
    var inst = ticket.find(function(i) { return i.id === id; });
    if (!inst) return;
    var isPizza = inst.category === 'pizza';
    var halfSide = null;
    if (isPizza && placement === 'left') halfSide = 'Left';
    else if (isPizza && placement === 'right') halfSide = 'Right';

    var modObj = { name: modName, price: modPrice, charged: charged, prefix: halfSide };
    inst.mods.push(modObj);
    modRefs.push({ inst: inst, mod: modObj });
  });

  var logLabel = modName + (charged ? ' +$' + modPrice.toFixed(2) : '');
  modifierSession.appliedMods.push({
    prefixId: prefix.id,
    prefixLabel: prefix.label,
    modId: mod.id || mod.label,
    modLabel: mod.label,
    placement: placement,
    affectedItemIds: modifierSession.selectedItems.slice(),
    modRefs: modRefs,
    logLabel: logLabel,
  });

  renderTicket();
  refreshModifierPanel();
}

function refreshModifierPanel() {
  var panel = modifierSession.panelEl;
  if (!panel) return;

  // Refresh prefix button states
  UNI_PREFIXES.forEach(function(p) {
    var btn = panel._prefixBtns[p.id];
    if (!btn) return;
    var isActive = modifierSession.activePrefix === p.id;
    var pDef = PREFIXES.find(function(x) { return x.id === p.id; }) || {};
    var pColor = pDef.color || T.card;
    var pTextColor = pDef.textColor || T.text;
    var inner = btn.firstElementChild || btn.querySelector('div');
    if (inner) {
      inner.style.background = isActive ? pColor : T.card;
      inner.style.color = isActive ? pTextColor : pColor;
    }
  });

  // Refresh placement bar (pizza)
  refreshPlacementBar();

  // Refresh applied mods log
  renderAppliedModsLog(panel);
}

function refreshModCatTabs(panel) {
  if (!panel || !panel._catTabBtns || !panel._modData) return;
  panel._modData.forEach(function(cat) {
    var btn = panel._catTabBtns[cat.id];
    if (!btn) return;
    var isActive = panel._activeCatId === cat.id;
    btn.style.background = isActive ? cat.color : T.card;
    btn.style.color = isActive ? cat.textColor : cat.color;
  });
}

function renderModButtonGrid(panel) {
  var grid = panel._modGrid;
  if (!grid) return;
  grid.innerHTML = '';

  var activeCat = null;
  (panel._modData || []).forEach(function(cat) {
    if (cat.id === panel._activeCatId) activeCat = cat;
  });
  if (!activeCat) return;

  var catColor = activeCat.color;
  var catText = activeCat.textColor;

  // Flatten all items from all subcats
  (activeCat.subcats || []).forEach(function(sub) {
    (sub.items || []).forEach(function(item) {
      var btn = document.createElement('div');
      btn.style.cssText = [
        'display:flex;align-items:center;justify-content:center;',
        'height:52px;cursor:pointer;',
        'font-family:' + T.fb + ';font-size:22px;font-weight:bold;',
        'text-align:center;word-break:break-word;',
        'background:' + T.card + ';',
        'color:' + catText + ';',
        'border:2px solid ' + catColor + ';',
        'transition:background 80ms;',
      ].join('');
      btn.textContent = item.label;

      btn.addEventListener('pointerdown', function() {
        btn.style.background = catColor;
        btn.style.color = activeCat.textColor === catText ? T.text : catText;
      });
      btn.addEventListener('pointerup', function() {
        btn.style.background = T.card;
        btn.style.color = catText;
        applyModifier(item);
      });
      btn.addEventListener('pointerleave', function() {
        btn.style.background = T.card;
        btn.style.color = catText;
      });

      grid.appendChild(btn);
    });
  });
}

function renderAppliedModsLog(panel) {
  var log = panel._log;
  if (!log) return;
  log.innerHTML = '';

  if (modifierSession.appliedMods.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'font-family:' + T.fb + ';font-size:30px;color:' + T.mutedText + ';text-align:center;padding:4px 0;';
    empty.textContent = 'No modifiers applied';
    log.appendChild(empty);
    return;
  }

  modifierSession.appliedMods.forEach(function(entry, idx) {
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;font-family:' + T.fb + ';font-size:30px;color:' + T.gold + ';line-height:1.2;';
    var label = document.createElement('span');
    label.textContent = entry.logLabel || (entry.prefixLabel + ' \u2192 ' + entry.modLabel);
    row.appendChild(label);
    var removeBtn = document.createElement('span');
    removeBtn.textContent = '\u2715';
    removeBtn.style.cssText = 'color:' + T.verm + ';cursor:pointer;padding:0 4px;font-size:28px;flex-shrink:0;';
    removeBtn.addEventListener('pointerup', (function(i) {
      return function(e) {
        e.stopPropagation();
        var removed = modifierSession.appliedMods.splice(i, 1)[0];
        removed.modRefs.forEach(function(ref) {
          var mIdx = ref.inst.mods.indexOf(ref.mod);
          if (mIdx !== -1) ref.inst.mods.splice(mIdx, 1);
        });
        renderTicket();
        refreshModifierPanel();
      };
    })(idx));
    row.appendChild(removeBtn);
    log.appendChild(row);
  });

  // RESET button to clear all applied modifiers
  if (modifierSession.appliedMods.length > 0) {
    var resetPair = buildStyledButton({ label: 'RESET ALL', variant: 'vermillion', size: 'sm', onClick: function() {
      cancelSession();
    } });
    resetPair.wrap.style.marginTop = '6px';
    resetPair.wrap.style.width = '100%';
    log.appendChild(resetPair.wrap);
  }

  log.scrollTop = log.scrollHeight;
}

function undoLastMod() {
  if (modifierSession.appliedMods.length === 0) return;
  var last = modifierSession.appliedMods.pop();

  // Remove the mod from all affected items
  last.modRefs.forEach(function(ref) {
    var idx = ref.inst.mods.indexOf(ref.mod);
    if (idx !== -1) ref.inst.mods.splice(idx, 1);
  });

  // Reset prefix if no more mods
  if (modifierSession.appliedMods.length === 0) {
    modifierSession.activePrefix = null;
  }

  renderTicket();
  refreshModifierPanel();
}

function cancelSession() {
  // Roll back ALL mods in reverse order
  while (modifierSession.appliedMods.length > 0) {
    var entry = modifierSession.appliedMods.pop();
    entry.modRefs.forEach(function(ref) {
      var idx = ref.inst.mods.indexOf(ref.mod);
      if (idx !== -1) ref.inst.mods.splice(idx, 1);
    });
  }
  // Close modifier panel if open so _modPanelItem doesn't leak
  if (_modPanel) closeModifierPanel();
  endModifierSession();
}

function finalizeSession() {
  // Mods are already on ticket items — just close the session
  endModifierSession();
}

function endModifierSession() {
  modifierSession.active = false;
  modifierSession.activePrefix = null;
  modifierSession.activePlacement = null;
  modifierSession.appliedMods = [];
  modifierSession.hasPizza = false;

  // Remove panel
  if (modifierSession.panelEl && modifierSession.panelEl.parentNode) {
    modifierSession.panelEl.parentNode.removeChild(modifierSession.panelEl);
  }
  modifierSession.panelEl = null;

  // Clear selection
  modifierSession.selectedItems = [];
  ticket.forEach(function(i) { i.selected = false; });

  // Restore grid
  if (_gridWrap) _gridWrap.style.display = '';

  renderTicket();
  rebuildBottomBar();
}


// ── KIND MODIFIER PANEL — inline replacement for modifier-panel.js ────────
// Builds our Vz2.0 modifier UI directly. Returns { destroy() }.

var _PREFIX_DEFS = [
  { id:'ADD',     label:'ADD',     color: null },  // T.greenWarm
  { id:'EXTRA',   label:'EXTRA',   color: null },  // T.elec
  { id:'NO',      label:'NO',      color: null },  // T.verm
  { id:'ON SIDE', label:'ON SIDE', color: null },  // T.gold
  { id:'LITE',    label:'LITE',    color: null },  // T.gold
];

var _PLACE_DEFS = [
  { id:'LEFT',  label:'½ LEFT'  },
  { id:'WHOLE', label:'WHOLE'   },
  { id:'RIGHT', label:'RIGHT ½' },
];

function _prefixColor(id) {
  if (id === 'ADD')     return T.greenWarm;
  if (id === 'EXTRA')   return T.elec;
  if (id === 'NO')      return T.verm;
  if (id === 'ON SIDE') return T.gold;
  if (id === 'LITE')    return T.gold;
  return T.card;
}

function buildKindModPanel(container, item, modConfig, catColor, enablePlacement, callbacks) {
  modConfig = modConfig || {};
  var includedItems   = modConfig.includedItems   || [];
  var mandatoryGroups = modConfig.mandatoryGroups || [];
  var optionalGroups  = modConfig.optionalGroups  || [];
  var isPizza = !!enablePlacement;

  // ── State ──────────────────────────────────────────
  var inclState  = {};   // mod.id  → 'NO'|'ON SIDE'
  var optState   = {};   // optId   → { prefix, placement }
  var mandState  = {};   // groupKey → { key, label, price }
  var activePrefix = 'ADD';
  var activePlacement = 'WHOLE';

  // ── Root overlay ────────────────────────────────────
  var ov = document.createElement('div');
  ov.style.cssText = [
    'flex:1;min-height:0;',
    'background:' + T.bg + ';',
    'display:flex;flex-direction:column;',
    'overflow:hidden;',
  ].join('');

  // strip is rendered by openModifierPanel as a separate _mainArea flex child
  var itemPx = typeof item.price === 'number' ? item.price : 0;

  // ── Scrollable content ──────────────────────────────
  var scroll = document.createElement('div');
  scroll.style.cssText = 'flex:1;overflow-y:auto;padding:44px 14px 10px;';
  ov.appendChild(scroll);

  // ── DONE button ─────────────────────────────────────
  var doneWrap = document.createElement('div');
  doneWrap.style.cssText = 'flex-shrink:0;padding:8px 14px 10px;';
  var doneBtn = buildPillButton({ label: 'DONE — ADD TO CHECK', color: T.green, textColor: T.well });
  doneBtn.style.width = '100%';
  doneBtn.style.fontSize = '16px';
  doneBtn.addEventListener('pointerup', function() { callbacks.onSend(_buildActiveItem()); });
  doneWrap.appendChild(doneBtn);
  ov.appendChild(doneWrap);

  // ── Helpers ─────────────────────────────────────────
  function sectionLabel(text, color) {
    var d = document.createElement('div');
    d.style.cssText = [
      'display:flex;align-items:center;gap:8px;',
      'font-family:' + T.fb + ';font-size:10px;color:' + color + ';',
      'letter-spacing:2px;margin-bottom:8px;margin-top:4px;',
    ].join('');
    var t = document.createElement('span');
    t.textContent = text;
    t.style.cssText = 'pointer-events:none;';
    var line = document.createElement('div');
    line.style.cssText = 'height:1px;flex:1;background:' + color + '33;pointer-events:none;';
    d.appendChild(t);
    d.appendChild(line);
    return d;
  }

  function pill(label, bg, active, onClick) {
    var el = document.createElement('div');
    el.style.cssText = [
      'display:inline-flex;align-items:center;gap:5px;',
      'padding:8px 16px;border-radius:999px;cursor:pointer;',
      'user-select:none;font-family:' + T.fh + ';font-weight:700;font-size:13px;',
      'color:#fff;',
      'background:' + (active ? bg : T.card) + ';',
      'border:1px solid ' + (active ? bg : 'rgba(255,255,255,0.1)') + ';',
      'box-shadow:' + (active ? '0 4px 0 ' + hexToRgba(bg, 0.5) : '0 3px 0 #111') + ';',
      'transition:all 100ms;',
      'pointer-events:auto;touch-action:manipulation;white-space:nowrap;',
    ].join('');
    el.textContent = label;
    if (onClick) el.addEventListener('pointerup', onClick);
    return el;
  }

  function pillWrap() {
    var d = document.createElement('div');
    d.style.cssText = 'display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px;';
    return d;
  }

  // ── Build active item for commit ─────────────────────
  function _buildActiveItem() {
    var optMods = [];
    Object.keys(optState).forEach(function(optId) {
      var s = optState[optId];
      if (!s) return;
      // Find the option def
      var found = null;
      optionalGroups.forEach(function(g) {
        (g.options || []).forEach(function(o) {
          if ((o.id || o.key) === optId) found = o;
        });
      });
      if (!found) return;
      var placeMap = { 'LEFT': '1st', 'RIGHT': '2nd', 'WHOLE': null };
      optMods.push({
        prefix:    s.prefix,
        label:     found.label,
        price:     found.price || 0,
        placement: placeMap[s.placement] || null,
      });
    });

    var removals = Object.keys(inclState).filter(function(id) {
      return inclState[id] === 'NO';
    });

    // Build preview mods for ticket
    var previewMods = [];
    optMods.forEach(function(m) {
      var halfSide = m.placement === '1st' ? 'Left' : m.placement === '2nd' ? 'Right' : null;
      var charged = (m.prefix === 'ADD' || m.prefix === 'EXTRA') && m.price > 0;
      previewMods.push({ name: m.prefix + ' ' + m.label, price: charged ? m.price : 0, charged: charged, prefix: halfSide });
    });
    removals.forEach(function(rid) {
      var inc = includedItems.find(function(i) { return i.id === rid; });
      if (inc) previewMods.push({ name: 'NO ' + inc.label, price: 0, charged: false, prefix: null });
    });
    Object.keys(inclState).forEach(function(rid) {
      if (inclState[rid] === 'ON SIDE') {
        var inc = includedItems.find(function(i) { return i.id === rid; });
        if (inc) previewMods.push({ name: 'ON SIDE ' + inc.label, price: 0, charged: false, prefix: null });
      }
    });

    callbacks.onUpdate({ itemLabel: item.label, basePrice: itemPx, mods: previewMods });

    // Build mandatory selections map
    var mandSel = {};
    Object.keys(mandState).forEach(function(k) { mandSel[k] = mandState[k]; });

    return {
      itemLabel:           item.label,
      basePrice:           itemPx,
      mandatorySelections: mandSel,
      optionalModifiers:   optMods,
      includedRemovals:    removals,
      allergens:           [],
      allergenNote:        '',
      note:                '',
    };
  }

  // ── Render content sections ──────────────────────────
  function renderContent() {
    scroll.innerHTML = '';

    // ── SNAKE BREADCRUMB CARD — matches grid tile style ──
    var snakeCard = document.createElement('div');
    snakeCard.style.cssText = [
      'display:flex;gap:6px;align-items:stretch;',
      'margin-bottom:12px;',
    ].join('');

    // Crumb tiles — filled, same style as buildCrumbTile
    snakeState.crumbs.forEach(function(crumb) {
      var tile = document.createElement('div');
      tile.style.cssText = [
        'display:flex;align-items:center;justify-content:center;',
        'padding:10px 14px;border-radius:10px;min-height:95px;',
        'background:' + crumb.color + ';',
        'border-left:4px solid ' + crumb.color + ';',
        'box-shadow:0 4px 0 ' + hexToRgba(crumb.color, 0.55) + ';',
        'font-family:' + T.fh + ';font-weight:700;font-size:22px;',
        'color:#fff;letter-spacing:1px;pointer-events:none;',
      ].join('');
      tile.textContent = crumb.label;
      snakeCard.appendChild(tile);
    });

    // Item tile — same style as buildItemTile but filled, tap to cancel
    var itemTile = document.createElement('div');
    itemTile.style.cssText = [
      'display:flex;flex-direction:column;justify-content:center;',
      'padding:10px 14px;border-radius:10px;cursor:pointer;',
      'background:' + catColor + ';',
      'border-left:4px solid ' + catColor + ';',
      'box-shadow:0 4px 0 ' + hexToRgba(catColor, 0.55) + ';',
      'pointer-events:auto;touch-action:manipulation;',
      'min-height:95px;min-width:120px;',
    ].join('');
    var icn = document.createElement('span');
    icn.style.cssText = 'font-family:' + T.fh + ';font-weight:700;font-size:22px;color:#fff;pointer-events:none;';
    icn.textContent = item.label;
    var icp = document.createElement('span');
    icp.style.cssText = 'font-family:' + T.fb + ';font-size:14px;color:rgba(255,255,255,0.75);margin-top:4px;pointer-events:none;';
    icp.textContent = '$' + itemPx.toFixed(2);
    itemTile.appendChild(icn);
    itemTile.appendChild(icp);
    itemTile.addEventListener('pointerup', function() { callbacks.onCancel(); });
    snakeCard.appendChild(itemTile);
    scroll.appendChild(snakeCard);

    // ── MANDATORY GROUPS ──
    mandatoryGroups.forEach(function(g) {
      scroll.appendChild(sectionLabel('REQUIRED — ' + g.label, T.verm));
      var wrap = pillWrap();
      (g.options || []).forEach(function(opt) {
        var sel = mandState[g.key] && mandState[g.key].key === (opt.key || opt.id);
        var p = pill(opt.label, T.verm, sel, function() {
          if (sel) { delete mandState[g.key]; }
          else { mandState[g.key] = { key: opt.key || opt.id, label: opt.label, price: opt.price || 0 }; }
          renderContent();
        });
        wrap.appendChild(p);
      });
      scroll.appendChild(wrap);
    });

    // ── INCLUDED ──
    if (includedItems.length > 0) {
      scroll.appendChild(sectionLabel('INCLUDED — TAP TO REMOVE OR SIDE', T.mutedText));
      var inclWrap = pillWrap();
      includedItems.forEach(function(inc) {
        var state = inclState[inc.id] || null;
        var bg    = state === 'NO' ? T.verm : state === 'ON SIDE' ? T.gold : T.card;
        var lbl   = state ? '[' + state + '] ' + inc.label : inc.label;
        var p = pill(lbl, bg, !!state, function() {
          var cycle = ['NO', 'ON SIDE', null];
          var next  = cycle[(cycle.indexOf(inclState[inc.id] || null) + 1) % cycle.length];
          if (next === null) delete inclState[inc.id]; else inclState[inc.id] = next;
          renderContent();
        });
        inclWrap.appendChild(p);
      });
      scroll.appendChild(inclWrap);
    }

    // ── OPTIONS ──
    if (optionalGroups.length > 0) {
      scroll.appendChild(sectionLabel('OPTIONS', T.greenWarm));

      // Prefix toolbar
      var pfxWrap = document.createElement('div');
      pfxWrap.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;';
      _PREFIX_DEFS.forEach(function(pfx) {
        var isActive = activePrefix === pfx.id;
        var pc = _prefixColor(pfx.id);
        var btn = document.createElement('div');
        btn.style.cssText = [
          'padding:5px 14px;border-radius:999px;cursor:pointer;',
          'user-select:none;pointer-events:auto;touch-action:manipulation;',
          'font-family:' + T.fb + ';font-weight:700;font-size:11px;letter-spacing:1px;',
          'color:#fff;',
          'background:' + (isActive ? pc : T.card) + ';',
          'border:1px solid ' + (isActive ? pc : 'rgba(255,255,255,0.1)') + ';',
          'box-shadow:' + (isActive ? '0 3px 0 ' + hexToRgba(pc, 0.55) : '0 2px 0 #111') + ';',
          'transition:all 100ms;white-space:nowrap;',
        ].join('');
        btn.textContent = pfx.label;
        btn.addEventListener('pointerup', function() {
          activePrefix = pfx.id;
          renderContent();
        });
        pfxWrap.appendChild(btn);
      });
      scroll.appendChild(pfxWrap);

      // Placement bar — pizza only
      if (isPizza) {
        var placeBar = document.createElement('div');
        placeBar.style.cssText = [
          'display:flex;gap:3px;margin-bottom:10px;',
          'background:' + T.well + ';border-radius:10px;padding:3px;',
        ].join('');
        _PLACE_DEFS.forEach(function(pl) {
          var isActive = activePlacement === pl.id;
          var seg = document.createElement('div');
          seg.style.cssText = [
            'flex:' + (pl.id === 'WHOLE' ? 2 : 1) + ';text-align:center;',
            'padding:7px 8px;border-radius:8px;cursor:pointer;',
            'pointer-events:auto;touch-action:manipulation;',
            'font-family:' + T.fb + ';font-weight:700;font-size:10px;letter-spacing:1px;',
            'color:' + (isActive ? '#fff' : T.mutedText) + ';',
            'background:' + (isActive ? catColor : 'transparent') + ';',
            'box-shadow:' + (isActive ? '0 3px 0 ' + hexToRgba(catColor, 0.55) : 'none') + ';',
            'transition:all 120ms;',
          ].join('');
          seg.textContent = pl.label;
          seg.addEventListener('pointerup', function() {
            activePlacement = pl.id;
            renderContent();
          });
          placeBar.appendChild(seg);
        });
        scroll.appendChild(placeBar);
      }

      // Option pills for each optional group
      optionalGroups.forEach(function(g) {
        if (g.label) scroll.appendChild(sectionLabel(g.label, T.greenWarm));
        var optWrap = pillWrap();
        (g.options || []).forEach(function(opt) {
          var optId = opt.id || opt.key;
          var s     = optState[optId] || null;
          var isActive = !!s;
          var bg    = isActive ? _prefixColor(s.prefix) : T.card;
          var lbl   = isActive ? '[' + s.prefix + ']' + (s.placement !== 'WHOLE' ? '[' + s.placement + ']' : '') + ' ' + opt.label : opt.label;
          var p = pill(lbl, bg, isActive, function() {
            if (isActive) { delete optState[optId]; }
            else { optState[optId] = { prefix: activePrefix, placement: activePlacement }; }
            renderContent();
          });
          optWrap.appendChild(p);
        });
        scroll.appendChild(optWrap);
      });

      // Show a message if no groups configured (pizza fallback)
      if (optionalGroups.length === 0 && includedItems.length === 0 && mandatoryGroups.length === 0) {
        var msg = document.createElement('div');
        msg.style.cssText = 'font-family:' + T.fh + ';font-size:13px;color:' + T.mutedText + ';text-align:center;padding:24px 0;';
        msg.textContent = 'No modifiers configured — tap DONE to add';
        scroll.appendChild(msg);
      }
    } else if (optionalGroups.length === 0 && includedItems.length === 0 && mandatoryGroups.length === 0) {
      var msg2 = document.createElement('div');
      msg2.style.cssText = 'font-family:' + T.fh + ';font-size:13px;color:' + T.mutedText + ';text-align:center;padding:24px 0;';
      msg2.textContent = 'No modifiers configured — tap DONE to add';
      scroll.appendChild(msg2);
    }
  }

  renderContent();
  container.appendChild(ov);

  return {
    destroy: function() {
      if (ov.parentNode) ov.parentNode.removeChild(ov);
    },
  };
}


// ── MODIFIER PANEL (overlay on _mainArea) ─────────
function openModifierPanel(item, modConfig, catColor, enablePlacement) {
  if (_modPanel) closeModifierPanel();
  if (!_mainArea) return;

  _modPanelOpen = true;

  // Hide grid + tab bar, show snake strip above the panel, hide bottom bar
  if (_gridWrap)    _gridWrap.style.display    = 'none';
  if (_snakeTabBar) _snakeTabBar.style.display = 'none';
  if (_snakeStrip)  { _snakeStrip.innerHTML = ''; _snakeStrip.style.display = 'none'; }
  if (_bottomBar)   _bottomBar.style.display   = 'none';
  _mainArea.style.border = 'none';

  _modPanel = buildKindModPanel(_mainArea, item, modConfig, catColor, enablePlacement, {
    onUpdate: function(outputItem) { _modPanelItem = outputItem; renderTicket(); },
    onSend:   function(activeItem) { commitModifierPanelItem(item, activeItem, modConfig); },
    onCancel: function()           { closeModifierPanel(); },
  });
  renderTicket();
}

function _buildSnakeStrip(item, catColor) {
  if (!_snakeStrip) return;
  _snakeStrip.innerHTML = '';
  _snakeStrip.style.display = 'flex';

  // Crumb tiles
  snakeState.crumbs.forEach(function(crumb) {
    var chip = document.createElement('div');
    chip.style.cssText = [
      'background:' + crumb.color + ';border-radius:8px;',
      'border-left:4px solid ' + crumb.color + ';',
      'padding:6px 16px;font-family:' + T.fh + ';',
      'font-weight:700;font-size:14px;color:#fff;letter-spacing:1px;',
      'pointer-events:none;',
    ].join('');
    chip.textContent = crumb.label;
    _snakeStrip.appendChild(chip);
  });

  // Item chip — tap to cancel
  var itemChip = document.createElement('div');
  itemChip.style.cssText = [
    'background:' + catColor + ';border-radius:8px;',
    'border-left:4px solid ' + catColor + ';',
    'padding:6px 16px;font-family:' + T.fh + ';',
    'font-weight:700;font-size:14px;color:#fff;letter-spacing:1px;',
    'display:flex;align-items:center;gap:8px;cursor:pointer;',
    'pointer-events:auto;touch-action:manipulation;',
    'box-shadow:0 0 12px ' + hexToRgba(catColor, 0.5) + ';',
  ].join('');
  var itemName = document.createElement('span');
  itemName.style.cssText = 'pointer-events:none;';
  itemName.textContent = item.label;
  var itemPrice = document.createElement('span');
  itemPrice.style.cssText = 'font-family:' + T.fb + ';font-size:13px;color:rgba(255,255,255,0.7);pointer-events:none;';
  itemPrice.textContent = '$' + (typeof item.price === 'number' ? item.price.toFixed(2) : '0.00');
  itemChip.appendChild(itemName);
  itemChip.appendChild(itemPrice);
  itemChip.addEventListener('pointerup', function() { closeModifierPanel(); });
  _snakeStrip.appendChild(itemChip);
}

function closeModifierPanel() {
  if (_modPanel) {
    _modPanel.destroy();
    _modPanel = null;
  }
  _modPanelItem = null;
  _modPanelOpen = false;

  // Restore grid + tab bar
  if (_gridWrap)    _gridWrap.style.display    = '';
  if (_snakeTabBar) _snakeTabBar.style.display = '';
  if (_snakeStrip)  { _snakeStrip.innerHTML = ''; _snakeStrip.style.display = 'none'; }
  if (_mainArea)    _mainArea.style.border     = '';

  renderTicket();

  requestAnimationFrame(function() {
    if (_bottomBar) _bottomBar.style.display = '';
    rebuildBottomBar();
  });
}



function commitModifierPanelItem(originalItem, activeItem, modConfig) {
  modConfig = modConfig || {};
  // Build ticket item from modifier panel state
  var mands = activeItem.mandatorySelections;
  var mandPrice = 0;
  Object.keys(mands).forEach(function(k) {
    mandPrice += mands[k].price || 0;
  });

  // Mandatory selections as modifier lines
  var mods = [];
  var mandGroups = modConfig.mandatoryGroups || [];
  mandGroups.forEach(function(g) {
    if (mands[g.key]) {
      mods.push({
        name: mands[g.key].label,
        price: mands[g.key].price || 0,
        charged: (mands[g.key].price || 0) > 0,
        prefix: null,
      });
    }
  });

  // Optional modifiers — map placement to Left/Right prefix
  activeItem.optionalModifiers.forEach(function(m) {
    var charged = m.prefix !== 'NO' && m.price > 0;
    var halfSide = m.placement === '1st' ? 'Left' : m.placement === '2nd' ? 'Right' : null;
    var parentMod = {
      name: m.prefix + ' ' + m.label,
      price: m.prefix === 'NO' ? 0 : m.price,
      charged: charged,
      prefix: halfSide,
      children: [],
    };
    // Special exclusions as child mods (indented on ticket)
    if (m.special && m.exclusions && m.exclusions.length > 0) {
      m.exclusions.forEach(function(ex) {
        parentMod.children.push({ name: 'NO ' + ex, price: 0, charged: false });
      });
    }
    mods.push(parentMod);
  });

  // Included removals
  var includedItems = modConfig.includedItems || [];
  activeItem.includedRemovals.forEach(function(rid) {
    var incl = includedItems.find(function(i) { return i.id === rid; });
    if (incl) {
      mods.push({ name: 'NO ' + incl.label, price: 0, charged: false, prefix: null });
    }
  });

  // Allergens
  var ALLERGEN_LABELS = {
    nuts: 'Nuts', shellfish: 'Shellfish', gluten: 'Gluten', dairy: 'Dairy',
    soy: 'Soy', eggs: 'Eggs', fish: 'Fish',
  };
  activeItem.allergens.forEach(function(aId) {
    var label = ALLERGEN_LABELS[aId] || aId;
    mods.push({ name: '\u26A0 ALLERGEN: ' + label, price: 0, charged: false, prefix: null });
  });
  if (activeItem.allergenNote) {
    mods.push({ name: '\u26A0 ALLERGEN: ' + activeItem.allergenNote, price: 0, charged: false, prefix: null });
  }

  // Note
  if (activeItem.note) {
    mods.push({ name: '\uD83D\uDCDD ' + activeItem.note, price: 0, charged: false, prefix: null });
  }

  var ticketItem = {
    id:        ++ticketSeq,
    idemKey:   _idemKey(),
    name:      activeItem.itemLabel,
    unitPrice: activeItem.basePrice,
    mods:      mods,
    selected:  false,
    sent:      false,
    category:  snakeState.catId,
    seat_number: _activeSeat,
    // Preserve modifier panel data for ledger
    _modPanelData: {
      mandatory: mands,
      optionalModifiers: activeItem.optionalModifiers,
      includedRemovals: activeItem.includedRemovals,
      allergens: activeItem.allergens,
      allergenNote: activeItem.allergenNote,
      note: activeItem.note,
    },
  };

  ticket.push(ticketItem);
  closeModifierPanel();
}

// ── TAB SWITCHING ─────────────────────────────────
function switchTab(tab) {
  // No-op — navigation handled by snake nav
}


// ── TICKET ────────────────────────────────────────
// Build modifier config from Overseer-authored mandatory + universal assignments.
// Returns null when no assignment matches — caller falls back to hardcoded configs.
function resolveBackendModifierConfig(itemId, catId) {
  if (!itemId && !catId) return null;

  var mandatoryGroups = [];
  var pricingDriverKey = null;
  MANDATORY_ASSIGNMENTS.forEach(function(asgn) {
    var hit = (asgn.target_type === 'item' && asgn.target_id === itemId)
           || (asgn.target_type === 'category' && asgn.target_id === catId);
    if (!hit) return;
    var entry = {
      key: asgn.assignment_id,
      label: (asgn.label || '').toUpperCase(),
      drivesPricing: !!asgn.drives_pricing,
      options: (asgn.modifier_ids || []).map(function(mid) {
        var m = MODIFIER_MASTER[mid] || { name: mid, price: 0 };
        return { key: mid, label: m.name, price: m.price };
      }),
    };
    if (entry.drivesPricing && !pricingDriverKey) pricingDriverKey = asgn.assignment_id;
    mandatoryGroups.push(entry);
  });

  var optionalGroups = [];
  UNIVERSAL_ASSIGNMENTS.forEach(function(asgn) {
    if (asgn.category_id !== catId) return;
    (asgn.group_ids || []).forEach(function(gid) {
      var grp = MODIFIER_GROUPS.find(function(g) { return g.group_id === gid; });
      if (!grp) return;
      optionalGroups.push({
        key: grp.group_id,
        label: (grp.name || '').toUpperCase(),
        options: (grp.modifiers || []).map(function(m) {
          var priceByOption = m.price_by_option && Object.keys(m.price_by_option).length > 0 ? m.price_by_option : null;
          return {
            id: m.modifier_id,
            label: m.name,
            price: parseFloat(m.price) || 0,
            priceByOption: priceByOption,
          };
        }),
      });
    });
  });

  if (mandatoryGroups.length === 0 && optionalGroups.length === 0) return null;
  return {
    mandatoryGroups: mandatoryGroups,
    optionalGroups: optionalGroups,
    includedItems: [],
    pricingDriverKey: pricingDriverKey,
  };
}

function getMenuCat(id) {
  return MENU_DATA.find(function(c) { return c.id === id; });
}

function getModCat(id) {
  return MOD_DATA.find(function(c) { return c.id === id; });
}

function handleItemSelect(item) {
  var name  = item.label || item;
  var price = typeof item.price === 'number' ? item.price : 0;

  // ── Combo flow: picking side or soda ──
  if (comboFlow) {
    if (comboFlow.step === 'side') {
      comboFlow.ticketItem.mods.push({ name: name, price: 0, charged: false });
      comboFlow.step = 'drink';
      // Navigate snake to drinks
      var drinksCat = getMenuCat('drinks');
      if (drinksCat) _selectCat(drinksCat);
      renderTicket();
      rebuildBottomBar();
      return;
    }
    if (comboFlow.step === 'drink') {
      comboFlow.ticketItem.mods.push({ name: name, price: 0, charged: false });
      comboFlow = null;
      // Return to category home
      snakeState = { view:'cats', crumbs:[], catId:null, subId:null };
      renderSnakeGrid();
      _refreshSnakeTabBar();
      renderTicket();
      rebuildBottomBar();
      return;
    }
  }

  // ── Start combo flow if selected from COMBO category ──
  if (snakeState.catId === 'combo') {
    var comboMods = [];
    if (item.selectedMods) {
      item.selectedMods.forEach(function(sm) {
        comboMods.push({ name: sm.label, price: sm.price || 0, charged: sm.price > 0 });
      });
    }
    var ticketItem = {
      id:        ++ticketSeq,
      idemKey:   _idemKey(),
      name:      'Combo ' + name,
      unitPrice: price,
      mods:      comboMods,
      selected:  false,
      sent:      false,
      category:  'combo',
      seat_number: _activeSeat,
    };
    ticket.push(ticketItem);
    comboFlow = { step: 'side', ticketItem: ticketItem };
    var sidesCat = getMenuCat('sides');
    if (sidesCat) _selectCat(sidesCat);
    renderTicket();
    rebuildBottomBar();
    return;
  }

  // ── Pizza builder: size tap opens the overlay ──
  if (item.pizzaSize) {
    showPizzaBuilderOverlay(item, PIZZA_BUILDER_DATA).then(function(result) {
      ticket.push({
        id:        ++ticketSeq,
        idemKey:   _idemKey(),
        name:      result.name,
        unitPrice: result.unitPrice,
        mods:      result.mods || [],
        selected:  false,
        sent:      false,
        category:  'pizza',
        seat_number: _activeSeat,
      });
      renderTicket();
      rebuildBottomBar();
    }).catch(function() { /* cancelled */ });
    return;
  }

  // ── Modifier panel: resolve config from backend assignments ──
  var catId = snakeState.catId;
  if (!catId && item.id) catId = ITEM_TO_CATEGORY[item.id] || null;

  var backendConfig = resolveBackendModifierConfig(item.id, catId);
  var overseerIncluded = item.id ? INCLUDED_BY_ITEM[item.id] : null;

  if (backendConfig || (overseerIncluded && overseerIncluded.length > 0)) {
    var effectiveConfig = backendConfig ? Object.assign({}, backendConfig) : {};
    if (overseerIncluded && overseerIncluded.length > 0) {
      effectiveConfig.includedItems = overseerIncluded;
    }
    var catColor = catId ? T.catColor(catId.toUpperCase()) : T.green;
    var menuCat = catId ? getMenuCat(catId) : null;
    var enablePlacement = menuCat ? !!menuCat.enablePlacement : false;
    openModifierPanel(item, effectiveConfig, catColor, enablePlacement);
    return;
  }

  // ── Pizza fallback: always open modifier panel for pizza categories ──
  var menuCatForFallback = catId ? getMenuCat(catId) : null;
  if (menuCatForFallback && (menuCatForFallback.enablePlacement || menuCatForFallback.pizzaBuilder)) {
    var fallbackConfig = { mandatoryGroups: [], optionalGroups: [], includedItems: [] };
    openModifierPanel(item, fallbackConfig, menuCatForFallback.color, true);
    return;
  }

  addToTicket(item);
}

function addToTicket(item) {
  var name  = item.label || item;
  var price = typeof item.price === 'number' ? item.price : 0;

  if (modifierSession.active) {
    // Apply modifier to all selected instances
    var selected = ticket.filter(function(i) { return i.selected; });
    if (selected.length === 0) {
      showToast('Select an item first', { bg: T.dimText, duration: 2000 });
      return;
    }

    // Check if current modifier category has half_placement
    var modCatId = snakeState.catId;
    var modCat = modCatId ? getModCat(modCatId) : null;
    if (modCat && modCat.half_placement) {
      var halfPrice = typeof item.half_price === 'number' ? item.half_price : null;
      // Use first selected item for overlay context
      var targetInst = selected[0];
      showHalfPlacementOverlay(targetInst.name, name, price, halfPrice, targetInst.mods)
        .then(function(result) {
          selected.forEach(function(inst) {
            // Re-selection: if same mod on other side, move it
            var otherSide = result.side === 'Left' ? 'Right' : 'Left';
            for (var i = inst.mods.length - 1; i >= 0; i--) {
              if (inst.mods[i].name === name && inst.mods[i].prefix === otherSide) {
                inst.mods.splice(i, 1);
              }
            }
            var modPrice = halfPrice != null ? halfPrice : 0;
            var mod = { name: name, price: modPrice, half_price: halfPrice, charged: modPrice > 0, prefix: result.side };
            inst.mods.push(mod);
            modHistory.push({ inst: inst, mod: mod });
          });
          renderTicket();
          rebuildBottomBar();
        })
        .catch(function() { /* cancelled */ });
      return;
    }

    var pfx = PREFIXES.find(function(p) { return p.id === modifierSession.activePrefix; });
    var modName = (pfx ? pfx.label + ' ' : '') + name;
    var charged = price > 0;
    selected.forEach(function(inst) {
      var mod = { name: modName, price: price, charged: charged, prefix: null };
      inst.mods.push(mod);
      modHistory.push({ inst: inst, mod: mod });
    });
  } else {
    // New item instance
    var mods = [];
    if (item.selectedMods) {
      item.selectedMods.forEach(function(sm) {
        mods.push({ name: sm.label, price: sm.price || 0, charged: sm.price > 0 });
      });
    }
    ticket.push({
      id:        ++ticketSeq,
      idemKey:   _idemKey(),
      name:      name,
      unitPrice: price,
      mods:      mods,
      selected:  false,
      sent:      false,
      category:  snakeState.catId,
      seat_number: _activeSeat,
    });
  }
  renderTicket();
  rebuildBottomBar();
}

function renderTicket() {
  if (SceneManager.getActiveWorking() !== 'order-entry') return;
  var list = document.getElementById('ticket-list');
  if (!list) return;
  list.innerHTML = '';

  // In check-overview mode, only show newly added (unsent) items
  var displayTicket = ticket;
  if (sceneParams.returnScene === 'check-overview') {
    displayTicket = ticket.filter(function(inst) { return !inst.sent; });
    if (displayTicket.length === 0 && !_modPanelItem) {
      var hint = document.createElement('div');
      hint.style.cssText = 'padding:20px 8px;font-family:' + T.fb + ';font-size:' + T.fsB3 + ';color:' + T.mutedText + ';text-align:center;';
      hint.textContent = 'Tap items to add';
      list.appendChild(hint);
      return;
    }
  }

  // ── Group by seat (check-overview mode) then by name ──
  var hasSeatGroups = sceneParams.returnScene === 'check-overview' &&
    sceneParams.seatNumbers && sceneParams.seatNumbers.length > 1;

  if (hasSeatGroups) {
    // Collect unique seat numbers in order
    var seatOrder = [];
    var seatItems = {};
    displayTicket.forEach(function(inst) {
      var sn = inst.seat_number || 1;
      if (!seatItems[sn]) { seatItems[sn] = []; seatOrder.push(sn); }
      seatItems[sn].push(inst);
    });
    seatOrder.sort(function(a, b) { return a - b; });

    for (var si = 0; si < seatOrder.length; si++) {
      var sn = seatOrder[si];
      // Seat header
      var seatHdr = document.createElement('div');
      seatHdr.style.cssText = 'padding:4px 8px 2px;font-family:' + T.fh + ';font-size:' + T.fsB2 + ';color:' + T.green + ';letter-spacing:2px;border-bottom:1px solid ' + T.border + ';margin-bottom:2px;';
      seatHdr.textContent = 'S-' + String(sn).padStart(3, '0');
      list.appendChild(seatHdr);

      // Render items for this seat using the same group logic below
      var seatTicket = seatItems[sn];
      _renderTicketGroup(list, seatTicket);
    }
    _appendModPreview(list);
    _updateTicketTotals();
    return;
  }

  _renderTicketGroup(list, displayTicket);
  _appendModPreview(list);
  _updateTicketTotals();
}

function _appendModPreview(list) {
  if (!_modPanelItem) return;
  // Remove ALL stale previews (may lack data-mod-preview from interrupted renders)
  var children = list.children;
  for (var ri = children.length - 1; ri >= 0; ri--) {
    if (children[ri].textContent.indexOf('\u270E') !== -1) {
      list.removeChild(children[ri]);
    }
  }

  var previewMods = (_modPanelItem.mods || []);
  var previewModTotal = previewMods.reduce(function(s, m) { return s + m.price; }, 0);
  var previewPrice = (_modPanelItem.basePrice || 0) + previewModTotal;
  var fs = T.fsB2;
  var fsMod = T.fsB3;

  var pc = document.createElement('div');
  pc.setAttribute('data-mod-preview', '1');
  pc.style.cssText = 'flex-shrink:0;margin-bottom:2px;background:' + T.well + ';border-left:3px solid ' + T.gold + ';';
  _applyCardBevel(pc);

  var pRow = document.createElement('div');
  pRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:4px 8px;';
  var pName = document.createElement('span');
  pName.style.cssText = 'font-family:' + T.fb + ';font-size:' + fs + ';font-weight:bold;color:' + T.green + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;';
  pName.textContent = '\u270E ' + _modPanelItem.itemLabel;
  var pPrice = document.createElement('span');
  pPrice.style.cssText = 'font-family:' + T.fb + ';font-size:' + fs + ';font-weight:bold;color:' + T.gold + ';white-space:nowrap;flex-shrink:0;margin-left:6px;';
  pPrice.textContent = '$' + previewPrice.toFixed(2);
  pRow.appendChild(pName);
  pRow.appendChild(pPrice);
  pc.appendChild(pRow);

  // Partition into whole / left / right
  var wholeMods = [];
  var leftMods = [];
  var rightMods = [];
  for (var pi = 0; pi < previewMods.length; pi++) {
    var pm = previewMods[pi];
    if (pm.prefix === 'Left') leftMods.push(pm);
    else if (pm.prefix === 'Right') rightMods.push(pm);
    else wholeMods.push(pm);
  }

  // Whole mods with X buttons — mint text, gold prices
  wholeMods.forEach(function(m) {
    var removeHandler = function() {
      if (_modPanel && m._source != null) _modPanel.removeMod(m._source, m._idx);
      else { var mi = _modPanelItem.mods.indexOf(m); if (mi !== -1) _modPanelItem.mods.splice(mi, 1); }
      renderTicket();
    };
    pc.appendChild(buildModRowSized(m.name, m.price, fsMod, removeHandler));
    // Show exclusion children (e.g. "NO Ketchup" under "ADD Cheeseburger")
    if (m.children && m.children.length > 0) {
      m.children.forEach(function(child) {
        var childRow = buildModRowSized(child.name, child.price, '14px');
        childRow.style.paddingLeft = '32px';
        childRow.style.color = T.verm;
        childRow.style.fontStyle = 'italic';
        pc.appendChild(childRow);
      });
    }
  });

  // Half-table for left/right mods
  if (leftMods.length > 0 || rightMods.length > 0) {
    var inst = { sent: false, mods: _modPanelItem.mods };
    pc.appendChild(buildHalfTable(leftMods, rightMods, fsMod, inst));
  }

  list.appendChild(pc);
}

function _updateTicketTotals() {
  var totals = computeTicketTotals();
  if (_modPanelItem) {
    var previewMods = (_modPanelItem.mods || []);
    var previewModTotal = previewMods.reduce(function(s, m) { return s + m.price; }, 0);
    var previewPrice = _modPanelItem.basePrice + previewModTotal;
    totals.subtotal += previewPrice;
    var _t = computeTotals(totals.subtotal);
    totals.tax = _t.tax;
    totals.cardTotal = _t.cardTotal;
    totals.cashPrice = _t.cashPrice;
  }
  OrderSummary.update({
    checkId: currentCheckNumber || '',
    skipItems: true,
    subtotal: totals.subtotal,
    tax: totals.tax,
    cardTotal: totals.cardTotal,
    cashPrice: totals.cashPrice,
  });
}

// ── Swipe-to-delete wrapper ──────────────────────
function _wrapSwipeDelete(innerEl, onDelete) {
  var THRESHOLD = 60;
  var BTN_W = 70;

  var wrap = document.createElement('div');
  wrap.style.cssText = 'position:relative;overflow:hidden;flex-shrink:0;';

  // Delete button behind
  var delBtn = document.createElement('div');
  delBtn.style.cssText = 'position:absolute;right:0;top:0;bottom:0;width:' + BTN_W + 'px;display:flex;align-items:center;justify-content:center;background:' + T.verm + ';color:' + T.text + ';font-family:' + T.fh + ';font-size:' + T.fsB3 + ';letter-spacing:1px;cursor:pointer;user-select:none;';
  delBtn.textContent = 'DELETE';
  wrap.appendChild(delBtn);

  // Inner content on top
  innerEl.style.position = 'relative';
  innerEl.style.zIndex = '1';
  innerEl.style.transition = 'transform 150ms ease-out';
  wrap.appendChild(innerEl);

  var startX = 0;
  var currentX = 0;
  var swiping = false;
  var revealed = false;

  innerEl.addEventListener('pointerdown', function(e) {
    startX = e.clientX;
    currentX = 0;
    swiping = true;
    innerEl.style.transition = 'none';
  });

  innerEl.addEventListener('pointermove', function(e) {
    if (!swiping) return;
    var dx = e.clientX - startX;
    if (dx > 0) dx = 0; // no right swipe
    if (dx < -BTN_W) dx = -BTN_W;
    currentX = dx;
    innerEl.style.transform = 'translateX(' + dx + 'px)';
  });

  innerEl.addEventListener('pointerup', function() {
    if (!swiping) return;
    swiping = false;
    innerEl.style.transition = 'transform 150ms ease-out';
    if (currentX < -THRESHOLD) {
      // Reveal delete
      innerEl.style.transform = 'translateX(-' + BTN_W + 'px)';
      revealed = true;
    } else {
      innerEl.style.transform = 'translateX(0)';
      revealed = false;
    }
  });

  innerEl.addEventListener('pointerleave', function() {
    if (!swiping) return;
    swiping = false;
    innerEl.style.transition = 'transform 150ms ease-out';
    if (currentX < -THRESHOLD) {
      innerEl.style.transform = 'translateX(-' + BTN_W + 'px)';
      revealed = true;
    } else {
      innerEl.style.transform = 'translateX(0)';
      revealed = false;
    }
  });

  delBtn.addEventListener('pointerup', function() {
    onDelete();
  });

  return wrap;
}

function _renderTicketGroup(list, displayTicket) {
  var groups = {};
  var groupOrder = [];
  displayTicket.forEach(function(inst) {
    if (!groups[inst.name]) {
      groups[inst.name] = [];
      groupOrder.push(inst.name);
    }
    groups[inst.name].push(inst);
  });

  groupOrder.forEach(function(name) {
    var instances = groups[name];
    var hasCharged = instances.some(function(inst) {
      return inst.mods.some(function(m) { return m.charged; });
    });

    // Selection check: use modifierSession for batch flow, inst.selected for old tab flow
    var isSelected = function(inst) {
      if (modifierSession.selectedItems.length > 0 || modifierSession.active) {
        return modifierSession.selectedItems.indexOf(inst.id) !== -1;
      }
      return inst.selected;
    };
    var anySelected = instances.some(isSelected);
    var hasMods = instances.some(function(inst) { return inst.mods.length > 0; });

    if (!hasCharged && !anySelected && !hasMods) {
      // ── Collapsed group card ──────────────────────
      var groupPrice = instances.reduce(function(sum, i) {
        return sum + i.unitPrice + i.mods.reduce(function(ms, m) { return ms + m.price; }, 0);
      }, 0);

      var gc = document.createElement('div');
      gc.style.cssText = [
        'flex-shrink:0;cursor:pointer;touch-action:manipulation;',
        'background:' + T.bg + ';',
      ].join('');
      _applyCardBevel(gc);

      var gRow = document.createElement('div');
      gRow.style.cssText = 'display:flex;align-items:center;padding:3px 6px 3px 8px;';

      var allSent = instances.every(function(i) { return i.sent; });
      var gName = document.createElement('span');
      gName.style.cssText = 'font-family:' + T.fb + ';font-size:14px;font-weight:bold;color:' + T.green + ';flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none;';
      gName.textContent = (allSent ? '\u2713 ' : '') + (instances.length > 1 ? instances.length + '\u00d7 ' : '') + name;

      var gPrice = document.createElement('span');
      gPrice.style.cssText = 'font-family:' + T.fb + ';font-size:14px;font-weight:bold;color:' + T.green + ';flex-shrink:0;margin-left:6px;pointer-events:none;';
      gPrice.textContent = '$' + groupPrice.toFixed(2);

      gRow.appendChild(gName);
      gRow.appendChild(gPrice);

      // X delete button — unsent items only
      var anyUnsentNow = instances.some(function(i) { return !i.sent; });
      if (anyUnsentNow) {
        var gXBtn = document.createElement('div');
        gXBtn.style.cssText = 'width:22px;height:22px;flex-shrink:0;margin-left:6px;display:flex;align-items:center;justify-content:center;border-radius:4px;background:' + T.verm + '22;border:1px solid ' + T.verm + '66;color:' + T.verm + ';font-size:12px;font-weight:bold;cursor:pointer;pointer-events:auto;touch-action:manipulation;';
        gXBtn.textContent = '\u00d7';
        gXBtn.addEventListener('pointerup', function(e) {
          e.stopPropagation();
          instances.forEach(function(inst) {
            if (inst.sent) return;
            var idx = ticket.indexOf(inst);
            if (idx !== -1) ticket.splice(idx, 1);
          });
          renderTicket();
          rebuildBottomBar();
        });
        gRow.appendChild(gXBtn);
      }

      gc.appendChild(gRow);

      // Charged mods only in collapsed state
      var chargedMods = [];
      instances.forEach(function(inst) {
        inst.mods.forEach(function(m) {
          if (m.charged) chargedMods.push(m);
        });
      });
      if (chargedMods.length > 0) {
        var sep = buildSeparator();
        gc.appendChild(sep);
        chargedMods.forEach(function(m) {
          gc.appendChild(buildModRow(m.name, m.price, true, false));
          if (m.children && m.children.length > 0) {
            m.children.forEach(function(child) {
              var childRow = buildModRow(child.name, child.price, true, false);
              childRow.style.paddingLeft = '24px';
              childRow.style.color = T.verm;
              childRow.style.fontStyle = 'italic';
              gc.appendChild(childRow);
            });
          }
        });
      }

      // Short tap = select; long-press = edit quantity
      var _qtyHoldTimer = null;
      var _qtyDidHold = false;
      gc.addEventListener('pointerdown', function() {
        if (modifierSession.active) return;
        _qtyDidHold = false;
        _qtyHoldTimer = setTimeout(function() {
          _qtyDidHold = true;
          // Only allow qty edit on unsent items
          var allUnsent = instances.every(function(i) { return !i.sent; });
          if (!allUnsent) {
            showToast('Cannot edit qty on sent items', { duration: 1500 });
            return;
          }
          showQtyEditor(name, instances);
        }, 500);
      });
      gc.addEventListener('pointerup', function() {
        clearTimeout(_qtyHoldTimer);
        if (_qtyDidHold) return;
        if (modifierSession.active) return;
        // Toggle select all instances into modifierSession
        instances.forEach(function(i) {
          i.selected = true;
          if (modifierSession.selectedItems.indexOf(i.id) === -1) {
            modifierSession.selectedItems.push(i.id);
          }
        });
        renderTicket();
        rebuildBottomBar();
      });
      gc.addEventListener('pointerleave', function() {
        clearTimeout(_qtyHoldTimer);
      });

      list.appendChild(gc);

    } else {
      // ── Individual instance cards ─────────────────
      instances.forEach(function(inst) {
        var active    = isSelected(inst);
        var isExpanded = !!_expandedItems[inst.id];
        var hasMods   = inst.mods.length > 0;
        var bg        = active ? T.well : T.bg;

        var ic = document.createElement('div');
        ic.style.cssText = [
          'flex-shrink:0;touch-action:manipulation;pointer-events:auto;',
          'background:' + bg + ';margin-bottom:2px;',
        ].join('');
        _applyCardBevel(ic);

        // ── Header row ─────────────────────────────
        var iRow = document.createElement('div');
        iRow.style.cssText = [
          'display:flex;align-items:center;padding:3px 6px 3px 8px;',
          'pointer-events:auto;touch-action:manipulation;cursor:pointer;',
        ].join('');

        // Expand chevron — only if has mods
        if (hasMods) {
          var chevron = document.createElement('span');
          chevron.style.cssText = 'font-size:10px;color:' + T.mutedText + ';margin-right:4px;flex-shrink:0;pointer-events:none;transition:transform 150ms;';
          chevron.textContent = isExpanded ? '▾' : '▸';
          iRow.appendChild(chevron);
          ic._chevron = chevron;
        }

        var iName = document.createElement('span');
        iName.style.cssText = [
          'font-family:' + T.fb + ';font-size:14px;font-weight:bold;',
          'color:' + T.green + ';flex:1;min-width:0;',
          'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
          'pointer-events:none;',
        ].join('');
        iName.textContent = (inst.sent ? '✓ ' : '') + (active ? '● ' : '') + inst.name;

        var total = inst.unitPrice + inst.mods.reduce(function(s, m) { return s + m.price; }, 0);
        var iPrice = document.createElement('span');
        iPrice.style.cssText = 'font-family:' + T.fb + ';font-size:14px;font-weight:bold;color:' + T.green + ';flex-shrink:0;margin-left:6px;pointer-events:none;';
        iPrice.textContent = '$' + total.toFixed(2);

        iRow.appendChild(iName);
        iRow.appendChild(iPrice);

        // X delete button — unsent items only
        if (!inst.sent) {
          var xBtn = document.createElement('div');
          xBtn.style.cssText = [
            'width:22px;height:22px;flex-shrink:0;margin-left:6px;',
            'display:flex;align-items:center;justify-content:center;',
            'border-radius:4px;background:' + T.verm + '22;border:1px solid ' + T.verm + '66;',
            'color:' + T.verm + ';font-size:12px;font-weight:bold;cursor:pointer;',
            'pointer-events:auto;touch-action:manipulation;',
          ].join('');
          xBtn.textContent = '×';
          xBtn.addEventListener('pointerup', (function(instance) {
            return function(e) {
              e.stopPropagation();
              var idx = ticket.indexOf(instance);
              if (idx !== -1) ticket.splice(idx, 1);
              delete _expandedItems[instance.id];
              renderTicket();
              rebuildBottomBar();
            };
          })(inst));
          iRow.appendChild(xBtn);
        }

        ic.appendChild(iRow);

        // ── Mod rows — collapsed by default ──────────
        if (hasMods && isExpanded) {
          var wholeMods = [], leftMods = [], rightMods = [];
          inst.mods.forEach(function(m) {
            if (m.prefix === 'Left') leftMods.push(m);
            else if (m.prefix === 'Right') rightMods.push(m);
            else wholeMods.push(m);
          });

          if (wholeMods.length > 0) {
            ic.appendChild(buildSeparator());
            wholeMods.forEach(function(m) {
              ic.appendChild(buildModRowSized(m.name, m.price, '13px', null));
              if (m.children && m.children.length > 0) {
                m.children.forEach(function(child) {
                  var cr = buildModRowSized(child.name, child.price, '12px');
                  cr.style.paddingLeft = '28px';
                  cr.style.color = T.verm;
                  cr.style.fontStyle = 'italic';
                  ic.appendChild(cr);
                });
              }
            });
          }

          if (leftMods.length > 0 || rightMods.length > 0) {
            ic.appendChild(buildHalfTable(leftMods, rightMods, '13px', inst.sent ? null : inst));
          }
        }

        // Collapsed mod count hint
        if (hasMods && !isExpanded) {
          var modHint = document.createElement('div');
          modHint.style.cssText = 'padding:1px 8px 3px 22px;font-family:' + T.fb + ';font-size:11px;color:' + T.mutedText + ';pointer-events:none;';
          modHint.textContent = inst.mods.length + ' modifier' + (inst.mods.length > 1 ? 's' : '');
          ic.appendChild(modHint);
        }

        // Tap header row → expand/collapse mods; toggle selection
        iRow.addEventListener('pointerup', function(e) {
          if (modifierSession.active) return;
          if (hasMods) {
            // Toggle expand
            if (_expandedItems[inst.id]) {
              delete _expandedItems[inst.id];
            } else {
              _expandedItems[inst.id] = true;
            }
          }
          // Toggle selection
          var idx = modifierSession.selectedItems.indexOf(inst.id);
          if (idx !== -1) {
            modifierSession.selectedItems.splice(idx, 1);
            inst.selected = false;
          } else {
            modifierSession.selectedItems.push(inst.id);
            inst.selected = true;
          }
          renderTicket();
          rebuildBottomBar();
        });

        list.appendChild(ic);
      });
    }
  });

  // ── Live preview: active modifier panel item ──────
  if (_modPanelItem) {
    var previewCard = document.createElement('div');
    previewCard.style.cssText = [
      'flex-shrink:0;',
      'background:' + T.bg + ';',
      'margin-bottom:2px;',
    ].join('');
    _applyCardBevel(previewCard);

    // Item header row
    var pRow = document.createElement('div');
    pRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:3px 8px;';
    var pName = document.createElement('span');
    pName.style.cssText = 'font-family:' + T.fb + ';font-size:26px;font-weight:bold;color:' + T.green + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;';
    pName.textContent = '\u270E ' + _modPanelItem.itemLabel;
    var pPrice = document.createElement('span');
    pPrice.style.cssText = 'font-family:' + T.fb + ';font-size:26px;font-weight:bold;color:' + T.gold + ';white-space:nowrap;flex-shrink:0;margin-left:6px;';
    var previewTotal = _modPanelItem.basePrice + (_modPanelItem.mods || []).reduce(function(s, m) { return s + m.price; }, 0);
    pPrice.textContent = '$' + previewTotal.toFixed(2);
    pRow.appendChild(pName);
    pRow.appendChild(pPrice);
    previewCard.appendChild(pRow);

    // Modifier lines — partition into whole / left / right (same as committed items)
    var pMods = _modPanelItem.mods || [];
    var pWhole = [];
    var pLeft = [];
    var pRight = [];
    pMods.forEach(function(m) {
      if (m.prefix === 'Left') pLeft.push(m);
      else if (m.prefix === 'Right') pRight.push(m);
      else pWhole.push(m);
    });

    if (pWhole.length > 0) {
      previewCard.appendChild(buildSeparator());
      pWhole.forEach(function(m) {
        var removeFn = (m._source && _modPanel) ? (function(src, idx) {
          return function() { _modPanel.removeMod(src, idx); };
        })(m._source, m._idx) : null;
        previewCard.appendChild(buildModRowSized(m.name, m.price, '20px', removeFn));
        if (m.children && m.children.length > 0) {
          m.children.forEach(function(child) {
            var childRow = buildModRowSized(child.name, child.price, '16px');
            childRow.style.paddingLeft = '32px';
            childRow.style.color = T.verm;
            childRow.style.fontStyle = 'italic';
            previewCard.appendChild(childRow);
          });
        }
      });
    }

    if (pLeft.length > 0 || pRight.length > 0) {
      previewCard.appendChild(buildHalfTable(pLeft, pRight, '20px'));
    }

    list.appendChild(previewCard);

    // Auto-scroll to show the latest preview content
    requestAnimationFrame(function() {
      list.scrollTop = list.scrollHeight;
    });
  }

}

// ── SEPARATOR + MOD ROW helpers ───────────────────
function buildSeparator() {
  var sep = document.createElement('div');
  sep.style.cssText = 'padding:0 8px;font-family:' + T.fb + ';font-size:' + T.fsB3 + ';color:' + T.greenDk + ';letter-spacing:2px;overflow:hidden;white-space:nowrap;line-height:1;';
  sep.textContent = '- - - - - - - - - - - - - - - - - -';
  return sep;
}

function buildModRow(name, price, dark, showPrice) {
  var row = document.createElement('div');
  row.style.cssText = [
    'display:flex;justify-content:space-between;',
    'padding:2px 8px 2px 20px;',
    'font-family:' + T.fb + ';font-size:' + T.fsB3 + ';font-weight:bold;',
    'color:' + (dark ? T.well : T.gold) + ';',
  ].join('');
  var n = document.createElement('span');
  n.textContent = name;
  var p = document.createElement('span');
  p.textContent = price > 0 ? '+$' + price.toFixed(2) : '$0.00';
  row.appendChild(n);
  row.appendChild(p);
  return row;
}

function buildModRowSized(name, price, fontSize, onRemove) {
  var row = document.createElement('div');
  row.style.cssText = [
    'display:flex;align-items:center;',
    'padding:1px 8px 1px 16px;',
    'font-family:' + T.fb + ';font-size:' + fontSize + ';font-weight:bold;',
    'color:' + T.green + ';',
  ].join('');
  // Remove button (shown for unsent items)
  if (onRemove) {
    var x = document.createElement('span');
    x.style.cssText = [
      'flex-shrink:0;width:22px;height:22px;margin-right:4px;',
      'display:flex;align-items:center;justify-content:center;',
      'font-size:14px;color:' + T.verm + ';cursor:pointer;',
      'border:1px solid ' + T.verm + ';clip-path:polygon(3px 0%,calc(100% - 3px) 0%,100% 3px,100% calc(100% - 3px),calc(100% - 3px) 100%,3px 100%,0% calc(100% - 3px),0% 3px);',
    ].join('');
    x.textContent = '\u2715';
    x.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      onRemove();
    });
    row.appendChild(x);
  }
  var n = document.createElement('span');
  n.style.cssText = 'flex:1;';
  n.textContent = name;
  var p = document.createElement('span');
  p.style.cssText = 'flex-shrink:0;color:' + T.gold + ';';
  p.textContent = price > 0 ? '+$' + price.toFixed(2) : '';
  row.appendChild(n);
  if (price > 0) row.appendChild(p);
  return row;
}

function buildHalfTable(leftMods, rightMods, fontSize, removableInst) {
  var table = document.createElement('div');
  table.style.cssText = 'padding:2px 8px;';

  // Divider
  var divTop = document.createElement('div');
  divTop.style.cssText = 'display:flex;border-bottom:1px solid ' + T.greenDk + ';margin-bottom:1px;';
  var hdrL = document.createElement('div');
  hdrL.style.cssText = 'flex:1;font-family:' + T.fb + ';font-size:' + fontSize + ';font-weight:bold;color:' + T.gold + ';text-align:center;';
  hdrL.textContent = '1ST';
  var hdrSep = document.createElement('div');
  hdrSep.style.cssText = 'width:1px;background:' + T.greenDk + ';margin:0 4px;';
  var hdrR = document.createElement('div');
  hdrR.style.cssText = 'flex:1;font-family:' + T.fb + ';font-size:' + fontSize + ';font-weight:bold;color:' + T.gold + ';text-align:center;';
  hdrR.textContent = '2ND';
  divTop.appendChild(hdrL);
  divTop.appendChild(hdrSep);
  divTop.appendChild(hdrR);
  table.appendChild(divTop);

  function _makeRemoveBtn(mod) {
    var x = document.createElement('span');
    x.style.cssText = [
      'flex-shrink:0;width:18px;height:18px;margin:0 2px;',
      'display:inline-flex;align-items:center;justify-content:center;',
      'font-size:11px;color:' + T.verm + ';cursor:pointer;',
      'border:1px solid ' + T.verm + ';clip-path:polygon(3px 0%,calc(100% - 3px) 0%,100% 3px,100% calc(100% - 3px),calc(100% - 3px) 100%,3px 100%,0% calc(100% - 3px),0% 3px);',
    ].join('');
    x.textContent = '\u2715';
    x.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      var mi = removableInst.mods.indexOf(mod);
      if (mi !== -1) removableInst.mods.splice(mi, 1);
      renderTicket();
      rebuildBottomBar();
    });
    return x;
  }

  // Rows — zip left and right
  var maxRows = Math.max(leftMods.length, rightMods.length);
  for (var i = 0; i < maxRows; i++) {
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;';

    var cellL = document.createElement('div');
    cellL.style.cssText = 'flex:1;display:flex;align-items:center;font-family:' + T.fb + ';font-size:' + fontSize + ';color:' + T.green + ';padding:0 4px;';
    if (removableInst && leftMods[i]) cellL.appendChild(_makeRemoveBtn(leftMods[i]));
    var lText = document.createElement('span');
    lText.textContent = leftMods[i] ? stripPlacementPrefix(leftMods[i].name) : '';
    cellL.appendChild(lText);

    var sep = document.createElement('div');
    sep.style.cssText = 'width:1px;align-self:stretch;background:' + T.greenDk + ';margin:0 4px;flex-shrink:0;';

    var cellR = document.createElement('div');
    cellR.style.cssText = 'flex:1;display:flex;align-items:center;justify-content:flex-end;font-family:' + T.fb + ';font-size:' + fontSize + ';color:' + T.green + ';padding:0 4px;';
    var rText = document.createElement('span');
    rText.textContent = rightMods[i] ? stripPlacementPrefix(rightMods[i].name) : '';
    cellR.appendChild(rText);
    if (removableInst && rightMods[i]) cellR.appendChild(_makeRemoveBtn(rightMods[i]));

    row.appendChild(cellL);
    row.appendChild(sep);
    row.appendChild(cellR);
    table.appendChild(row);

    // Render children (exclusions) for specials in half-table
    var lChildren = (leftMods[i] && leftMods[i].children) ? leftMods[i].children : [];
    var rChildren = (rightMods[i] && rightMods[i].children) ? rightMods[i].children : [];
    var maxChildren = Math.max(lChildren.length, rChildren.length);
    for (var ci = 0; ci < maxChildren; ci++) {
      var cRow = document.createElement('div');
      cRow.style.cssText = 'display:flex;align-items:center;';
      var cL = document.createElement('div');
      cL.style.cssText = 'flex:1;font-family:' + T.fb + ';font-size:' + (parseInt(fontSize) - 4) + 'px;color:' + T.verm + ';font-style:italic;padding:0 4px 0 20px;';
      cL.textContent = lChildren[ci] ? lChildren[ci].name : '';
      var cSep = document.createElement('div');
      cSep.style.cssText = 'width:1px;align-self:stretch;background:' + T.greenDk + ';margin:0 4px;flex-shrink:0;';
      var cR = document.createElement('div');
      cR.style.cssText = 'flex:1;font-family:' + T.fb + ';font-size:' + (parseInt(fontSize) - 4) + 'px;color:' + T.verm + ';font-style:italic;padding:0 4px 0 20px;text-align:right;';
      cR.textContent = rChildren[ci] ? rChildren[ci].name : '';
      cRow.appendChild(cL);
      cRow.appendChild(cSep);
      cRow.appendChild(cR);
      table.appendChild(cRow);
    }
  }

  // Bottom divider
  var divBot = document.createElement('div');
  divBot.style.cssText = 'border-top:1px solid ' + T.greenDk + ';margin-top:1px;';
  table.appendChild(divBot);

  return table;
}

function stripPlacementPrefix(name) {
  return name;
}

// ── QUANTITY EDITOR ─────────────────────────────
function showQtyEditor(itemName, instances) {
  SceneManager.interrupt('qty-edit', {
    onConfirm: function(newQty) {
      var currentQty = instances.length;
      if (newQty === currentQty || newQty < 1) return;
      if (newQty > currentQty) {
        // Add more instances (clone from first)
        var template = instances[0];
        for (var i = 0; i < newQty - currentQty; i++) {
          ticket.push({
            id:        ++ticketSeq,
            idemKey:   _idemKey(),
            name:      template.name,
            unitPrice: template.unitPrice,
            mods:      template.mods.map(function(m) { return { name: m.name, price: m.price, charged: m.charged, prefix: m.prefix }; }),
            selected:  false,
            sent:      false,
            category:  template.category,
            seat_number: template.seat_number,
          });
        }
      } else {
        // Remove from the end (unsent only)
        var toRemove = currentQty - newQty;
        for (var j = instances.length - 1; j >= 0 && toRemove > 0; j--) {
          var idx = ticket.indexOf(instances[j]);
          if (idx !== -1) { ticket.splice(idx, 1); toRemove--; }
        }
      }
      renderTicket();
      rebuildBottomBar();
    },
    onCancel: function() {},
    params: { itemName: itemName, currentQty: instances.length },
  });
}

function _buildItemPayload(inst) {
  var payload = {
    menu_item_id: inst.name.toLowerCase().replace(/\s+/g, '_'),
    name:         inst.name,
    price:        inst.unitPrice,
    quantity:     1,
    category:     inst.category || 'general',
    seat_number:  inst.seat_number || 1,
    modifiers:    inst.mods.map(function(m) {
      return {
        name: m.name, price: m.price, modifier_price: m.price,
        charged: m.charged, prefix: m.prefix || null,
        half_price: m.half_price != null ? m.half_price : null,
      };
    }),
  };

  // Include modifier panel data for atomic ledger write (ORDER_ITEM_ADDED)
  if (inst._modPanelData) {
    var mpd = inst._modPanelData;
    payload.mandatory_selections = mpd.mandatory;
    payload.included_removals = mpd.includedRemovals;
    payload.allergens = mpd.allergens;
    payload.allergen_note = mpd.allergenNote || '';
    payload.note = mpd.note || '';
    payload.optional_modifiers = mpd.optionalModifiers.map(function(m) {
      return { prefix: m.prefix, modifier_id: m.modifierId, label: m.label, price: m.price };
    });
  }

  return payload;
}

async function handleSaveOnly() {
  if (ticket.length === 0) return;
  if (isSending) return;

  var unsentInstances = ticket.filter(function(inst) { return !inst.sent; });
  if (unsentInstances.length === 0) return;

  isSending = true;

  try {
    // Step 1 — create order if needed
    if (!currentOrderId) {
      var createRes = await fetch(API + '/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          order_type:  'quick_service',
          guest_count: (sceneParams.seatNumbers && sceneParams.seatNumbers.length) || 1,
          customer_name: null,
          server_id:   sceneParams.employeeId || null,
          server_name: sceneParams.employeeName || null,
        }),
      });
      if (!createRes.ok) throw new Error('Order create failed: ' + createRes.status);
      var created = await createRes.json();
      if (!created || !created.order_id) throw new Error('Invalid order response — missing order_id');
      currentOrderId = created.order_id;
      currentCheckNumber = created.check_number;
    }

    // Step 2 — post unsent items (seat already assigned per-item)
    var itemPromises = [];
    for (var ui = 0; ui < unsentInstances.length; ui++) {
      var inst = unsentInstances[ui];
      itemPromises.push({ inst: inst, promise: fetch(API + '/orders/' + currentOrderId + '/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': inst.idemKey || _idemKey() },
        body: JSON.stringify(_buildItemPayload(inst)),
      })});
    }
    var results = await Promise.allSettled(itemPromises.map(function(p) { return p.promise; }));
    var anyFailed = false;
    results.forEach(function(r, idx) {
      if (r.status === 'fulfilled' && r.value.ok) {
        itemPromises[idx].inst.sent = true;
      } else {
        anyFailed = true;
      }
    });
    if (anyFailed) throw new Error('Some items failed to save');

    showToast('Items saved', { bg: T.greenWarm, duration: 1500 });
  } catch (err) {
    console.warn('[KINDpos] Save failed:', err);
    showToast('Save failed', { bg: T.verm });
    throw err;
  } finally {
    isSending = false;
  }
}

async function handleSend() {
  if (ticket.length === 0) return;
  if (isSending) return;

  var unsentInstances = ticket.filter(function(inst) { return !inst.sent; });

  // All items already sent — resend to kitchen only
  if (unsentInstances.length === 0 && currentOrderId) {
    isSending = true;
    try {
      await fetch(API + '/orders/' + currentOrderId + '/send', { method: 'POST' });
      fetch(API + '/print/ticket/' + currentOrderId, { method: 'POST' })
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); })
        .catch(function(err) {
          console.warn('[KINDpos] Kitchen print failed:', err);
          showToast('Kitchen ticket print failed — check printer');
        });
      showToast('Resent to kitchen', { bg: T.greenWarm, duration: 2000 });
    } catch (err) {
      console.warn('[KINDpos] Resend failed:', err);
      showToast('Resend failed', { bg: T.verm, duration: 2000 });
    } finally {
      isSending = false;
    }
    return;
  }

  isSending = true;
  var totals = computeTicketTotals();

  try {
    // Step 1 — create order on first send, reuse on subsequent sends
    if (!currentOrderId) {
      var createRes = await fetch(API + '/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          order_type:  'quick_service',
          guest_count: (sceneParams.seatNumbers && sceneParams.seatNumbers.length) || 1,
          customer_name: null,
          server_id:   sceneParams.employeeId || null,
          server_name: sceneParams.employeeName || null,
        }),
      });
      if (!createRes.ok) throw new Error('Order create failed: ' + createRes.status);
      var created = await createRes.json();
      if (!created || !created.order_id) throw new Error('Invalid order response — missing order_id');
      currentOrderId = created.order_id;   // use the backend-generated ID
      currentCheckNumber = created.check_number;
      setSceneName(currentCheckNumber);
    }

    // Step 2 — post unsent instances (seat already assigned per-item)
    var itemPromises = [];
    for (var ui = 0; ui < unsentInstances.length; ui++) {
      var inst = unsentInstances[ui];
      itemPromises.push({ inst: inst, promise: fetch(API + '/orders/' + currentOrderId + '/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': inst.idemKey || _idemKey() },
        body: JSON.stringify(_buildItemPayload(inst)),
      })});
    }
    var results = await Promise.allSettled(itemPromises.map(function(p) { return p.promise; }));
    var anyFailed = false;
    results.forEach(function(r, idx) {
      if (r.status === 'fulfilled' && r.value.ok) {
        itemPromises[idx].inst.sent = true;
      } else {
        anyFailed = true;
        console.warn('[KINDpos] Item POST failed:', itemPromises[idx].inst.name,
          r.status === 'rejected' ? r.reason : 'HTTP ' + r.value.status);
      }
    });
    if (anyFailed) {
      renderTicket();
      throw new Error('Some items failed to send');
    }

    // Step 3 — send to kitchen + trigger kitchen ticket print
    await fetch(API + '/orders/' + currentOrderId + '/send', { method: 'POST' });

    // Mark remaining items as sent (order-level confirmation)
    ticket.forEach(function(inst) { inst.sent = true; });

    // Fire kitchen print — non-blocking, dispatcher handles retry
    fetch(API + '/print/ticket/' + currentOrderId, { method: 'POST' })
      .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); })
      .catch(function(err) {
        console.warn('[KINDpos] Kitchen print failed:', err);
        showToast('Kitchen ticket print failed — check printer');
      });

  } catch (err) {
    console.warn('[KINDpos] Send failed:', err);
    throw err;
  } finally {
    isSending = false;
  }

  // Update UI — SEND becomes RESEND, ticket shows sent state
  renderTicket();
  rebuildBottomBar();

  // Reset hex nav — ticket stays visible for PAY

}

function deepCopyTicket(src) {
  return src.map(function(inst) {
    return {
      id:        inst.id,
      idemKey:   inst.idemKey || _idemKey(),
      name:      inst.name,
      unitPrice: inst.unitPrice,
      mods:      inst.mods.map(function(m) {
        return { name: m.name, price: m.price, charged: m.charged, prefix: m.prefix || null, half_price: m.half_price != null ? m.half_price : null };
      }),
      selected:  false,   // always reset selection on copy
      sent:      inst.sent,
      category:  inst.category || null,
      seat_number: inst.seat_number,
    };
  });
}

// ── CLOSE (X button) ────────────────────────────
function handleClose() {
  OrderSummary.hide();
  SceneManager.mountWorking('check-overview', {
    checkId: currentOrderId || sceneParams.recallOrderId,
    pin: sceneParams.pin,
    employeeId: sceneParams.employeeId,
    employeeName: sceneParams.employeeName,
    returnLanding: sceneParams.returnLanding,
  });
}

// ── RECALL FROM BACKEND (open saved check) ──────
function recallFromBackend(orderId) {
  fetch(API + '/orders/' + orderId)
    .then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(order) {
      if (SceneManager.getActiveWorking() !== 'order-entry') return;
      currentOrderId = order.order_id;
      currentCheckNumber = order.check_number || null;
      if (currentCheckNumber) setSceneName(currentCheckNumber);

      // Convert backend items to frontend ticket format
      ticket = (order.items || []).map(function(item) {
        ticketSeq += 1;
        return {
          id:        ticketSeq,
          idemKey:   _idemKey(),
          name:      item.name,
          unitPrice: item.price,
          mods:      (item.modifiers || []).map(function(m) {
            return {
              name:       m.name,
              price:      m.modifier_price != null ? m.modifier_price : (m.price || 0),
              charged:    m.charged != null ? m.charged : true,
              prefix:     m.prefix || null,
              half_price: m.half_price != null ? m.half_price : null,
            };
          }),
          selected:  false,
          sent:      true,  // items from backend have already been sent
          category:  item.category || null,
          seat_number: item.seat_number || null,
        };
      });

      renderTicket();
      rebuildBottomBar();
    })
    .catch(function(err) {
      console.warn('[KINDpos] Failed to recall order:', err);
      showToast('Failed to load saved check', { bg: T.verm, duration: 2000 });
    });
}