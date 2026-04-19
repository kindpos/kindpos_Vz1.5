// ═══════════════════════════════════════════════════
//  KINDpos Terminal — column-editor  (Vz2.0)
//  Transactional overlay: multi-column item editor
//  Works for seats within a check or checks within a selection
//
//  Ported from SM2 version — logic preserved, visuals reskinned
//  to Nostalgia theme (pill buttons, left accent bars, border-radius).
//
//  SceneManager.openTransactional('column-editor', {
//    columns: [{ id, label, items: [{ name, qty, price }] }],
//    operations: ['MERGE', 'MOVE', 'SPLIT', 'TRANSFER'],
//    onSave: function(columns) {},
//  })
// ═══════════════════════════════════════════════════

import { SceneManager, defineScene } from '../scene-manager.js';
import { T } from '../tokens.js';
import {
  buildPillButton,
  hexToRgba,
  darkenHex,
} from '../theme-manager.js';
import { showToast } from '../components.js';
import { setHeaderBack } from '../app.js';

// ── Inject invisible scrollbar styles ──
(function() {
  if (document.getElementById('ce-scroll-style')) return;
  var s = document.createElement('style');
  s.id = 'ce-scroll-style';
  s.textContent = '.ce-scroll::-webkit-scrollbar{display:none}.ce-hscroll::-webkit-scrollbar{display:none}';
  document.head.appendChild(s);
})();

function fmt(n) { return '$' + (n || 0).toFixed(2); }

function colTotal(col) {
  var t = 0;
  for (var i = 0; i < col.items.length; i++) t += col.items[i].qty * col.items[i].price;
  return t;
}

// Color assignments per operation (replaces SM2 variants)
function _opColors(label) {
  switch (label) {
    case 'MERGE':    return { color: T.green,     dark: T.greenDk     };
    case 'CONFIRM':  return { color: T.green,     dark: T.greenDk     };
    case 'CANCEL':   return { color: T.verm,      dark: T.vermDk      };
    case 'TRANSFER': return { color: T.gold,      dark: T.goldDk      };
    case 'DONE':     return { color: T.greenWarm, dark: T.greenWarmDk };
    default:         return { color: T.card,      dark: darkenHex(T.card, 0.4) };
  }
}

