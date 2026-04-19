// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Manager Landing  (Vz2.0)
//  Ported from manager-landing-sm2.js — new theme, new layout
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
import { showToast } from '../components.js';
import {
  buildSalesOverview,
  buildLineCard,
  buildCOBCard,
} from '../charts.js';

// ── Server color palette ──────────────────────────
var SRV_PALETTE = [
  '#38bdf8', // sky
  '#a78bfa', // violet
  '#fb923c', // peach
  '#34d399', // emerald
  '#facc15', // yellow
  '#f472b6', // pink
  '#e879f9', // fuchsia
  '#4ade80', // green
];

// ── Helpers ───────────────────────────────────────
function fmt(n) {
  n = n || 0;
  var abs = Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return (n < 0 ? '\u2212$' : '$') + abs;
}

function checkNum(order) {
  return order.check_number || ('C-' + String(order.order_id).slice(0, 3).toUpperCase());
}

function ordersByFilter(allOrders, filter, serverId) {
  return (allOrders || []).filter(function(o) {
    var statusOk = false;
    if (filter === 'OPEN')   statusOk = o.status === 'open';
    if (filter === 'CLOSED') statusOk = o.status === 'closed' || o.status === 'paid';
    if (filter === 'VOID')   statusOk = o.status === 'voided';
    if (!statusOk) return false;
    if (serverId && o.server_id !== serverId) return false;
    return true;
  });
}

// ── Filter cycles ─────────────────────────────────
var STATUS_CYCLE  = { OPEN: 'CLOSED', CLOSED: 'VOID', VOID: 'OPEN' };
var STATUS_COLORS = {
  OPEN:   { color: T.green, dark: T.greenDk },
  CLOSED: { color: T.gold,  dark: T.goldDk  },
  VOID:   { color: T.verm,  dark: T.vermDk  },
};

// ── Data fetching ─────────────────────────────────
function fetchAllData(state) {
  var today = new Date();
  var dateStr = today.getFullYear() + '-' +
    String(today.getMonth() + 1).padStart(2, '0') + '-' +
    String(today.getDate()).padStart(2, '0');

  return Promise.all([
    fetch('/api/v1/orders/day-summary')
      .then(function(r) { return r.json(); }).catch(function() { return {}; }),
    fetch('/api/v1/orders')
      .then(function(r) { return r.json(); }).catch(function() { return []; }),
    fetch('/api/v1/servers/clocked-in')
      .then(function(r) { return r.json(); }).catch(function() { return { staff: [] }; }),
    fetch('/api/v1/reports/labor-summary?date=' + dateStr)
      .then(function(r) { return r.json(); }).catch(function() { return {}; }),
  ]).then(function(results) {
    var daySummary  = results[0] || {};
    var orders      = Array.isArray(results[1]) ? results[1] : [];
    var staffResult = results[2] || {};
    var laborData   = results[3] || {};

    _wireSalesData(state, daySummary, orders, laborData);
    _wireOrders(state, orders);
    _wireStaffData(state, staffResult, orders);
    _wireCloseDayData(state, daySummary);
    _wireServerColors(state, staffResult);
  });
}

function _wireSalesData(state, day, orders, labor) {
  // Build sparkline from dayparts (AM / PM / Late), padded to 7 points.
  var sparkData = null;
  var parts = day.dayparts || [];
  if (parts.length > 0) {
    var pts = parts.map(function(p) { return p.sales || 0; });
    while (pts.length < 7) { pts.push(pts[pts.length - 1] || 0); }
    sparkData = pts.slice(0, 7);
  }

  state.salesData = {
    net_sales:     day.net_sales    || 0,
    cash_total:    day.cash_total   || 0,
    card_total:    day.card_total   || 0,
    avg_check:     day.check_avg    || day.avg_check || 0,
    total_covers:  day.guest_count  || 0,
    active_checks: (orders || []).filter(function(o) { return o.status === 'open'; }).length,
    labor_cob:     labor.cob_percent || 0,
    labor_hours:   labor.total_hours || 0,
    labor_cost:    labor.labor_cost  || 0,
    staff_count:   labor.staff_count || 0,
    sparkData:     sparkData,
  };
}

function _wireOrders(state, orders) {
  state.allOrders = (orders || []).map(function(o) {
    return {
      order_id:      o.order_id,
      check_number:  o.check_number || ('C-' + String(o.order_id).slice(0, 3).toUpperCase()),
      server_id:     o.server_id   || '',
      server_name:   o.server_name || '',
      customer_name: o.customer_name || o.table || '',
      status:        o.status,
      items:         o.items    || [],
      payments:      o.payments || [],
      total:         o.total    || o.subtotal || 0,
      seat_count:    o.seat_count || o.covers || o.guest_count || 1,
    };
  });
}

function _wireStaffData(state, staffResult, orders) {
  var staff = (staffResult.staff || []);
  state.staffData = {
    servers: staff.map(function(s) {
      var myOrders  = (orders || []).filter(function(o) { return o.server_id === s.employee_id; });
      var open      = myOrders.filter(function(o) { return o.status === 'open'; });
      var closed    = myOrders.filter(function(o) { return o.status === 'closed' || o.status === 'paid'; });
      var unadj = 0;
      closed.forEach(function(o) {
        (o.payments || []).forEach(function(p) {
          if (p.method === 'card' && p.status === 'confirmed' && p.tip_amount == null) unadj++;
        });
      });
      return {
        id:             s.employee_id,
        name:           s.employee_name || s.name || '',
        open_tables:    open.length,
        closed_checks:  closed.length,
        unadj_tips:     unadj,
        checked_out:    false,
      };
    }),
  };
}

