// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Modifier Panel
//  Single-screen modifier builder for menu items
//  Overlays on the hex-canvas in order-entry scene
//  All state is ephemeral until SEND
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { T } from './tokens.js';
import { buildStyledButton, applySunkenStyle, chamfer, shadowColor, applyCardBevel } from './sm2-shim.js';
import { showKeyboard } from './keyboard.js';
import { SceneManager, defineScene } from './scene-manager.js';
import { buildCard } from './theme-manager.js';

// ── Standard allergen list (FDA/industry standard colors) ──
var ALLERGENS = [
  { id: 'dairy',     label: 'Dairy',        color: '#4A90D9' },
  { id: 'eggs',      label: 'Eggs',         color: '#F5C518' },
  { id: 'fish',      label: 'Fish',         color: '#1B3A5C', light: true },
  { id: 'gluten',    label: 'Gluten',       color: '#A0794A' },
  { id: 'nuts',      label: 'Nuts',         color: '#E87C1E' },
  { id: 'shellfish', label: 'Shellfish',    color: '#D94040' },
  { id: 'soy',       label: 'Soy',          color: '#5AAE3A' },
  { id: 'other',     label: 'Other / Note', color: '#8855BB' },
];

// ── Prefix definitions for optional section ──
var OPT_PREFIXES = [
  { id: 'ADD',     label: 'ADD',     variant: 'mint' },
  { id: 'NO',      label: 'NO',      variant: 'vermillion' },
  { id: 'EXTRA',   label: 'EXTRA',   variant: 'dark' },
  { id: 'ON SIDE', label: 'ON SIDE', variant: 'gold' },
  { id: 'SUB',     label: 'SUB',     variant: 'ghost' },
];

// ── Placement segments ──
var PLACEMENTS = [
  { id: '1st',   label: '1st' },
  { id: 'whole', label: 'Whole' },
  { id: '2nd',   label: '2nd' },
];

/**
 * ModifierPanel — single-screen modifier builder
 *
 * Layout:
 *   ┌──────────────────────────────────────────┐
 *   │  Item Name: Modifiers                    │
 *   ├──────────────────────────────────────────┤
 *   │  [1st | Whole | 2nd]                     │
 *   ├──────────────────────────────────────────┤
 *   │ ┌─ Mandatory: ────────────────────────┐  │
 *   │ │ Size: [Sm][Med][Lg][XL]             │  │
 *   │ └────────────────────────────────────-┘  │
 *   │ ┌─ Included: ────────────────────────┐   │
 *   │ │  [Cheese] [Sauce]                  │   │
 *   │ └────────────────────────────────────-┘  │
 *   │ ┌─ Optional: ────────────────────────┐   │
 *   │ │  [grid of options]                 │   │
 *   │ │  [ADD][NO][EXTRA][ON SIDE][SUB]    │   │
 *   │ └────────────────────────────────────-┘  │
 *   ├──────────────────────────────────────────┤
 *   │  [<<<]  [NOTE] [ALRG]    [CONFIRM]      │
 *   └──────────────────────────────────────────┘
 */
