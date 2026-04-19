// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Persistent Order Summary Panel  (Vz2.0)
//  Left-column panel that persists across order + payment flow
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════
//
//  Ported from SM2 version. Reskinned to Nostalgia theme:
//    - Left accent bar + border-radius instead of applyCardBevel/chamfer
//    - T.green replaces T.mint for structural elements
//    - T.elec (cyan) replaces T.cyan for card/payment accents
//    - T.text (with opacity) replaces T.mutedText
// ═══════════════════════════════════════════════════

import { T } from './tokens.js';
import { buildButton } from './components.js';
import { SceneManager } from './scene-manager.js';
import { hexToRgba } from './theme-manager.js';

var _el = null;          // #order-summary container
var _itemScroll = null;  // scrollable item list
var _summaryBox = null;  // subtotal/discount/tax box
var _pricesBox = null;   // card/cash prices box
var _paidRow = null;     // dynamic paid row
var _remainRow = null;   // dynamic remaining row
var _checkIdEl = null;   // check ID display
var _nameEl = null;      // customer name display (tappable)
var _onNameTap = null;   // callback when check ID / name is tapped
var _splitBtn = null;    // split button ref
var _headerTitle = null; // header title element ref
var _colHead = null;     // column header container ref
var _summaryRowEl = null;// summary row (contains summary box + split btn)
var _mode = 'order';     // 'order' or 'checkout'
var _collapsible = false;
var _onItemTap = null;
var _onSeatHeaderTap = null;
var _expandedItems = {};
var _itemRenderLocked = false;
var _customTitle = null;

// Muted text helper (replaces T.mutedText)
function _muted() { return hexToRgba(T.text, 0.55); }

// Apply the Vz2.0 "inset well" look to a box (used for summary + prices panels).
function _applyWellStyle(box) {
  box.style.background   = T.well;
  box.style.borderLeft   = T.accentBarW + ' solid ' + T.green;
  box.style.borderRadius = '8px';
  box.style.boxSizing    = 'border-box';
}

function _container() {
  if (!_el) _el = document.getElementById('order-summary');
  return _el;
}

// ═══════════════════════════════════════════════════
//  BUILD — One-time panel construction
// ═══════════════════════════════════════════════════