function _wireCloseDayData(state, day) {
  var servers     = ((state.staffData || {}).servers || []);
  var pending     = servers.filter(function(s) { return !s.checked_out; }).length;
  var unadj       = servers.reduce(function(s, srv) { return s + srv.unadj_tips; }, 0);
  var allOut      = servers.length > 0 && pending === 0;
  var allAdj      = unadj === 0;
  state.closeDayData = {
    all_checked_out:   allOut,
    pending_count:     pending,
    all_tips_adjusted: allAdj,
    unadjusted_count:  unadj,
    batch_ready:       allOut && allAdj,
  };
}

function _wireServerColors(state, staffResult) {
  var staff = staffResult.staff || [];
  state.serverColorMap = {};
  staff.forEach(function(s, i) {
    state.serverColorMap[s.employee_id] = SRV_PALETTE[i % SRV_PALETTE.length];
  });
}

// ── Check tile ────────────────────────────────────
function _buildCheckTile(order, isSelected, srvColor, onClick, onLongPress, filterColor) {
  var tile = document.createElement('div');
  tile.style.cssText = [
    'width:140px;height:120px;flex-shrink:0;',
    'background:' + (isSelected ? hexToRgba(T.green, 0.12) : T.well) + ';',
    'border-left:4px solid ' + (isSelected ? T.green : (filterColor || srvColor || T.border)) + ';',
    'border-radius:10px;',
    'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;',
    'padding:10px 12px;cursor:pointer;text-align:center;',
    'box-shadow:' + (isSelected ? '0 0 14px ' + hexToRgba(T.green, 0.2) : 'none') + ';',
    'transition:all 0.15s;',
    'pointer-events:auto;touch-action:manipulation;',
  ].join('');

  var idEl = document.createElement('div');
  idEl.textContent   = checkNum(order);
  idEl.style.cssText = 'font-family:' + T.fh + ';font-size:18px;font-weight:700;color:' + (isSelected ? T.green : T.text) + ';letter-spacing:0.06em;';

  var srvEl = document.createElement('div');
  var srvName = (order.server_name || order.server_id || '').split(' ')[0].toUpperCase();
  srvEl.textContent   = srvName;
  srvEl.style.cssText = 'font-family:' + T.fb + ';font-size:12px;color:' + (srvColor || T.elec) + ';opacity:0.9;letter-spacing:0.04em;';

  var cvrEl = document.createElement('div');
  cvrEl.textContent   = 'x' + (order.seat_count || 1);
  cvrEl.style.cssText = 'font-family:' + T.fb + ';font-size:12px;color:' + T.text + ';opacity:0.55;';

  var amtEl = document.createElement('div');
  amtEl.textContent   = fmt(order.total || 0);
  amtEl.style.cssText = 'font-family:' + T.fh + ';font-size:22px;font-weight:700;color:' + T.gold + ';text-shadow:0 0 8px ' + hexToRgba(T.gold, 0.3) + ';margin-top:2px;';

  tile.appendChild(idEl);
  tile.appendChild(srvEl);
  tile.appendChild(cvrEl);
  tile.appendChild(amtEl);

  // Tap = select/deselect (via onClick). Long-press (550ms) = rename.
  var lpTimer = null;
  var didLongPress = false;
  tile.addEventListener('pointerdown', function() {
    didLongPress = false;
    lpTimer = setTimeout(function() {
      didLongPress = true;
      if (onLongPress) onLongPress(order);
    }, 550);
  });
  tile.addEventListener('pointerup', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    if (didLongPress) { didLongPress = false; return; }
    if (onClick) onClick();
  });
  tile.addEventListener('pointerleave', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    didLongPress = false;
  });
  tile.addEventListener('pointercancel', function() {
    if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; }
    didLongPress = false;
  });

  return tile;
}

function _buildNewTile(onClick) {
  var tile = document.createElement('div');
  tile.style.cssText = 'width:110px;height:90px;flex-shrink:0;border:1px dashed ' + hexToRgba(T.green, 0.4) + ';border-radius:10px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:background 0.1s;';
  var plus = document.createElement('span');
  plus.style.cssText = 'font-family:' + T.fh + ';font-size:28px;color:' + hexToRgba(T.green, 0.5) + ';pointer-events:none;';
  plus.textContent = '+';
  tile.appendChild(plus);
  tile.addEventListener('pointerdown',  function() { tile.style.background = hexToRgba(T.green, 0.08); });
  tile.addEventListener('pointerup',    function() { tile.style.background = 'transparent'; if (onClick) onClick(); });
  tile.addEventListener('pointerleave', function() { tile.style.background = 'transparent'; });
  return tile;
}