export function ModifierPanel(container, opts) {
  var self = this;
  var item = opts.item;
  var config = item.modifierConfig || {};
  var onUpdate = opts.onUpdate || function() {};
  var onSend = opts.onSend || function() {};
  var onCancel = opts.onCancel || function() {};
  var catColor = opts.catColor || T.mint;
  var enablePlacement = opts.enablePlacement === true;

  // ── Active item state (ephemeral until SEND) ──
  var activeItem = {
    itemId: item.id || item.label.toLowerCase().replace(/\s+/g, '-'),
    itemLabel: item.label,
    basePrice: item.price || 0,
    mandatorySelections: {},
    optionalModifiers: [],
    includedRemovals: [],
    allergens: [],
    allergenNote: '',
    note: '',
  };

  // Initialize mandatory defaults
  var mandatoryGroups = config.mandatoryGroups || [];
  mandatoryGroups.forEach(function(g) {
    if (g.defaultKey) {
      var opt = g.options.find(function(o) { return o.key === g.defaultKey; });
      if (opt) {
        activeItem.mandatorySelections[g.key] = { key: opt.key, label: opt.label, price: opt.price || 0 };
      }
    }
  });

  var includedItems = config.includedItems || [];
  var optionalGroups = config.optionalGroups || [];
  // Mandatory group key whose selection drives optional-modifier pricing.
  // When set AND unchosen, the OPT tab is gated until a selection is made.
  var pricingDriverKey = config.pricingDriverKey || null;

  var activeOptPrefix = 'ADD';
  var activePlacement = 'whole';
  var expandedSection = mandatoryGroups.length > 0 ? 'mandatory' : null;
  var expandedMandGroup = null; // key of expanded mandatory group card

  // ── DOM refs ──
  var rootEl = null;
  var _mainCard = null;
  var placementBarEl = null;
  var _tabBar = null;
  var mandatoryContentEl = null;
  var includedContentEl = null;
  var optionalContentEl = null;
  var prefixBarEl = null;
  var _notePairRef = null;
  var _alrgPairRef = null;

  // ── Bevel helpers (match clock-in card pattern) ──
  function _lightenHex(hex, pct) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return '#' + [
      Math.min(255, Math.round(r + (255 - r) * pct)),
      Math.min(255, Math.round(g + (255 - g) * pct)),
      Math.min(255, Math.round(b + (255 - b) * pct)),
    ].map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
  }
  function _darkenHex(hex, pct) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    var f = 1 - pct;
    return '#' + [Math.round(r * f), Math.round(g * f), Math.round(b * f)]
      .map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
  }

  // ── Build section content container ──
  function _buildSectionContent() {
    var content = document.createElement('div');
    content.style.cssText = [
      'flex:1;min-height:0;',
      'overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none;',
      'padding:6px 8px;',
    ].join('');
    return content;
  }

  // ── Tab references ──
  var _tabEls = {};
  var _tabColors = {};
  var _sectionKeys = [];

  function _renderTabs() {
    if (!_tabBar) return;
    for (var i = 0; i < _sectionKeys.length; i++) {
      var key = _sectionKeys[i];
      var tab = _tabEls[key];
      if (!tab) continue;
      var isActive = expandedSection === key;
      var color = _tabColors[key] || T.mint;
      tab.style.background = isActive ? color : T.bgDark;
      tab.style.color = isActive ? T.bgDark : color;
      tab.style.borderBottom = isActive ? '3px solid ' + color : '3px solid transparent';
    }
    // Update card border to match active tab color
    var activeColor = _tabColors[expandedSection] || T.numpadChassis;
    if (_mainCard) {
      _mainCard.style.borderTop = '5px solid ' + _lightenHex(activeColor, 0.2);
      _mainCard.style.borderLeft = '5px solid ' + _lightenHex(activeColor, 0.2);
      _mainCard.style.borderBottom = '5px solid ' + _darkenHex(activeColor, 0.3);
      _mainCard.style.borderRight = '5px solid ' + _darkenHex(activeColor, 0.3);
    }
    // Gate OPT tab until the pricing-driver mandatory has a selection
    var optGated = _isOptionalGated();
    var optTab = _tabEls['optional'];
    if (optTab) {
      optTab.style.opacity = optGated ? '0.35' : '';
      optTab.style.cursor = optGated ? 'not-allowed' : 'pointer';
    }
    if (optGated && expandedSection === 'optional') {
      expandedSection = mandatoryGroups.length > 0 ? 'mandatory' : (includedItems.length > 0 ? 'included' : null);
    }

    // Show/hide content panels
    if (mandatoryContentEl) mandatoryContentEl.style.display = expandedSection === 'mandatory' ? '' : 'none';
    if (includedContentEl) includedContentEl.style.display = expandedSection === 'included' ? '' : 'none';
    if (optionalContentEl) optionalContentEl.style.display = expandedSection === 'optional' ? '' : 'none';
    // Prefixes: only for optional
    if (prefixBarEl) prefixBarEl.style.display = expandedSection === 'optional' ? 'flex' : 'none';
    // Placement: optional + included, only if category has it enabled
    if (placementBarEl) {
      var placementVisible = enablePlacement && (expandedSection === 'optional' || expandedSection === 'included');
      placementBarEl.style.display = placementVisible ? '' : 'none';
    }
  }

  function _isOptionalGated() {
    return !!pricingDriverKey && !activeItem.mandatorySelections[pricingDriverKey];
  }

  // ── Build the panel ──
  function build() {
    rootEl = document.createElement('div');
    rootEl.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;z-index:5;display:flex;flex-direction:column;gap:8px;';

    // Main card: beveled border
    _mainCard = document.createElement('div');
    var card = _mainCard;
    card.style.cssText = [
      'width:100%;flex:1;min-height:0;',
      'background:' + T.bg + ';',
      'border-top:5px solid ' + _lightenHex(T.numpadChassis, 0.2) + ';',
      'border-left:5px solid ' + _lightenHex(T.numpadChassis, 0.2) + ';',
      'border-bottom:5px solid ' + _darkenHex(T.numpadChassis, 0.3) + ';',
      'border-right:5px solid ' + _darkenHex(T.numpadChassis, 0.3) + ';',
      'display:flex;flex-direction:column;',
      'box-sizing:border-box;overflow:hidden;',
    ].join('');
    card.style.clipPath = chamfer(8);

    // ── Header: "Item Name: Modifiers" + ALRG/NOTE buttons ──
    var headerEl = document.createElement('div');
    headerEl.style.cssText = [
      'flex-shrink:0;padding:4px 6px 4px 10px;',
      'font-family:' + T.fh + ';font-size:18px;',
      'border-bottom:2px solid ' + _darkenHex(T.numpadChassis, 0.3) + ';',
      'background:' + T.bgDark + ';',
      'display:flex;align-items:center;gap:6px;',
    ].join('');

    var titleEl = document.createElement('div');
    titleEl.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    var nameSpan = document.createElement('span');
    nameSpan.style.color = catColor;
    nameSpan.textContent = activeItem.itemLabel;
    var modSpan = document.createElement('span');
    modSpan.style.color = T.textPrimary;
    modSpan.textContent = ': Modifiers';
    titleEl.appendChild(nameSpan);
    titleEl.appendChild(modSpan);
    headerEl.appendChild(titleEl);

    // ALRG button (header)
    _alrgPairRef = buildStyledButton({ label: 'ALRG', variant: 'vermillion', size: 'sm', onClick: function() {
      SceneManager.interrupt('allergen-select', {
        onConfirm: function() {
          fireUpdate();
          _refreshAlrgBtn();
        },
        onCancel: function() {
          fireUpdate();
          _refreshAlrgBtn();
        },
        params: { activeItem: activeItem, fireUpdate: fireUpdate },
      });
    }});
    _alrgPairRef.wrap.style.minWidth = '0';
    _alrgPairRef.wrap.style.width = '72px';
    _alrgPairRef.wrap.style.height = '32px';
    _alrgPairRef.inner.style.padding = '2px 8px';
    _alrgPairRef.inner.style.fontSize = '15px';
    _alrgPairRef.inner.style.color = '#ffffff';
    headerEl.appendChild(_alrgPairRef.wrap);
    _refreshAlrgBtn();

    // NOTE button (header)
    _notePairRef = buildStyledButton({ label: 'NOTE', variant: 'gold', size: 'sm', onClick: function() {
      showKeyboard({
        placeholder: 'Special instructions...',
        initialValue: activeItem.note,
        maxLength: 100,
        onDone: function(val) {
          activeItem.note = val || '';
          fireUpdate();
          _refreshNoteBtn();
        },
        onDismiss: function() {},
        dismissOnDone: true,
      });
    }});
    _notePairRef.wrap.style.minWidth = '0';
    _notePairRef.wrap.style.width = '72px';
    _notePairRef.wrap.style.height = '32px';
    _notePairRef.inner.style.padding = '2px 8px';
    _notePairRef.inner.style.fontSize = '15px';
    headerEl.appendChild(_notePairRef.wrap);
    _refreshNoteBtn();

    card.appendChild(headerEl);

    // ── Tab bar ──
    _tabBar = document.createElement('div');
    _tabBar.style.cssText = [
      'flex-shrink:0;display:flex;gap:0;',
      'background:' + T.bgDark + ';',
      'border-bottom:2px solid ' + _darkenHex(T.numpadChassis, 0.3) + ';',
    ].join('');
    _sectionKeys = [];

    function _addTab(label, key, color) {
      _sectionKeys.push(key);
      _tabColors[key] = color;
      var tab = document.createElement('div');
      tab.style.cssText = [
        'flex:1;text-align:center;padding:6px 4px;cursor:pointer;user-select:none;',
        'font-family:' + T.fh + ';font-size:16px;font-weight:bold;letter-spacing:1px;',
        'transition:background 80ms,color 80ms;',
      ].join('');
      tab.textContent = label;
      tab.addEventListener('pointerup', function() {
        if (key === 'optional' && _isOptionalGated()) return;
        expandedSection = key;
        _renderTabs();
      });
      _tabEls[key] = tab;
      _tabBar.appendChild(tab);
    }

    if (mandatoryGroups.length > 0) _addTab('MAND', 'mandatory', catColor);
    if (includedItems.length > 0) _addTab('INCL', 'included', T.cyan);
    if (optionalGroups.length > 0) _addTab('OPT', 'optional', T.mint);

    card.appendChild(_tabBar);

    // ── Content area (single panel, tabs switch content) ──
    var contentArea = document.createElement('div');
    contentArea.style.cssText = [
      'flex:1;display:flex;flex-direction:column;',
      'overflow:hidden;min-height:0;padding:4px;',
    ].join('');

    if (mandatoryGroups.length > 0) {
      mandatoryContentEl = _buildSectionContent();
      mandatoryContentEl.style.position = 'relative';
      contentArea.appendChild(mandatoryContentEl);
    }

    if (includedItems.length > 0) {
      includedContentEl = _buildSectionContent();
      contentArea.appendChild(includedContentEl);
    }

    if (optionalGroups.length > 0) {
      optionalContentEl = _buildSectionContent();
      contentArea.appendChild(optionalContentEl);
    }

    card.appendChild(contentArea);
    rootEl.appendChild(card);

    // ── Bottom controls card (separate from main) ──
    var bottomCard = document.createElement('div');
    bottomCard.style.cssText = [
      'flex-shrink:0;',
      'background:' + T.bgDark + ';',
      'border:3px solid ' + _darkenHex(T.numpadChassis, 0.3) + ';',
      'display:flex;flex-direction:column;gap:2px;',
      'padding:3px 4px;box-sizing:border-box;',
    ].join('');
    bottomCard.style.clipPath = chamfer(6);

    // Prefix bar
    if (optionalGroups.length > 0) {
      prefixBarEl = document.createElement('div');
      prefixBarEl.style.cssText = 'display:flex;flex-direction:row;gap:3px;';
      bottomCard.appendChild(prefixBarEl);
    }

    // Placement bar
    placementBarEl = document.createElement('div');
    bottomCard.appendChild(placementBarEl);

    // Action buttons
    var actionBar = document.createElement('div');
    actionBar.style.cssText = 'display:flex;gap:4px;';

    // Cancel/Undo button
    var undoPair = buildStyledButton({ label: '<<<', variant: 'vermillion', size: 'sm' });
    undoPair.inner.style.color = '#ffffff';
    undoPair.wrap.style.flex = '1';

    var _backTimer = null;
    var _backDidHold = false;
    var holdFill = document.createElement('div');
    holdFill.style.cssText = 'position:absolute;left:0;top:0;bottom:0;width:0;background:rgba(255,255,255,0.25);pointer-events:none;z-index:1;transition:none;';
    undoPair.wrap.style.position = 'relative';
    undoPair.wrap.style.overflow = 'hidden';
    undoPair.wrap.appendChild(holdFill);

    undoPair.wrap.addEventListener('pointerdown', function(e) {
      e.stopPropagation();
      _backDidHold = false;
      holdFill.style.transition = 'width 600ms linear';
      holdFill.style.width = '100%';
      _backTimer = setTimeout(function() {
        _backDidHold = true;
        holdFill.style.transition = 'none';
        holdFill.style.width = '0';
        onCancel();
      }, 600);
    });
    undoPair.wrap.addEventListener('pointerup', function(e) {
      e.stopPropagation();
      clearTimeout(_backTimer);
      holdFill.style.transition = 'none';
      holdFill.style.width = '0';
      if (!_backDidHold) {
        if (activeItem.optionalModifiers.length > 0) {
          activeItem.optionalModifiers.pop();
        } else if (activeItem.includedRemovals.length > 0) {
          activeItem.includedRemovals.pop();
        } else if (activeItem.allergens.length > 0) {
          activeItem.allergens.pop();
        } else if (activeItem.allergenNote) {
          activeItem.allergenNote = '';
        } else if (activeItem.note) {
          activeItem.note = '';
        }
        fireUpdate();
        renderAll();
        _refreshNoteBtn();
        _refreshAlrgBtn();
      }
    });
    undoPair.wrap.addEventListener('pointerleave', function() {
      clearTimeout(_backTimer);
      holdFill.style.transition = 'none';
      holdFill.style.width = '0';
    });

    // CONFIRM button
    var confirmPair = buildStyledButton({ label: 'CONFIRM', variant: 'mint', size: 'sm', onClick: function() { handleSend(); } });
    confirmPair.wrap.style.flex = '3';

    actionBar.appendChild(undoPair.wrap);
    actionBar.appendChild(confirmPair.wrap);
    bottomCard.appendChild(actionBar);

    rootEl.appendChild(bottomCard);
    container.appendChild(rootEl);

    _renderTabs();
    renderAll();
  }

  // ═══ REFRESH ACTION BAR INDICATORS ═══
  function _refreshNoteBtn() {
    if (!_notePairRef) return;
    _notePairRef.inner.textContent = activeItem.note ? 'NOTE\u2022' : 'NOTE';
  }
  function _refreshAlrgBtn() {
    if (!_alrgPairRef) return;
    _alrgPairRef.inner.textContent = (activeItem.allergens.length > 0 || activeItem.allergenNote) ? 'ALRG\u2022' : 'ALRG';
  }

  // ═══ RENDER ALL SECTIONS ═══
  function renderAll() {
    renderPlacement();
    renderMandatory();
    renderIncluded();
    renderOptional();
    renderPrefixBar();
  }

  // ═══ PLACEMENT BAR (compact, above action buttons) ═══
  function renderPlacement() {
    placementBarEl.innerHTML = '';
    if (!enablePlacement || (optionalGroups.length === 0 && mandatoryGroups.length === 0)) {
      placementBarEl.style.display = 'none';
      return;
    }
    placementBarEl.style.display = '';

    var placeRow = document.createElement('div');
    placeRow.style.cssText = [
      'display:flex;height:36px;',
      'border:2px solid ' + catColor + ';',
      'background:' + T.bgDark + ';',
    ].join('');

    var placeSegs = {};
    PLACEMENTS.forEach(function(pl, i) {
      if (i > 0) {
        var div = document.createElement('div');
        div.style.cssText = 'width:1px;background:' + T.bgEdge + ';flex-shrink:0;';
        placeRow.appendChild(div);
      }

      var isActive = activePlacement === pl.id;
      var seg = document.createElement('div');
      seg.style.cssText = [
        'flex:' + (pl.id === 'whole' ? '2' : '1') + ';',
        'display:flex;align-items:center;justify-content:center;',
        'font-family:' + T.fb + ';font-size:16px;letter-spacing:1px;text-transform:uppercase;font-weight:bold;',
        'background:' + (isActive ? catColor : 'transparent') + ';',
        'color:' + (isActive ? T.bgDark : T.mutedText) + ';',
        'cursor:pointer;transition:background 80ms,color 80ms;',
      ].join('');
      seg.textContent = pl.label;

      seg.addEventListener('pointerup', function(e) {
        e.stopPropagation();
        activePlacement = pl.id;
        _refreshPlacement(placeSegs);
      });

      placeRow.appendChild(seg);
      placeSegs[pl.id] = seg;
    });

    placementBarEl.appendChild(placeRow);
  }

  function _refreshPlacement(segs) {
    PLACEMENTS.forEach(function(pl) {
      var seg = segs[pl.id];
      if (!seg) return;
      var isActive = activePlacement === pl.id;
      seg.style.background = isActive ? catColor : 'transparent';
      seg.style.color = isActive ? T.bgDark : T.mutedText;
    });
  }

  // ═══ PREFIX BAR (horizontal row) ═══
  function renderPrefixBar() {
    if (!prefixBarEl) return;
    prefixBarEl.innerHTML = '';

    OPT_PREFIXES.forEach(function(pfx) {
      var isActive = activeOptPrefix === pfx.id;
      var btn = document.createElement('div');
      btn.style.cssText = [
        'flex:1 1 0;text-align:center;cursor:pointer;user-select:none;',
        'font-family:' + T.fh + ';font-size:11px;font-weight:bold;letter-spacing:1px;',
        'padding:3px 8px;white-space:nowrap;',
        'border:2px solid ' + T.numpadChassis + ';',
        'background:' + (isActive ? T.numpadChassis : T.bgDark) + ';',
        'color:' + (isActive ? T.bgDark : T.textPrimary) + ';',
        'box-sizing:border-box;',
      ].join('');
      btn.style.clipPath = chamfer(4);
      btn.textContent = pfx.label;

      btn.addEventListener('pointerup', function(e) {
        e.stopPropagation();
        activeOptPrefix = pfx.id;
        renderPrefixBar();
      });

      prefixBarEl.appendChild(btn);
    });
  }

  // ═══ MANDATORY SECTION ═══
  var _mandOverlay = null; // active selection overlay element

  function renderMandatory() {
    if (!mandatoryContentEl) return;
    mandatoryContentEl.innerHTML = '';
    _mandOverlay = null;

    // Tile grid — each mandatory group is a card tile (check-tile style)
    var cols = Math.min(mandatoryGroups.length, 3);
    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(' + cols + ',1fr);gap:8px;align-content:start;';

    mandatoryGroups.forEach(function(group) {
      var currentSel = activeItem.mandatorySelections[group.key];
      var hasSelection = !!currentSel;

      var tile = document.createElement('div');
      tile.style.cssText = [
        'background:' + T.bgDark + ';',
        'padding:10px 8px;',
        'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;',
        'min-height:48px;cursor:pointer;user-select:none;box-sizing:border-box;',
      ].join('');
      applyCardBevel(tile, catColor, 5);
      tile.style.clipPath = chamfer(8);

      // Group label (always visible at top of tile)
      var label = document.createElement('div');
      label.style.cssText = 'font-family:' + T.fh + ';font-size:16px;font-weight:bold;color:' + T.textPrimary + ';text-transform:uppercase;letter-spacing:0.5px;';
      label.textContent = group.label;
      tile.appendChild(label);

      // Selection value (shown below label when selected)
      if (hasSelection) {
        var val = document.createElement('div');
        val.style.cssText = 'font-family:' + T.fh + ';font-size:20px;font-weight:bold;color:' + catColor + ';';
        val.textContent = currentSel.label;
        tile.appendChild(val);
      } else {
        var prompt = document.createElement('div');
        prompt.style.cssText = 'font-family:' + T.fb + ';font-size:12px;color:' + T.mutedText + ';';
        prompt.textContent = 'tap to select';
        tile.appendChild(prompt);
      }

      // Tap tile → show selection overlay
      tile.addEventListener('pointerup', function(e) {
        e.stopPropagation();
        _showMandatoryOverlay(group);
      });

      grid.appendChild(tile);
    });

    mandatoryContentEl.appendChild(grid);
  }

  function _showMandatoryOverlay(group) {
    // Remove any existing overlay
    if (_mandOverlay && _mandOverlay.parentNode) _mandOverlay.parentNode.removeChild(_mandOverlay);

    var currentSel = activeItem.mandatorySelections[group.key];

    _mandOverlay = document.createElement('div');
    _mandOverlay.style.cssText = [
      'position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;',
      'background:' + T.bg + ';',
      'display:flex;flex-direction:column;padding:8px;box-sizing:border-box;',
    ].join('');

    // Overlay header
    var hdr = document.createElement('div');
    hdr.style.cssText = [
      'flex-shrink:0;padding:6px 10px;margin-bottom:8px;text-align:center;',
      'font-family:' + T.fh + ';font-size:16px;font-weight:bold;color:' + catColor + ';',
      'border-bottom:2px solid ' + catColor + ';',
    ].join('');
    hdr.textContent = 'Select ' + group.label;
    _mandOverlay.appendChild(hdr);

    // Option cards grid
    var optCount = (group.options || []).length;
    var optCols = optCount <= 4 ? 2 : 3;
    var optGrid = document.createElement('div');
    optGrid.style.cssText = [
      'flex:1;min-height:0;overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none;',
      'display:grid;grid-template-columns:repeat(' + optCols + ',1fr);gap:8px;align-content:start;padding:4px;',
    ].join('');

    (group.options || []).forEach(function(opt) {
      var isSelected = currentSel && currentSel.key === opt.key;

      var card = document.createElement('div');
      card.style.cssText = [
        'background:' + (isSelected ? catColor : T.bgDark) + ';',
        'border:2px solid ' + (isSelected ? catColor : T.numpadChassis) + ';',
        'padding:10px 8px;',
        'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;',
        'min-height:48px;cursor:pointer;user-select:none;box-sizing:border-box;',
      ].join('');
      card.style.clipPath = chamfer(6);

      var optLabel = document.createElement('div');
      optLabel.style.cssText = [
        'font-family:' + T.fh + ';font-size:16px;font-weight:bold;text-align:center;',
        'color:' + (isSelected ? T.bgDark : T.textPrimary) + ';',
      ].join('');
      optLabel.textContent = opt.label;
      card.appendChild(optLabel);

      card.addEventListener('pointerup', function(e) {
        e.stopPropagation();
        // Dismiss overlay and apply selection
        if (_mandOverlay && _mandOverlay.parentNode) _mandOverlay.parentNode.removeChild(_mandOverlay);
        _mandOverlay = null;
        expandedMandGroup = null;
        onMandatoryChange(group.key, opt);
      });

      optGrid.appendChild(card);
    });

    _mandOverlay.appendChild(optGrid);
    mandatoryContentEl.appendChild(_mandOverlay);
  }

  function onMandatoryChange(groupKey, newSelection) {
    activeItem.mandatorySelections[groupKey] = {
      key: newSelection.key, label: newSelection.label, price: newSelection.price || 0,
    };

    // Reprice optional modifiers against ALL mandatory selections
    activeItem.optionalModifiers = activeItem.optionalModifiers.map(function(mod) {
      // Backend-authored size-based pricing (priceByOption) — track the driver
      if (mod.priceByOption) {
        var driverSel = pricingDriverKey && activeItem.mandatorySelections[pricingDriverKey]
          ? activeItem.mandatorySelections[pricingDriverKey].key
          : null;
        if (driverSel == null) {
          var mKeys = Object.keys(activeItem.mandatorySelections);
          if (mKeys.length > 0) driverSel = activeItem.mandatorySelections[mKeys[0]].key;
        }
        var override = driverSel != null ? mod.priceByOption[driverSel] : undefined;
        var nextPrice = override !== undefined ? override : (mod.basePrice != null ? mod.basePrice : mod.price);
        return Object.assign({}, mod, { price: nextPrice });
      }
      // Legacy priceMap path
      if (mod.priceMap) {
        var resolved;
        var mandKeys = Object.keys(activeItem.mandatorySelections);
        for (var i = 0; i < mandKeys.length; i++) {
          var mk = activeItem.mandatorySelections[mandKeys[i]].key;
          if (mod.priceMap[mk] !== undefined) {
            resolved = mod.priceMap[mk];
            break;
          }
        }
        if (resolved === undefined) resolved = mod.priceMap['default'];
        if (resolved === undefined) resolved = mod.price;
        return Object.assign({}, mod, { price: resolved });
      }
      return mod;
    });

    fireUpdate();
    renderAll();
  }

  // ═══ INCLUDED SECTION ═══
  function renderIncluded() {
    if (!includedContentEl) return;
    includedContentEl.innerHTML = '';

    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:8px;';

    includedItems.slice().sort(function(a, b) { return a.label.localeCompare(b.label); }).forEach(function(incl) {
      var isRemoved = activeItem.includedRemovals.indexOf(incl.id) !== -1;

      var card = document.createElement('div');
      card.style.cssText = [
        'border:2px solid ' + (isRemoved ? T.vermillion : T.numpadChassis) + ';',
        'background:' + (isRemoved ? T.vermillion : T.numpadChassis) + ';',
        'padding:10px 8px;display:flex;align-items:center;justify-content:center;',
        'min-height:48px;cursor:pointer;user-select:none;box-sizing:border-box;',
        'font-family:' + T.fh + ';font-size:14px;font-weight:bold;',
        'color:' + T.bgDark + ';text-align:center;',
      ].join('');
      card.style.clipPath = chamfer(6);
      card.textContent = isRemoved ? 'NO ' + incl.label : incl.label;

      card.addEventListener('pointerup', function() {
        var idx = activeItem.includedRemovals.indexOf(incl.id);
        if (idx !== -1) { activeItem.includedRemovals.splice(idx, 1); }
        else { activeItem.includedRemovals.push(incl.id); }
        fireUpdate();
        renderIncluded();
      });

      grid.appendChild(card);
    });

    includedContentEl.appendChild(grid);
  }

  // ═══ OPTIONAL SECTION ═══
  function renderOptional() {
    if (!optionalContentEl) return;
    optionalContentEl.innerHTML = '';

    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding-bottom:16px;';

    var mandKey = _currentMandatoryKey();

    // Merge all optional groups, tag each with groupKey, sort alphabetically
    var allOpts = [];
    optionalGroups.forEach(function(g) {
      (g.options || []).forEach(function(opt) {
        allOpts.push({ opt: opt, groupKey: g.key });
      });
    });
    allOpts.sort(function(a, b) {
      return a.opt.label.localeCompare(b.opt.label);
    });

    allOpts.forEach(function(entry) {
      var opt = entry.opt;
      var price = _resolvePrice(opt, mandKey);

      // Card-style button matching mandatory theme
      var card = document.createElement('div');
      var borderColor = opt.special ? T.gold : T.numpadChassis;
      card.style.cssText = [
        'border:2px solid ' + borderColor + ';',
        'background:' + T.bgDark + ';',
        'padding:10px 4px;display:flex;align-items:center;justify-content:center;',
        'min-height:48px;cursor:pointer;user-select:none;box-sizing:border-box;',
        'font-family:' + T.fh + ';font-size:13px;font-weight:bold;',
        'color:' + T.textPrimary + ';text-align:center;',
      ].join('');
      card.style.clipPath = chamfer(6);
      card.textContent = opt.label;

      // Special: short tap = add, long press = customize popout
      if (opt.special && opt.includes) {
        var _holdTimer = null;
        var _didHold = false;
        card.addEventListener('pointerdown', function(e) {
          _didHold = false;
          _holdTimer = setTimeout(function() {
            _didHold = true;
            var existing = _findSpecialMod(opt.id);
            if (!existing) {
              applyOptionalMod(entry.groupKey, opt, mandKey);
              existing = _findSpecialMod(opt.id);
            }
            if (existing) showSpecialPopout(existing, opt);
          }, 400);
        });
        card.addEventListener('pointerup', function() {
          clearTimeout(_holdTimer);
          if (!_didHold) applyOptionalMod(entry.groupKey, opt, mandKey);
        });
        card.addEventListener('pointerleave', function() {
          clearTimeout(_holdTimer);
        });
      } else {
        card.addEventListener('pointerup', function() {
          applyOptionalMod(entry.groupKey, opt, mandKey);
        });
      }

      grid.appendChild(card);
    });

    optionalContentEl.appendChild(grid);
  }

  function applyOptionalMod(groupKey, opt, mandKey) {
    var price = _resolvePrice(opt, mandKey);
    var modId = opt.id || opt.label.toLowerCase().replace(/\s+/g, '-');

    var _restorePrefix = false;
    if (activeOptPrefix === 'ADD') {
      var hasAdd = false;
      var hasExtra = false;
      for (var i = 0; i < activeItem.optionalModifiers.length; i++) {
        var em = activeItem.optionalModifiers[i];
        if (em.modifierId === modId && em.placement === activePlacement) {
          if (em.prefix === 'ADD') hasAdd = true;
          if (em.prefix === 'EXTRA') hasExtra = true;
        }
      }
      // If item is included (not removed), treat as already added → jump to EXTRA
      var isIncluded = includedItems.some(function(inc) {
        return inc.label.toLowerCase() === opt.label.toLowerCase() &&
          activeItem.includedRemovals.indexOf(inc.id) === -1;
      });
      if (isIncluded && !hasExtra) {
        activeOptPrefix = 'EXTRA';
        _restorePrefix = true;
      } else if (hasAdd && !hasExtra) {
        activeOptPrefix = 'EXTRA';
        _restorePrefix = true;
      }
      if (hasAdd && hasExtra) {
        return;
      }
    }

    var mod = {
      prefix: activeOptPrefix,
      modifierId: modId,
      label: opt.label,
      price: price,
      basePrice: opt.price || 0,
      priceMap: opt.priceMap || null,
      priceByOption: opt.priceByOption || null,
      groupKey: groupKey,
      placement: activePlacement || 'whole',
    };
    if (opt.special && opt.includes) {
      mod.special = true;
      mod.includes = opt.includes.slice();
      mod.exclusions = [];
    }
    activeItem.optionalModifiers.push(mod);
    if (_restorePrefix) activeOptPrefix = 'ADD';
    fireUpdate();
    renderOptional();
    renderPrefixBar();
  }

  function _findSpecialMod(modId) {
    for (var i = activeItem.optionalModifiers.length - 1; i >= 0; i--) {
      if (activeItem.optionalModifiers[i].modifierId === modId && activeItem.optionalModifiers[i].special) {
        return activeItem.optionalModifiers[i];
      }
    }
    return null;
  }

  // ═══ SPECIAL POPOUT (long-press customization) ═══
  function showSpecialPopout(mod, opt) {
    SceneManager.interrupt('special-customize', {
      onConfirm: function() {
        fireUpdate();
        renderOptional();
      },
      onCancel: function() {
        fireUpdate();
        renderOptional();
      },
      params: { mod: mod, fireUpdate: fireUpdate },
    });
  }

  // ═══ SEND ═══
  function handleSend() {
    var unsatisfied = mandatoryGroups.filter(function(g) {
      return !activeItem.mandatorySelections[g.key];
    });
    if (unsatisfied.length > 0) {
      // Re-render mandatory to show red borders on unselected groups
      renderMandatory();
      return;
    }
    onSend(activeItem);
  }

  // ═══ HELPERS ═══

  function _currentMandatoryKey() {
    // Prefer the pricing-driver group when set, so optional prices track size.
    if (pricingDriverKey && activeItem.mandatorySelections[pricingDriverKey]) {
      return activeItem.mandatorySelections[pricingDriverKey].key;
    }
    var keys = Object.keys(activeItem.mandatorySelections);
    if (keys.length > 0) return activeItem.mandatorySelections[keys[0]].key;
    return 'default';
  }

  function _resolvePrice(opt, mandKey) {
    // Backend-authored size-based pricing wins over the legacy priceMap path.
    if (opt.priceByOption && mandKey && opt.priceByOption[mandKey] !== undefined) {
      return opt.priceByOption[mandKey];
    }
    if (opt.priceMap) {
      var p = opt.priceMap[mandKey];
      if (p !== undefined) return p;
      p = opt.priceMap['default'];
      if (p !== undefined) return p;
    }
    return opt.price || 0;
  }

  function fireUpdate() {
    onUpdate(buildOutputItem());
  }

  function buildOutputItem() {
    var mands = activeItem.mandatorySelections;

    var mandPrice = 0;
    Object.keys(mands).forEach(function(k) { mandPrice += mands[k].price || 0; });

    // Modifier lines: MANDATORY → INCLUDED → OPTIONAL
    var mods = [];

    // Mandatory selections
    mandatoryGroups.forEach(function(g) {
      if (mands[g.key]) {
        mods.push({
          name: mands[g.key].label,
          price: mands[g.key].price || 0,
          charged: (mands[g.key].price || 0) > 0,
          prefix: null,
        });
      }
    });

    // Included removals (removable)
    activeItem.includedRemovals.forEach(function(rid, idx) {
      var incl = includedItems.find(function(i) { return i.id === rid; });
      if (incl) mods.push({ name: 'NO ' + incl.label, price: 0, charged: false, prefix: null, _source: 'included', _idx: idx });
    });

    // Optional modifiers (removable)
    activeItem.optionalModifiers.forEach(function(m, idx) {
      var halfSide = m.placement === '1st' ? 'Left' : m.placement === '2nd' ? 'Right' : null;
      var parentMod = {
        name: m.prefix + ' ' + m.label,
        price: m.prefix === 'NO' ? 0 : m.price,
        charged: m.prefix !== 'NO' && m.price > 0,
        prefix: halfSide,
        children: [],
        _source: 'optional',
        _idx: idx,
      };
      if (m.special && m.exclusions && m.exclusions.length > 0) {
        m.exclusions.forEach(function(ex) {
          parentMod.children.push({ name: 'NO ' + ex, price: 0, charged: false });
        });
      }
      mods.push(parentMod);
    });

    activeItem.allergens.forEach(function(aId, idx) {
      var a = ALLERGENS.find(function(x) { return x.id === aId; });
      if (a) mods.push({ name: '\u26A0 ALLERGEN: ' + a.label, price: 0, charged: false, prefix: null, _source: 'allergen', _idx: idx });
    });
    if (activeItem.allergenNote) {
      mods.push({ name: '\u26A0 ALLERGEN: ' + activeItem.allergenNote, price: 0, charged: false, prefix: null, _source: 'allergenNote' });
    }
    if (activeItem.note) {
      mods.push({ name: '\uD83D\uDCDD ' + activeItem.note, price: 0, charged: false, prefix: null, _source: 'note' });
    }

    return {
      itemLabel: activeItem.itemLabel,
      basePrice: activeItem.basePrice,
      mods: mods,
      activeItem: activeItem,
    };
  }

  // ═══ PUBLIC API ═══
  self.removeMod = function(source, idx) {
    if (source === 'included') {
      activeItem.includedRemovals.splice(idx, 1);
    } else if (source === 'optional') {
      activeItem.optionalModifiers.splice(idx, 1);
    } else if (source === 'allergen') {
      activeItem.allergens.splice(idx, 1);
    } else if (source === 'allergenNote') {
      activeItem.allergenNote = '';
    } else if (source === 'note') {
      activeItem.note = '';
    }
    fireUpdate();
    renderAll();
    _refreshNoteBtn();
    _refreshAlrgBtn();
  };

  self.destroy = function() {
    if (rootEl && rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
    rootEl = null;
  };

  self.getActiveItem = function() { return activeItem; };
  self.getOutputItem = function() { return buildOutputItem(); };

  build();
  fireUpdate();
}