function _build() {
  var el = _container();
  if (!el) return;
  el.innerHTML = '';

  el.style.cssText += [
    'display:none;',
    'flex-direction:column;',
    'background:' + T.card + ';',
    'border-left:' + T.accentBarW + ' solid ' + T.green + ';',
    'border-radius:' + T.chamferCard + 'px;',
    'box-shadow:0 4px 16px rgba(0,0,0,0.28);',
    'overflow:hidden;',
  ].join('');

  // ── Header ──
  var header = document.createElement('div');
  header.style.cssText = [
    'padding:10px 14px;flex-shrink:0;',
    'background:' + T.green + ';',
    'display:flex;justify-content:space-between;align-items:center;',
    'gap:8px;',
  ].join('');

  _headerTitle = document.createElement('div');
  _headerTitle.style.cssText = [
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsB3 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.well + ';',
    'letter-spacing:0.12em;',
    'text-transform:uppercase;',
  ].join('');
  _headerTitle.textContent = 'ORDER RECAP';

  var checkWrap = document.createElement('div');
  checkWrap.style.cssText = 'display:flex;flex-direction:column;align-items:flex-end;cursor:pointer;min-width:0;';
  _checkIdEl = document.createElement('div');
  _checkIdEl.style.cssText = [
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsB3 + ';',
    'color:' + T.well + ';',
    'white-space:nowrap;',
  ].join('');
  _nameEl = document.createElement('div');
  _nameEl.style.cssText = [
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsB4 + ';',
    'color:' + T.well + ';',
    'opacity:0.75;',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px;',
  ].join('');
  checkWrap.appendChild(_checkIdEl);
  checkWrap.appendChild(_nameEl);
  checkWrap.addEventListener('pointerup', function() {
    if (_onNameTap) _onNameTap();
  });
  header.appendChild(_headerTitle);
  header.appendChild(checkWrap);
  el.appendChild(header);

  // ── Column headers ──
  _colHead = document.createElement('div');
  _colHead.style.cssText = [
    'display:grid;grid-template-columns:1fr 40px 68px;align-items:center;',
    'padding:6px 12px;',
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsB4 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.text + ';',
    'opacity:0.7;',
    'letter-spacing:0.12em;',
    'border-bottom:1px solid ' + T.border + ';',
    'flex-shrink:0;',
  ].join('');
  var hdrItem = document.createElement('span');
  hdrItem.textContent = 'ITEM';
  var hdrQty = document.createElement('span');
  hdrQty.textContent = 'QTY';
  hdrQty.style.cssText = 'text-align:right;';
  var hdrPrice = document.createElement('span');
  hdrPrice.textContent = 'PRICE';
  hdrPrice.style.cssText = 'text-align:right;';
  _colHead.appendChild(hdrItem);
  _colHead.appendChild(hdrQty);
  _colHead.appendChild(hdrPrice);
  el.appendChild(_colHead);

  // ── Scrollable items ──
  _itemScroll = document.createElement('div');
  _itemScroll.id = 'ticket-list';
  _itemScroll.style.cssText = [
    'flex:1;overflow-y:auto;overflow-x:hidden;',
    'padding:4px 10px;',
    'scrollbar-width:none;-ms-overflow-style:none;',
    'display:flex;flex-direction:column;gap:4px;',
  ].join('');
  // Kill the scrollbar on webkit
  _injectScrollStyle();
  el.appendChild(_itemScroll);

  // ── Bottom: [Summary | Split] row ──
  _summaryRowEl = document.createElement('div');
  _summaryRowEl.style.cssText = [
    'flex-shrink:0;display:flex;gap:6px;',
    'padding:6px 8px;',
  ].join('');

  _summaryBox = document.createElement('div');
  _summaryBox.style.cssText = 'flex:1;padding:8px 12px;';
  _applyWellStyle(_summaryBox);
  _summaryRowEl.appendChild(_summaryBox);

  _splitBtn = null;
  el.appendChild(_summaryRowEl);

  // ── Prices box ──
  _pricesBox = document.createElement('div');
  _pricesBox.style.cssText = [
    'flex-shrink:0;padding:8px 12px;margin:0 8px 8px;',
  ].join('');
  _applyWellStyle(_pricesBox);
  el.appendChild(_pricesBox);
}

var _scrollStyleInjected = false;
function _injectScrollStyle() {
  if (_scrollStyleInjected) return;
  if (document.getElementById('os-scroll-style')) { _scrollStyleInjected = true; return; }
  var s = document.createElement('style');
  s.id = 'os-scroll-style';
  s.textContent = '#ticket-list::-webkit-scrollbar{display:none}';
  document.head.appendChild(s);
  _scrollStyleInjected = true;
}

// ═══════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════

function _modRow(mod) {
  var modRow = document.createElement('div');
  modRow.style.cssText = [
    'display:grid;grid-template-columns:1fr 72px;gap:0 6px;',
    'padding:0 0 1px 10px;',
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsB3 + ';',
    'color:' + T.green + ';',
  ].join('');
  var modName = document.createElement('div');
  modName.textContent = mod.name;
  modName.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  var modPrice = document.createElement('div');
  modPrice.style.cssText = 'text-align:right;color:' + T.gold + ';';
  modPrice.textContent = mod.price > 0 ? '+$' + mod.price.toFixed(2) : '';
  modRow.appendChild(modName);
  modRow.appendChild(modPrice);
  return modRow;
}

function _halfCell(mod) {
  var td = document.createElement('div');
  td.style.cssText = 'flex:1;padding:1px 2px;color:' + T.green + ';';
  if (!mod) return td;
  var nameEl = document.createElement('div');
  nameEl.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:' + (mod.price > 0 ? '12px' : '14px') + ';';
  nameEl.textContent = mod.name;
  if (mod.price > 0) {
    var pr = document.createElement('span');
    pr.style.color = T.gold;
    pr.textContent = ' +$' + mod.price.toFixed(2);
    nameEl.appendChild(pr);
  }
  td.appendChild(nameEl);
  // Special exclusion children (secondary mods)
  if (mod.children && mod.children.length > 0) {
    for (var c = 0; c < mod.children.length; c++) {
      var childEl = document.createElement('div');
      childEl.style.cssText = 'font-size:11px;color:' + T.verm + ';font-style:italic;padding-left:4px;';
      childEl.textContent = mod.children[c].name;
      td.appendChild(childEl);
    }
  }
  return td;
}

