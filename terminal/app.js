// ═══════════════════════════════════════════════════
//  KINDpos Terminal — app.js  (Vz2.0)
//  Entry point. Boots managers, loads config, opens gate.
//  Also exports setSceneName / setHeaderBack for scenes that
//  want the global top header bar.
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { SceneManager } from './scene-manager.js';
import { T, applyStoreTheme } from './tokens.js';

// ── Scene imports ─────────────────────────────────
import './scenes/login.js';
import './scenes/server-landing.js';
import './scenes/manager-landing.js';
import './scenes/check-overview.js';
import './scenes/column-editor.js';
import './scenes/order-entry.js';
import './scenes/payment.js';
import './scenes/server-checkout.js';

// ── Dev console hook ──────────────────────────────
// window._SM exposes SceneManager for console testing
// e.g. window._SM.mountWorking('server-landing', {})
window._SM = SceneManager;

// ═══════════════════════════════════════════════════
//  BOOT
// ═══════════════════════════════════════════════════

async function boot() {

  // 1. Init scene manager — wire DOM layers
  SceneManager.init();

  // 2. Wire header auto-hide on scene transitions
  SceneManager.onBeforeTransition(_hideHeader);

  // 3. Load store config from backend
  //    Applies store theme (colors, name, logo) before first render
  //    Falls back to Nostalgia defaults if API unavailable
  try {
    var res = await fetch('/api/v1/config/store');
    if (res.ok) {
      var config = await res.json();
      applyStoreTheme({
        storeName:       config.store_name      || 'Store Name',
        terminalId:      config.terminal_id     || 'Terminal 01',
        storePrimary:    config.primary_color   || null,
        storePrimaryDk:  config.primary_dark    || null,
        storeSecondary:  config.secondary_color || null,
        storeSecondaryDk:config.secondary_dark  || null,
        storeTertiary:   config.tertiary_color  || null,
        storeTertiaryDk: config.tertiary_dark   || null,
        storeLogoUrl:    config.logo_url        || null,
      });
    }
  } catch (e) {
    console.info('[app] Store config unavailable, using defaults');
  }

  // 4. Open gate → login scene
  SceneManager.openGate('login');
}

// ── Run ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', boot);

// ═══════════════════════════════════════════════════
//  HEADER API
//
//  Scenes that want a top header bar call:
//    setSceneName('CHECK')
//    setHeaderBack({ back: true, onBack: fn, x: true, onX: fn })
//
//  Header auto-hides on scene transitions (onBeforeTransition).
//  Each scene must re-call during render to keep it visible.
//  Landings don't call either — header stays hidden for them.
// ═══════════════════════════════════════════════════

var _headerEl     = null;
var _headerBackEl = null;
var _headerNameEl = null;
var _headerXEl    = null;

var HEADER_H = 44; // px, fixed

function _ensureHeader() {
  if (_headerEl) return _headerEl;

  _headerEl = document.getElementById('header');
  if (!_headerEl) {
    _headerEl = document.createElement('div');
    _headerEl.id = 'header';
    var terminal = document.getElementById('terminal') || document.body;
    terminal.appendChild(_headerEl);
  }

  _headerEl.style.cssText = [
    'position:absolute;top:0;left:0;right:0;',
    'height:' + HEADER_H + 'px;',
    'background:' + T.green + ';',
    'display:none;',                       // hidden until a scene sets it
    'align-items:center;',
    'padding:0 10px;',
    'gap:8px;',
    'z-index:50;',                         // above working, below interrupts
    'box-shadow:0 2px 12px rgba(0,0,0,0.35);',
    'box-sizing:border-box;',
  ].join('');

  // ← back arrow (left)
  _headerBackEl = document.createElement('div');
  _headerBackEl.style.cssText = [
    'display:none;',
    'font-family:' + T.fh + ';',
    'font-size:36px;',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.well + ';',
    'cursor:pointer;user-select:none;',
    'padding:0 14px;',
    'line-height:1;',
    'min-width:44px;',
    'text-align:center;',
  ].join('');
  _headerBackEl.textContent = '\u2039';
  _headerEl.appendChild(_headerBackEl);

  // scene name (center, fills space)
  _headerNameEl = document.createElement('div');
  _headerNameEl.style.cssText = [
    'flex:1;',
    'font-family:' + T.fh + ';',
    'font-size:' + T.fsH4 + ';',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.well + ';',
    'letter-spacing:0.16em;',
    'text-transform:uppercase;',
    'text-align:center;',
    'white-space:nowrap;',
    'overflow:hidden;',
    'text-overflow:ellipsis;',
  ].join('');
  _headerEl.appendChild(_headerNameEl);

  // × close (right)
  _headerXEl = document.createElement('div');
  _headerXEl.style.cssText = [
    'display:none;',
    'font-family:' + T.fh + ';',
    'font-size:26px;',
    'font-weight:' + T.fwBold + ';',
    'color:' + T.well + ';',
    'cursor:pointer;user-select:none;',
    'padding:0 14px;',
    'line-height:1;',
    'min-width:44px;',
    'text-align:center;',
  ].join('');
  _headerXEl.textContent = '\u2715';
  _headerEl.appendChild(_headerXEl);

  return _headerEl;
}

function _showHeader() {
  _ensureHeader();
  _headerEl.style.display = 'flex';
}

function _hideHeader() {
  if (!_headerEl) return;
  _headerEl.style.display  = 'none';
  // Clear handlers to prevent leaks across scenes
  _headerBackEl.onclick    = null;
  _headerXEl.onclick       = null;
  _headerBackEl.style.display = 'none';
  _headerXEl.style.display    = 'none';
  _headerNameEl.textContent   = '';
}

/**
 * Set the scene name in the header bar. Shows the header if it was hidden.
 * Call from inside a scene's render() function.
 */
export function setSceneName(name) {
  _ensureHeader();
  _headerNameEl.textContent = name || '';
  _showHeader();
}

/**
 * Configure the header's back button and X close button.
 * @param {object} opts
 * @param {boolean} opts.back  — show the ‹ back arrow
 * @param {Function} opts.onBack — back arrow handler
 * @param {boolean} opts.x     — show the × close button
 * @param {Function} opts.onX  — X handler (falls back to onBack)
 */
export function setHeaderBack(opts) {
  _ensureHeader();
  opts = opts || {};

  if (opts.back) {
    _headerBackEl.style.display = '';
    _headerBackEl.onclick = function() {
      if (opts.onBack) opts.onBack();
    };
  } else {
    _headerBackEl.style.display = 'none';
    _headerBackEl.onclick       = null;
  }

  if (opts.x) {
    _headerXEl.style.display = '';
    _headerXEl.onclick = function() {
      if (opts.onX) opts.onX();
      else if (opts.onBack) opts.onBack();
    };
  } else {
    _headerXEl.style.display = 'none';
    _headerXEl.onclick       = null;
  }

  _showHeader();
}