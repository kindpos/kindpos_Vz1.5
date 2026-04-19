// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Server Landing  (Vz2.0)
//  Ported from server-landing-sm2.js — correct APIs, new theme
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { defineScene, SceneManager } from '../scene-manager.js';
import { T }                          from '../tokens.js';
import {
  buildCard,
  buildPillButton,
  buildFloatButton,
  buildSectionLabel,
  hexToRgba,
  darkenHex,
} from '../theme-manager.js';
import {
  buildSalesOverview,
  buildStatCard,
  buildTipSparkBg,
} from '../charts.js';

// ── Filter cycle ──────────────────────────────────
var FILTER_CYCLE  = { OPEN: 'CLOSED', CLOSED: 'VOID', VOID: 'OPEN' };
var FILTER_COLORS = {
  OPEN:   { color: T.green, dark: T.greenDk },
  CLOSED: { color: T.gold,  dark: T.goldDk  },
  VOID:   { color: T.verm,  dark: T.vermDk  },
};

// ── Helpers ───────────────────────────────────────
function fmt(n) {
  n = n || 0;
  var abs = Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (n < 0 ? '\u2212$' : '$') + abs;
}

function checkNum(order) {
  return order.check_number || ('C-' + String(order.order_id).slice(0, 3).toUpperCase());
}

function ordersByFilter(allOrders, filter) {
  return (allOrders || []).filter(function(o) {
    if (filter === 'OPEN')   return o.status === 'open';
    if (filter === 'CLOSED') return o.status === 'closed' || o.status === 'paid';
    if (filter === 'VOID')   return o.status === 'voided';
    return false;
  });
}

function getClosedChecks(salesData) {
  return ((salesData || {}).checks || []).filter(function(c) {
    return c.status === 'closed';
  });
}

function fmtTurnTime(minutes) {
  if (!minutes) return '0:00';
  var m = Math.floor(minutes);
  var s = Math.round((minutes - m) * 60);
  return m + ':' + String(s).padStart(2, '0');
}

// ── Data fetching ─────────────────────────────────
function fetchAllData(state) {
  var sid = encodeURIComponent((state.emp || {}).id || '');
  return Promise.all([
    fetch('/api/v1/orders/day-summary?server_id=' + sid)
      .then(function(r) { return r.json(); }).catch(function() { return {}; }),
    fetch('/api/v1/orders?server_id=' + sid)
      .then(function(r) { return r.json(); }).catch(function() { return []; }),
    fetch('/api/v1/server/shift/table-stats?server_id=' + sid)
      .then(function(r) { return r.json(); }).catch(function() { return {}; }),
    fetch('/api/v1/server/shift/checkout-status?server_id=' + sid)
      .then(function(r) { return r.json(); }).catch(function() { return { openChecks: 0, unadjustedTips: 0 }; }),
    fetch('/api/v1/config/tipout')
      .then(function(r) { return r.json(); }).catch(function() { return []; }),
  ]).then(function(results) {
    var _rawSales = results[0] || {};
    // Attach sparkData from dayparts for sparkline rendering.
    var _parts = _rawSales.dayparts || [];
    if (_parts.length > 0) {
      var _pts = _parts.map(function(p) { return p.sales || 0; });
      while (_pts.length < 7) { _pts.push(_pts[_pts.length - 1] || 0); }
      _rawSales.sparkData = _pts.slice(0, 7);
    }
    state.salesData = _rawSales;
    state.allOrders      = Array.isArray(results[1]) ? results[1] : [];
    state.tableStats     = results[2] || {};
    state.checkoutStatus = results[3] || { openChecks: 0, unadjustedTips: 0 };
    var rules = Array.isArray(results[4]) ? results[4] : [];
    state.tipoutRate = rules.reduce(function(s, r) { return s + (r.percentage || 0); }, 0) / 100;
  });
}