function _summaryRow(label, value, color, bold) {
  var row = document.createElement('div');
  row.style.cssText = [
    'display:flex;justify-content:space-between;padding:2px 0;',
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsB2 + ';',
    bold ? 'font-weight:' + T.fwBold + ';' : '',
  ].join('');
  var l = document.createElement('span');
  l.style.color = T.text;
  l.textContent = label;
  var v = document.createElement('span');
  v.style.color = color || T.gold;
  v.textContent = value;
  v.setAttribute('data-val', '1');
  row.appendChild(l);
  row.appendChild(v);
  return row;
}

function _renderItems(items) {
  if (!_itemScroll) return;
  if (_itemRenderLocked) return;
  _itemScroll.innerHTML = '';
  var isCollapsible = _collapsible;
  (items || []).forEach(function(item, itemIndex) {
    // ── Seat header divider ──
    if (item.seatHeader) {
      var hdr = document.createElement('div');
      hdr.style.cssText = [
        'display:flex;justify-content:space-between;align-items:center;',
        'padding:6px 4px 4px;margin-top:6px;',
        'font-family:' + T.fh + ';',
        'font-size:' + T.fsB3 + ';',
        'font-weight:' + T.fwBold + ';',
        'color:' + T.green + ';',
        'letter-spacing:0.14em;',
        'border-bottom:2px solid ' + T.green + ';',
        'cursor:pointer;user-select:none;',
      ].join('');
      var hdrLabel = document.createElement('span');
      hdrLabel.textContent = item.seatId;
      var hdrTotal = document.createElement('span');
      hdrTotal.style.color = T.gold;
      hdrTotal.textContent = '$' + (item.seatTotal || 0).toFixed(2);
      hdr.appendChild(hdrLabel);
      hdr.appendChild(hdrTotal);
      if (_onSeatHeaderTap && item.seatIdx != null) {
        (function(idx) {
          hdr.addEventListener('pointerup', function() {
            _onSeatHeaderTap(idx);
          });
        })(item.seatIdx);
      }
      _itemScroll.appendChild(hdr);
      return;
    }

    var mods = item.mods || [];
    var hasMods = mods.length > 0;

    // ── Item header row ──
    var isSel = !!item.selected;
    var row = document.createElement('div');
    row.style.cssText = [
      'display:grid;grid-template-columns:1fr 40px 68px;align-items:center;',
      'padding:4px 10px 2px;',
      'font-family:' + T.fb + ';',
      'font-size:' + T.fsB2 + ';',
      'color:' + (isSel ? T.well : T.text) + ';',
      isSel ? 'background:' + T.gold + ';border-radius:6px;' : '',
      'border-bottom:1px solid ' + hexToRgba(T.border, 0.4) + ';',
      isCollapsible ? 'cursor:pointer;user-select:none;' : '',
    ].join('');
    var name = document.createElement('span');
    name.textContent = (item.sent ? '\u2713 ' : '') + item.name;
    name.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;';
    var qtyEl = document.createElement('span');
    qtyEl.style.cssText = 'text-align:right;color:' + (isSel ? T.well : T.text) + ';';
    qtyEl.textContent = String(item.qty || 1);
    var priceEl = document.createElement('span');
    priceEl.style.cssText = 'text-align:right;color:' + (isSel ? T.well : T.gold) + ';';
    priceEl.textContent = '$' + ((item.unitPrice || 0) * (item.qty || 1)).toFixed(2);
    row.appendChild(name);
    row.appendChild(qtyEl);
    row.appendChild(priceEl);

    // Collapse arrow only in collapsible mode
    var arrow = null;
    var isExpanded = !!_expandedItems[itemIndex];
    if (isCollapsible && hasMods) {
      arrow = document.createElement('span');
      arrow.style.cssText = 'flex-shrink:0;margin-left:4px;font-size:10px;color:' + _muted() + ';';
      arrow.textContent = isExpanded ? '\u25B2' : '\u25BC';
      row.appendChild(arrow);
    }

    _itemScroll.appendChild(row);

    // Attach tap handler for item selection + expand/collapse
    if (isCollapsible) {
      (function(idx) {
        row.addEventListener('pointerup', function() {
          if (_onItemTap) _onItemTap(idx);
        });
      })(itemIndex);
    }

    if (!hasMods) return;

    // ── Modifier detail container ──
    var modDetail = document.createElement('div');
    if (isCollapsible && !isExpanded) modDetail.style.display = 'none';

    // Partition into whole / left / right
    var wholeMods = [];
    var leftMods = [];
    var rightMods = [];
    for (var m = 0; m < mods.length; m++) {
      if (mods[m].prefix === 'Left') leftMods.push(mods[m]);
      else if (mods[m].prefix === 'Right') rightMods.push(mods[m]);
      else wholeMods.push(mods[m]);
    }

    // Whole mods + children
    for (var w = 0; w < wholeMods.length; w++) {
      modDetail.appendChild(_modRow(wholeMods[w]));
      if (wholeMods[w].children && wholeMods[w].children.length > 0) {
        for (var c = 0; c < wholeMods[w].children.length; c++) {
          var childRow = _modRow(wholeMods[w].children[c]);
          childRow.style.paddingLeft = '20px';
          childRow.style.color = T.verm;
          childRow.style.fontStyle = 'italic';
          modDetail.appendChild(childRow);
        }
      }
    }

    // 1st/2nd table (half-and-half mods, e.g. pizza)
    if (leftMods.length > 0 || rightMods.length > 0) {
      var halfTable = document.createElement('div');
      halfTable.style.cssText = 'padding:2px 0 2px 10px;';

      var hdrRow = document.createElement('div');
      hdrRow.style.cssText = [
        'display:flex;',
        'border-bottom:1px solid ' + _muted() + ';',
        'margin-bottom:1px;',
        'font-family:' + T.fb + ';font-size:' + T.fsB3 + ';',
        'font-weight:' + T.fwBold + ';',
        'color:' + T.green + ';',
      ].join('');
      var hdrL = document.createElement('div');
      hdrL.style.cssText = 'flex:1;text-align:center;';
      hdrL.textContent = '1ST';
      var hdrSep = document.createElement('div');
      hdrSep.style.cssText = 'width:1px;background:' + _muted() + ';margin:0 3px;';
      var hdrR = document.createElement('div');
      hdrR.style.cssText = 'flex:1;text-align:center;';
      hdrR.textContent = '2ND';
      hdrRow.appendChild(hdrL);
      hdrRow.appendChild(hdrSep);
      hdrRow.appendChild(hdrR);
      halfTable.appendChild(hdrRow);

      var maxRows = Math.max(leftMods.length, rightMods.length);
      for (var r = 0; r < maxRows; r++) {
        var tr = document.createElement('div');
        tr.style.cssText = 'display:flex;font-family:' + T.fb + ';line-height:1.3;';
        var tdL = _halfCell(leftMods[r]);
        var tdSep2 = document.createElement('div');
        tdSep2.style.cssText = 'width:1px;background:' + _muted() + ';margin:0 3px;flex-shrink:0;';
        var tdR = _halfCell(rightMods[r]);
        tr.appendChild(tdL);
        tr.appendChild(tdSep2);
        tr.appendChild(tdR);
        halfTable.appendChild(tr);
      }

      modDetail.appendChild(halfTable);
    }

    _itemScroll.appendChild(modDetail);

    // Toggle expand/collapse on tap (item selection handled above for all items)
    if (isCollapsible && hasMods) {
      (function(detail, arrowEl, idx) {
        row.addEventListener('pointerup', function() {
          if (detail && arrowEl) {
            var isOpen = detail.style.display !== 'none';
            detail.style.display = isOpen ? 'none' : '';
            arrowEl.textContent = isOpen ? '\u25BC' : '\u25B2';
            if (isOpen) delete _expandedItems[idx];
            else _expandedItems[idx] = true;
          }
        });
      })(modDetail, arrow, itemIndex);
    }
  });
}

