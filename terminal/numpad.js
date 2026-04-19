// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Numpad Component  (Vz2.0)
//  Ported from original — faithful to the hardware feel
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { T, chamfer } from './tokens.js';
import { lightenHex, darkenHex, hexToRgba } from './theme-manager.js';

// ── Numpad dimensions ─────────────────────────────
var PAD = {
  displayH: 80,
  gap:      20,
  cardPad:  18,
  keyW:     110,
  keyH:     100,
  keyGap:   16,
};

// ── Internal key builder ──────────────────────────
// Pill-style: filled color, dark text, bottom shadow, thin chamfer
function _buildKey(opts) {
  var o      = opts || {};
  var bg     = o.bg     || T.green;
  var bgDk   = o.bgDk   || darkenHex(bg, 0.35);
  var textColor = o.textColor || T.well;
  var wrap = document.createElement('div');
  wrap.style.cssText = [
    'width:' + (o.w || PAD.keyW) + 'px;',
    'height:' + (o.h || PAD.keyH) + 'px;',
    'background:' + bg + ';',
    'border:none;',
    'border-radius:14px;',
    'display:flex;align-items:center;justify-content:center;',
    'cursor:pointer;user-select:none;',
    'pointer-events:auto;touch-action:manipulation;',
    'box-sizing:border-box;',
    'box-shadow:0 6px 0 ' + bgDk + ', inset 0 1px 0 rgba(255,255,255,0.2);',
    'transition:transform 0.05s, box-shadow 0.05s;',
  ].join('');

  var label = document.createElement('div');
  label.style.cssText = [
    'font-family:' + T.fh + ';',
    'font-size:' + (o.fontSize || '44px') + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + textColor + ';',
    'line-height:1;',
    'pointer-events:none;',
  ].join('');
  label.textContent = o.label || '';

  wrap.appendChild(label);

  // Press state — pill sink
  wrap.addEventListener('pointerdown', function() {
    wrap.style.transform  = 'translateY(4px)';
    wrap.style.boxShadow  = '0 2px 0 ' + bgDk + ', inset 0 1px 0 rgba(255,255,255,0.1)';
  });
  var _rel = function() {
    wrap.style.transform = '';
    wrap.style.boxShadow = '0 6px 0 ' + bgDk + ', inset 0 1px 0 rgba(255,255,255,0.2)';
  };
  wrap.addEventListener('pointerup',     _rel);
  wrap.addEventListener('pointerleave',  _rel);
  wrap.addEventListener('pointercancel', _rel);

  return { wrap: wrap, label: label };
}

