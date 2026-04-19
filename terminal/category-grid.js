// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Category Grid Component
//  Chamfered-tile nav, drop-in HexNav replacement
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { T } from './tokens.js';
import { hexToRgba } from './theme-manager.js';
import { applyCardBevel, chamfer } from './sm2-shim.js';

// Shrink label font until it fits the tile. Allows natural multi-word
// wrapping; shrinks when a single long word overflows width, or when
// wrapped lines overflow height. Runs after first paint so layout is real.
function _fitLabel(tile, lbl) {
  requestAnimationFrame(function() {
    var max = 26;
    var min = 12;
    var size = max;
    lbl.style.fontSize = size + 'px';
    var availW = tile.clientWidth  - 20;
    var availH = tile.clientHeight - 16;
    if (availW <= 0 || availH <= 0) return;
    while (size > min && (lbl.scrollWidth > availW || lbl.scrollHeight > availH)) {
      size -= 1;
      lbl.style.fontSize = size + 'px';
    }
  });
}

function _alphaCmp(a, b) {
  var la = String(a.label || a.name || a).toLowerCase();
  var lb = String(b.label || b.name || b).toLowerCase();
  return la < lb ? -1 : la > lb ? 1 : 0;
}

// ═══════════════════════════════════════════════════
//  CategoryGrid
//  Usage:
//    var grid = new CategoryGrid(containerEl, {
//      data: menuData,            // array of cat objects
//      onSelect: fn(item, mods),  // called on leaf tap (mods always {})
//      columns: 3,                // grid columns (default 3)
//      sort:    'alpha',          // 'alpha' | 'none' | fn(a,b) (default 'alpha')
//    });
//    grid.setData(newData);       // swap data, return to State A
//    grid.setColumns(n);          // re-layout with a new column count
//    grid.setSort(spec);          // change sort ('alpha' | 'none' | fn)
//    grid.reset();                // return to State A
//    grid.destroy();              // remove from DOM
//
//  HexNav-compatible stubs so order-entry's combo/modifier paths keep
//  working without touching hex-nav.js:
//    grid.getCatId()
//    grid.lockNav() / grid.unlockNav()
//    grid.showPickList(label, color, textColor, items)
// ═══════════════════════════════════════════════════

