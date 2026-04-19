// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Keyboard STUB  (Vz2.0)
//  Temporary replacement for the SM2 on-screen QWERTY keyboard.
//  Same public API (showKeyboard / hideKeyboard / isKeyboardVisible)
//  so callers don't need to change. Uses a simple modal with a
//  native <input> — the OS on-screen keyboard (touch devices) or
//  physical keyboard (desktop) handles the actual typing.
//
//  TODO: Replace with a proper Vz2.0 on-screen QWERTY component
//  when the real keyboard is ported.
// ═══════════════════════════════════════════════════

import { T } from './tokens.js';
import { buildPillButton, darkenHex } from './theme-manager.js';

var _root = null;
var _visible = false;
var _opts = {};
var _input = null;

// ═══════════════════════════════════════════════════
//  PUBLIC API
// ═══════════════════════════════════════════════════

export function showKeyboard(opts) {
  _opts = opts || {};
  _buildIfNeeded();
  _input.value = _opts.initialValue || '';
  _input.placeholder = _opts.placeholder || '';
  if (_opts.maxLength) _input.maxLength = _opts.maxLength;
  else _input.removeAttribute('maxlength');

  var host = document.getElementById('terminal') || document.body;
  if (!_root.parentNode) host.appendChild(_root);

  _visible = true;
  // Focus on the next frame so the input is actually in the DOM
  requestAnimationFrame(function() {
    _input.focus();
    _input.setSelectionRange(_input.value.length, _input.value.length);
  });
}

export function hideKeyboard() {
  if (!_visible) return;
  _visible = false;
  if (_root && _root.parentNode) _root.parentNode.removeChild(_root);
}

export function isKeyboardVisible() {
  return _visible;
}

// ═══════════════════════════════════════════════════
//  INTERNAL — build the modal once, reuse
// ═══════════════════════════════════════════════════

function _buildIfNeeded() {
  if (_root) return;

  _root = document.createElement('div');
  _root.style.cssText = [
    'position:absolute;inset:0;z-index:200;',
    'background:rgba(0,0,0,0.55);',
    'display:flex;align-items:center;justify-content:center;',
  ].join('');

  // Dismiss on backdrop tap
  _root.addEventListener('pointerup', function(e) {
    if (e.target === _root) {
      if (_opts.onDismiss) _opts.onDismiss();
      hideKeyboard();
    }
  });

  var panel = document.createElement('div');
  panel.style.cssText = [
    'min-width:360px;max-width:480px;',
    'padding:24px;',
    'background:' + T.card + ';',
    'border:3px solid ' + T.green + ';',
    'border-radius:' + T.chamferCard + 'px;',
    'box-shadow:0 12px 40px rgba(0,0,0,0.55);',
    'display:flex;flex-direction:column;gap:14px;',
  ].join('');

  var label = document.createElement('div');
  label.style.cssText = [
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsB2 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.green + ';',
    'letter-spacing:0.18em;',
    'text-transform:uppercase;',
    'text-align:center;',
  ].join('');
  label.textContent = 'ENTER TEXT';
  panel.appendChild(label);

  _input = document.createElement('input');
  _input.type = 'text';
  _input.style.cssText = [
    'width:100%;box-sizing:border-box;',
    'padding:12px 14px;',
    'background:' + T.well + ';',
    'border:2px solid ' + T.border + ';',
    'border-radius:8px;',
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsB1 + ';',
    'color:' + T.text + ';',
    'outline:none;',
  ].join('');
  _input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      _handleDone();
    } else if (e.key === 'Escape') {
      if (_opts.onDismiss) _opts.onDismiss();
      hideKeyboard();
    } else if (_opts.onInput) {
      // defer so value reflects the new keystroke
      setTimeout(function() { _opts.onInput(_input.value); }, 0);
    }
  });
  panel.appendChild(_input);

  var btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex;gap:12px;justify-content:space-between;';

  var cancelBtn = buildPillButton({
    label:    'CANCEL',
    color:    T.card,
    darkBg:   darkenHex(T.card, 0.4),
    fontSize: T.fsB2,
    onClick:  function() {
      if (_opts.onDismiss) _opts.onDismiss();
      hideKeyboard();
    },
  });
  cancelBtn.style.flex  = '1';
  cancelBtn.style.color = T.text;

  var doneBtn = buildPillButton({
    label:    'DONE',
    color:    T.green,
    darkBg:   T.greenDk,
    fontSize: T.fsB2,
    onClick:  _handleDone,
  });
  doneBtn.style.flex = '1';

  btnRow.appendChild(cancelBtn);
  btnRow.appendChild(doneBtn);
  panel.appendChild(btnRow);

  _root.appendChild(panel);
}

function _handleDone() {
  var val = _input.value;
  if (_opts.onDone) _opts.onDone(val);
  if (_opts.dismissOnDone !== false) hideKeyboard();
}