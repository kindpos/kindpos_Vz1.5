// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Theme Manager  (Vz2.0)
//  Visual construction — cards, buttons, numpad, pins
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════
//
//  tokens.js owns the raw values.
//  theme-manager.js owns the construction.
//
//  Usage:
//    import { buildCard, buildPillButton, buildNumKey,
//             buildPinBox, buildFloatButton,
//             lightenHex, darkenHex, hexToRgba } from './theme-manager.js';
//
//  Rules:
//   1. Always call builders — never write inline styles in scenes.
//   2. Always pass colors from T — never hardcode hex in scenes.
//   3. buildCard() returns { wrap, card } — append wrap to DOM.
// ═══════════════════════════════════════════════════

import { T, chamfer } from './tokens.js';

// ═══════════════════════════════════════════════════
//  COLOR UTILITIES
// ═══════════════════════════════════════════════════

export function lightenHex(hex, pct) {
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  return '#' + [
    Math.min(255, Math.round(r + (255 - r) * pct)),
    Math.min(255, Math.round(g + (255 - g) * pct)),
    Math.min(255, Math.round(b + (255 - b) * pct)),
  ].map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}

export function darkenHex(hex, pct) {
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  var f = 1 - pct;
  return '#' + [Math.round(r * f), Math.round(g * f), Math.round(b * f)]
    .map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}