// ── Check preview ─────────────────────────────────
function _buildPreview(orders, allOrders) {
  var wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:4px;';

  var total = orders.reduce(function(s, o) { return s + (o.total || 0); }, 0);
  var hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;padding-bottom:6px;border-bottom:1px solid ' + hexToRgba(T.border, 0.4) + ';margin-bottom:4px;';
  var hLabel = document.createElement('div');
  hLabel.style.cssText = 'font-family:' + T.fh + ';font-size:14px;font-weight:700;color:' + T.green + ';letter-spacing:0.08em;';
  hLabel.textContent   = orders.length > 1 ? orders.length + ' CHECKS' : checkNum(orders[0]);
  var hTotal = document.createElement('div');
  hTotal.style.cssText = 'font-family:' + T.fh + ';font-size:14px;font-weight:700;color:' + T.gold + ';';
  hTotal.textContent   = fmt(total);
  hdr.appendChild(hLabel);
  hdr.appendChild(hTotal);
  wrap.appendChild(hdr);

  orders.forEach(function(order) {
    if (orders.length > 1) {
      var sub = document.createElement('div');
      sub.style.cssText = 'font-family:' + T.fh + ';font-size:11px;color:' + T.green + ';letter-spacing:0.06em;margin-top:4px;';
      sub.textContent   = checkNum(order) + (order.server_name ? ' · ' + order.server_name.split(' ')[0] : '');
      wrap.appendChild(sub);
    } else if (order.server_name) {
      var srvLbl = document.createElement('div');
      srvLbl.style.cssText = 'font-family:' + T.fb + ';font-size:11px;color:' + T.elec + ';margin-bottom:4px;';
      srvLbl.textContent   = order.server_name.toUpperCase();
      wrap.appendChild(srvLbl);
    }

    (order.items || []).slice(0, 3).forEach(function(item) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid ' + hexToRgba(T.border, 0.2) + ';';
      var nm  = document.createElement('span'); nm.style.cssText  = 'font-family:' + T.fb + ';font-size:11px;color:' + T.text + ';'; nm.textContent  = item.name || 'Item';
      var pr  = document.createElement('span'); pr.style.cssText  = 'font-family:' + T.fb + ';font-size:11px;color:' + T.gold + ';';  pr.textContent  = fmt(item.price || 0);
      row.appendChild(nm); row.appendChild(pr);
      wrap.appendChild(row);
    });
    if ((order.items || []).length > 3) {
      var more = document.createElement('div');
      more.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.text + ';opacity:0.5;padding-top:2px;';
      more.textContent   = '+ ' + (order.items.length - 3) + ' more';
      wrap.appendChild(more);
    }
  });

  return wrap;
}

// ── Gate row ──────────────────────────────────────
function _buildGateRow(met, label) {
  var row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:8px;';
  var icon = document.createElement('span');
  icon.style.cssText  = 'font-size:16px;color:' + (met ? T.green : T.verm) + ';';
  icon.textContent    = met ? '✓' : '✗';
  var text = document.createElement('span');
  text.style.cssText  = 'font-family:' + T.fh + ';font-size:13px;font-weight:700;color:' + (met ? T.green : T.verm) + ';';
  text.textContent    = label;
  row.appendChild(icon);
  row.appendChild(text);
  return { row: row, icon: icon, text: text, setMet: function(v, l) {
    icon.textContent   = v ? '✓' : '✗';
    icon.style.color   = v ? T.green : T.verm;
    text.textContent   = l || label;
    text.style.color   = v ? T.green : T.verm;
  }};
}

// ── Server checkout row ───────────────────────────
function _buildServerRow(srv, onClick) {
  var isDone = srv.checked_out;
  var hasIssue = !isDone && (srv.open_tables > 0 || srv.unadj_tips > 0);
  var borderColor = isDone ? T.elec : hasIssue ? T.verm : T.green;

  var row = document.createElement('div');
  row.style.cssText = [
    'display:flex;align-items:center;justify-content:space-between;',
    'padding:5px 8px;border-radius:6px;',
    'background:' + T.well + ';',
    'border-left:3px solid ' + borderColor + ';',
    'cursor:' + (isDone ? 'default' : 'pointer') + ';',
    'transition:background 0.1s;',
  ].join('');

  var name = document.createElement('div');
  name.style.cssText = 'font-family:' + T.fh + ';font-size:14px;font-weight:700;color:' + T.text + ';';
  name.textContent   = srv.name;

  var badges = document.createElement('div');
  badges.style.cssText = 'display:flex;gap:8px;align-items:center;';

  if (isDone) {
    var doneBdg = document.createElement('span');
    doneBdg.style.cssText = 'font-family:' + T.fb + ';font-size:11px;color:' + T.elec + ';font-weight:700;letter-spacing:0.08em;';
    doneBdg.textContent   = '✓ checked out';
    badges.appendChild(doneBdg);
  } else {
    var openBdg = document.createElement('span');
    openBdg.style.cssText = 'font-family:' + T.fb + ';font-size:11px;letter-spacing:0.06em;color:' + (srv.open_tables > 0 ? T.verm : T.green) + ';';
    openBdg.textContent   = srv.open_tables + ' open';

    var unadjBdg = document.createElement('span');
    unadjBdg.style.cssText = 'font-family:' + T.fb + ';font-size:11px;letter-spacing:0.06em;color:' + (srv.unadj_tips > 0 ? T.verm : T.green) + ';';
    unadjBdg.textContent   = srv.unadj_tips + ' unadj';

    badges.appendChild(openBdg);
    badges.appendChild(unadjBdg);
  }

  row.appendChild(name);
  row.appendChild(badges);

  if (!isDone) {
    row.addEventListener('pointerdown',  function() { row.style.background = hexToRgba(T.green, 0.08); });
    row.addEventListener('pointerup',    function() { row.style.background = T.well; if (onClick) onClick(srv); });
    row.addEventListener('pointerleave', function() { row.style.background = T.well; });
  }

  return row;
}

// ═══════════════════════════════════════════════════
//  SCENE
// ═══════════════════════════════════════════════════

