// ═══════════════════════════════════════════════════
//  KINDpos Terminal — SM2 Compat Shim (Vz2.0)
//
//  Bridge module. Exports the SM2-era helpers (buildStyledButton,
//  applySunkenStyle, chamfer, bevelEdges, shadowColor) backed by
//  Vz2.0 primitives so existing scene/overlay code can run unchanged.
//
//  Also patches runtime aliases onto T:
//    T.mutedText  — moderate-opacity text
//    T.dimText    — low-opacity text
//    T.darkBtn    — alias for T.card (SM2 name)
//    T.mint       — alias for T.green (SM2 name)
//    T.vermillion — alias for T.verm  (SM2 name)
//    T.goGreen    — alias for T.greenWarm
//    T.cyan       — alias for T.elec
//    T.red        — alias for T.verm
//    T.lavender   — alias for T.elec (closest match)
//    T.yellow     — alias for T.warning (unadjusted tips, thresholds)
//    T.bg / T.bgDark / T.bgLight / T.bgEdge / T.numpadChassis
//    T.fsBtn / T.fsBtnSm / T.fsSmall / T.fsCon / T.fsConSm / T.fsItem / T.fsMod
//    T.catColor   — function returning fallback green
//    T.shadowX/Y  — numeric offsets (3, 4)
//
//  These are additive. Anything already set on T is left alone.
//  Importing this module has a side-effect; do it once from any SM2 file.
// ═══════════════════════════════════════════════════

import { T } from './tokens.js';
import { buildPillButton, hexToRgba, darkenHex } from './theme-manager.js';

// ── Runtime token aliases (additive, don't stomp existing) ──
(function patchT() {
  var aliases = {
    mutedText:     hexToRgba(T.text, 0.6),
    dimText:       hexToRgba(T.text, 0.45),
    darkBtn:       T.card,
    mint:          T.green,
    mintEdgeD:     T.greenDk,
    vermillion:    T.verm,
    goGreen:       T.greenWarm,
    cyan:          T.elec,
    red:           T.verm,
    lavender:      T.elec,
    yellow:        T.warning,
    bg:            T.bg,
    bgDark:        T.well,
    bgLight:       T.card,
    bgEdge:        T.border,
    numpadChassis: T.green,
    fsBtn:         T.fsB2,
    fsBtnSm:       T.fsB3,
    fsSmall:       T.fsB3,
    fsCon:         T.fsB2,
    fsConSm:       T.fsB3,
    fsItem:        T.fsB2,
    fsMod:         T.fsB3,
    shadowX:       3,
    shadowY:       4,
  };
  Object.keys(aliases).forEach(function(k) {
    if (T[k] === undefined) T[k] = aliases[k];
  });
  if (typeof T.catColor !== 'function') {
    T.catColor = function() { return T.green; };
  }
})();

// ═══════════════════════════════════════════════════
//  buildStyledButton — SM2 returned {wrap, inner}; wrap was the bevel
//  chassis, inner was the tappable content surface. In Vz2.0 we have
//  single-element pill buttons; we return both pointing at the same
//  button so callers that mutate .inner.style.background/color/etc
//  keep working without modification.
// ═══════════════════════════════════════════════════

export function buildStyledButton(arg) {
  var label = '', color = T.card, dark = darkenHex(T.card, 0.4),
      size  = T.fsB2, onClick = null, textColor = T.text;

  if (typeof arg === 'object' && arg !== null) {
    var variantMap = {
      mint:       { c: T.green,     d: T.greenDk,      t: T.well },
      dark:       { c: T.card,      d: darkenHex(T.card, 0.4), t: T.text },
      vermillion: { c: T.verm,      d: T.vermDk,       t: '#fff' },
      red:        { c: T.verm,      d: T.vermDk,       t: '#fff' },
      goGreen:    { c: T.greenWarm, d: T.greenWarmDk,  t: T.well },
      gold:       { c: T.gold,      d: T.goldDk,       t: T.well },
      cyan:       { c: T.elec,      d: darkenHex(T.elec, 0.4), t: T.well },
      ghost:      { c: T.card,      d: darkenHex(T.card, 0.4), t: T.text },
    };
    var v = variantMap[arg.variant] || variantMap.dark;
    label     = arg.label || '';
    color     = v.c;
    dark      = v.d;
    textColor = v.t;
    onClick   = arg.onClick || null;
    size      = (arg.size === 'sm') ? T.fsB3 : T.fsB2;
  } else if (typeof arg === 'string') {
    color = arg;
    dark  = darkenHex(arg, 0.4);
  }

  var btn = buildPillButton({
    label:    label,
    color:    color,
    darkBg:   dark,
    fontSize: size,
    onClick:  onClick,
  });
  btn.style.color         = textColor;
  btn.style.pointerEvents = 'auto';
  return { wrap: btn, inner: btn };
}

// ═══════════════════════════════════════════════════
//  applySunkenStyle — SM2 inset-well look (input fields, log areas)
// ═══════════════════════════════════════════════════

export function applySunkenStyle(el) {
  el.style.background   = T.well;
  el.style.border       = '1px solid ' + T.border;
  el.style.borderRadius = '6px';
  el.style.boxShadow    = 'inset 0 2px 4px rgba(0,0,0,0.35)';
}

// ═══════════════════════════════════════════════════
//  chamfer — SM2 clip-path helper. Vz2.0 uses border-radius; return
//  empty string so any clipPath assignment is a no-op. Existing
//  border-radius on the element wins.
// ═══════════════════════════════════════════════════

export function chamfer(_n) { return ''; }

// ═══════════════════════════════════════════════════
//  bevelEdges — SM2 returned {light, dark} edge colors for 4-side
//  bevel borders. Vz2.0 uses flat cards with a single left accent
//  bar; return monochrome so any legacy application is invisible.
// ═══════════════════════════════════════════════════

export function bevelEdges(color) {
  return { light: color, dark: color };
}

// ═══════════════════════════════════════════════════
//  shadowColor — SM2 helper returning an rgba shadow from a color.
//  Vz2.0 equivalent: same color at ~80% opacity.
// ═══════════════════════════════════════════════════

export function shadowColor(color, alpha) {
  if (alpha == null) alpha = 0.8;
  return hexToRgba(color || '#000', alpha);
}

// ═══════════════════════════════════════════════════
//  applyCardBevel — SM2 4-side bevel on chassis cards. Vz2.0 replaces
//  with left accent bar + border-radius + drop shadow.
// ═══════════════════════════════════════════════════

export function applyCardBevel(el, _width) {
  if (!el.style.background)   el.style.background   = T.card;
  el.style.borderLeft       = T.accentBarW + ' solid ' + T.green;
  el.style.borderRadius     = T.chamferCard + 'px';
  if (!el.style.boxShadow)    el.style.boxShadow    = '0 4px 16px rgba(0,0,0,0.28)';
}

// Re-export theme-manager primitives for convenience — lets SM2 files
// get everything they need from this single shim import.
export { hexToRgba, darkenHex };