export function hexToRgba(hex, alpha) {
  var r = parseInt(hex.slice(1, 3), 16);
  var g = parseInt(hex.slice(3, 5), 16);
  var b = parseInt(hex.slice(5, 7), 16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}

// ═══════════════════════════════════════════════════
//  CARD BUILDER
//  Left accent bar + chamfer clip-path.
//  Returns { wrap, card }
//   wrap — outer div, overflow:visible (float buttons clear the edge)
//   card — inner div, clipped + styled
//
//  opts:
//    accent      — border-left color (default: T.green)
//    bg          — background (default: T.card)
//    padding     — inner padding (default: '14px 16px')
//    width / height / flex
//    chamferSize — clip-path px (default: T.chamferCard)
//    cssText     — extra styles for inner card
// ═══════════════════════════════════════════════════

export function buildCard(opts) {
  var o      = opts || {};
  var accent = o.accent  || T.green;
  var bg     = o.bg      || T.card;
  var pad    = o.padding || '14px 16px';
  var cham   = o.chamferSize != null ? o.chamferSize : T.chamferCard;

  var wrap = document.createElement('div');
  wrap.style.position      = 'relative';
  wrap.style.overflow      = 'visible';
  wrap.style.display       = 'flex';
  wrap.style.flexDirection = 'column';
  if (o.flex)   wrap.style.flex   = o.flex;
  if (o.width)  wrap.style.width  = o.width;
  if (o.height) wrap.style.height = o.height;

  var card = document.createElement('div');
  card.style.flex       = '1';
  card.style.background = bg;
  card.style.clipPath   = cham > 0 ? chamfer(cham) : 'none';
  card.style.borderLeft = T.accentBarW + ' solid ' + accent;
  card.style.padding    = pad;
  card.style.boxSizing  = 'border-box';
  card.style.overflow   = 'hidden';
  card.style.boxShadow  = '0 4px 16px rgba(0,0,0,0.28)';
  if (o.cssText) card.style.cssText += o.cssText;

  wrap.appendChild(card);
  return { wrap: wrap, card: card };
}

// ═══════════════════════════════════════════════════
//  WELL BUILDER
//  Inset panel — numpad chassis, data panels, PIN field
// ═══════════════════════════════════════════════════

export function buildWell(opts) {
  var o      = opts || {};
  var accent = o.accent || null;

  var el = document.createElement('div');
  el.style.background = o.bg || T.well;
  el.style.clipPath   = chamfer(o.chamferSize != null ? o.chamferSize : T.chamferWell);
  el.style.padding    = o.padding || '20px';
  el.style.boxSizing  = 'border-box';
  if (accent) el.style.borderLeft = T.accentBarW + ' solid ' + hexToRgba(accent, 0.4);
  if (o.width)  el.style.width  = o.width;
  if (o.height) el.style.height = o.height;
  return el;
}

// ═══════════════════════════════════════════════════
//  PILL BUTTON BUILDER
//  All interactive action buttons.
//
//  opts:
//    label, color, darkBg, onClick, disabled, fontSize, width
// ═══════════════════════════════════════════════════

export function buildPillButton(opts) {
  var o      = opts || {};
  var color  = o.color  || T.green;
  var darkBg = o.darkBg || T.greenDk;

  var btn = document.createElement('button');
  btn.style.background    = color;
  btn.style.border        = 'none';
  btn.style.borderRadius  = T.pillRadius;
  btn.style.cursor        = 'pointer';
  btn.style.padding       = '14px 32px';
  btn.style.fontFamily    = T.fh;
  btn.style.fontSize      = o.fontSize || T.fsB2;
  btn.style.fontWeight    = T.fwBold;
  btn.style.color         = (color === T.verm) ? '#fff' : T.well;
  btn.style.letterSpacing = '0.08em';
  btn.style.textTransform = 'uppercase';
  btn.style.boxShadow     = '0 6px 0 ' + darkBg;
  btn.style.transition    = T.transitionFast;
  btn.style.outline       = 'none';
  btn.style.whiteSpace    = 'nowrap';
  btn.style.userSelect    = 'none';
  btn.style.pointerEvents = 'auto';
  btn.style.touchAction   = 'manipulation';
  if (o.width) btn.style.width = o.width;
  if (o.label) btn.textContent = o.label;

  btn.addEventListener('pointerdown', function() {
    if (btn._disabled) return;
    btn.style.background = darkBg;
    btn.style.color      = color;
    btn.style.boxShadow  = 'none';
    btn.style.transform  = 'translateY(1px)';
  });
  var _rel = function() {
    if (btn._disabled) return;
    btn.style.background = color;
    btn.style.color      = (color === T.verm) ? '#fff' : T.well;
    btn.style.boxShadow  = '0 6px 0 ' + darkBg;
    btn.style.transform  = '';
  };
  btn.addEventListener('pointerup',    _rel);
  btn.addEventListener('pointerleave', _rel);
  if (o.onClick) btn.addEventListener('pointerup', o.onClick);

  btn._disabled = false;
  btn.setDisabled = function(d) {
    btn._disabled       = d;
    btn.style.opacity   = d ? '0.4'  : '1';
    btn.style.pointerEvents = d ? 'none' : '';
    btn.style.cursor    = d ? 'not-allowed' : 'pointer';
  };
  if (o.disabled) btn.setDisabled(true);

  return btn;
}

// ═══════════════════════════════════════════════════
//  FLOAT BUTTON BUILDER
//  Straddles card border (OPEN/CLOSED toggle, CHECKOUT).
//  Caller positions it absolute on the outer wrap.
// ═══════════════════════════════════════════════════

export function buildFloatButton(opts) {
  var o      = opts || {};
  var color  = o.color  || T.green;
  var darkBg = o.darkBg || T.greenDk;

  var btn = document.createElement('button');
  btn.style.background    = color;
  btn.style.border        = 'none';
  btn.style.borderRadius  = T.pillRadius;
  btn.style.cursor        = 'pointer';
  btn.style.padding       = '14px 40px';
  btn.style.fontFamily    = T.fh;
  btn.style.fontSize      = T.fsB2;
  btn.style.fontWeight    = T.fwBold;
  btn.style.color         = (color === T.verm) ? '#fff' : T.well;
  btn.style.letterSpacing = '0.12em';
  btn.style.textTransform = 'uppercase';
  btn.style.boxShadow     = '0 6px 0 ' + darkBg + ', 0 0 14px ' + hexToRgba(color, 0.3);
  btn.style.transition    = T.transitionFast;
  btn.style.outline       = 'none';
  btn.style.position      = 'relative';
  btn.style.zIndex        = '10';
  btn.style.userSelect    = 'none';
  btn.style.pointerEvents = 'auto';
  btn.style.touchAction   = 'manipulation';
  if (o.label) btn.textContent = o.label;

  btn.addEventListener('pointerdown', function() {
    btn.style.background = darkBg;
    btn.style.color      = color;
    btn.style.boxShadow  = 'none';
    btn.style.transform  = 'translateY(1px)';
  });
  var _rel = function() {
    btn.style.background = color;
    btn.style.color      = T.well;
    btn.style.boxShadow  = '0 6px 0 ' + darkBg + ', 0 0 14px ' + hexToRgba(color, 0.3);
    btn.style.transform  = '';
  };
  btn.addEventListener('pointerup',    _rel);
  btn.addEventListener('pointerleave', _rel);
  if (o.onClick) btn.addEventListener('pointerup', o.onClick);

  // Color swap — for cycling OPEN → CLOSED → VOID
  btn.setColor = function(newColor, newDark) {
    color  = newColor;
    darkBg = newDark;
    btn.style.background = color;
    btn.style.boxShadow  = '0 6px 0 ' + darkBg + ', 0 0 14px ' + hexToRgba(color, 0.3);
  };

  return btn;
}

// ═══════════════════════════════════════════════════
//  NUMPAD KEY BUILDER
//  Chamfer + filled color + dark text.
//  The original KINDpos numpad identity — preserved.
//
//  opts:
//    label, type ('digit'|'clr'|'ent'), onClick, height, width
// ═══════════════════════════════════════════════════

export function buildNumKey(opts) {
  var o    = typeof opts === 'string' ? { label: opts } : (opts || {});
  var type = o.type || 'digit';

  // Text color per key type — dark background, colored label
  var textColors = {
    digit: T.green,
    clr:   T.verm,
    ent:   T.greenWarm,
  };
  var textColor = o.color || textColors[type] || T.green;

  // Embossed shadow — raised 3D lift, same treatment as original
  var shadowRaised = [
    'inset 0 3px 0 rgba(255,255,255,0.10)',
    'inset 0 -3px 0 rgba(0,0,0,0.55)',
    'inset 0 6px 12px rgba(0,0,0,0.35)',
    '0 4px 10px rgba(0,0,0,0.5)',
    '0 0 0 1px rgba(0,0,0,0.3)',
  ].join(',');

  var shadowPressed = [
    'inset 0 2px 0 rgba(255,255,255,0.06)',
    'inset 0 -2px 0 rgba(0,0,0,0.55)',
    'inset 0 10px 20px rgba(0,0,0,0.50)',
    '0 1px 4px rgba(0,0,0,0.4)',
    '0 0 0 1px rgba(0,0,0,0.3)',
  ].join(',');

  var btn = document.createElement('button');
  btn.style.background    = T.well;       // dark key face
  btn.style.border        = 'none';
  btn.style.clipPath      = chamfer(T.chamferKey);
  btn.style.cursor        = 'pointer';
  btn.style.height        = o.height || '112px';
  btn.style.width         = o.width  || '100%';
  btn.style.fontFamily    = T.fh;
  btn.style.fontSize      = type === 'digit' ? '44px' : '26px';
  btn.style.fontWeight    = T.fwBold;
  btn.style.color         = textColor;    // colored label
  btn.style.letterSpacing = type === 'digit' ? '0.02em' : '0.08em';
  btn.style.textShadow    = '0 0 12px ' + textColor;
  btn.style.boxShadow     = shadowRaised;
  btn.style.transition    = T.transitionFast;
  btn.style.outline       = 'none';
  btn.style.userSelect    = 'none';
  btn.style.boxSizing     = 'border-box';
  if (o.label) btn.textContent = o.label;

  btn.addEventListener('pointerdown', function() {
    btn.style.boxShadow = shadowPressed;
    btn.style.transform = 'translateY(3px)';
  });
  var _rel = function() {
    btn.style.boxShadow = shadowRaised;
    btn.style.transform = '';
  };
  btn.addEventListener('pointerup',    _rel);
  btn.addEventListener('pointerleave', _rel);
  if (o.onClick) btn.addEventListener('pointerup', o.onClick);

  return btn;
}

// ═══════════════════════════════════════════════════
//  NUMPAD CHASSIS BUILDER
//  Full numpad: well container + 4×3 key grid.
//  opts.onKey(label) called on each keypress.
//  Returns the chassis element.
// ═══════════════════════════════════════════════════

export function buildNumpadChassis(opts) {
  var o     = opts || {};
  var onKey = o.onKey || function() {};

  var chassis = buildWell({ padding: '10px' });
  chassis.style.display       = 'flex';
  chassis.style.flexDirection = 'column';
  chassis.style.gap           = '12px';

  var rows = [
    [{ label: '1', type: 'digit' }, { label: '2', type: 'digit' }, { label: '3', type: 'digit' }],
    [{ label: '4', type: 'digit' }, { label: '5', type: 'digit' }, { label: '6', type: 'digit' }],
    [{ label: '7', type: 'digit' }, { label: '8', type: 'digit' }, { label: '9', type: 'digit' }],
    [{ label: 'CLR', type: 'clr' }, { label: '0',   type: 'digit' }, { label: 'ENT', type: 'ent' }],
  ];

  rows.forEach(function(row) {
    var rowEl = document.createElement('div');
    rowEl.style.display             = 'grid';
    rowEl.style.gridTemplateColumns = 'repeat(3, 1fr)';
    rowEl.style.gap                 = '12px';
    row.forEach(function(k) {
      rowEl.appendChild(buildNumKey({
        label: k.label, type: k.type,
        onClick: (function(lbl) { return function() { onKey(lbl); }; })(k.label),
      }));
    });
    chassis.appendChild(rowEl);
  });

  return chassis;
}

// ═══════════════════════════════════════════════════
//  PIN BOX BUILDER
//  Returns { box, setFilled(bool) }
// ═══════════════════════════════════════════════════

export function buildPinBox() {
  var box = document.createElement('div');
  box.style.width          = '88px';
  box.style.height         = '88px';
  box.style.clipPath       = chamfer(T.chamferPin);
  box.style.background     = T.well;
  box.style.border         = '1.5px solid ' + T.border;
  box.style.display        = 'flex';
  box.style.alignItems     = 'center';
  box.style.justifyContent = 'center';
  box.style.boxSizing      = 'border-box';
  box.style.transition     = T.transitionMed;
  box.style.flexShrink     = '0';

  var pip = document.createElement('div');
  pip.style.width      = '20px';
  pip.style.height     = '20px';
  pip.style.clipPath   = chamfer(2);
  pip.style.background = T.green;
  pip.style.boxShadow  = '0 0 8px ' + T.green;
  pip.style.display    = 'none';
  box.appendChild(pip);

  box.setFilled = function(filled) {
    if (filled) {
      box.style.background = hexToRgba(T.green, 0.12);
      box.style.border     = '1.5px solid ' + T.green;
      box.style.boxShadow  = '0 0 12px ' + hexToRgba(T.green, 0.35);
      pip.style.display    = 'block';
    } else {
      box.style.background = T.well;
      box.style.border     = '1.5px solid ' + T.border;
      box.style.boxShadow  = 'none';
      pip.style.display    = 'none';
    }
  };

  return { box: box, pip: pip };
}

// ═══════════════════════════════════════════════════
//  PIN ROW BUILDER
//  4 boxes in a row. Returns { row, setCount(n) }
// ═══════════════════════════════════════════════════

export function buildPinRow() {
  var row = document.createElement('div');
  row.style.display        = 'flex';
  row.style.gap            = '20px';
  row.style.justifyContent = 'center';

  var boxes = [buildPinBox(), buildPinBox(), buildPinBox(), buildPinBox()];
  boxes.forEach(function(b) { row.appendChild(b.box); });

  return {
    row: row,
    boxes: boxes,
    setCount: function(n) {
      boxes.forEach(function(b, i) { b.setFilled(i < n); });
    },
  };
}

// ═══════════════════════════════════════════════════
//  SECTION LABEL BUILDER
//  Small spaced uppercase label
// ═══════════════════════════════════════════════════

export function buildSectionLabel(text, accent) {
  var el = document.createElement('div');
  el.textContent         = text;
  el.style.fontFamily    = T.fb;
  el.style.fontSize      = T.fsB3;
  el.style.fontWeight    = T.fwMed;
  el.style.color         = accent || T.green;
  el.style.letterSpacing = '0.2em';
  el.style.textTransform = 'uppercase';
  return el;
}

// ═══════════════════════════════════════════════════
//  HERO NUMBER BUILDER
//  Large display number — use T.gold for money always
// ═══════════════════════════════════════════════════

export function buildHeroNumber(value, color) {
  var el = document.createElement('div');
  el.textContent         = value;
  el.style.fontFamily    = T.fh;
  el.style.fontSize      = T.fsHero;
  el.style.fontWeight    = T.fwBold;
  el.style.color         = color || T.gold;
  el.style.letterSpacing = '0.04em';
  el.style.lineHeight    = '1';
  el.style.textShadow    = '0 0 16px ' + hexToRgba(color || T.gold, 0.35);
  return el;
}

// ═══════════════════════════════════════════════════
//  DATA ROW BUILDER
//  Label + value pair. Returns row element with
//  setValue(v) and setColor(c) helpers.
// ═══════════════════════════════════════════════════

export function buildDataRow(labelText, valueText, valueColor) {
  var row = document.createElement('div');
  row.style.display        = 'flex';
  row.style.justifyContent = 'space-between';
  row.style.alignItems     = 'baseline';
  row.style.padding        = '4px 0';
  row.style.borderBottom   = '1px solid rgba(90,95,102,0.3)';

  var lbl = document.createElement('span');
  lbl.textContent         = labelText;
  lbl.style.fontFamily    = T.fb;
  lbl.style.fontSize      = T.fsB3;
  lbl.style.color         = T.text;
  lbl.style.letterSpacing = '0.1em';
  lbl.style.textTransform = 'uppercase';

  var val = document.createElement('span');
  val.textContent      = valueText;
  val.style.fontFamily = T.fb;
  val.style.fontSize   = T.fsB1;
  val.style.fontWeight = T.fwMed;
  val.style.color      = valueColor || T.text;
  if (valueColor) val.style.textShadow = '0 0 8px ' + hexToRgba(valueColor, 0.35);

  row.appendChild(lbl);
  row.appendChild(val);
  row.setValue = function(v) { val.textContent = v; };
  row.setColor = function(c) {
    val.style.color      = c;
    val.style.textShadow = '0 0 8px ' + hexToRgba(c, 0.35);
  };
  return row;
}

// ═══════════════════════════════════════════════════
//  DIVIDER BUILDER
// ═══════════════════════════════════════════════════

export function buildDivider(margin) {
  var el = document.createElement('div');
  el.style.height     = '1px';
  el.style.background = T.border;
  el.style.opacity    = '0.5';
  el.style.margin     = margin || '16px 0';
  return el;
}