// ── Public builder ────────────────────────────────
export function buildNumpad(opts) {
  var o = opts || {};

  var maxDigits     = o.maxDigits     || 6;
  var masked        = o.masked        !== false;
  var onSubmit      = o.onSubmit      || function() {};
  var onChange      = o.onChange      || null;
  var displayFormat = o.displayFormat || null;
  var onCancel      = o.onCancel      || null;
  var submitLabel   = o.submitLabel   || '>>>';
  var canSubmit     = o.canSubmit     || function(p) { return p.length > 0; };
  var maskChar      = o.maskChar      || '\u25C6';

  // Color overrides
  var digitColor   = o.digitColor   || T.green;
  var clearColor   = o.clearColor   || T.verm;
  var submitColor  = o.submitColor  || T.greenWarm;
  var displayColor = o.displayColor || T.green;
  var chassisColor = o.chassisColor || T.well;
  var chassisLight = lightenHex(T.bg, 0.08);
  var chassisDark  = darkenHex(T.bg, 0.2);

  var keyW = o.keyW || PAD.keyW;
  var keyH = o.keyH || PAD.keyH;
  var keyGap  = o.keyGap  != null ? o.keyGap  : PAD.keyGap;
  var cardPad = o.cardPad != null ? o.cardPad : PAD.cardPad;
  var bevel   = 5;
  var cardH   = keyH * 4 + keyGap * 3 + cardPad * 2 + bevel * 2;

  var pin = '';
  var _submitCooldown = false;

  // ── Container ──────────────────────────────────
  var container = document.createElement('div');
  container.style.cssText = [
    'display:flex;flex-direction:column;',
    'gap:' + (o.gap != null ? o.gap : PAD.gap) + 'px;',
    'position:relative;',
    'width:' + (o.width || (keyW * 3 + keyGap * 2 + cardPad * 2 + bevel * 2)) + 'px;',
  ].join('');

  // ── Cancel button ───────────────────────────────
  if (onCancel) {
    var xBtn = document.createElement('div');
    xBtn.style.cssText = [
      'position:absolute;top:-18px;right:-18px;z-index:10;',
      'width:42px;height:42px;',
      'background:' + T.well + ';',
      'border:2px solid ' + T.verm + ';',
      'color:' + T.verm + ';',
      'font-family:' + T.fb + ';font-size:20px;font-weight:bold;',
      'display:flex;align-items:center;justify-content:center;',
      'cursor:pointer;',
      'clip-path:' + chamfer(6) + ';',
    ].join('');
    xBtn.textContent = 'X';
    xBtn.addEventListener('pointerup', function() { onCancel(); });
    container.appendChild(xBtn);
  }

  // ── Display ─────────────────────────────────────
  var displayH = o.displayH || PAD.displayH;
  var displayWrap = document.createElement('div');
  displayWrap.style.cssText = [
    'width:100%;height:' + displayH + 'px;',
    'filter:drop-shadow(3px 4px 0px rgba(0,0,0,0.55));',
  ].join('');

  var display = document.createElement('div');
  display.style.cssText = [
    'width:100%;height:100%;box-sizing:border-box;',
    'background:' + T.well + ';',
    'display:flex;align-items:center;justify-content:center;',
    'font-family:' + T.fb + ';',
    'font-size:32px;',
    'color:' + displayColor + ';',
    'letter-spacing:10px;',
    'border-top:'    + bevel + 'px solid ' + chassisColor + ';',
    'border-left:'   + bevel + 'px solid ' + chassisColor + ';',
    'border-bottom:' + bevel + 'px solid ' + chassisColor + ';',
    'border-right:'  + bevel + 'px solid ' + chassisColor + ';',
    'border-radius:14px;',
  ].join('');

  displayWrap.appendChild(display);
  container.appendChild(displayWrap);

  // ── Chassis ─────────────────────────────────────
  var cardWrap = document.createElement('div');
  cardWrap.style.cssText = [
    'width:100%;height:' + cardH + 'px;',
    'filter:drop-shadow(3px 4px 0px rgba(0,0,0,0.6)) drop-shadow(0 0 16px ' + hexToRgba(chassisColor, 0.2) + ');',
  ].join('');

  var card = document.createElement('div');
  card.style.cssText = [
    'width:100%;height:100%;',
    'padding:' + cardPad + 'px;',
    'display:grid;',
    'grid-template-columns:repeat(3,' + keyW + 'px);',
    'grid-template-rows:repeat(4,' + keyH + 'px);',
    'gap:' + keyGap + 'px;',
    'box-sizing:border-box;',
    'background:' + chassisColor + ';',
    'border-top:'    + bevel + 'px solid ' + chassisLight + ';',
    'border-left:'   + bevel + 'px solid ' + chassisLight + ';',
    'border-bottom:' + bevel + 'px solid ' + chassisDark  + ';',
    'border-right:'  + bevel + 'px solid ' + chassisDark  + ';',
    'border-radius:18px;',
  ].join('');

  cardWrap.appendChild(card);
  container.appendChild(cardWrap);

  // ── Keys ────────────────────────────────────────
  var layout = [
    { label: '1',         type: 'digit'  },
    { label: '2',         type: 'digit'  },
    { label: '3',         type: 'digit'  },
    { label: '4',         type: 'digit'  },
    { label: '5',         type: 'digit'  },
    { label: '6',         type: 'digit'  },
    { label: '7',         type: 'digit'  },
    { label: '8',         type: 'digit'  },
    { label: '9',         type: 'digit'  },
    { label: 'clr',       type: 'clear'  },
    { label: '0',         type: 'digit'  },
    { label: submitLabel, type: 'submit' },
  ];

  layout.forEach(function(key) {
    var keyBg, keyBgDk, textColor, fontSize;
    if (key.type === 'clear') {
      keyBg = T.verm; keyBgDk = T.vermDk;
      textColor = T.well; fontSize = '38px';
    } else if (key.type === 'submit') {
      keyBg = T.greenWarm; keyBgDk = T.greenWarmDk;
      textColor = T.well; fontSize = '32px';
    } else {
      keyBg = T.green; keyBgDk = darkenHex(T.green, 0.35);
      textColor = T.well; fontSize = '44px';
    }

    var pair = _buildKey({ label: key.label, bg: keyBg, bgDk: keyBgDk, textColor: textColor, fontSize: fontSize, w: keyW, h: keyH });

    if (key.type === 'clear') {
      var _clrTimer = null;
      var _clrFired = false;
      pair.wrap.addEventListener('pointerdown', function() {
        _clrFired = false;
        _clrTimer = setTimeout(function() {
          _clrFired = true;
          pin = '';
          _render();
          if (onChange) onChange(pin);
        }, 500);
      });
      pair.wrap.addEventListener('pointerup', function() {
        if (_clrTimer) { clearTimeout(_clrTimer); _clrTimer = null; }
        if (!_clrFired) {
          if (pin.length > 0) {
            pin = pin.slice(0, -1);
            _render();
            if (onChange) onChange(pin);
          }
        }
      });
      pair.wrap.addEventListener('pointercancel', function() {
        if (_clrTimer) { clearTimeout(_clrTimer); _clrTimer = null; }
      });
    } else {
      pair.wrap.addEventListener('pointerup', function() {
        if (key.type === 'digit') {
          if (pin.length < maxDigits) {
            container._clearHint();
            pin += key.label;
            _render();
            if (onChange) onChange(pin);
          }
        } else if (key.type === 'submit') {
          if (canSubmit(pin) && !_submitCooldown) {
            _submitCooldown = true;
            setTimeout(function() { _submitCooldown = false; }, 200);
            onSubmit(pin);
          }
        }
      });
    }

    card.appendChild(pair.wrap);
  });

  // ── Render ──────────────────────────────────────
  function _render() {
    if (displayFormat) {
      display.textContent = displayFormat(pin);
    } else if (masked) {
      display.textContent = pin.split('').map(function() { return maskChar; }).join(' ');
    } else {
      display.textContent = pin;
    }
  }

  // ── Public API ──────────────────────────────────
  container.clear   = function() { pin = ''; _render(); };
  container.getPin  = function() { return pin; };
  container.setPin  = function(d) { pin = d || ''; _render(); };

  container.setError = function(msg) {
    display.textContent = msg || '';
    display.style.color = T.verm;
    setTimeout(function() {
      display.style.color = displayColor;
      pin = ''; _render();
    }, 1200);
  };

  var _hintActive = false;
  container.setHint = function(msg, color) {
    display.textContent = msg || '';
    display.style.color = color || T.green;
    _hintActive = true;
  };
  container._clearHint = function() {
    if (_hintActive) {
      _hintActive = false;
      display.style.color = displayColor;
      _render();
    }
  };

  _render();
  return container;
}