export function CategoryGrid(container, opts) {
  var o        = opts || {};
  var onSelect = o.onSelect || function() {};
  var data     = o.data    || [];
  var columns  = o.columns || 3;
  var sortSpec = o.sort    !== undefined ? o.sort : 'alpha';

  // Drill path. Empty = State A (categories). Non-empty = State B
  // with the top of the stack as the parent back tile.
  var path = [];
  var navLocked = false;

  // Mandatory-modifier picking state. When active, the grid shows the
  // item's requiredMods groups (and drills into each group's choices)
  // instead of the cat/subcat nav.
  var modState = {
    active:       false,
    item:         null,
    groups:       [],    // filtered list of groups with choices
    selectedMods: [],    // [{ group, label, price }]
    satisfied:    {},    // { groupId: true }
    group:        null,  // currently drilled-into group, else null
  };

  function resetMods() {
    modState.active = false;
    modState.item = null;
    modState.groups = [];
    modState.selectedMods = [];
    modState.satisfied = {};
    modState.group = null;
  }

  // ── Root element ──
  var root = document.createElement('div');
  applyGridStyle();
  container.appendChild(root);

  function applyGridStyle() {
    root.style.cssText = [
      'width:100%;height:100%;box-sizing:border-box;',
      'display:grid;grid-template-columns:repeat(' + columns + ', 1fr);gap:12px;',
      'padding:12px;',
      'background:' + T.bg + ';',
      'border-radius:0;',
      'overflow:auto;align-content:start;',
    ].join('');
  }

  function sortChildren(children) {
    if (!children || children.length === 0) return children;
    if (sortSpec === 'none') return children;
    var cmp = typeof sortSpec === 'function' ? sortSpec : _alphaCmp;
    return children.slice().sort(cmp);
  }

  // Build a tile element.
  //   mode: 'border' (idle cat/subcat) or 'solid' (parent back tile)
  function buildTile(cfg) {
    var mode   = cfg.mode || 'border';
    var color  = cfg.color || T.mint;
    var label  = cfg.label || '';
    var price  = cfg.price;
    var isBack = !!cfg.back;
    var onTap  = cfg.onTap;

    var tile = document.createElement('div');

    var baseBg   = mode === 'solid' ? color    : T.bgDark;
    var labelClr = mode === 'solid' ? T.bgDark : color;

    tile.style.cssText = [
      'position:relative;box-sizing:border-box;',
      'display:flex;flex-direction:column;align-items:center;justify-content:center;',
      'min-height:120px;padding:14px 10px;',
      'background:' + baseBg + ';',
      'border-radius:0;',
      'clip-path:' + chamfer(8) + ';',
      'cursor:pointer;user-select:none;-webkit-user-select:none;',
      'pointer-events:auto;touch-action:manipulation;',
      'transition:transform 60ms, filter 60ms;',
    ].join('');

    // Style D bevel derived from the category color — light top/left,
    // dark bottom/right — same helper used by the rest of the chassis.
    applyCardBevel(tile, color, 7);

    if (mode === 'border') {
      tile.style.boxShadow = '0 0 8px ' + hexToRgba(color, 0.33);
    } else {
      tile.style.boxShadow = 'inset 0 2px 0 ' + hexToRgba(T.bgLight, 0.5)
        + ', inset 0 -2px 0 ' + hexToRgba(T.bgEdge, 0.6);
    }

    // Label — natural wrapping; _fitLabel shrinks font on overflow.
    var lbl = document.createElement('div');
    lbl.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-weight:bold;font-size:26px;line-height:1.1;',
      'color:' + labelClr + ';',
      'text-align:center;pointer-events:none;',
      'max-width:100%;',
    ].join('');
    lbl.textContent = label;
    tile.appendChild(lbl);
    _fitLabel(tile, lbl);

    // Price (gold) if provided
    if (price !== undefined && price !== null && price !== '') {
      var p = document.createElement('div');
      p.style.cssText = [
        'font-family:' + T.fb + ';',
        'font-size:20px;margin-top:6px;',
        'color:' + T.gold + ';',
        'pointer-events:none;',
      ].join('');
      var pv = Number(price);
      p.textContent = isNaN(pv) ? String(price) : ('$' + pv.toFixed(2));
      tile.appendChild(p);
    }

    if (isBack) {
      var back = document.createElement('div');
      back.style.cssText = [
        'position:absolute;left:0;right:0;bottom:8px;',
        'font-family:' + T.fh + ';',
        'font-weight:bold;font-size:16px;letter-spacing:2px;',
        'color:' + T.bgDark + ';',
        'text-align:center;pointer-events:none;',
      ].join('');
      back.textContent = '\u2190 BACK';
      tile.appendChild(back);
    }

    // Visual press state via pointer events, tap via click event so a
    // small finger wiggle doesn't cancel the tap (pointerleave would).
    tile.addEventListener('pointerdown', function() {
      tile.style.transform = 'translate(2px, 3px)';
      tile.style.filter = 'brightness(1.1)';
    });
    function resetPress() {
      tile.style.transform = '';
      tile.style.filter = '';
    }
    tile.addEventListener('pointerup',     resetPress);
    tile.addEventListener('pointercancel', resetPress);
    tile.addEventListener('pointerleave',  resetPress);
    tile.addEventListener('click', function() {
      if (navLocked) return;
      if (onTap) onTap();
    });

    return tile;
  }

  // ── Data helpers ──
  // Categories in this menu wrap items in a single "subcats[0].items"
  // array. Treat that wrapper as transparent so drilling into a cat
  // shows items directly.
  function childrenOf(node) {
    if (node.subcats && node.subcats.length > 0) {
      if (node.subcats.length === 1 && node.subcats[0].items) {
        return node.subcats[0].items;
      }
      return node.subcats;
    }
    if (node.items) return node.items;
    return [];
  }

  function hasChildren(node) {
    if (node.subcats && node.subcats.length > 0) return true;
    if (node.items && node.items.length > 0) return true;
    return false;
  }

  // ── Render ──
  function render() {
    root.innerHTML = '';
    if (modState.active) {
      if (modState.group) renderModChoices();
      else                renderModGroups();
      return;
    }
    if (path.length === 0) renderStateA();
    else                    renderStateB();
  }

  function renderStateA() {
    sortChildren(data).forEach(function(cat) {
      root.appendChild(buildTile({
        mode:  'border',
        color: cat.color || T.mint,
        label: cat.label || cat.name || '',
        onTap: function() { drillInto(cat); },
      }));
    });
  }

  function renderStateB() {
    var parent      = path[path.length - 1];
    var parentColor = parent.color || T.mint;
    var children    = sortChildren(childrenOf(parent));

    root.appendChild(buildTile({
      mode:  'solid',
      color: parentColor,
      label: parent.label || parent.name || '',
      back:  true,
      onTap: function() { goBack(); },
    }));

    children.forEach(function(child) {
      root.appendChild(buildTile({
        mode:  'border',
        color: parentColor,
        label: child.label || child.name || '',
        price: child.price,
        onTap: function() {
          if (hasChildren(child)) {
            drillInto(child);
          } else if (child.requiredMods && child.requiredMods.length > 0) {
            startMods(child);
          } else {
            onSelect(child, {});
          }
        },
      }));
    });
  }

  // ── Modifier flow ──
  // Backend payloads sometimes use `name`/`modifier_id` instead of the
  // `label`/`id` documented in hex-nav. Normalize both shapes so tiles
  // always show a human name.
  function _label(o) {
    return (o && (o.label || o.name)) || '';
  }
  function _id(o) {
    return (o && (o.id || o.group_id || o.modifier_id)) || '';
  }

  function startMods(item) {
    var groups = (item.requiredMods || []).filter(function(g) {
      return g.choices && g.choices.length > 0;
    });
    if (groups.length === 0) {
      onSelect(item, {});
      return;
    }
    modState.active = true;
    modState.item = item;
    modState.groups = groups;
    modState.selectedMods = [];
    modState.satisfied = {};
    modState.group = null;
    render();
  }

  function pickChoice(group, choice) {
    var gid = _id(group);
    // Single-select: replace any prior pick for this group.
    modState.selectedMods = modState.selectedMods.filter(function(m) {
      return m.group !== gid;
    });
    modState.selectedMods.push({
      group: gid,
      label: _label(choice),
      price: choice.price || 0,
    });
    modState.satisfied[gid] = true;
    modState.group = null;
    render();
  }

  function finalizeMods() {
    var result = {};
    for (var k in modState.item) result[k] = modState.item[k];
    result.selectedMods = modState.selectedMods.slice();
    resetMods();
    onSelect(result, {});
    render();
  }

  function cancelMods() {
    resetMods();
    render();
  }

  // Mod-flow tiles always inherit the drilled-into category color so
  // groups, choices, and the item back tile read as one family. Falls
  // back to the item's own color (pick-list flows) or mint.
  function _modColor() {
    return (path[0] && path[0].color)
        || (modState.item && modState.item.color)
        || T.mint;
  }

  function renderModGroups() {
    var item     = modState.item;
    var catColor = _modColor();

    root.appendChild(buildTile({
      mode:  'solid',
      color: catColor,
      label: _label(item),
      price: item.price,
      back:  true,
      onTap: function() { cancelMods(); },
    }));

    modState.groups.forEach(function(g) {
      var gid    = _id(g);
      var picked = null;
      modState.selectedMods.forEach(function(m) { if (m.group === gid) picked = m; });
      var isDone = !!modState.satisfied[gid];
      root.appendChild(buildTile({
        mode:  isDone ? 'solid' : 'border',
        color: catColor,
        label: picked ? picked.label : _label(g),
        onTap: function() {
          modState.group = g;
          render();
        },
      }));
    });

    var allDone = modState.groups.length > 0 && modState.groups.every(function(g) {
      return modState.satisfied[_id(g)];
    });
    if (allDone) {
      root.appendChild(buildTile({
        mode:  'solid',
        color: T.goGreen,
        label: 'DONE',
        onTap: function() { finalizeMods(); },
      }));
    }
  }

  function renderModChoices() {
    var g        = modState.group;
    var catColor = _modColor();

    root.appendChild(buildTile({
      mode:  'solid',
      color: catColor,
      label: _label(g),
      back:  true,
      onTap: function() {
        modState.group = null;
        render();
      },
    }));

    (g.choices || []).forEach(function(c) {
      root.appendChild(buildTile({
        mode:  'border',
        color: catColor,
        label: _label(c),
        price: c.price,
        onTap: function() { pickChoice(g, c); },
      }));
    });
  }

  function drillInto(node) {
    path.push(node);
    render();
  }

  function goBack() {
    path.pop();
    render();
  }

  // ── Public API ──
  this.setData = function(newData) {
    data = newData || [];
    path = [];
    resetMods();
    render();
  };

  this.setColumns = function(n) {
    columns = Math.max(1, n | 0);
    applyGridStyle();
    render();
  };

  this.setSort = function(spec) {
    sortSpec = spec !== undefined ? spec : 'alpha';
    render();
  };

  this.reset = function() {
    path = [];
    resetMods();
    render();
  };

  this.destroy = function() {
    if (root && root.parentNode) root.parentNode.removeChild(root);
  };

  // ── HexNav-compatible stubs ──
  // Top-level cat id of the current drill path (null at State A).
  this.getCatId = function() {
    return path.length > 0 ? (path[0].id || null) : null;
  };

  this.lockNav   = function() { navLocked = true;  };
  this.unlockNav = function() { navLocked = false; };

  // Replace the current view with a custom synthesized parent + items.
  // Used by the combo flow to prompt for sides / drinks.
  this.showPickList = function(label, color, textColor, items) {
    path = [{
      id:        'pick-' + (label || '').toLowerCase(),
      label:     label || '',
      color:     color || T.mint,
      textColor: textColor,
      items:     items || [],
    }];
    render();
  };

  // ── Init ──
  render();
}