// ── Check tile ────────────────────────────────────
function buildCheckTile(order, isSelected, onClick) {
  var tile = document.createElement('div');
  tile.style.cssText = [
    'width:110px;height:90px;flex-shrink:0;',
    'background:' + (isSelected ? hexToRgba(T.green, 0.15) : T.well) + ';',
    'border-left:4px solid ' + (isSelected ? T.green : T.border) + ';',
    'border-radius:10px;',
    'display:flex;flex-direction:column;justify-content:space-between;',
    'padding:12px 14px;cursor:pointer;',
    'box-shadow:' + (isSelected ? '0 0 16px ' + hexToRgba(T.green, 0.25) : 'none') + ';',
    'transition:all 0.15s;',
  ].join('');

  var idEl = document.createElement('div');
  idEl.textContent   = checkNum(order);
  idEl.style.cssText = 'font-family:' + T.fh + ';font-size:14px;font-weight:700;color:' + (isSelected ? T.green : T.text) + ';letter-spacing:0.06em;';

  var guestEl = document.createElement('div');
  var guests = order.seat_count || order.guest_count || order.covers || 1;
  guestEl.textContent   = 'x' + guests;
  guestEl.style.cssText = 'font-family:' + T.fb + ';font-size:12px;color:' + T.text + ';opacity:0.6;';

  var totalEl = document.createElement('div');
  var total = order.total != null ? fmt(order.total) : fmt((order.total_cents || 0) / 100);
  totalEl.textContent   = total;
  totalEl.style.cssText = 'font-family:' + T.fh + ';font-size:16px;font-weight:700;color:' + T.gold + ';text-shadow:0 0 8px ' + hexToRgba(T.gold, 0.35) + ';';

  tile.appendChild(idEl);
  tile.appendChild(guestEl);
  tile.appendChild(totalEl);
  tile.addEventListener('pointerup', onClick);
  return tile;
}

function buildNewCheckTile(onClick) {
  var tile = document.createElement('div');
  tile.style.cssText = [
    'width:110px;height:90px;flex-shrink:0;',
    'border:1px dashed ' + hexToRgba(T.green, 0.5) + ';',
    'border-radius:10px;',
    'display:flex;align-items:center;justify-content:center;',
    'cursor:pointer;transition:background 0.1s;',
  ].join('');
  var plus = document.createElement('span');
  plus.style.cssText = 'font-family:' + T.fh + ';font-size:32px;color:' + hexToRgba(T.green, 0.6) + ';pointer-events:none;';
  plus.textContent = '+';
  tile.appendChild(plus);
  tile.addEventListener('pointerdown',  function() { tile.style.background = hexToRgba(T.green, 0.08); });
  tile.addEventListener('pointerup',    function() { tile.style.background = 'transparent'; if (onClick) onClick(); });
  tile.addEventListener('pointerleave', function() { tile.style.background = 'transparent'; });
  return tile;
}

// ── Check preview ─────────────────────────────────
function buildPreview(orders) {
  var wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:4px;';
  var combinedTotal = orders.reduce(function(s, o) {
    return s + (o.total != null ? (o.total || 0) : (o.total_cents || 0) / 100);
  }, 0);

  // Header
  var hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;padding-bottom:6px;border-bottom:1px solid ' + hexToRgba(T.border, 0.5) + ';margin-bottom:4px;';
  var hLabel = document.createElement('div');
  hLabel.style.cssText = 'font-family:' + T.fh + ';font-size:14px;font-weight:700;color:' + T.green + ';letter-spacing:0.08em;';
  hLabel.textContent   = orders.length > 1 ? orders.length + ' CHECKS' : checkNum(orders[0]);
  var hTotal = document.createElement('div');
  hTotal.style.cssText = 'font-family:' + T.fh + ';font-size:14px;font-weight:700;color:' + T.gold + ';text-shadow:0 0 8px ' + hexToRgba(T.gold, 0.4) + ';';
  hTotal.textContent   = fmt(combinedTotal);
  hdr.appendChild(hLabel);
  hdr.appendChild(hTotal);
  wrap.appendChild(hdr);

  orders.forEach(function(order, oi) {
    if (orders.length > 1) {
      var sub = document.createElement('div');
      sub.style.cssText = 'font-family:' + T.fh + ';font-size:11px;color:' + T.green + ';letter-spacing:0.06em;margin-top:4px;';
      sub.textContent   = checkNum(order);
      wrap.appendChild(sub);
    }
    var items = order.items || [];
    items.slice(0, 4).forEach(function(item) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid ' + hexToRgba(T.border, 0.3) + ';';
      var nm = document.createElement('span');
      nm.style.cssText  = 'font-family:' + T.fb + ';font-size:11px;color:' + T.text + ';';
      nm.textContent    = item.name || item.menu_item_name || 'Item';
      var pr = document.createElement('span');
      pr.style.cssText  = 'font-family:' + T.fb + ';font-size:11px;color:' + T.gold + ';';
      pr.textContent    = fmt(item.price || (item.price_cents || 0) / 100);
      row.appendChild(nm);
      row.appendChild(pr);
      wrap.appendChild(row);
    });
    if (items.length > 4) {
      var more = document.createElement('div');
      more.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.text + ';opacity:0.5;padding-top:2px;';
      more.textContent   = '+ ' + (items.length - 4) + ' more';
      wrap.appendChild(more);
    }
  });
  return wrap;
}