defineScene({
  name: 'manager-landing',

  state: {
    emp:             null,
    allOrders:       [],
    salesData:       null,
    staffData:       null,
    closeDayData:    null,
    serverColorMap:  {},
    filter:          'OPEN',
    filteredServer:  null,  // null = ALL SERVERS
    selectedIds:     [],
    _refreshing:     false,
    el:              null,
    _refs:           {},
  },

  render: function(container, params, state) {
    state.emp = params.staff || params.emp || params || {};
    state.el  = container;

    // ── Root grid ──────────────────────────────────
    var root = document.createElement('div');
    root.style.cssText = [
      'position:absolute;inset:0;background:' + T.bg + ';',
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
    leftCol.style.cssText = 'grid-column:1;grid-row:1/3;display:flex;flex-direction:column;justify-content:flex-end;gap:10px;overflow:visible;';
    root.appendChild(leftCol);

    // ── Heatmap + Check Preview share same space ──
    // Preview is absolutely positioned over heatmap, appears on tile select
    var topSlot = document.createElement('div');
    topSlot.style.cssText = 'flex:1;position:relative;overflow:hidden;border-radius:10px;';
    leftCol.appendChild(topSlot);

    // ── Revenue Line Card (replaces heatmap placeholder) ──
    var lineCardInst = buildLineCard({
      label:    '7-Day Revenue',
      value:    '$0.00',
      delta:    '',
      thisWeek: [0,0,0,0,0,0,0],
      lastWeek: [0,0,0,0,0,0,0],
    });
    lineCardInst.wrap.style.cssText += 'position:absolute;inset:0;z-index:1;';
    topSlot.appendChild(lineCardInst.wrap);

    // Check preview (absolutely positioned over heatmap, hidden by default)
    var previewSlide = document.createElement('div');
    previewSlide.style.cssText = [
      'z-index:2;',
      'position:absolute;inset:0;',
      'background:' + T.card + ';',
      'border-left:4px solid ' + T.green + ';',
      'border-radius:10px;',
      'box-shadow:0 4px 16px rgba(0,0,0,0.28);',
      'padding:12px 14px;',
      'display:flex;flex-direction:column;',
      'opacity:0;pointer-events:none;',
      'transition:opacity 0.2s ease;',
      'overflow:hidden;',
    ].join('');
    topSlot.appendChild(previewSlide);

    var prevLabel = buildSectionLabel('Check Preview');
    prevLabel.style.marginBottom = '10px';
    previewSlide.appendChild(prevLabel);

    var prevContent = document.createElement('div');
    prevContent.style.flex = '1';
    previewSlide.appendChild(prevContent);

    // Action buttons grid
    var actGrid = document.createElement('div');
    actGrid.style.cssText = 'display:none;grid-template-columns:1fr 1fr;gap:5px;margin-top:8px;';
    var _prevOps = [
      { label: 'Print',    color: T.greenWarm, dark: T.greenWarmDk },
      { label: 'Pay',      color: T.gold,      dark: T.goldDk      },
      { label: 'Discount', color: T.elec,      dark: T.elecDk      },
      { label: 'Void',     color: T.verm,      dark: T.vermDk      },
    ];
    _prevOps.forEach(function(op) {
      var b = buildPillButton({ label: op.label, color: op.color, darkBg: op.dark,
        onClick: function() { _handleEditAction(op.label, state); },
      });
      b.style.cssText += 'font-size:14px;padding:8px 10px;';
      actGrid.appendChild(b);
    });
    previewSlide.appendChild(actGrid);

    // Dummy wrap ref for backward compat
    var prevResult = { wrap: previewSlide, card: previewSlide };

    // ── Sales Overview (flex — takes remaining space) ──
    var salesOuter = document.createElement('div');
    salesOuter.style.cssText = 'flex-shrink:0;height:250px;position:relative;overflow:visible;display:flex;flex-direction:column;';
    leftCol.appendChild(salesOuter);

    var salesResult = buildCard({ accent: T.gold, padding: '20px 16px' });
    salesResult.wrap.style.flex = '1';
    salesResult.card.style.height = '100%';
    salesResult.card.style.display       = 'flex';
    salesResult.card.style.flexDirection = 'column';
    salesResult.card.style.gap           = '18px';
    salesOuter.appendChild(salesResult.wrap);

    var salesLabel = buildSectionLabel('Sales Overview', T.text);
    salesLabel.style.fontSize = '16px';
    salesResult.card.appendChild(salesLabel);

    var salesOverview = buildSalesOverview({ netSales: 0, cash: 0, card: 0 });
    salesResult.card.appendChild(salesOverview.wrap);

    // ─────────────────────────────────────────────
    //  CHECK GRID (cols 2-3, row 1)
    // ─────────────────────────────────────────────
    // ── Check grid (cols 2-3, row 1) ──
    var gridOuter = document.createElement('div');
    gridOuter.style.cssText = 'grid-column:2/4;grid-row:1;position:relative;overflow:visible;';
    root.appendChild(gridOuter);

    var gridResult = buildCard({ accent: STATUS_COLORS['OPEN'].color, padding: '0', flex: '1' });
    gridResult.wrap.style.height = '100%';
    gridResult.card.style.height = '100%';
    gridResult.card.style.boxSizing = 'border-box';
    gridResult.card.style.overflow  = 'hidden';
    gridResult.card.style.display   = 'flex';
    gridResult.card.style.flexDirection = 'column';
    gridOuter.appendChild(gridResult.wrap);

    var tileGrid = document.createElement('div');
    tileGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;align-content:flex-start;flex:1;min-height:0;padding:14px 14px 10px;overflow:hidden;';
    gridResult.card.appendChild(tileGrid);

    // Filter footer — sits inside the card at the bottom right
    var filterFooter = document.createElement('div');
    filterFooter.style.cssText = [
      'display:flex;align-items:center;justify-content:space-between;',
      'padding:8px 14px 10px;flex-shrink:0;',
      'border-top:1px solid rgba(255,255,255,0.06);',
    ].join('');
    gridResult.card.appendChild(filterFooter);

    // Left side of footer: Edit/Close button (hidden until selection)
    var footerLeft = document.createElement('div');
    footerLeft.style.cssText = 'display:flex;align-items:center;';
    filterFooter.appendChild(footerLeft);

    // Right side of footer: filter tabs
    var footerRight = document.createElement('div');
    footerRight.style.cssText = 'display:flex;align-items:center;gap:8px;';
    filterFooter.appendChild(footerRight);

    // Edit panel — appended to root, covers full bottom area cols 2-3
    var editPanel = document.createElement('div');
    editPanel.style.cssText = [
      'position:absolute;',
      'left:320px;right:10px;bottom:10px;',
      'height:270px;',
      'background:' + T.card + ';',
      'border:2px solid ' + T.gold + ';',
      'border-radius:10px;',
      'padding:22px;',
      'display:grid;grid-template-columns:repeat(3,1fr);align-content:center;gap:18px;',
      'transform:translateY(calc(100% + 20px));',
      'transition:transform 0.22s ease;',
      'z-index:20;',
    ].join('');
    root.appendChild(editPanel);

    // Grouped by color family: cyan row (structural/modifier ops), green row (output/access)
    var _editOps = [
      { label: 'Merge',    color: T.elec,   dark: T.elecDk   },
      { label: 'Split',    color: T.elec,   dark: T.elecDk   },
      { label: 'Discount', color: T.elec,   dark: T.elecDk   },
      { label: 'Transfer', color: T.green,  dark: T.greenDk  },
      { label: 'Print',    color: T.green,  dark: T.greenDk  },
      { label: 'Open',     color: T.green,  dark: T.greenDk  },
    ];

    _editOps.forEach(function(op) {
      var b = buildPillButton({
        label:   op.label,
        color:   op.color,
        darkBg:  op.dark,
        onClick: function() { _handleEditAction(op.label, state); },
      });
      b.style.cssText += 'width:100%;font-size:18px;padding:16px 8px;text-align:center;letter-spacing:0.1em;';
      editPanel.appendChild(b);
    });

    // Edit panel dispatcher — central router for all edit-panel button actions.
    // Called with the button label ('Merge'|'Split'|'Discount'|'Transfer'|'Print'|'Open')
    // and the landing's mutable state object (so we can read selectedIds + emp).
    function _handleEditAction(label, st) {
      var ids = st.selectedIds || [];
      if (ids.length === 0) {
        showToast('Select a check first', { bg: T.verm, duration: 1800 });
        return;
      }

      if (label === 'Open' || label === 'Pay') {
        var orderId = ids[0];
        SceneManager.mountWorking('check-overview', {
          checkId:       orderId,
          returnLanding: 'manager-landing',
          employeeId:    st.emp ? st.emp.id   : null,
          employeeName:  st.emp ? st.emp.name : null,
          pin:           st.emp ? st.emp.pin  : null,
        });
        return;
      }

      if (label === 'Split') {
        // Split operates on a single check. Open it and auto-trigger the
        // column-editor (edit-seats) flow. check-overview reads autoSplit
        // after initial render.
        if (ids.length > 1) {
          showToast('Select only one check to split', { bg: T.verm, duration: 1800 });
          return;
        }
        SceneManager.mountWorking('check-overview', {
          checkId:       ids[0],
          returnLanding: 'manager-landing',
          employeeId:    st.emp ? st.emp.id   : null,
          employeeName:  st.emp ? st.emp.name : null,
          pin:           st.emp ? st.emp.pin  : null,
          autoSplit:     true,
        });
        return;
      }

      if (label === 'Print') {
        // Fire a receipt print for each selected check.
        var printed = 0, failed = 0;
        ids.forEach(function(orderId) {
          fetch('/api/v1/orders/' + orderId + '/print/receipt', { method: 'POST' })
            .then(function(r) {
              if (r.ok) printed++;
              else      failed++;
              if (printed + failed === ids.length) {
                showToast(
                  failed === 0
                    ? 'Printed ' + printed + ' receipt' + (printed === 1 ? '' : 's')
                    : printed + ' printed, ' + failed + ' failed',
                  { bg: failed === 0 ? T.green : T.gold, duration: 2000 }
                );
              }
            })
            .catch(function() { failed++; });
        });
        showToast('Printing ' + ids.length + ' receipt' + (ids.length === 1 ? '' : 's') + '…', { bg: T.green, duration: 1200 });
        return;
      }

      if (label === 'Void') {
        if (!st.emp || (!st.emp.id && !st.emp.employee_id)) {
          showToast('Manager approval required', { bg: T.verm, duration: 2000 });
          return;
        }
        var confirmMsg = ids.length === 1
          ? 'Void check ' + (ids[0]) + '?'
          : 'Void ' + ids.length + ' checks?';
        showToast(confirmMsg + ' — tap again to confirm', { bg: T.verm, duration: 3000 });
        if (!st._voidPending) {
          st._voidPending = true;
          setTimeout(function() { st._voidPending = false; }, 3000);
          return;
        }
        st._voidPending = false;
        var voided = 0, vFailed = 0;
        ids.forEach(function(orderId) {
          fetch('/api/v1/orders/' + orderId + '/void', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ approved_by: st.emp.employee_id || st.emp.id, reason: 'Manager void from landing' }),
          }).then(function(r) {
            if (r.ok) voided++;
            else       vFailed++;
            if (voided + vFailed === ids.length) {
              showToast(
                vFailed === 0
                  ? 'Voided ' + voided + ' check' + (voided === 1 ? '' : 's')
                  : voided + ' voided, ' + vFailed + ' failed',
                { bg: vFailed === 0 ? T.green : T.gold, duration: 2000 }
              );
              st.selectedIds = [];
              refresh();
            }
          }).catch(function() { vFailed++; });
        });
        return;
      }

      if (label === 'Merge') {
        if (ids.length < 2) {
          showToast('Select 2+ checks to merge', { bg: T.verm, duration: 2000 });
          return;
        }
        var approver = st.emp ? (st.emp.employee_id || st.emp.id) : null;
        if (!approver) {
          showToast('Manager approval required', { bg: T.verm, duration: 2000 });
          return;
        }
        // First selected = target, rest = sources
        var targetId  = ids[0];
        var sourceIds = ids.slice(1);
        showToast('Merging ' + sourceIds.length + ' check(s) into ' + targetId + '…', { bg: T.elec, duration: 1500 });
        fetch('/api/v1/orders/' + targetId + '/merge', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ source_ids: sourceIds, approved_by: approver }),
        }).then(function(r) {
          return r.json().then(function(data) {
            if (r.ok) {
              showToast('Merged into ' + targetId, { bg: T.green, duration: 2000 });
              st.selectedIds = [];
              refresh();
            } else {
              showToast(data.detail || 'Merge failed', { bg: T.verm, duration: 2500 });
            }
          });
        }).catch(function() {
          showToast('Merge failed — check connection', { bg: T.verm, duration: 2000 });
        });
        return;
      }

      // Discount / Transfer — dedicated flows not yet spec'd.
      showToast(label + ' — coming soon', { bg: T.gold, duration: 1800 });
    }

    // Filter tabs inside the card footer
    var serverBtn = buildPillButton({ label: 'ALL SERVERS', color: T.elec, darkBg: T.elecDk, fontSize: T.fsB3 });
    serverBtn.style.pointerEvents = 'auto';
    serverBtn._color = T.elec; serverBtn._dark = T.elecDk;
    serverBtn.setColor = function(c, d) {
      serverBtn._color = c; serverBtn._dark = d;
      serverBtn.style.background = c;
      serverBtn.style.boxShadow  = '0 6px 0 ' + d;
    };
    footerRight.appendChild(serverBtn);

    var filterBtn = buildPillButton({ label: 'OPEN', color: T.green, darkBg: T.greenDk, fontSize: T.fsB3 });
    filterBtn.style.pointerEvents = 'auto';
    filterBtn.setColor = function(c, d) {
      filterBtn.style.background = c;
      filterBtn.style.boxShadow  = '0 6px 0 ' + d;
    };
    footerRight.appendChild(filterBtn);

    // Edit float button — bottom-left, appears when a tile is selected
    var editBtn = buildPillButton({ label: 'OPTIONS', color: T.green, darkBg: T.greenDk, fontSize: T.fsB3 });
    editBtn.style.opacity       = '0';
    editBtn.style.pointerEvents = 'none';
    editBtn.style.transition    = 'opacity 0.15s ease';
    // setColor replaces internal press/release handlers so hover doesn't revert
    editBtn._btnColor = T.green;
    editBtn._btnDark  = T.greenDk;
    editBtn.setColor = function(c, d) {
      editBtn._btnColor = c;
      editBtn._btnDark  = d;
      editBtn.style.background = c;
      editBtn.style.boxShadow  = '0 6px 0 ' + d;
      editBtn.style.color      = (c === T.verm) ? '#fff' : T.well;
    };
    // Override press/release to use live _btnColor/_btnDark
    editBtn.addEventListener('pointerdown', function() {
      editBtn.style.background = editBtn._btnDark;
      editBtn.style.color      = editBtn._btnColor;
      editBtn.style.boxShadow  = 'none';
      editBtn.style.transform  = 'translateY(1px)';
    });
    var _editRel = function() {
      editBtn.style.background = editBtn._btnColor;
      editBtn.style.color      = (editBtn._btnColor === T.verm) ? '#fff' : T.well;
      editBtn.style.boxShadow  = '0 6px 0 ' + editBtn._btnDark;
      editBtn.style.transform  = '';
    };
    editBtn.addEventListener('pointerup',    _editRel);
    editBtn.addEventListener('pointerleave', _editRel);
    footerLeft.appendChild(editBtn);

    // ─────────────────────────────────────────────
    //  COB / LABOR (col 2, row 2)
    // ─────────────────────────────────────────────
    var cobResult = buildCard({ accent: T.gold, padding: '12px 14px' });
    cobResult.wrap.style.gridColumn = '2';
    cobResult.wrap.style.gridRow    = '2';
    cobResult.card.style.display    = 'flex';
    cobResult.card.style.flexDirection = 'column';
    cobResult.card.style.justifyContent = 'space-between';
    root.appendChild(cobResult.wrap);

    var cobLabel = buildSectionLabel('Labor / COB', T.text);
    cobLabel.style.fontSize = '16px';
    cobResult.card.appendChild(cobLabel);

    var cobInst = buildCOBCard();
    cobResult.card.appendChild(cobInst.wrap);

    // ─────────────────────────────────────────────
    //  SERVER CHECKOUTS (col 3, row 2)
    // ─────────────────────────────────────────────
    var chkOuter = document.createElement('div');
    chkOuter.style.cssText = 'grid-column:3;grid-row:2;position:relative;overflow:visible;display:flex;flex-direction:column;';
    root.appendChild(chkOuter);

    var chkResult = buildCard({ accent: T.elec, padding: '12px 14px' });
    chkResult.wrap.style.flex = '1';
    chkResult.card.style.display = 'flex';
    chkResult.card.style.flexDirection = 'column';
    chkOuter.appendChild(chkResult.wrap);

    var chkLabel = buildSectionLabel('Server Checkouts', T.text);
    chkLabel.style.fontSize = '16px';
    chkLabel.style.marginBottom = '6px';
    chkResult.card.appendChild(chkLabel);

    var serverList = document.createElement('div');
    serverList.style.cssText = 'display:flex;flex-direction:column;gap:5px;flex:1;overflow:hidden;';
    chkResult.card.appendChild(serverList);

    // Close Day float button
    var closeDayBtn = buildFloatButton({ label: 'Close Day', color: T.verm, darkBg: T.vermDk });
    closeDayBtn.style.cssText += 'position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);';
    chkOuter.appendChild(closeDayBtn);

    // Store all live-update refs
    state._refs = {
      tileGrid, previewSlide, prevContent, actGrid,
      salesOverview, lineCardInst, cobInst, salesOuter,
      serverList, serverBtn, filterBtn, closeDayBtn, editBtn, editPanel, tileGrid,
    };

    // ─────────────────────────────────────────────
    //  RENDER FUNCTIONS
    // ─────────────────────────────────────────────

    function renderTiles() {
      var r = state._refs;
      r.tileGrid.innerHTML = '';
      var visible = ordersByFilter(state.allOrders, state.filter, state.filteredServer);
      visible.forEach(function(order) {
        var id = order.order_id;
        var selected = state.selectedIds.indexOf(id) !== -1;
        var srvColor = state.serverColorMap[order.server_id] || T.elec;
        var _fc = STATUS_COLORS[state.filter] || {};
        r.tileGrid.appendChild(_buildCheckTile(order, selected, srvColor, function() {
          var idx = state.selectedIds.indexOf(id);
          if (idx === -1) state.selectedIds.push(id);
          else state.selectedIds.splice(idx, 1);
          renderTiles();
          renderPreview();
        }, function(ord) {
          SceneManager.mountWorking('check-overview', {
            checkId:       ord.order_id,
            returnLanding: 'manager-landing',
            employeeId:    state.emp ? state.emp.id   : null,
            employeeName:  state.emp ? state.emp.name : null,
            pin:           state.emp ? state.emp.pin  : null,
          });
        }, _fc.color));
      });
      if (state.filter === 'OPEN') {
        var newTile = document.createElement('div');
        newTile.style.cssText = [
          'width:140px;height:120px;flex-shrink:0;',
          'border:1px dashed ' + hexToRgba(T.green, 0.5) + ';',
          'border-radius:10px;',
          'display:flex;align-items:center;justify-content:center;',
          'cursor:pointer;transition:background 0.1s;',
          'pointer-events:auto;touch-action:manipulation;',
        ].join('');
        var plus = document.createElement('span');
        plus.style.cssText = 'font-family:' + T.fh + ';font-size:36px;color:' + hexToRgba(T.green, 0.6) + ';pointer-events:none;';
        plus.textContent = '+';
        newTile.appendChild(plus);
        newTile.addEventListener('pointerdown',  function() { newTile.style.background = hexToRgba(T.green, 0.08); });
        newTile.addEventListener('pointerup',    function() {
          newTile.style.background = 'transparent';
          SceneManager.mountWorking('check-overview', {
            checkId:       null,
            returnLanding: 'manager-landing',
            employeeId:    state.emp ? state.emp.id   : null,
            employeeName:  state.emp ? state.emp.name : null,
            pin:           state.emp ? state.emp.pin  : null,
          });
        });
        newTile.addEventListener('pointerleave', function() { newTile.style.background = 'transparent'; });
        r.tileGrid.appendChild(newTile);
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
      r.actGrid.style.display = 'none';

      if (state.selectedIds.length === 0) {
        r.previewSlide.style.opacity       = '0';
        r.previewSlide.style.pointerEvents = 'none';
        r.editBtn.style.opacity            = '0';
        r.editBtn.style.pointerEvents      = 'none';
        _editPanelOpen = false;
        r.editPanel.style.transform        = 'translateY(110%)';
        r.editBtn.textContent              = 'OPTIONS';
        r.editBtn.setColor(T.green, T.greenDk);
        r.salesOuter.style.opacity       = '1';
        r.salesOuter.style.pointerEvents = 'auto';
        return;
      }

      var selected = state.allOrders.filter(function(o) {
        return state.selectedIds.indexOf(o.order_id) !== -1;
      });
      if (selected.length > 0) r.prevContent.appendChild(_buildPreview(selected, state.allOrders));
      r.actGrid.style.display            = 'grid';
      r.previewSlide.style.opacity       = '1';
      r.previewSlide.style.pointerEvents = 'auto';
      r.editBtn.style.opacity            = '1';
      r.editBtn.style.pointerEvents      = 'auto';
    }

    function renderSales() {
      var sd = state.salesData || {};
      var r  = state._refs;
      r.salesOverview.update(
        sd.net_sales  || 0,
        sd.cash_total || 0,
        sd.card_total || 0,
        sd.net_sales > 0 ? '▲ vs last week' : '',
        sd.sparkData  || null
      );
      r.lineCardInst.update(
        fmt(sd.net_sales || 0),
        sd.net_sales > 0 ? '▲ vs last week' : '',
        sd.sparkData  || null,
        null
      );
    }

    function renderCOB() {
      var sd      = state.salesData || {};
      var servers = ((state.staffData || {}).servers || []);
      var pct     = sd.labor_cob || 0;
      state._refs.cobInst.update(
        pct,
        sd.staff_count  || 0,
        sd.labor_hours  || 0,
        sd.labor_cost   || 0,
        servers.map(function(s, i) {
          return {
            name:  s.name,
            hours: s.hours || 0,
            color: state.serverColorMap[s.id] || SRV_PALETTE[i % SRV_PALETTE.length],
          };
        })
      );
    }

    function renderGate() {
      var r  = state._refs;
      var cd = state.closeDayData || {};
      // Close Day button — disabled unless batch ready
      if (!cd.batch_ready) {
        r.closeDayBtn.setColor(T.border, darkenHex(T.border, 0.3));
      } else {
        r.closeDayBtn.setColor(T.verm, T.vermDk);
      }
    }

    function renderServerList() {
      var r       = state._refs;
      var servers = ((state.staffData || {}).servers || []);
      r.serverList.innerHTML = '';
      if (servers.length === 0) {
        var empty = document.createElement('div');
        empty.textContent   = 'No servers clocked in';
        empty.style.cssText = 'font-family:' + T.fb + ';font-size:13px;color:' + T.border + ';letter-spacing:0.12em;text-align:center;padding:8px 0;';
        r.serverList.appendChild(empty);
        return;
      }
      // Sort: active first, checked out last
      var sorted = servers.slice().sort(function(a, b) {
        if (a.checked_out && !b.checked_out) return 1;
        if (!a.checked_out && b.checked_out) return -1;
        return 0;
      });
      sorted.forEach(function(srv) {
        r.serverList.appendChild(_buildServerRow(srv, function(s) {
          SceneManager.mountWorking('server-checkout', { staff: s, fromManager: true });
        }));
      });
    }

    function renderServerFilter() {
      var r       = state._refs;
      var servers = ((state.staffData || {}).servers || []);
      if (!state.filteredServer) {
        r.serverBtn.textContent = 'ALL SERVERS';
        r.serverBtn.setColor(T.elec, T.elecDk);
        return;
      }
      var srv = servers.find(function(s) { return s.id === state.filteredServer; });
      if (srv) {
        var name = srv.name.split(' ')[0].toUpperCase();
        var color = state.serverColorMap[srv.id] || T.elec;
        r.serverBtn.textContent = name;
        r.serverBtn.setColor(color, darkenHex(color, 0.35));
      }
    }

    // Edit button — toggles action panel
    var _editPanelOpen = false;
    editBtn.addEventListener('pointerup', function() {
      if (state.selectedIds.length === 0) return;
      _editPanelOpen = !_editPanelOpen;
      var r = state._refs;
      r.editPanel.style.transform = _editPanelOpen ? 'translateY(0)' : 'translateY(110%)';
      editBtn.textContent         = _editPanelOpen ? 'CLOSE' : 'OPTIONS';
      editBtn.setColor(_editPanelOpen ? T.verm : T.green, _editPanelOpen ? T.vermDk : T.greenDk);
      salesOuter.style.opacity        = _editPanelOpen ? '0.25' : '1';
      salesOuter.style.pointerEvents  = _editPanelOpen ? 'none' : 'auto';
      r.serverBtn.style.opacity   = _editPanelOpen ? '0.3' : '1';
      r.filterBtn.style.opacity   = _editPanelOpen ? '0.3' : '1';
      r.serverBtn.style.pointerEvents = _editPanelOpen ? 'none' : 'auto';
      r.filterBtn.style.pointerEvents = _editPanelOpen ? 'none' : 'auto';
    });

    // ─────────────────────────────────────────────
    //  FILTER HANDLERS
    // ─────────────────────────────────────────────

    filterBtn.addEventListener('pointerup', function() {
      state.filter      = STATUS_CYCLE[state.filter];
      state.selectedIds = [];
      var fc = STATUS_COLORS[state.filter];
      state._refs.filterBtn.textContent = state.filter;
      state._refs.filterBtn.setColor(fc.color, fc.dark);
      gridResult.card.style.borderLeft = T.accentBarW + ' solid ' + fc.color;
      renderTiles();
      renderPreview();
    });

    serverBtn.addEventListener('pointerup', function() {
      var servers = ((state.staffData || {}).servers || []);
      if (servers.length === 0) return;
      // Build cycle: null → server[0] → server[1] → ... → null
      var ids = [null].concat(servers.map(function(s) { return s.id; }));
      var cur = ids.indexOf(state.filteredServer);
      state.filteredServer = ids[(cur + 1) % ids.length];
      state.selectedIds    = [];
      renderTiles();
      renderPreview();
      renderServerFilter();
    });

    // ─────────────────────────────────────────────
    //  CLOSE DAY
    // ─────────────────────────────────────────────
    closeDayBtn.addEventListener('pointerup', function() {
      var cd = state.closeDayData || {};
      if (!cd.batch_ready) return;
      SceneManager.openTransactional('close-day', { staff: state.emp });
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
        try { renderSales();        } catch(e) { console.warn('[ml] renderSales threw:', e); }
        try { renderGate();         } catch(e) { console.warn('[ml] renderGate threw:', e); }
        try { renderCOB();          } catch(e) { console.warn('[ml] renderCOB threw:', e); }
        try { renderServerList();   } catch(e) { console.warn('[ml] renderServerList threw:', e); }
        try { renderServerFilter(); } catch(e) { console.warn('[ml] renderServerFilter threw:', e); }
        try { renderTiles();        } catch(e) { console.warn('[ml] renderTiles threw:', e); }
        try { renderPreview();      } catch(e) { console.warn('[ml] renderPreview threw:', e); }
      }).catch(function() { state._refreshing = false; });
    }

    refresh();

    var _onUpdate = function() { refresh(); };
    SceneManager.on('order:updated', _onUpdate);
    SceneManager.on('order:closed',  _onUpdate);
    SceneManager.on('tip:adjusted',  _onUpdate);

    return function cleanup() {
      state.el = null;
      SceneManager.off('order:updated', _onUpdate);
      SceneManager.off('order:closed',  _onUpdate);
      SceneManager.off('tip:adjusted',  _onUpdate);
    };
  },
});