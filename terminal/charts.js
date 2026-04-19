// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Charts  (Vz2.0)
//  Chart + data visualization builders.
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════
//
//  Usage:
//    import {
//      buildStatCard, buildCashCardBar,
//      buildLineCard, buildCOBCard,
//      buildTipSparkBg,
//    } from '../charts.js';
//
//  Rules:
//   1. All colors come from T — never hardcode hex here.
//   2. All SVG paths use preserveAspectRatio="none" — responsive by default.
//   3. Square data points only — never circles.
//   4. Gold = money always. Lavender = last week / comparison always.
// ═══════════════════════════════════════════════════

import { T }                    from './tokens.js';
import { hexToRgba, darkenHex } from './theme-manager.js';

// ── Internal: SVG namespace shorthand ────────────
var SVG_NS = 'http://www.w3.org/2000/svg';

function _svgEl(tag, attrs) {
  var el = document.createElementNS(SVG_NS, tag);
  if (attrs) Object.keys(attrs).forEach(function(k) { el.setAttribute(k, attrs[k]); });
  return el;
}

// ── Internal: normalize data to 0-1 range ────────
function _normalize(data) {
  var min = Math.min.apply(null, data);
  var max = Math.max.apply(null, data);
  var range = max - min || 1;
  return data.map(function(v) { return (v - min) / range; });
}