// ── Tip row ───────────────────────────────────────
function buildTipRow(chk, onTap) {
  var adjusted = chk.adjusted;
  var row = document.createElement('div');
  row.style.cssText = [
    'display:flex;align-items:center;gap:10px;',
    'padding:8px 6px;border-radius:6px;cursor:pointer;',
    'background:' + (adjusted ? hexToRgba(T.green, 0.06) : 'transparent') + ';',
    'transition:background 0.12s;',
  ].join('');

  var dot = document.createElement('div');
  dot.style.cssText = [
    'width:8px;height:8px;border-radius:50%;flex-shrink:0;transition:all 0.12s;',
    'background:' + (adjusted ? T.green : 'transparent') + ';',
    'border:1.5px solid ' + (adjusted ? T.green : T.border) + ';',
    'box-shadow:' + (adjusted ? '0 0 6px ' + T.green : 'none') + ';',
  ].join('');

  var idEl = document.createElement('div');
  idEl.textContent   = chk.checkLabel || checkNum({ order_id: chk.checkId }) || 'CHK';
  idEl.style.cssText = 'font-family:' + T.fh + ';font-size:12px;color:' + T.text + ';flex:1;letter-spacing:0.06em;';

  var amtEl = document.createElement('div');
  amtEl.textContent   = fmt(chk.amount || 0);
  amtEl.style.cssText = 'font-family:' + T.fb + ';font-size:11px;color:' + T.text + ';opacity:0.7;';

  var tipEl = document.createElement('div');
  tipEl.textContent   = adjusted ? fmt(chk.tip || 0) : '—';
  tipEl.style.cssText = 'font-family:' + T.fb + ';font-size:11px;min-width:44px;text-align:right;color:' + (adjusted ? T.green : T.border) + ';';

  row.appendChild(dot);
  row.appendChild(idEl);
  row.appendChild(amtEl);
  row.appendChild(tipEl);

  row.addEventListener('pointerdown',  function() { row.style.background = hexToRgba(T.green, 0.1); });
  row.addEventListener('pointerup',    function() {
    row.style.background = adjusted ? hexToRgba(T.green, 0.06) : 'transparent';
    if (onTap) onTap(chk);
  });
  row.addEventListener('pointerleave', function() {
    row.style.background = adjusted ? hexToRgba(T.green, 0.06) : 'transparent';
  });
  return row;
}

// ═══════════════════════════════════════════════════
//  SCENE
// ═══════════════════════════════════════════════════