// ═══════════════════════════════════════════════════
//  SPECIAL CUSTOMIZE — Interrupt Scene (SM2)
//  Long-press a special to toggle its included toppings
// ═══════════════════════════════════════════════════

function _lightenH(hex, pct) {
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  return '#' + [
    Math.min(255, Math.round(r + (255 - r) * pct)),
    Math.min(255, Math.round(g + (255 - g) * pct)),
    Math.min(255, Math.round(b + (255 - b) * pct)),
  ].map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}
function _darkenH(hex, pct) {
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  var f = 1 - pct;
  return '#' + [Math.round(r * f), Math.round(g * f), Math.round(b * f)]
    .map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}

defineScene({
  name: 'special-customize',
  render: function(container, params) {
    var mod = params.mod;
    var fireUpdate = params.fireUpdate;
    var onConfirm = params.onConfirm;
    var onCancel = params.onCancel;
    var savedExclusions = mod.exclusions.slice();

    var panel = document.createElement('div');
    panel.style.cssText = [
      'width:90%;max-width:600px;',
      'background:' + T.bg + ';',
      'border-top:7px solid ' + _lightenH(T.gold, 0.2) + ';',
      'border-left:7px solid ' + _lightenH(T.gold, 0.2) + ';',
      'border-bottom:7px solid ' + _darkenH(T.gold, 0.3) + ';',
      'border-right:7px solid ' + _darkenH(T.gold, 0.3) + ';',
      'display:flex;flex-direction:column;overflow:hidden;',
      'max-height:90%;',
    ].join('');
    panel.style.clipPath = chamfer(10);

    var header = document.createElement('div');
    header.style.cssText = [
      'background:' + T.gold + ';padding:12px 16px;flex-shrink:0;',
      'font-family:' + T.fh + ';font-size:22px;color:' + T.bgDark + ';',
    ].join('');
    header.textContent = mod.label;
    panel.appendChild(header);

    var gridWrap = document.createElement('div');
    gridWrap.style.cssText = [
      'flex:1;overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none;',
      'padding:8px;',
    ].join('');

    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:6px;';

    function renderGrid() {
      grid.innerHTML = '';
      (mod.includes || []).forEach(function(incLabel) {
        var isExcluded = mod.exclusions.indexOf(incLabel) !== -1;
        var variant = isExcluded ? 'vermillion' : 'dark';
        var label = isExcluded ? 'NO ' + incLabel : incLabel;
        var pair = buildStyledButton({ label: label, variant: variant, size: 'md' });
        pair.wrap.style.width = '100%';
        pair.wrap.style.minWidth = '0';
        pair.inner.style.fontSize = '18px';
        pair.inner.style.fontFamily = T.fb;

        pair.wrap.addEventListener('pointerup', function() {
          var idx = mod.exclusions.indexOf(incLabel);
          if (idx !== -1) { mod.exclusions.splice(idx, 1); }
          else { mod.exclusions.push(incLabel); }
          if (fireUpdate) fireUpdate();
          renderGrid();
        });

        grid.appendChild(pair.wrap);
      });
    }
    renderGrid();
    gridWrap.appendChild(grid);
    panel.appendChild(gridWrap);

    var actionBar = document.createElement('div');
    actionBar.style.cssText = [
      'flex-shrink:0;padding:8px;',
      'border-top:3px solid ' + _darkenH(T.gold, 0.3) + ';',
      'background:' + T.bgDark + ';',
      'display:flex;gap:8px;',
    ].join('');
    var cancelPair = buildStyledButton({ label: 'CANCEL', variant: 'vermillion', size: 'md',
      onClick: function() {
        mod.exclusions.length = 0;
        for (var i = 0; i < savedExclusions.length; i++) {
          mod.exclusions.push(savedExclusions[i]);
        }
        onCancel();
      },
    });
    cancelPair.wrap.style.flex = '1';
    actionBar.appendChild(cancelPair.wrap);
    var donePair = buildStyledButton({ label: 'DONE', variant: 'mint', size: 'md',
      onClick: function() { onConfirm(); },
    });
    donePair.wrap.style.flex = '1';
    actionBar.appendChild(donePair.wrap);
    panel.appendChild(actionBar);

    container.appendChild(panel);
  },
});