// ── Internal: build SVG path string from data ────
// Returns path 'd' attribute for a line across a viewBox
function _linePath(data, vbW, vbH, padTop, padBot) {
  padTop = padTop || 4;
  padBot = padBot || 2;
  var norm = _normalize(data);
  var step = vbW / (norm.length - 1);
  return norm.map(function(v, i) {
    var x = i * step;
    var y = padTop + (1 - v) * (vbH - padTop - padBot);
    return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
}

// ── Internal: build area path (line + close to bottom) ─
function _areaPath(data, vbW, vbH, padTop, padBot) {
  var line = _linePath(data, vbW, vbH, padTop, padBot);
  return line + ' L' + vbW + ',' + vbH + ' L0,' + vbH + 'Z';
}

// ═══════════════════════════════════════════════════
//  buildSparkline
//  Minimal inline sparkline — used inside stat cards.
//
//  opts:
//    data      — array of numbers (7+ points recommended)
//    color     — line + fill color (use T tokens)
//    height    — pixel height of container (default 30)
// ═══════════════════════════════════════════════════

export function buildSparkline(opts) {
  var o     = opts || {};
  var data  = o.data  || [0, 0, 0, 0, 0, 0, 0];
  var color = o.color || T.gold;
  var h     = o.height || 30;

  var wrap = document.createElement('div');
  wrap.style.cssText = 'width:100%;height:' + h + 'px;flex-shrink:0;';

  var vbW = 200, vbH = h;
  var svg = _svgEl('svg', {
    viewBox:             '0 0 ' + vbW + ' ' + vbH,
    preserveAspectRatio: 'none',
    style:               'width:100%;height:100%;display:block;',
  });

  var gradId = 'spark-grad-' + Math.random().toString(36).slice(2, 7);
  var defs   = _svgEl('defs');
  var grad   = _svgEl('linearGradient', { id: gradId, x1: '0', y1: '0', x2: '0', y2: '1' });
  var stop1  = _svgEl('stop', { offset: '0%',   'stop-color': color, 'stop-opacity': '0.25' });
  var stop2  = _svgEl('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': '0'    });
  grad.appendChild(stop1);
  grad.appendChild(stop2);
  defs.appendChild(grad);
  svg.appendChild(defs);

  var linePath = _linePath(data, vbW, vbH, 4, 2);
  var areaPath = _areaPath(data, vbW, vbH, 4, 2);

  var area = _svgEl('path', { d: areaPath, fill: 'url(#' + gradId + ')', stroke: 'none' });
  var line = _svgEl('path', { d: linePath, fill: 'none', stroke: color, 'stroke-width': '1.5', 'stroke-linecap': 'round' });

  svg.appendChild(area);
  svg.appendChild(line);
  wrap.appendChild(svg);
  return wrap;
}

// ═══════════════════════════════════════════════════
//  buildStatCard
//  Full stat card — header label + big number + delta + sparkline.
//  Supports normal, warning, and critical frame states.
//
//  opts:
//    title       — card label (uppercase monospace)
//    value       — display string ('$4,821', '142', etc.)
//    color       — big number color (use T.gold, T.elec, T.text, etc.)
//    delta       — string ('▲ 12%', '▼ 2%', '⚠ 3 pending', etc.)
//    deltaColor  — override (default: T.positive for ▲, T.verm for ▼)
//    sparkData   — array of numbers for sparkline
//    sparkColor  — sparkline color (defaults to color)
//    state       — 'normal' | 'warning' | 'critical'
//
//  Returns { wrap, setValue, setDelta, setState }
// ═══════════════════════════════════════════════════

export function buildStatCard(opts) {
  var o          = opts || {};
  var color      = o.color      || T.gold;
  var sparkColor = o.sparkColor || color;
  var state      = o.state      || 'normal';

  var wrap = document.createElement('div');
  wrap.style.cssText = [
    'display:flex;flex-direction:column;',
    'background:' + T.card + ';',
    'border-radius:10px;',
    'overflow:hidden;',
    'border:1px solid rgba(255,255,255,0.04);',
    'flex:1;',
  ].join('');

  // Header
  var hdr = document.createElement('div');
  hdr.style.cssText = [
    'display:flex;align-items:center;justify-content:space-between;',
    'padding:8px 12px;flex-shrink:0;',
    'border-bottom:1px solid rgba(255,255,255,0.05);',
  ].join('');

  var titleEl = document.createElement('span');
  titleEl.textContent   = (o.title || '').toUpperCase();
  titleEl.style.cssText = 'font-family:' + T.fb + ';font-size:9px;letter-spacing:2px;color:' + T.border + ';';

  var dot = document.createElement('div');
  dot.style.cssText = 'width:7px;height:7px;border-radius:50%;background:' + color + ';box-shadow:0 0 5px ' + hexToRgba(color, 0.5) + ';';

  hdr.appendChild(titleEl);
  hdr.appendChild(dot);
  wrap.appendChild(hdr);

  // Body
  var body = document.createElement('div');
  body.style.cssText = 'padding:8px 12px 4px;flex-shrink:0;';

  var valueEl = document.createElement('div');
  valueEl.textContent   = o.value || '—';
  valueEl.style.cssText = 'font-family:' + T.fh + ';font-size:24px;font-weight:700;line-height:1;color:' + color + ';margin-bottom:3px;';

  var deltaEl = document.createElement('div');
  deltaEl.textContent   = o.delta || '';
  deltaEl.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + (o.deltaColor || T.positive) + ';margin-bottom:4px;';

  body.appendChild(valueEl);
  body.appendChild(deltaEl);
  wrap.appendChild(body);

  // Sparkline
  var spark = buildSparkline({ data: o.sparkData || [0,0,0,0,0,0,0], color: sparkColor, height: 30 });
  spark.style.marginTop = 'auto';
  wrap.appendChild(spark);

  // State styling
  function _applyState(s) {
    if (s === 'warning') {
      wrap.style.border    = '1px solid ' + T.warning;
      wrap.style.boxShadow = '0 0 0 1px ' + hexToRgba(T.warning, 0.2);
    } else if (s === 'critical') {
      wrap.style.border    = '1px solid ' + T.verm;
      wrap.style.boxShadow = '0 0 0 1px ' + hexToRgba(T.verm, 0.2);
    } else {
      wrap.style.border    = '1px solid rgba(255,255,255,0.04)';
      wrap.style.boxShadow = 'none';
    }
  }
  _applyState(state);

  return {
    wrap:     wrap,
    setValue: function(v) { valueEl.textContent = v; },
    setDelta: function(d, c) {
      deltaEl.textContent  = d;
      if (c) deltaEl.style.color = c;
    },
    setState: function(s) { _applyState(s); },
  };
}

// ═══════════════════════════════════════════════════
//  buildCashCardBar
//  Stacked horizontal bar showing cash vs card split.
//
//  opts:
//    cash   — cash total (number)
//    card   — card total (number)
//
//  Returns { wrap, update(cash, card) }
// ═══════════════════════════════════════════════════

export function buildCashCardBar(opts) {
  var o = opts || {};

  var wrap = document.createElement('div');
  wrap.style.cssText = 'flex-shrink:0;display:flex;flex-direction:column;gap:5px;';

  var labelRow = document.createElement('div');
  labelRow.style.cssText = 'display:flex;justify-content:space-between;align-items:baseline;';

  var lbl = document.createElement('span');
  lbl.textContent   = 'CASH / CARD';
  lbl.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + T.border + ';letter-spacing:1px;';

  var amounts = document.createElement('div');
  amounts.style.cssText = 'display:flex;gap:10px;';

  var cashAmt = document.createElement('span');
  cashAmt.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + T.green + ';';

  var cardAmt = document.createElement('span');
  cardAmt.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + T.elec + ';';

  amounts.appendChild(cashAmt);
  amounts.appendChild(cardAmt);
  labelRow.appendChild(lbl);
  labelRow.appendChild(amounts);
  wrap.appendChild(labelRow);

  // Bar track
  var track = document.createElement('div');
  track.style.cssText = 'display:flex;height:10px;border-radius:3px;overflow:hidden;gap:2px;';

  var cashFill = document.createElement('div');
  cashFill.style.cssText = 'background:' + T.green + ';border-radius:2px;box-shadow:0 0 8px ' + hexToRgba(T.green, 0.35) + ';transition:width 0.4s ease;';

  var cardFill = document.createElement('div');
  cardFill.style.cssText = 'flex:1;background:' + T.elec + ';border-radius:2px;box-shadow:0 0 8px ' + hexToRgba(T.elec, 0.35) + ';';

  track.appendChild(cashFill);
  track.appendChild(cardFill);
  wrap.appendChild(track);

  // Pct row
  var pctRow = document.createElement('div');
  pctRow.style.cssText = 'display:flex;justify-content:space-between;';

  var cashPct = document.createElement('span');
  cashPct.style.cssText = 'font-family:' + T.fb + ';font-size:8px;color:' + T.green + ';opacity:0.7;';

  var cardPct = document.createElement('span');
  cardPct.style.cssText = 'font-family:' + T.fb + ';font-size:8px;color:' + T.elec + ';opacity:0.7;';

  pctRow.appendChild(cashPct);
  pctRow.appendChild(cardPct);
  wrap.appendChild(pctRow);

  function fmt(n) {
    return '$' + (n || 0).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function update(cash, card) {
    var total = (cash || 0) + (card || 0) || 1;
    var cp    = Math.round((cash / total) * 100);
    cashFill.style.width  = cp + '%';
    cashAmt.textContent   = fmt(cash) + ' cash';
    cardAmt.textContent   = fmt(card) + ' card';
    cashPct.textContent   = cp + '%';
    cardPct.textContent   = (100 - cp) + '%';
  }

  update(o.cash || 0, o.card || 0);

  return { wrap: wrap, update: update };
}

// ═══════════════════════════════════════════════════
//  buildSalesOverview
//  Full sales overview card content:
//  Net Sales stat card + Cash/Card breakdown bar.
//  Designed for the 250px bottom-left card in both landings.
//
//  opts:
//    netSales   — number
//    cash       — number
//    card       — number
//    netDelta   — string e.g. '▲ 12%'
//    sparkData  — array of numbers (7 points, daily net sales)
//
//  Returns { wrap, update(netSales, cash, card, netDelta, sparkData) }
//  Caller appends wrap to card.card.
// ═══════════════════════════════════════════════════

export function buildSalesOverview(opts) {
  var o = opts || {};

  var wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:10px;flex:1;min-height:0;';

  // Net Sales stat card
  var netCard = buildStatCard({
    title:     'Net Sales',
    value:     '$0.00',
    color:     T.gold,
    delta:     '',
    sparkData: o.sparkData || [0,0,0,0,0,0,0],
  });
  netCard.wrap.style.flexShrink = '0';
  wrap.appendChild(netCard.wrap);

  // Cash / Card bar
  var bar = buildCashCardBar({ cash: o.cash || 0, card: o.card || 0 });
  wrap.appendChild(bar.wrap);

  function fmt(n) {
    var abs = Math.abs(n || 0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (n < 0 ? '\u2212$' : '$') + abs;
  }

  function update(netSales, cash, card, netDelta, sparkData) {
    netCard.setValue(fmt(netSales || 0));
    netCard.setDelta(netDelta || '', netDelta && netDelta[0] === '▼' ? T.verm : T.positive);
    bar.update(cash || 0, card || 0);
    // Re-render sparkline if new data provided
    if (sparkData && sparkData.length) {
      var oldSpark = netCard.wrap.lastElementChild;
      if (oldSpark) {
        var newSpark = buildSparkline({ data: sparkData, color: T.gold, height: 30 });
        newSpark.style.marginTop = 'auto';
        netCard.wrap.replaceChild(newSpark, oldSpark);
      }
    }
  }

  update(o.netSales, o.cash, o.card, o.netDelta, o.sparkData);

  return { wrap: wrap, update: update };
}

// ═══════════════════════════════════════════════════
//  buildLineCard
//  Expandable revenue trend card.
//  Collapsed: full-bleed background sparkline + big number.
//  Expanded: full chart with grid, axes, day labels, range tabs.
//
//  opts:
//    label      — card label ('7-Day Revenue')
//    value      — display string ('$4,821')
//    delta      — string ('▲ 12.4% vs last week')
//    thisWeek   — array of 7 numbers (Mon–Sun, today last)
//    lastWeek   — array of 7 numbers
//    days       — array of 7 labels (['Mon','Tue',...])
//
//  Returns { wrap, update(value, delta, thisWeek, lastWeek) }
// ═══════════════════════════════════════════════════

export function buildLineCard(opts) {
  var o = opts || {};
  var days = o.days || ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  var wrap = document.createElement('div');
  wrap.style.cssText = [
    'position:relative;width:100%;height:100%;',
    'background:' + T.card + ';',
    'border-left:4px solid ' + T.border + ';',
    'border-radius:10px;',
    'overflow:hidden;',
    'cursor:pointer;',
    'transition:border-color 0.2s;',
    'user-select:none;',
  ].join('');

  // ── Background sparkline (collapsed state) ──
  var bgWrap = document.createElement('div');
  bgWrap.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;border-radius:10px;';

  var bgSvg = document.createElementNS(SVG_NS, 'svg');
  bgSvg.style.cssText        = 'width:100%;height:100%;';
  bgSvg.setAttribute('preserveAspectRatio', 'none');
  bgWrap.appendChild(bgSvg);
  wrap.appendChild(bgWrap);

  // ── Collapsed overlay ──
  var collapsed = document.createElement('div');
  collapsed.style.cssText = [
    'position:relative;z-index:1;',
    'padding:18px 20px;',
    'display:flex;align-items:flex-end;justify-content:space-between;',
    'height:100%;box-sizing:border-box;',
    'transition:opacity 0.25s ease;',
  ].join('');

  var colLeft = document.createElement('div');
  var colLabel = document.createElement('div');
  colLabel.style.cssText = 'font-family:' + T.fb + ';font-size:9px;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.4);margin-bottom:4px;';
  colLabel.textContent   = o.label || '7-Day Revenue';

  var colValue = document.createElement('div');
  colValue.style.cssText = 'font-family:' + T.fh + ';font-size:30px;font-weight:800;color:' + T.gold + ';line-height:1;';

  var colDelta = document.createElement('div');
  colDelta.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.positive + ';margin-top:3px;';

  colLeft.appendChild(colLabel);
  colLeft.appendChild(colValue);
  colLeft.appendChild(colDelta);

  var colRight = document.createElement('div');
  colRight.style.textAlign = 'right';
  var colHint = document.createElement('div');
  colHint.textContent   = 'tap to expand ↕';
  colHint.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:rgba(255,255,255,0.18);';
  colRight.appendChild(colHint);

  collapsed.appendChild(colLeft);
  collapsed.appendChild(colRight);
  wrap.appendChild(collapsed);

  // ── Expanded content ──
  var expanded = document.createElement('div');
  expanded.style.cssText = [
    'position:absolute;inset:0;z-index:2;',
    'background:' + T.card + ';',
    'border-radius:10px;',
    'display:flex;flex-direction:column;',
    'opacity:0;pointer-events:none;',
    'transition:opacity 0.25s ease;',
  ].join('');

  // Expanded header
  var expHdr = document.createElement('div');
  expHdr.style.cssText = 'display:flex;align-items:flex-start;justify-content:space-between;padding:16px 18px 12px;flex-shrink:0;';

  var expLeft = document.createElement('div');
  var expTitle = document.createElement('div');
  expTitle.textContent   = o.label || '7-Day Revenue';
  expTitle.style.cssText = 'font-family:' + T.fb + ';font-size:9px;letter-spacing:2px;text-transform:uppercase;color:' + T.border + ';margin-bottom:5px;';

  var expValue = document.createElement('div');
  expValue.style.cssText = 'font-family:' + T.fh + ';font-size:32px;font-weight:800;color:' + T.gold + ';line-height:1;';

  var expDelta = document.createElement('div');
  expDelta.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.positive + ';margin-top:4px;';

  expLeft.appendChild(expTitle);
  expLeft.appendChild(expValue);
  expLeft.appendChild(expDelta);

  var closeBtn = document.createElement('button');
  closeBtn.textContent   = 'CLOSE ↑';
  closeBtn.style.cssText = [
    'font-family:' + T.fb + ';font-size:9px;letter-spacing:1px;',
    'color:' + T.border + ';background:rgba(255,255,255,0.07);',
    'border:1px solid rgba(255,255,255,0.1);border-radius:4px;',
    'padding:5px 10px;cursor:pointer;',
  ].join('');

  expHdr.appendChild(expLeft);
  expHdr.appendChild(closeBtn);
  expanded.appendChild(expHdr);

  // Chart well
  var chartWell = document.createElement('div');
  chartWell.style.cssText = [
    'flex:1;margin:0 16px 12px;min-height:0;',
    'background:' + T.well + ';',
    'border-radius:6px;',
    'padding:10px 10px 20px;',
    'position:relative;overflow:hidden;',
  ].join('');
  expanded.appendChild(chartWell);

  var expSvg = document.createElementNS(SVG_NS, 'svg');
  expSvg.style.cssText        = 'width:100%;height:100%;overflow:visible;';
  expSvg.setAttribute('preserveAspectRatio', 'none');
  chartWell.appendChild(expSvg);

  // Footer: legend + range tabs
  var footer = document.createElement('div');
  footer.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:0 16px 14px;flex-shrink:0;';

  var legend = document.createElement('div');
  legend.style.cssText = 'display:flex;gap:14px;';

  function _legendItem(label, color, dashed) {
    var item = document.createElement('div');
    item.style.cssText = 'display:flex;align-items:center;gap:5px;';
    var dot = document.createElement('div');
    dot.style.cssText = 'width:8px;height:8px;border-radius:2px;background:' + color + ';' + (dashed ? 'opacity:0.5;' : 'box-shadow:0 0 5px ' + hexToRgba(color, 0.4) + ';');
    var lbl = document.createElement('span');
    lbl.textContent   = label;
    lbl.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + T.border + ';';
    item.appendChild(dot);
    item.appendChild(lbl);
    return item;
  }
  legend.appendChild(_legendItem('This Week', T.gold, false));
  legend.appendChild(_legendItem('Last Week', T.lavender, true));
  footer.appendChild(legend);

  var rangeTabs = document.createElement('div');
  rangeTabs.style.cssText = 'display:flex;gap:4px;';
  ['7D','30D','90D'].forEach(function(r, i) {
    var tab = document.createElement('button');
    tab.textContent   = r;
    tab.style.cssText = [
      'font-family:' + T.fb + ';font-size:9px;letter-spacing:1px;',
      'padding:4px 9px;border-radius:4px;border:none;cursor:pointer;',
      'background:' + (i === 0 ? hexToRgba(T.green, 0.15) : 'rgba(255,255,255,0.06)') + ';',
      'color:' + (i === 0 ? T.green : T.border) + ';',
      'transition:background 0.15s,color 0.15s;',
    ].join('');
    tab.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      rangeTabs.querySelectorAll('button').forEach(function(t) {
        t.style.background = 'rgba(255,255,255,0.06)';
        t.style.color      = T.border;
      });
      tab.style.background = hexToRgba(T.green, 0.15);
      tab.style.color      = T.green;
    });
    rangeTabs.appendChild(tab);
  });
  footer.appendChild(rangeTabs);
  expanded.appendChild(footer);
  wrap.appendChild(expanded);

  // ── Expand / collapse ──
  var _open = false;

  wrap.addEventListener('pointerup', function() {
    if (_open) return;
    _open = true;
    collapsed.style.opacity      = '0';
    collapsed.style.pointerEvents = 'none';
    expanded.style.opacity       = '1';
    expanded.style.pointerEvents = 'auto';
    wrap.style.cursor            = 'default';
  });

  closeBtn.addEventListener('pointerup', function(e) {
    e.stopPropagation();
    _open = false;
    collapsed.style.opacity       = '1';
    collapsed.style.pointerEvents = 'auto';
    expanded.style.opacity        = '0';
    expanded.style.pointerEvents  = 'none';
    wrap.style.cursor             = 'pointer';
  });

  // ── Render chart data ──
  function _renderBgSvg(thisWeek, lastWeek) {
    while (bgSvg.firstChild) bgSvg.removeChild(bgSvg.firstChild);
    var vbW = 480, vbH = 96;
    bgSvg.setAttribute('viewBox', '0 0 ' + vbW + ' ' + vbH);

    var gradId = 'lc-bg-' + Math.random().toString(36).slice(2, 6);
    var defs   = _svgEl('defs');
    var grad   = _svgEl('linearGradient', { id: gradId, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(_svgEl('stop', { offset: '0%',   'stop-color': T.gold, 'stop-opacity': '0.1' }));
    grad.appendChild(_svgEl('stop', { offset: '100%', 'stop-color': T.gold, 'stop-opacity': '0'   }));
    defs.appendChild(grad);
    bgSvg.appendChild(defs);

    // all data points pooled for shared scale
    var all = (thisWeek || []).concat(lastWeek || []);
    var min = Math.min.apply(null, all);
    var max = Math.max.apply(null, all);
    var range = max - min || 1;
    var pad = 8;

    function _pts(data) {
      return (data || []).map(function(v, i) {
        var x = (i / (data.length - 1)) * vbW;
        var y = pad + (1 - (v - min) / range) * (vbH - pad * 2);
        return x.toFixed(1) + ',' + y.toFixed(1);
      });
    }

    var twPts = _pts(thisWeek || []);
    var lwPts = _pts(lastWeek || []);

    if (lwPts.length > 1) {
      bgSvg.appendChild(_svgEl('path', {
        d:            'M' + lwPts.join(' L'),
        fill:         'none',
        stroke:       T.lavender,
        'stroke-width': '1',
        opacity:      '0.3',
        'stroke-dasharray': '5 4',
      }));
    }

    if (twPts.length > 1) {
      var twPath = 'M' + twPts.join(' L');
      bgSvg.appendChild(_svgEl('path', {
        d: twPath + ' L' + vbW + ',' + vbH + ' L0,' + vbH + 'Z',
        fill: 'url(#' + gradId + ')', stroke: 'none',
      }));
      bgSvg.appendChild(_svgEl('path', {
        d: twPath, fill: 'none', stroke: T.gold,
        'stroke-width': '1.5', opacity: '0.7',
      }));
    }
  }

  function _renderExpSvg(thisWeek, lastWeek) {
    while (expSvg.firstChild) expSvg.removeChild(expSvg.firstChild);
    var vbW = 440, vbH = 140;
    expSvg.setAttribute('viewBox', '0 0 ' + vbW + ' ' + vbH);

    var all = (thisWeek || []).concat(lastWeek || []);
    var min = Math.min.apply(null, all);
    var max = Math.max.apply(null, all);
    var range = max - min || 1;
    var leftPad = 32, rightPad = 8, topPad = 12, botPad = 20;
    var chartW = vbW - leftPad - rightPad;
    var chartH = vbH - topPad - botPad;

    var gradId = 'lc-exp-' + Math.random().toString(36).slice(2, 6);
    var defs   = _svgEl('defs');
    var grad   = _svgEl('linearGradient', { id: gradId, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(_svgEl('stop', { offset: '0%',   'stop-color': T.gold, 'stop-opacity': '0.2' }));
    grad.appendChild(_svgEl('stop', { offset: '100%', 'stop-color': T.gold, 'stop-opacity': '0'   }));
    defs.appendChild(grad);
    expSvg.appendChild(defs);

    // Grid lines + y labels
    [0.75, 0.5, 0.25].forEach(function(frac) {
      var y = topPad + (1 - frac) * chartH;
      expSvg.appendChild(_svgEl('line', { x1: leftPad, y1: y, x2: vbW - rightPad, y2: y, stroke: T.gridLine, 'stroke-width': '1' }));
      var val = min + frac * range;
      var lbl = _svgEl('text', { x: leftPad - 4, y: y + 3, 'font-family': 'JetBrains Mono', 'font-size': '8', fill: T.axisText, 'text-anchor': 'end' });
      lbl.textContent = '$' + (val >= 1000 ? (val / 1000).toFixed(1) + 'k' : Math.round(val));
      expSvg.appendChild(lbl);
    });

    function _pts(data) {
      return (data || []).map(function(v, i) {
        var x = leftPad + (i / (data.length - 1)) * chartW;
        var y = topPad + (1 - (v - min) / range) * chartH;
        return { x: x, y: y };
      });
    }

    var twPts = _pts(thisWeek || []);
    var lwPts = _pts(lastWeek || []);

    // Day labels
    days.forEach(function(d, i) {
      if (!twPts[i]) return;
      var lbl = _svgEl('text', { x: twPts[i].x, y: vbH - 4, 'font-family': 'JetBrains Mono', 'font-size': '9', fill: T.axisText, 'text-anchor': 'middle' });
      lbl.textContent = d;
      expSvg.appendChild(lbl);
    });

    function _ptStr(pts) {
      return pts.map(function(p, i) { return (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ');
    }

    // Last week dashed
    if (lwPts.length > 1) {
      expSvg.appendChild(_svgEl('path', {
        d: _ptStr(lwPts), fill: 'none', stroke: T.lavender,
        'stroke-width': '1.5', 'stroke-dasharray': '5 4',
      }));
    }

    // This week area + line
    if (twPts.length > 1) {
      var twStr = _ptStr(twPts);
      var last  = twPts[twPts.length - 1];
      var first = twPts[0];
      expSvg.appendChild(_svgEl('path', {
        d: twStr + ' L' + last.x.toFixed(1) + ',' + (topPad + chartH) + ' L' + first.x.toFixed(1) + ',' + (topPad + chartH) + 'Z',
        fill: 'url(#' + gradId + ')', stroke: 'none',
      }));
      expSvg.appendChild(_svgEl('path', {
        d: twStr, fill: 'none', stroke: T.gold, 'stroke-width': '2',
      }));
      // Square data points
      twPts.slice(1).forEach(function(p) {
        expSvg.appendChild(_svgEl('rect', { x: p.x - 3, y: p.y - 3, width: '6', height: '6', fill: T.gold }));
      });
    }
  }

  function update(value, delta, thisWeek, lastWeek) {
    colValue.textContent = value || '$0.00';
    colDelta.textContent = delta || '';
    expValue.textContent = value || '$0.00';
    expDelta.textContent = delta || '';

    var tw = thisWeek || [0,0,0,0,0,0,0];
    var lw = lastWeek || [0,0,0,0,0,0,0];
    _renderBgSvg(tw, lw);
    _renderExpSvg(tw, lw);
  }

  update(o.value, o.delta, o.thisWeek, o.lastWeek);

  return { wrap: wrap, update: update };
}

// ═══════════════════════════════════════════════════
//  buildCOBCard
//  COB % bar with threshold markers + per-server hour bars.
//  Replaces the simple cobBarFill in manager-landing.
//
//  opts:
//    (none — all values set via update())
//
//  Returns {
//    wrap,
//    update(cobPct, floorCount, hours, laborCost, servers)
//    // servers: [{ name, hours, color }]
//  }
// ═══════════════════════════════════════════════════

export function buildCOBCard(opts) {
  var wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:10px;flex:1;min-height:0;';

  // Stats row
  var statsRow = document.createElement('div');
  statsRow.style.cssText = 'display:flex;justify-content:space-around;flex-shrink:0;';

  function _stat(val, label, color) {
    var el = document.createElement('div');
    var v  = document.createElement('div');
    v.style.cssText = 'font-family:' + T.fh + ';font-size:20px;font-weight:700;color:' + color + ';';
    v.textContent   = val;
    var l  = document.createElement('div');
    l.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.text + ';opacity:0.6;letter-spacing:1px;text-transform:uppercase;margin-top:1px;';
    l.textContent   = label;
    el.appendChild(v); el.appendChild(l);
    return { wrap: el, v: v };
  }

  var sCob   = _stat('0%',   'COB',     T.gold);
  var sFloor = _stat('0',    'Floor',   T.text);
  var sHours = _stat('0.0h', 'Hours',   T.elec);
  var sLabor = _stat('$0',   'Labor $', T.text);
  [sCob, sFloor, sHours, sLabor].forEach(function(s) { statsRow.appendChild(s.wrap); });
  wrap.appendChild(statsRow);

  // COB main bar
  var cobSection = document.createElement('div');
  cobSection.style.cssText = 'flex-shrink:0;';

  var cobLabelRow = document.createElement('div');
  cobLabelRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-bottom:4px;';

  var warnLbl = document.createElement('span');
  warnLbl.textContent   = '▲28% warn';
  warnLbl.style.cssText = 'font-family:' + T.fb + ';font-size:8px;color:' + T.warning + ';letter-spacing:1px;';

  var critLbl = document.createElement('span');
  critLbl.textContent   = '▲35% crit';
  critLbl.style.cssText = 'font-family:' + T.fb + ';font-size:8px;color:' + T.verm + ';letter-spacing:1px;';

  cobLabelRow.appendChild(warnLbl);
  cobLabelRow.appendChild(critLbl);
  cobSection.appendChild(cobLabelRow);

  var cobTrack = document.createElement('div');
  cobTrack.style.cssText = 'height:8px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;position:relative;';

  var cobFill = document.createElement('div');
  cobFill.style.cssText = 'height:100%;border-radius:2px;transition:width 0.4s ease,background 0.4s ease;';
  cobTrack.appendChild(cobFill);

  // Threshold marker lines (positioned over the track)
  var trackWrap = document.createElement('div');
  trackWrap.style.cssText = 'position:relative;';
  trackWrap.appendChild(cobTrack);

  [{ pct: 28, color: T.warning }, { pct: 35, color: T.verm }].forEach(function(t) {
    var line = document.createElement('div');
    line.style.cssText = 'position:absolute;top:-2px;bottom:-2px;width:1px;left:' + t.pct + '%;background:' + hexToRgba(t.color, 0.5) + ';pointer-events:none;';
    trackWrap.appendChild(line);
  });

  cobSection.appendChild(trackWrap);
  wrap.appendChild(cobSection);

  // Divider
  var div = document.createElement('div');
  div.style.cssText = 'height:1px;background:rgba(255,255,255,0.06);flex-shrink:0;';
  wrap.appendChild(div);

  // Server bars
  var serverBars = document.createElement('div');
  serverBars.style.cssText = 'display:flex;flex-direction:column;gap:6px;flex:1;justify-content:center;';
  wrap.appendChild(serverBars);

  function update(cobPct, floorCount, hours, laborCost, servers) {
    var pct = cobPct || 0;
    var barColor = pct >= (T.cobCrit * 100) ? T.verm : pct >= (T.cobWarn * 100) ? T.warning : T.green;

    sCob.v.textContent   = Math.round(pct) + '%';
    sCob.v.style.color   = barColor;
    sFloor.v.textContent = (floorCount || 0) + '';
    sHours.v.textContent = (hours || 0).toFixed(1) + 'h';
    sLabor.v.textContent = '$' + Math.round(laborCost || 0);

    cobFill.style.width      = Math.min(pct, 100) + '%';
    cobFill.style.background = barColor;
    cobFill.style.boxShadow  = '0 0 6px ' + hexToRgba(barColor, 0.4);

    // Rebuild server bars
    serverBars.innerHTML = '';
    var maxH = Math.max.apply(null, (servers || []).map(function(s) { return s.hours || 0; })) || 1;
    (servers || []).forEach(function(srv) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;';

      var name = document.createElement('span');
      name.textContent   = (srv.name || '').split(' ')[0].toUpperCase();
      name.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + T.border + ';width:52px;text-align:right;flex-shrink:0;';

      var track = document.createElement('div');
      track.style.cssText = 'flex:1;height:8px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;';

      var fill = document.createElement('div');
      fill.style.cssText = 'height:100%;border-radius:2px;background:' + (srv.color || T.green) + ';opacity:0.75;';
      fill.style.width   = Math.round((srv.hours / maxH) * 100) + '%';
      track.appendChild(fill);

      var hrs = document.createElement('span');
      hrs.textContent   = (srv.hours || 0).toFixed(1) + 'h';
      hrs.style.cssText = 'font-family:' + T.fb + ';font-size:9px;color:' + T.border + ';width:28px;';

      row.appendChild(name);
      row.appendChild(track);
      row.appendChild(hrs);
      serverBars.appendChild(row);
    });
  }

  update(0, 0, 0, 0, []);

  return { wrap: wrap, update: update };
}

// ═══════════════════════════════════════════════════
//  buildTipSparkBg
//  Subtle gold accumulation sparkline behind Tip Queue.
//  Appended as background to the tip card wrap element.
//
//  opts:
//    data — array of cumulative tip totals across the shift
//
//  Returns { el, update(data) }
// ═══════════════════════════════════════════════════

export function buildTipSparkBg(opts) {
  var o = opts || {};

  var el = document.createElement('div');
  el.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;border-radius:10px;';

  var svg = document.createElementNS(SVG_NS, 'svg');
  svg.style.cssText = 'position:absolute;bottom:0;left:0;width:100%;height:100%;';
  svg.setAttribute('preserveAspectRatio', 'none');
  el.appendChild(svg);

  function update(data) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!data || data.length < 2) return;

    var vbW = 300, vbH = 400;
    svg.setAttribute('viewBox', '0 0 ' + vbW + ' ' + vbH);

    var gradId = 'tip-spark-' + Math.random().toString(36).slice(2, 6);
    var defs   = _svgEl('defs');
    var grad   = _svgEl('linearGradient', { id: gradId, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(_svgEl('stop', { offset: '0%',   'stop-color': T.gold, 'stop-opacity': '0.06' }));
    grad.appendChild(_svgEl('stop', { offset: '100%', 'stop-color': T.gold, 'stop-opacity': '0'    }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    var norm = _normalize(data);
    var pts  = norm.map(function(v, i) {
      return { x: (i / (norm.length - 1)) * vbW, y: 10 + (1 - v) * (vbH - 10) };
    });
    var pathStr = pts.map(function(p, i) { return (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ');

    svg.appendChild(_svgEl('path', { d: pathStr + ' L' + vbW + ',' + vbH + ' L0,' + vbH + 'Z', fill: 'url(#' + gradId + ')', stroke: 'none' }));
    svg.appendChild(_svgEl('path', { d: pathStr, fill: 'none', stroke: T.gold, 'stroke-width': '1', opacity: '0.2' }));
  }

  update(o.data || []);

  return { el: el, update: update };
}