defineScene({
  name: 'server-landing',

  state: {
    filter:      'OPEN',
    allOrders:   [],
    salesData:   {},
    tableStats:  {},
    checkoutStatus: { openChecks: 0, unadjustedTips: 0 },
    tipoutRate:  0,
    selectedIds: [],
    emp:         null,
    _refreshing: false,
    el:          null,

    // Refs to live-update DOM elements
    _refs: {},
  },

  render: function(container, params, state) {
    state.emp = params.staff || params.emp || params || {};
    state.el  = container;

    // ── Root grid ──────────────────────────────────
    var root = document.createElement('div');
    root.style.cssText = [
      'position:absolute;inset:0;',
      'background:' + T.bg + ';',
      'display:grid;',
      'grid-template-columns:300px 1fr 1fr;',
      'grid-template-rows:1fr 250px;',
      'gap:10px;padding:28px 10px 32px;',
      'box-sizing:border-box;overflow:visible;',
      'font-family:' + T.fb + ';',
    ].join('');
    container.appendChild(root);

    // ─────────────────────────────────────────────
    //  LEFT COLUMN (spans both rows)
    // ─────────────────────────────────────────────
    var leftCol = document.createElement('div');
    leftCol.style.cssText = 'grid-column:1;grid-row:1/3;display:flex;flex-direction:column;gap:10px;overflow:visible;';
    root.appendChild(leftCol);

    // ── Check preview (collapses when nothing selected) ──
    var previewSlide = document.createElement('div');
    previewSlide.style.cssText = 'max-height:0;overflow:hidden;transition:max-height 0.25s ease;flex-shrink:0;';
    leftCol.appendChild(previewSlide);

    var prevResult = buildCard({ accent: T.green, padding: '12px 14px' });
    previewSlide.appendChild(prevResult.wrap);

    var prevLabel = buildSectionLabel('Check Preview');
    prevLabel.style.marginBottom = '10px';
    prevResult.card.appendChild(prevLabel);

    var prevContent = document.createElement('div');
    prevResult.card.appendChild(prevContent);

    var optionsBtn = buildPillButton({ label: 'Options', color: T.gold, darkBg: T.goldDk });
    optionsBtn.style.width      = '100%';
    optionsBtn.style.marginTop  = '10px';
    optionsBtn.style.display    = 'none';
    prevResult.card.appendChild(optionsBtn);

    var optionsGrid = document.createElement('div');
    optionsGrid.style.cssText = 'display:none;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;';
    ['Fire','Void','Split','Discount','Transfer','Print'].forEach(function(opt) {
      var b = buildPillButton({
        label:  opt,
        color:  opt === 'Void' ? T.verm : T.border,
        darkBg: opt === 'Void' ? T.vermDk : darkenHex(T.border, 0.3),
      });
      b.style.cssText += 'font-size:14px;padding:8px 10px;';
      optionsGrid.appendChild(b);
    });
    prevResult.card.appendChild(optionsGrid);

    var _optOpen = false;
    optionsBtn.addEventListener('pointerup', function() {
      _optOpen = !_optOpen;
      optionsBtn.textContent    = _optOpen ? '✕ Close' : 'Options';
      optionsGrid.style.display = _optOpen ? 'grid' : 'none';
    });

    // ── Tip queue (always visible) ──
    var tipOuter = document.createElement('div');
    tipOuter.style.cssText = 'flex:1;position:relative;overflow:visible;display:flex;flex-direction:column;';
    leftCol.appendChild(tipOuter);

    var tipResult = buildCard({ accent: T.green, flex: '1', padding: '0' });
    tipResult.wrap.style.flex   = '1';
    tipResult.card.style.display       = 'flex';
    tipResult.card.style.flexDirection = 'column';
    tipResult.card.style.overflow      = 'hidden';
    tipResult.card.style.position      = 'relative';
    tipOuter.appendChild(tipResult.wrap);

    // Tip accumulation sparkline background
    var tipSparkBg = buildTipSparkBg({ data: [0] });
    tipResult.card.insertBefore(tipSparkBg.el, tipResult.card.firstChild);

    // Tips header
    var tipHdr = document.createElement('div');
    tipHdr.style.cssText = 'padding:12px 14px 8px;border-bottom:1px solid ' + hexToRgba(T.border, 0.4) + ';flex-shrink:0;';

    var tipHdrRow = document.createElement('div');
    tipHdrRow.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;';
    var tipHdrLabel = buildSectionLabel('Tip Queue', T.text);
    var unadjBadge  = document.createElement('div');
    unadjBadge.style.cssText = 'font-family:' + T.fb + ';font-size:14px;color:' + T.verm + ';letter-spacing:0.1em;display:none;';
    tipHdrRow.appendChild(tipHdrLabel);
    tipHdrRow.appendChild(unadjBadge);
    tipHdr.appendChild(tipHdrRow);

    var tipsTotal = document.createElement('div');
    tipsTotal.style.cssText = 'font-family:' + T.fh + ';font-size:28px;font-weight:700;color:' + T.gold + ';text-shadow:0 0 14px ' + hexToRgba(T.gold, 0.4) + ';';
    tipsTotal.textContent   = '$0.00';
    tipHdr.appendChild(tipsTotal);
    tipResult.card.appendChild(tipHdr);

    // Scrollable tip rows
    var tipList = document.createElement('div');
    tipList.style.cssText = 'flex:1;overflow-y:auto;padding:6px 10px;display:flex;flex-direction:column;gap:2px;';
    tipResult.card.appendChild(tipList);

    // Checkout float button
    var checkoutBtn = buildFloatButton({ label: 'Checkout', color: T.green, darkBg: T.greenDk });
    checkoutBtn.style.cssText += 'position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);';
    tipOuter.appendChild(checkoutBtn);

    // ─────────────────────────────────────────────
    //  CHECK GRID (cols 2-3, row 1)
    // ─────────────────────────────────────────────
    var gridOuter = document.createElement('div');
    gridOuter.style.cssText = 'grid-column:2/4;grid-row:1;position:relative;overflow:visible;';
    root.appendChild(gridOuter);

    var gridResult = buildCard({ accent: T.green, padding: '14px 14px 14px', flex: '1' });
    gridResult.wrap.style.height           = '100%';
    gridResult.card.style.height           = '100%';
    gridResult.card.style.boxSizing        = 'border-box';
    gridResult.card.style.overflow         = 'visible';
    gridOuter.appendChild(gridResult.wrap);

    var tileGrid = document.createElement('div');
    tileGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;align-content:flex-start;height:100%;';
    gridResult.card.appendChild(tileGrid);

    // OPEN/CLOSED/VOID float toggle
    var filterBtn = buildFloatButton({ label: 'OPEN', color: T.green, darkBg: T.greenDk });
    filterBtn.style.cssText += 'position:absolute;top:-18px;right:16px;';
    gridOuter.appendChild(filterBtn);

    // ─────────────────────────────────────────────
    //  TABLE STATS (col 2, row 2)
    // ─────────────────────────────────────────────
    var statsResult = buildCard({ accent: T.elec, padding: '12px 14px' });
    statsResult.wrap.style.gridColumn = '2';
    statsResult.wrap.style.gridRow    = '2';
    root.appendChild(statsResult.wrap);

    var statsLbl = buildSectionLabel('Table Stats', T.text);
    statsLbl.style.marginBottom = '8px'; statsLbl.style.fontSize = '16px';
    statsResult.card.appendChild(statsLbl);

    var statsGrid = document.createElement('div');
    statsGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px;flex:1;min-height:0;overflow:hidden;';
    statsResult.card.appendChild(statsGrid);

    var scGuests = buildStatCard({ title: 'Guests',  value: '0',     color: T.text, delta: '' });
    var scAvg    = buildStatCard({ title: 'Chk Avg', value: '$0.00', color: T.gold, delta: '' });
    var scTables = buildStatCard({ title: 'Tables',  value: '0',     color: T.elec, delta: '' });
    var scTurn   = buildStatCard({ title: 'Turn',    value: '0:00',  color: T.elec, delta: '' });
    [scGuests, scAvg, scTables, scTurn].forEach(function(s) { statsGrid.appendChild(s.wrap); });

    // ─────────────────────────────────────────────
    //  SALES OVERVIEW (col 3, row 2)
    // ─────────────────────────────────────────────
    var salesResult = buildCard({ accent: T.gold, padding: '12px 14px' });
    salesResult.wrap.style.gridColumn = '3';
    salesResult.wrap.style.gridRow    = '2';
    root.appendChild(salesResult.wrap);

    var salesLbl = buildSectionLabel('Sales Overview', T.text);
    salesLbl.style.marginBottom = '6px'; salesLbl.style.fontSize = '16px';
    salesResult.card.appendChild(salesLbl);

    var srvSalesOverview = buildSalesOverview({ netSales: 0, cash: 0, card: 0 });
    salesResult.card.appendChild(srvSalesOverview.wrap);

    // Store refs for live updates
    state._refs = {
      tileGrid, previewSlide, prevContent, optionsBtn, optionsGrid,
      tipList, tipsTotal, unadjBadge, tipResult, checkoutBtn, filterBtn,
      tipSparkBg, scGuests, scAvg, scTables, scTurn, srvSalesOverview,
    };

    // ─────────────────────────────────────────────
    //  RENDER FUNCTIONS
    // ─────────────────────────────────────────────

    function renderTiles() {
      var r = state._refs;
      r.tileGrid.innerHTML = '';
      var visible = ordersByFilter(state.allOrders, state.filter);
      visible.forEach(function(order) {
        var id = order.order_id;
        var selected = state.selectedIds.indexOf(id) !== -1;
        r.tileGrid.appendChild(buildCheckTile(order, selected, function() {
          var idx = state.selectedIds.indexOf(id);
          if (idx === -1) state.selectedIds.push(id);
          else state.selectedIds.splice(idx, 1);
          renderTiles();
          renderPreview();
        }));
      });
      if (state.filter === 'OPEN') {
        r.tileGrid.appendChild(buildNewCheckTile(function() {
          SceneManager.mountWorking('check-overview', {
            checkId:       null,
            returnLanding: 'server-landing',
            employeeId:    state.emp ? state.emp.id   : null,
            employeeName:  state.emp ? state.emp.name : null,
            pin:           state.emp ? state.emp.pin  : null,
          });
        }));
      }
      if (visible.length === 0 && state.filter !== 'OPEN') {
        var empty = document.createElement('div');
        empty.textContent   = 'No ' + state.filter.toLowerCase() + ' checks';
        empty.style.cssText = 'font-family:' + T.fb + ';font-size:14px;color:' + T.border + ';letter-spacing:0.14em;padding:8px 4px;';
        r.tileGrid.appendChild(empty);
      }
    }

    function renderPreview() {
      var r = state._refs;
      r.prevContent.innerHTML = '';
      _optOpen = false;
      r.optionsGrid.style.display = 'none';
      r.optionsBtn.textContent    = 'Options';

      if (state.selectedIds.length === 0) {
        r.previewSlide.style.maxHeight = '0';
        r.optionsBtn.style.display     = 'none';
        return;
      }

      var selected = state.allOrders.filter(function(o) {
        return state.selectedIds.indexOf(o.order_id) !== -1;
      });
      if (selected.length > 0) r.prevContent.appendChild(buildPreview(selected));
      r.optionsBtn.style.display     = 'block';
      r.previewSlide.style.maxHeight = '320px';
    }

    function renderTips() {
      var r     = state._refs;
      var checks = getClosedChecks(state.salesData);
      r.tipList.innerHTML = '';

      if (checks.length === 0) {
        var empty = document.createElement('div');
        empty.textContent   = 'No closed checks yet';
        empty.style.cssText = 'font-family:' + T.fb + ';font-size:14px;color:' + T.border + ';text-align:center;padding:16px 0;letter-spacing:0.12em;';
        r.tipList.appendChild(empty);
        r.tipsTotal.textContent = '$0.00';
        r.unadjBadge.style.display = 'none';
        updateCheckout(0, checks.length);
        return;
      }

      var total  = 0;
      var unadj  = 0;
      checks.forEach(function(chk) {
        if (chk.adjusted) total += (chk.tip || 0);
        else unadj++;
        r.tipList.appendChild(buildTipRow(chk, function(c) {
          SceneManager.openTransactional('tip-adjustment', {
            check: c,
            onAdjusted: function() { refresh(); },
          });
        }));
      });

      r.tipsTotal.textContent = fmt(total);
      r.tipResult.card.style.borderLeft = '4px solid ' + (unadj > 0 ? T.verm : T.green);
      r.unadjBadge.textContent   = unadj > 0 ? (unadj + ' unadj') : '';
      r.unadjBadge.style.display = unadj > 0 ? 'block' : 'none';

      updateCheckout(unadj, state.checkoutStatus.openChecks || ordersByFilter(state.allOrders, 'OPEN').length);
    }

    function updateCheckout(unadj, openCount) {
      var btn = state._refs.checkoutBtn;
      var canGo = openCount === 0 && unadj === 0;
      if (canGo) {
        btn.setColor(T.green, T.greenDk);
        btn.textContent = 'Checkout';
      } else if (unadj > 0) {
        btn.setColor(T.verm, T.vermDk);
        btn.textContent = unadj + ' Unadj';
      } else {
        btn.setColor(T.border, darkenHex(T.border, 0.3));
        btn.textContent = 'Open Checks';
      }
    }

    function renderStats() {
      var ts = state.tableStats || {};
      var sd = state.salesData  || {};
      var r  = state._refs;

      r.scGuests.setValue(ts.guestCount   != null ? String(ts.guestCount)   : '0');
      r.scAvg.setValue(ts.checkAvg        != null ? fmt(ts.checkAvg)        : '$0.00');
      r.scTables.setValue(ts.tableCount   != null ? String(ts.tableCount)   : '0');
      r.scTurn.setValue(ts.avgTurnMinutes ? fmtTurnTime(ts.avgTurnMinutes)   : '0:00');

      r.srvSalesOverview.update(
        sd.net_sales  || 0,
        sd.cash_sales || sd.cash_total || 0,
        sd.card_sales || sd.card_total || 0,
        sd.net_sales > 0 ? '▲ vs yesterday' : '',
        sd.sparkData  || null
      );

      // Update tip sparkline with cumulative tip data if available
      var closedChecks = ((sd.checks || [])).filter(function(c) { return c.status === 'closed'; });
      if (closedChecks.length > 1) {
        var cumulative = [];
        var running = 0;
        closedChecks.forEach(function(c) { running += c.tip || 0; cumulative.push(running); });
        r.tipSparkBg.update(cumulative);
      }
    }

    // ─────────────────────────────────────────────
    //  FILTER TOGGLE
    // ─────────────────────────────────────────────
    filterBtn.addEventListener('pointerup', function() {
      state.filter      = FILTER_CYCLE[state.filter];
      state.selectedIds = [];
      var fc = FILTER_COLORS[state.filter];
      state._refs.filterBtn.textContent = state.filter;
      state._refs.filterBtn.setColor(fc.color, fc.dark);
      renderTiles();
      renderPreview();
    });

    // ─────────────────────────────────────────────
    //  CHECKOUT
    //  The button label + color in updateCheckout() communicates blocker
    //  state ("N Unadj" / "Open Checks" / "Checkout"), but navigation is
    //  always permitted — server-checkout owns the blocker resolution UI
    //  (banner, open-checks card, unadjusted-tips card). Gating access
    //  here would prevent the server from reaching the very scene that
    //  resolves the blockers.
    // ─────────────────────────────────────────────
    checkoutBtn.addEventListener('pointerup', function() {
      SceneManager.mountWorking('server-checkout', { staff: state.emp });
    });

    // ─────────────────────────────────────────────
    //  DATA + REFRESH
    // ─────────────────────────────────────────────
    function refresh() {
      if (state._refreshing || !state.el) return;
      state._refreshing = true;
      fetchAllData(state).then(function() {
        state._refreshing = false;
        if (!state.el) return;
        renderTiles();
        renderPreview();
        renderTips();
        renderStats();
      }).catch(function() { state._refreshing = false; });
    }

    // Initial load
    refresh();

    // Scene bus events
    SceneManager.on('order:updated', refresh);
    SceneManager.on('order:closed',  refresh);
    SceneManager.on('tip:adjusted',  refresh);

    return function cleanup() {
      state.el = null;
      SceneManager.off('order:updated', refresh);
      SceneManager.off('order:closed',  refresh);
      SceneManager.off('tip:adjusted',  refresh);
    };
  },
});