// ═══════════════════════════════════════════════════
//  ALLERGEN SELECT — Interrupt Scene (SM2)
//  Opened from ALRG button in modifier panel action bar
// ═══════════════════════════════════════════════════

defineScene({
  name: 'allergen-select',
  render: function(container, params) {
    var activeItem = params.activeItem;
    var fireUpdate = params.fireUpdate;
    var onConfirm = params.onConfirm;
    var onCancel = params.onCancel;
    var savedAllergens = activeItem.allergens.slice();
    var savedNote = activeItem.allergenNote;

    var panel = document.createElement('div');
    panel.style.cssText = [
      'width:90%;max-width:600px;',
      'background:' + T.bg + ';',
      'border-top:7px solid ' + _lightenH(T.vermillion, 0.2) + ';',
      'border-left:7px solid ' + _lightenH(T.vermillion, 0.2) + ';',
      'border-bottom:7px solid ' + _darkenH(T.vermillion, 0.3) + ';',
      'border-right:7px solid ' + _darkenH(T.vermillion, 0.3) + ';',
      'display:flex;flex-direction:column;overflow:hidden;',
      'max-height:90%;',
    ].join('');
    panel.style.clipPath = chamfer(10);

    var header = document.createElement('div');
    header.style.cssText = [
      'background:' + T.vermillion + ';padding:12px 16px;flex-shrink:0;',
      'font-family:' + T.fh + ';font-size:22px;color:#ffffff;',
    ].join('');
    header.textContent = 'Allergens';
    panel.appendChild(header);

    var gridWrap = document.createElement('div');
    gridWrap.style.cssText = [
      'flex:1;overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none;',
      'padding:8px;',
    ].join('');

    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:6px;';

    var noteDisplay = document.createElement('div');
    noteDisplay.style.cssText = [
      'margin-top:6px;padding:6px 10px;display:none;',
      'font-family:' + T.fb + ';font-size:14px;',
      'background:' + T.bgDark + ';color:' + T.textPrimary + ';',
      'border:2px solid ' + T.red + ';',
    ].join('');
    noteDisplay.style.clipPath = chamfer(6);

    function renderAllergenGrid() {
      grid.innerHTML = '';
      ALLERGENS.slice().sort(function(a, b) { return a.label.localeCompare(b.label); }).forEach(function(a) {
        if (a.id === 'other') {
          var isActive = activeItem.allergenNote.length > 0;
          var pair = buildStyledButton({ label: a.label, variant: 'dark', size: 'md' });
          pair.wrap.style.width = '100%';
          pair.wrap.style.minWidth = '0';
          pair.inner.style.fontSize = '20px';
          pair.wrap.style.background = a.color;
          pair.inner.style.color = a.light ? '#ffffff' : T.bgDark;
          if (isActive) {
            pair.wrap.style.outline = '3px solid ' + T.numpadChassis;
            pair.wrap.style.outlineOffset = '-3px';
          }
          pair.wrap.addEventListener('pointerup', function() {
            showKeyboard({
              placeholder: 'Describe allergen...',
              initialValue: activeItem.allergenNote,
              maxLength: 60,
              onDone: function(val) {
                activeItem.allergenNote = val || '';
                if (fireUpdate) fireUpdate();
                renderAllergenGrid();
              },
              onDismiss: function() {},
              dismissOnDone: true,
            });
          });
          grid.appendChild(pair.wrap);
          return;
        }

        var selected = activeItem.allergens.indexOf(a.id) !== -1;
        var pair = buildStyledButton({ label: a.label, variant: 'dark', size: 'md' });
        pair.wrap.style.width = '100%';
        pair.wrap.style.minWidth = '0';
        pair.inner.style.fontSize = '20px';
        pair.wrap.style.background = a.color;
        pair.inner.style.color = a.light ? '#ffffff' : T.bgDark;
        if (selected) {
          pair.wrap.style.outline = '3px solid ' + T.numpadChassis;
          pair.wrap.style.outlineOffset = '-3px';
        }

        pair.wrap.addEventListener('pointerup', function() {
          var idx = activeItem.allergens.indexOf(a.id);
          if (idx !== -1) { activeItem.allergens.splice(idx, 1); }
          else { activeItem.allergens.push(a.id); }
          if (fireUpdate) fireUpdate();
          renderAllergenGrid();
        });

        grid.appendChild(pair.wrap);
      });

      // Allergen note display
      if (activeItem.allergenNote) {
        noteDisplay.textContent = '\u26A0 ' + activeItem.allergenNote;
        noteDisplay.style.display = '';
      } else {
        noteDisplay.style.display = 'none';
      }
    }

    renderAllergenGrid();
    gridWrap.appendChild(grid);
    gridWrap.appendChild(noteDisplay);
    panel.appendChild(gridWrap);

    var actionBar = document.createElement('div');
    actionBar.style.cssText = [
      'flex-shrink:0;padding:8px;',
      'border-top:3px solid ' + _darkenH(T.vermillion, 0.3) + ';',
      'background:' + T.bgDark + ';',
      'display:flex;gap:8px;',
    ].join('');
    var cancelPair = buildStyledButton({ label: 'CANCEL', variant: 'vermillion', size: 'md',
      onClick: function() {
        activeItem.allergens.length = 0;
        for (var i = 0; i < savedAllergens.length; i++) {
          activeItem.allergens.push(savedAllergens[i]);
        }
        activeItem.allergenNote = savedNote;
        onCancel();
      },
    });
    cancelPair.wrap.style.flex = '1';
    actionBar.appendChild(cancelPair.wrap);
    var donePair = buildStyledButton({ label: 'DONE', variant: 'mint', size: 'md',
      onClick: function() { onConfirm(); },
    });
    donePair.wrap.style.flex = '1';
    actionBar.appendChild(donePair.wrap);
    panel.appendChild(actionBar);

    container.appendChild(panel);
  },
});