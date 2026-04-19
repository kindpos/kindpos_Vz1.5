// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Shared Components  (Vz2.0)
//  showToast, buildButton, buildGap, buildRoleButton
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════
//
//  Ported from SM2 version. Reskinned to Nostalgia theme:
//    - Pill-style buttons instead of Style D bevel
//    - border-radius instead of chamfer clip-path
//    - New token names (T.green, T.card, T.verm, T.text)
// ═══════════════════════════════════════════════════

import { T } from './tokens.js';
import {
  buildPillButton,
  lightenHex,
  darkenHex,
  hexToRgba,
} from './theme-manager.js';

// ═══════════════════════════════════════════════════
//  buildButton — generic pill-style button
//  Wraps buildPillButton with the shape older scenes expect:
//  a single element with textContent, width/height/color overrides,
//  and an onTap callback.
// ═══════════════════════════════════════════════════

export function buildButton(label, opts) {
  var o = opts || {};
  var fill       = o.fill       || T.card;
  var color      = o.color      || T.green;
  var fontSize   = o.fontSize   || T.fsB2;
  var fontFamily = o.fontFamily || T.fb;
  var width      = o.width;
  var height     = o.height;
  var onTap      = o.onTap      || null;
  var lineH      = o.lineHeight || '1.05';

  var btn = buildPillButton({
    label:    label,
    color:    fill,
    darkBg:   darkenHex(fill, 0.4),
    fontSize: fontSize,
  });

  // Override default pill styling to match old buildButton contract:
  // color override → text color; fontFamily → override font; label text
  // respects line-height and pre-line (for multi-line button labels).
  btn.style.color       = color;
  btn.style.fontFamily  = fontFamily;
  btn.style.lineHeight  = lineH;
  btn.style.whiteSpace  = 'pre-line';
  btn.style.padding     = '10px 18px';
  btn.style.textTransform = 'none';
  btn.style.letterSpacing = '0.04em';

  if (width)  btn.style.width  = width + 'px';
  if (height) btn.style.height = height + 'px';

  if (onTap) btn.addEventListener('pointerup', onTap);

  return btn;
}

// ═══════════════════════════════════════════════════
//  showToast — transient message pill, bottom-center
//
//  opts:
//    duration — ms before fade-out (default 4000)
//    bg       — background color (default T.verm for errors)
//    append   — optional DOM node to append inside (e.g. UNDO link)
// ═══════════════════════════════════════════════════

export function showToast(message, opts) {
  var o = opts || {};
  var duration = o.duration || 4000;
  var bg = o.bg || T.verm;

  // Pick a text color that reads cleanly on the chosen bg.
  // For light backgrounds (green, gold), dark text reads better.
  // For dark backgrounds (verm, card, greenDk), light text.
  var text = _toastTextColor(bg);

  var el = document.createElement('div');
  el.style.cssText = [
    'position:fixed;bottom:32px;left:50%;transform:translate(-50%, 8px);',
    'padding:14px 28px;',
    'background:' + bg + ';',
    'color:' + text + ';',
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsB2 + ';',
    'font-weight:' + T.fwBold + ';',
    'border-radius:999px;',
    'box-shadow:0 8px 24px rgba(0,0,0,0.45);',
    'z-index:9999;',
    'pointer-events:none;',
    'opacity:0;',
    'transition:opacity 0.22s ease, transform 0.22s ease;',
    'white-space:nowrap;',
    'max-width:calc(100% - 48px);',
    'overflow:hidden;text-overflow:ellipsis;',
  ].join('');
  el.textContent = message;

  if (o.append) {
    el.style.pointerEvents = 'auto';
    el.style.whiteSpace    = 'normal';
    el.appendChild(o.append);
  }

  document.body.appendChild(el);
  requestAnimationFrame(function() {
    el.style.opacity   = '1';
    el.style.transform = 'translate(-50%, 0)';
  });

  setTimeout(function() {
    el.style.opacity   = '0';
    el.style.transform = 'translate(-50%, 8px)';
    setTimeout(function() {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 240);
  }, duration);
}

// Pick a text color with decent contrast against `bg`.
// Simple luminance heuristic — accurate enough for our palette.
function _toastTextColor(bg) {
  if (typeof bg !== 'string' || bg.charAt(0) !== '#' || bg.length < 7) return T.well;
  var r = parseInt(bg.slice(1, 3), 16);
  var g = parseInt(bg.slice(3, 5), 16);
  var b = parseInt(bg.slice(5, 7), 16);
  var lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.55 ? T.well : T.text;
}

// ═══════════════════════════════════════════════════
//  buildGap — spacer element
// ═══════════════════════════════════════════════════

export function buildGap(px) {
  var gap = document.createElement('div');
  gap.style.height     = px + 'px';
  gap.style.flexShrink = '0';
  return gap;
}

// ═══════════════════════════════════════════════════
//  buildRoleButton — selectable role chip with glow
//  Used by clock-in and settings. Reskinned to Nostalgia:
//  border-radius pill, role-color fill when selected, role-color
//  outline when unselected. No chamfer/bevel.
// ═══════════════════════════════════════════════════

export function buildRoleButton(roleName, roleColor, onSelect) {
  var glowDefault = hexToRgba(roleColor, 0.35);

  var wrap = document.createElement('div');
  wrap.style.cssText = [
    'width:100%;height:100%;min-height:72px;',
    'background:' + T.card + ';',
    'border:3px solid ' + roleColor + ';',
    'border-radius:14px;',
    'display:flex;align-items:center;justify-content:center;',
    'box-sizing:border-box;padding:10px 18px;',
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsH3 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.text + ';',
    'text-transform:uppercase;',
    'letter-spacing:0.1em;',
    'cursor:pointer;user-select:none;',
    'box-shadow:0 0 14px ' + glowDefault + ';',
    'transition:' + T.transitionFast + ';',
  ].join('');
  wrap.textContent = roleName.toUpperCase();

  wrap._roleName = roleName;
  wrap._selected = false;

  function _applyDefault() {
    wrap.style.background = T.card;
    wrap.style.color      = T.text;
    wrap.style.border     = '3px solid ' + roleColor;
    wrap.style.boxShadow  = '0 0 14px ' + hexToRgba(roleColor, 0.35);
    wrap.style.transform  = '';
  }

  function _applySelected() {
    wrap.style.background = roleColor;
    wrap.style.color      = T.well;
    wrap.style.border     = '3px solid ' + lightenHex(roleColor, 0.3);
    wrap.style.boxShadow  = '0 0 22px ' + hexToRgba(roleColor, 0.85);
    wrap.style.transform  = '';
  }

  wrap._resetVisual = function() {
    if (wrap._selected) _applySelected();
    else _applyDefault();
  };

  wrap.addEventListener('pointerdown', function() {
    wrap.style.transform = 'translateY(2px)';
  });
  wrap.addEventListener('pointerup', function() {
    wrap.style.transform = '';
    onSelect(roleName);
  });
  wrap.addEventListener('pointerleave', function() {
    wrap._resetVisual();
  });

  return wrap;
}