function _renderSummary(params) {
  if (!_summaryBox) return;
  _summaryBox.innerHTML = '';
  _summaryBox.appendChild(_summaryRow('Subtotal:', '$' + (params.subtotal || 0).toFixed(2), T.gold));
  if (params.discount && params.discount > 0) {
    _summaryBox.appendChild(_summaryRow('Discount:', '$' + params.discount.toFixed(2), T.gold));
  }
  _summaryBox.appendChild(_summaryRow('Tax:', '$' + (params.tax || 0).toFixed(2), T.gold));
  _applyWellStyle(_summaryBox);
}

function _renderPrices(params) {
  if (!_pricesBox) return;
  _pricesBox.innerHTML = '';
  _pricesBox.appendChild(_summaryRow('Card Price:', '$' + (params.cardTotal || 0).toFixed(2), T.elec, true));
  _pricesBox.appendChild(_summaryRow('Cash Price:', '$' + (params.cashPrice || 0).toFixed(2), T.gold, true));

  // Dynamic split-progress rows (hidden until partial payment)
  _paidRow = _summaryRow('Paid:', '$0.00', T.elec);
  _paidRow.style.display = 'none';
  _pricesBox.appendChild(_paidRow);

  _remainRow = _summaryRow('Remaining:', '$' + (params.cardTotal || 0).toFixed(2), T.elec);
  _remainRow.style.display = 'none';
  _pricesBox.appendChild(_remainRow);

  _applyWellStyle(_pricesBox);
}