defineScene({
  name: 'column-editor',

  state: {
    listeners: [],
    columns: [],
    mode: null,          // null | 'move' | 'split'
    selectedItems: [],   // [{ colIdx, itemIdx }]
    splitTargets: [],    // [colIdx] for split destinations
    colEls: [],          // DOM refs per column
    opsPanel: null,
    columnsArea: null,
    statusEl: null,
    onSave: null,
  },

  render: function(container, params, state) {
    function track(el, event, handler) {
      el.addEventListener(event, handler);
      state.listeners.push({ el: el, event: event, handler: handler });
    }

    // Deep copy columns so mutations don't affect caller. Preserve item
    // metadata (item_id, menu_item_id, mods, …) so SPLIT can keep the
    // original item_id on the first copy and the caller can PATCH
    // existing backend items instead of POSTing duplicates.
    state.columns = [];
    var srcCols = params.columns || [];
    for (var ci = 0; ci < srcCols.length; ci++) {
      var sc = srcCols[ci];
      var items = [];
      for (var ii = 0; ii < sc.items.length; ii++) {
        var it = sc.items[ii];
        items.push({
          name: it.name,
          qty: it.qty,
          price: it.price,
          item_id: it.item_id,
          menu_item_id: it.menu_item_id,
          category: it.category,
          mods: it.mods,
          notes: it.notes,
        });
      }
      state.columns.push({ id: sc.id, label: sc.label, items: items });
    }
    state.onSave = params.onSave || null;

    setHeaderBack({
      back: true,
      onBack: function() {
        if (state.onSave) state.onSave(state.columns);
        SceneManager.closeTransactional('column-editor');
      },
      x: true,
    });

    var root = document.createElement('div');
    Object.assign(root.style, {
      position:      'absolute',
      inset:         '0',
      background:    T.bg,
      display:       'flex',
      flexDirection: 'column',
      overflow:      'hidden',
    });
    container.appendChild(root);

    // ═══════════════════════════════════════════════════
    //  Operations card (top bar)
    // ═══════════════════════════════════════════════════

    var opsCard = document.createElement('div');
    Object.assign(opsCard.style, {
      margin:         '12px 12px 0',
      borderRadius:   T.chamferCard + 'px',
      background:     T.card,
      borderLeft:     T.accentBarW + ' solid ' + T.green,
      boxShadow:      '0 4px 16px rgba(0,0,0,0.28)',
      display:        'flex',
      flexDirection:  'column',
      overflow:       'hidden',
      flexShrink:     '0',
    });

    var opsH = document.createElement('div');
    Object.assign(opsH.style, {
      background:     T.green,
      height:         '32px',
      display:        'flex',
      alignItems:     'center',
      padding:        '0 14px',
      fontFamily:     T.fh,
      fontSize:       T.fsB3,
      fontWeight:     T.fwBold,
      letterSpacing:  '0.2em',
      color:          T.well,
      textTransform:  'uppercase',
    });
    opsH.textContent = 'OPERATIONS';
    opsCard.appendChild(opsH);

    var opsBody = document.createElement('div');
    Object.assign(opsBody.style, {
      padding:    '10px 12px',
      display:    'flex',
      gap:        '10px',
      alignItems: 'center',
      flexWrap:   'wrap',
    });
    state.opsPanel = opsBody;

    // Status text (shows current mode instructions)
    var statusEl = document.createElement('div');
    Object.assign(statusEl.style, {
      fontFamily: T.fb,
      fontSize:   T.fsB3,
      color:      hexToRgba(T.text, 0.75),
      marginLeft: '8px',
      flex:       '1',
      minWidth:   '0',
    });
    state.statusEl = statusEl;

    // Operation buttons
    var ops = params.operations || ['MERGE', 'MOVE', 'SPLIT', 'TRANSFER'];

    function buildOpBtn(label) {
      var c = _opColors(label);
      var btn = buildPillButton({
        label:    label,
        color:    c.color,
        darkBg:   c.dark,
        fontSize: T.fsB2,
        onClick:  function() { handleOp(label); },
      });
      // "Dark" operation buttons (MOVE, SPLIT) need light text since the
      // pill default dark-text-on-color assumes a light fill.
      if (c.color === T.card) btn.style.color = T.text;
      return btn;
    }

    for (var oi = 0; oi < ops.length; oi++) {
      opsBody.appendChild(buildOpBtn(ops[oi]));
    }

    // Done button (close overlay). In split mode, DONE first applies
    // the staged split so the user doesn't need a separate CONFIRM step.
    var doneBtn = buildPillButton({
      label:    'DONE',
      color:    T.greenWarm,
      darkBg:   T.greenWarmDk,
      fontSize: T.fsB2,
      onClick:  function() {
        if (state.mode === 'split' && state.selectedItems.length > 0 && state.splitTargets.length > 0) {
          doSplit();
        }
        if (state.onSave) state.onSave(state.columns);
        SceneManager.closeTransactional('column-editor');
      },
    });
    opsBody.appendChild(doneBtn);

    opsBody.appendChild(statusEl);

    // Rebuild the ops panel for the current mode:
    //  - split: CANCEL only — tapping DONE applies the split
    //  - move:  CANCEL only (mode persists across moves)
    //  - idle:  the full ops list
    function renderOps() {
      while (opsBody.firstChild) opsBody.removeChild(opsBody.firstChild);
      var list;
      if (state.mode === 'split') list = ['CANCEL'];
      else if (state.mode === 'move') list = ['CANCEL'];
      else list = ops;
      for (var ri = 0; ri < list.length; ri++) {
        opsBody.appendChild(buildOpBtn(list[ri]));
      }
      opsBody.appendChild(doneBtn);
      opsBody.appendChild(statusEl);
    }
    opsCard.appendChild(opsBody);
    root.appendChild(opsCard);

    // ═══════════════════════════════════════════════════
    //  Columns area (horizontal scroll, each column vertical scroll)
    // ═══════════════════════════════════════════════════

    var colsArea = document.createElement('div');
    colsArea.className = 'ce-hscroll';
    Object.assign(colsArea.style, {
      flex:            '1',
      margin:          '12px',
      display:         'flex',
      gap:             '10px',
      overflowX:       'auto',
      overflowY:       'hidden',
      scrollbarWidth:  'none',
      msOverflowStyle: 'none',
    });
    state.columnsArea = colsArea;
    root.appendChild(colsArea);

    // ═══════════════════════════════════════════════════
    //  Render columns
    // ═══════════════════════════════════════════════════

    function renderColumns() {
      colsArea.innerHTML = '';
      state.colEls = [];

      for (var ci = 0; ci < state.columns.length; ci++) {
        colsArea.appendChild(buildColumn(ci));
      }

      // Fixed "+" column on the right
      var addCol = document.createElement('div');
      Object.assign(addCol.style, {
        minWidth:       '200px',
        borderRadius:   T.chamferCard + 'px',
        border:         '2px dashed ' + hexToRgba(T.green, 0.55),
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        cursor:         'pointer',
        userSelect:     'none',
        flexShrink:     '0',
        boxSizing:      'border-box',
      });
      var addPlus = document.createElement('div');
      Object.assign(addPlus.style, {
        fontFamily: T.fh,
        fontSize:   '56px',
        fontWeight: T.fwBold,
        color:      hexToRgba(T.green, 0.65),
      });
      addPlus.textContent = '+';
      addCol.appendChild(addPlus);

      track(addCol, 'pointerup', function() { handleAddColumn(); });
      colsArea.appendChild(addCol);
    }

    function buildColumn(colIdx) {
      var col = state.columns[colIdx];

      var colEl = document.createElement('div');
      Object.assign(colEl.style, {
        minWidth:       '220px',
        maxWidth:       '300px',
        borderRadius:   T.chamferCard + 'px',
        background:     T.card,
        borderLeft:     T.accentBarW + ' solid ' + T.green,
        boxShadow:      '0 4px 16px rgba(0,0,0,0.28)',
        display:        'flex',
        flexDirection:  'column',
        overflow:       'hidden',
        flexShrink:     '0',
      });

      // Column header (tappable for split target)
      var isSplitTarget = state.mode === 'split' && state.splitTargets.indexOf(colIdx) >= 0;
      var hdr = document.createElement('div');
      Object.assign(hdr.style, {
        background:     isSplitTarget ? T.gold : T.green,
        height:         '32px',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        padding:        '0 14px',
        fontFamily:     T.fh,
        fontSize:       T.fsB3,
        fontWeight:     T.fwBold,
        letterSpacing:  '0.2em',
        color:          T.well,
        textTransform:  'uppercase',
        cursor:         'pointer',
      });

      var hdrLabel = document.createElement('span');
      hdrLabel.textContent = col.label;
      hdr.appendChild(hdrLabel);

      var hdrTotal = document.createElement('span');
      hdrTotal.style.color = T.well;
      hdrTotal.textContent = fmt(colTotal(col));
      hdr.appendChild(hdrTotal);

      track(hdr, 'pointerup', (function(idx) {
        return function() { handleColumnTap(idx); };
      })(colIdx));

      colEl.appendChild(hdr);

      // Item list (vertical scroll)
      var itemList = document.createElement('div');
      itemList.className = 'ce-scroll';
      Object.assign(itemList.style, {
        flex:            '1',
        overflowY:       'auto',
        scrollbarWidth:  'none',
        msOverflowStyle: 'none',
        padding:         '6px',
      });

      for (var ii = 0; ii < col.items.length; ii++) {
        var item = col.items[ii];
        var row = document.createElement('div');
        Object.assign(row.style, {
          display:        'flex',
          justifyContent: 'space-between',
          padding:        '6px 8px',
          fontFamily:     T.fb,
          fontSize:       T.fsB3,
          color:          T.text,
          cursor:         'pointer',
          borderBottom:   '1px solid ' + hexToRgba(T.border, 0.4),
          borderRadius:   '4px',
        });

        // Reapply selection highlight if this item is still selected
        // (selection survives re-renders during move/split).
        var isSelected = false;
        for (var si = 0; si < state.selectedItems.length; si++) {
          if (state.selectedItems[si].colIdx === colIdx && state.selectedItems[si].itemIdx === ii) {
            isSelected = true;
            break;
          }
        }
        if (isSelected) {
          row.style.background = T.gold;
          row.style.color      = T.well;
        }

        var nameEl = document.createElement('span');
        nameEl.textContent = (item.qty > 1 ? item.qty + 'x ' : '') + item.name;
        row.appendChild(nameEl);

        var priceEl = document.createElement('span');
        priceEl.style.color = isSelected ? T.well : T.gold;
        priceEl.textContent = fmt(item.qty * item.price);
        row.appendChild(priceEl);

        // Item tap for move/split selection
        (function(cIdx, iIdx, rowEl) {
          track(rowEl, 'pointerup', function() {
            handleItemTap(cIdx, iIdx, rowEl);
          });
        })(colIdx, ii, row);

        itemList.appendChild(row);
      }

      if (col.items.length === 0) {
        var emptyEl = document.createElement('div');
        Object.assign(emptyEl.style, {
          fontFamily: T.fb,
          fontSize:   T.fsB3,
          color:      hexToRgba(T.text, 0.55),
          textAlign:  'center',
          padding:    '16px 0',
        });
        emptyEl.textContent = 'Empty';
        itemList.appendChild(emptyEl);
      }

      colEl.appendChild(itemList);

      state.colEls.push({ el: colEl, hdr: hdr, hdrLabel: hdrLabel, hdrTotal: hdrTotal, itemList: itemList });
      return colEl;
    }

    // ═══════════════════════════════════════════════════
    //  Operation handlers
    // ═══════════════════════════════════════════════════

    function handleOp(op) {
      if (op === 'MERGE') doMerge();
      else if (op === 'MOVE') enterMoveMode();
      else if (op === 'SPLIT') enterSplitMode();
      else if (op === 'TRANSFER') doTransfer();
      else if (op === 'CANCEL') cancelMode();
      else if (op === 'CONFIRM') confirmAction();
    }

    function setStatus(text) {
      state.statusEl.textContent = text;
    }

    function clearMode() {
      state.mode = null;
      state.selectedItems = [];
      state.splitTargets = [];
      setStatus('');
      renderOps();
      renderColumns();
    }

    // Clear pending selection/targets but keep the current mode active.
    // Used so MOVE persists across moves until the user cancels.
    function clearSelection() {
      state.selectedItems = [];
      state.splitTargets = [];
      renderColumns();
    }

    function cancelMode() {
      clearMode();
    }

    function confirmAction() {
      if (state.mode === 'split') doSplit();
    }

    // ── MERGE ──
    function doMerge() {
      if (state.columns.length < 2) return;
      var target = state.columns[0];
      for (var ci = 1; ci < state.columns.length; ci++) {
        for (var ii = 0; ii < state.columns[ci].items.length; ii++) {
          target.items.push(state.columns[ci].items[ii]);
        }
      }
      // Recombine lines that were previously split. Two lines with the
      // same menu_item_id / name / modifier signature / notes are treated
      // as one — prices sum and we keep the first one's item_id (the
      // other's backend item gets DELETEd by check-overview's onSave).
      target.items = _collapseDuplicates(target.items);
      state.columns = [target];
      clearMode();
    }

    // Build a signature that's stable across split copies so MERGE can
    // collapse them. Mods and notes are included so "Burger extra cheese"
    // and "Burger no cheese" stay distinct.
    function _itemSignature(it) {
      var menuId = it.menu_item_id || '';
      var name = it.name || '';
      var notes = it.notes || '';
      var modSig = '';
      if (Array.isArray(it.mods) && it.mods.length) {
        modSig = it.mods.map(function(m) {
          return (m.prefix || '') + '|' + (m.name || '') + '|' + (m.price || 0);
        }).sort().join(';');
      }
      return menuId + '::' + name + '::' + modSig + '::' + notes;
    }

    function _collapseDuplicates(items) {
      var out = [];
      var indexBySig = {};
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var sig = _itemSignature(it);
        if (indexBySig[sig] !== undefined) {
          var target = out[indexBySig[sig]];
          target.price = Math.round((target.price + (it.price || 0)) * 100) / 100;
          // Prefer an existing backend item_id so we PATCH instead of
          // POST + orphan the old record.
          if (!target.item_id && it.item_id) target.item_id = it.item_id;
        } else {
          indexBySig[sig] = out.length;
          out.push({
            name: it.name,
            qty: it.qty,
            price: it.price,
            item_id: it.item_id,
            menu_item_id: it.menu_item_id,
            category: it.category,
            mods: it.mods,
            notes: it.notes,
          });
        }
      }
      return out;
    }

    // ── MOVE ──
    function enterMoveMode() {
      state.mode = 'move';
      state.selectedItems = [];
      setStatus('Select items, then tap a column header or + (CANCEL to exit)');
      renderOps();
      renderColumns();
    }

    // ── SPLIT ──
    function enterSplitMode() {
      state.mode = 'split';
      state.selectedItems = [];
      state.splitTargets = [];
      setStatus('Select items, tap the checks to split across. Tap DONE when ready.');
      renderOps();
      renderColumns();
    }

    function handleItemTap(colIdx, itemIdx, rowEl) {
      if (state.mode !== 'move' && state.mode !== 'split') return;

      var found = -1;
      for (var i = 0; i < state.selectedItems.length; i++) {
        if (state.selectedItems[i].colIdx === colIdx && state.selectedItems[i].itemIdx === itemIdx) {
          found = i;
          break;
        }
      }

      if (found >= 0) {
        state.selectedItems.splice(found, 1);
        rowEl.style.background = '';
        rowEl.style.color = T.text;
        // Also reset the price cell color — need to re-query since we don't
        // have a direct reference.
        var priceCell = rowEl.lastChild;
        if (priceCell) priceCell.style.color = T.gold;
      } else {
        state.selectedItems.push({ colIdx: colIdx, itemIdx: itemIdx });
        rowEl.style.background = T.gold;
        rowEl.style.color = T.well;
        var priceCell2 = rowEl.lastChild;
        if (priceCell2) priceCell2.style.color = T.well;
      }
    }

    function handleColumnTap(colIdx) {
      if (state.mode === 'move' && state.selectedItems.length > 0) {
        doMove(colIdx);
      } else if (state.mode === 'split') {
        toggleSplitTarget(colIdx);
      }
    }

    function handleAddColumn() {
      var nextNum = state.columns.length + 1;
      var newCol = { id: 'NEW-' + nextNum, label: 'S-' + String(nextNum).padStart(3, '0'), items: [] };

      if (state.mode === 'move' && state.selectedItems.length > 0) {
        // Move selected items into the new column; keep move mode active
        // so the user can continue moving without re-tapping MOVE.
        var moved = extractSelectedItems();
        newCol.items = moved;
        state.columns.push(newCol);
        clearSelection();
      } else if (state.mode === 'split') {
        // Add new column as an extra split target; the split executes
        // when the user taps DONE.
        state.columns.push(newCol);
        state.splitTargets.push(state.columns.length - 1);
        setStatus('Select items, tap the checks to split across, then tap DONE  (' + state.splitTargets.length + ' targets)');
        renderColumns();
      } else {
        state.columns.push(newCol);
        renderColumns();
      }
    }

    function extractSelectedItems() {
      // Sort descending by itemIdx so splicing doesn't shift indices
      var sorted = state.selectedItems.slice().sort(function(a, b) {
        if (a.colIdx !== b.colIdx) return b.colIdx - a.colIdx;
        return b.itemIdx - a.itemIdx;
      });
      var items = [];
      for (var i = 0; i < sorted.length; i++) {
        var s = sorted[i];
        var removed = state.columns[s.colIdx].items.splice(s.itemIdx, 1)[0];
        items.push(removed);
      }
      items.reverse();
      return items;
    }

    function doMove(targetColIdx) {
      var moved = extractSelectedItems();
      for (var i = 0; i < moved.length; i++) {
        state.columns[targetColIdx].items.push(moved[i]);
      }
      // Keep MOVE mode active so the user can move again without
      // re-tapping MOVE. CANCEL exits.
      clearSelection();
    }

    function toggleSplitTarget(colIdx) {
      var found = state.splitTargets.indexOf(colIdx);
      if (found >= 0) {
        state.splitTargets.splice(found, 1);
        if (state.colEls[colIdx]) state.colEls[colIdx].hdr.style.background = T.green;
      } else {
        state.splitTargets.push(colIdx);
        if (state.colEls[colIdx]) state.colEls[colIdx].hdr.style.background = T.gold;
      }
      setStatus('Select items, tap the checks to split across, then tap DONE  (' + state.splitTargets.length + ' targets)');
    }

    function doSplit() {
      if (state.selectedItems.length === 0) return;

      // Group selections by source column so splicing doesn't shift indices
      // within a column. Track each item's source so the split always
      // includes the seat the item came from — tapping a single target seat
      // should produce a 2-way split (source + target), not a move.
      var bySource = {};
      state.selectedItems.forEach(function(sel) {
        if (!bySource[sel.colIdx]) bySource[sel.colIdx] = [];
        bySource[sel.colIdx].push(sel.itemIdx);
      });

      var extracted = []; // [{ item, source }]
      Object.keys(bySource).forEach(function(colIdxStr) {
        var colIdx = Number(colIdxStr);
        var idxs = bySource[colIdx].slice().sort(function(a, b) { return b - a; });
        idxs.forEach(function(itemIdx) {
          var item = state.columns[colIdx].items[itemIdx];
          state.columns[colIdx].items.splice(itemIdx, 1);
          extracted.push({ item: item, source: colIdx });
        });
      });

      for (var i = 0; i < extracted.length; i++) {
        var item = extracted[i].item;
        var source = extracted[i].source;

        // Destination set = this item's source column ∪ any tapped targets.
        var destSet = {};
        destSet[source] = true;
        for (var tt = 0; tt < state.splitTargets.length; tt++) {
          destSet[state.splitTargets[tt]] = true;
        }
        var targets = Object.keys(destSet).map(Number);
        var targetCount = targets.length;

        // Divide the EFFECTIVE price (base + modifier total) so the
        // customer's total stays the same after a split. Mods are
        // stripped from each split copy — their cost is rolled into
        // the new base. onSave detects the mods changed vs. the
        // original backend record and DELETE+POSTs instead of PATCHing,
        // which is the only way to strip mods from an existing line.
        var modTotal = Array.isArray(item.mods)
          ? item.mods.reduce(function(s, m) { return s + (m.price || 0); }, 0)
          : 0;
        var effective = (item.price || 0) + modTotal;
        var splitPrice = Math.round(effective / targetCount * 100) / 100;
        var remainder = Math.round((effective - splitPrice * targetCount) * 100) / 100;

        for (var t = 0; t < targetCount; t++) {
          var tIdx = targets[t];
          var price = splitPrice;
          if (t === 0) price = splitPrice + remainder; // first target absorbs rounding
          var splitItem = {
            name: item.name,
            qty: item.qty,
            price: price,
            menu_item_id: item.menu_item_id,
            category: item.category,
            mods: [],
            notes: item.notes,
          };
          // First copy keeps item_id so onSave can DELETE that exact
          // backend record before POSTing the rebuilt line.
          if (t === 0 && item.item_id) {
            splitItem.item_id = item.item_id;
          }
          state.columns[tIdx].items.push(splitItem);
        }
      }

      clearMode();
    }

    // ── TRANSFER ──
    function doTransfer() {
      var orderId = params.orderId || null;
      var currentServerId = params.serverId || null;
      SceneManager.interrupt('server-picker', {
        onConfirm: function(server) {
          if (!orderId) {
            showToast('Transfer: ' + server.employee_name + ' (no order to update)', { bg: T.gold });
            return;
          }
          // Reassign the order to the selected server
          fetch('/api/v1/orders/' + orderId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              server_id: server.employee_id,
              server_name: server.employee_name,
            }),
          }).then(function(r) {
            if (r.ok) showToast('Transferred to ' + server.employee_name, { bg: T.greenWarm });
            else showToast('Transfer failed', { bg: T.verm });
          }).catch(function() { showToast('Transfer failed', { bg: T.verm }); });
        },
        onCancel: function() {},
        params: { excludeId: currentServerId },
      });
    }

    // Initial render
    renderColumns();
  },

  unmount: function(state) {
    for (var i = 0; i < state.listeners.length; i++) {
      var l = state.listeners[i];
      l.el.removeEventListener(l.event, l.handler);
    }
    state.listeners = [];
  },
});