// ═══════════════════════════════════════════════════
//  CHECKOUT MODE — configure panel for checkout/close-day
// ═══════════════════════════════════════════════════

function _configureForMode(mode) {
  _mode = mode;
  if (mode === 'checkout') {
    if (_headerTitle) _headerTitle.textContent = 'CHECKOUT RECAP';
    if (_colHead) _colHead.style.display = 'none';
    if (_splitBtn) _splitBtn.style.display = 'none';
    if (_summaryRowEl) _summaryRowEl.style.padding = '6px 8px 0';
  } else {
    if (_headerTitle) _headerTitle.textContent = _customTitle || 'ORDER RECAP';
    if (_colHead) {
      _colHead.style.display = '';
      _colHead.style.gridTemplateColumns = '1fr 40px 68px';
      _colHead.innerHTML = '';
      ['ITEM', 'QTY', 'PRICE'].forEach(function(t, i) {
        var c = document.createElement('div');
        c.textContent = t;
        if (i > 0) c.style.textAlign = 'right';
        _colHead.appendChild(c);
      });
    }
    if (_splitBtn) _splitBtn.style.display = '';
    if (_summaryRowEl) _summaryRowEl.style.padding = '6px 8px';
  }
}

function _renderCheckoutBreakdown(params) {
  if (!_itemScroll) return;
  _itemScroll.innerHTML = '';

  var sections = params.sections || [];
  for (var s = 0; s < sections.length; s++) {
    var sec = sections[s];

    var hdr = document.createElement('div');
    hdr.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-size:' + T.fsB2 + ';',
      'font-weight:' + T.fwBold + ';',
      'color:' + T.text + ';',
      'letter-spacing:0.08em;',
      'padding:6px 0 2px;',
      s > 0 ? 'border-top:1px solid ' + T.border + ';margin-top:4px;' : '',
    ].join('');
    hdr.textContent = sec.title;
    _itemScroll.appendChild(hdr);

    var rows = sec.rows || [];
    for (var r = 0; r < rows.length; r++) {
      _itemScroll.appendChild(_summaryRow(rows[r].label, rows[r].value, T.gold));
    }
  }
}

function _renderCheckoutSummary(params) {
  if (!_summaryBox) return;
  _summaryBox.innerHTML = '';
  _summaryBox.appendChild(_summaryRow('Cash Sales:', '$' + (params.cashSales || 0).toFixed(2), T.gold));
  _summaryBox.appendChild(_summaryRow('Tips:', '$' + (params.tips || 0).toFixed(2), T.gold));
  _applyWellStyle(_summaryBox);
}

function _renderCashExpected(params) {
  if (!_pricesBox) return;
  _pricesBox.innerHTML = '';

  var label = document.createElement('div');
  label.style.cssText = [
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsB2 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.text + ';',
    'letter-spacing:0.08em;',
    'text-align:center;margin-bottom:2px;',
  ].join('');
  label.textContent = 'CASH EXPECTED';
  _pricesBox.appendChild(label);

  var hero = document.createElement('div');
  hero.style.cssText = [
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsH3 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.gold + ';',
    'text-align:center;padding:4px 0;',
  ].join('');
  hero.textContent = '$' + (params.cashExpected || 0).toFixed(2);
  hero.setAttribute('data-cash-expected', '1');
  _pricesBox.appendChild(hero);

  _applyWellStyle(_pricesBox);
}

// ═══════════════════════════════════════════════════
//  PUBLIC API
// ═══════════════════════════════════════════════════

export var OrderSummary = {

  show: function(params) {
    params = params || {};
    var el = _container();
    if (!el) return;

    if (!_itemScroll) _build();
    _collapsible = !!params.collapsible;
    _onItemTap = params.onItemTap || null;
    _onSeatHeaderTap = params.onSeatHeaderTap || null;
    _customTitle = params.title || null;
    _configureForMode('order');

    if (_checkIdEl) _checkIdEl.textContent = params.checkId || '';
    if (_nameEl) _nameEl.textContent = params.customerName || '';
    _onNameTap = params.onNameTap || null;
    _itemRenderLocked = false;

    _renderItems(params.items);
    _renderSummary(params);
    _renderPrices(params);

    SceneManager.showSummary();
  },

  hide: function() {
    _onNameTap = null;
    _onItemTap = null;
    SceneManager.hideSummary();
  },

  lockItemRender: function() { _itemRenderLocked = true; },
  unlockItemRender: function() { _itemRenderLocked = false; },

  update: function(params) {
    params = params || {};
    if (_checkIdEl && params.checkId !== undefined) _checkIdEl.textContent = params.checkId;
    if (_nameEl && params.customerName !== undefined) _nameEl.textContent = params.customerName || '';
    if (params.onNameTap !== undefined) _onNameTap = params.onNameTap;
    if (params.onItemTap !== undefined) _onItemTap = params.onItemTap;
    if (params.onSeatHeaderTap !== undefined) _onSeatHeaderTap = params.onSeatHeaderTap;
    if (params.items && !params.skipItems) _renderItems(params.items);
    _renderSummary(params);
    _renderPrices(params);
  },

  updateSplit: function(opts) {
    opts = opts || {};
    if (_paidRow) {
      _paidRow.style.display = 'flex';
      var pv = _paidRow.querySelector('[data-val]');
      if (pv) pv.textContent = '$' + (opts.totalPaid || 0).toFixed(2);
    }
    if (_remainRow) {
      _remainRow.style.display = 'flex';
      var rv = _remainRow.querySelector('[data-val]');
      if (rv) rv.textContent = '$' + (opts.remaining || 0).toFixed(2);
    }
  },

  showCheckout: function(params) {
    params = params || {};
    var el = _container();
    if (!el) return;
    if (!_itemScroll) _build();
    _configureForMode('checkout');

    if (_headerTitle && params.title) _headerTitle.textContent = params.title;
    if (_checkIdEl) _checkIdEl.textContent = params.label || '';

    _renderCheckoutBreakdown(params);
    _renderCheckoutSummary(params);
    _renderCashExpected(params);

    SceneManager.showSummary();
  },

  updateCheckout: function(params) {
    params = params || {};
    if (_headerTitle && params.title) _headerTitle.textContent = params.title;
    if (_checkIdEl && params.label !== undefined) _checkIdEl.textContent = params.label;
    if (params.checks) _renderCheckoutBreakdown(params);
    _renderCheckoutSummary(params);
    _renderCashExpected(params);
  },

  getElement: function() {
    return _container();
  },
};