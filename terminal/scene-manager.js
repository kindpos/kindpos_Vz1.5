// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Scene Manager  (Vz2.0)
//  Layer Stack: Gate / Working / Transactional / Interrupt
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════
//
//  Architecture unchanged from v3 — proven in production.
//  Only change: imports from ./tokens.js (Nostalgia values).
//
//  Layer hierarchy (z-index low → high):
//    Working       (10)  — primary scene canvas
//    Transactional (20)  — overlays above working scene
//    Summary       (25)  — order summary panel (left column)
//    Interrupt     (30)  — blocks all input until resolved
//    Gate          (100) — full-screen blocks (login)
//
//  Usage:
//    import { SceneManager, defineScene } from './scene-manager.js';
//    SceneManager.init();
//    SceneManager.openGate('login');
// ═══════════════════════════════════════════════════

import { T, onThemeChange } from './tokens.js';

// ── Scene Registry ────────────────────────────────
const _scenes = {};

// ── Layer State ───────────────────────────────────
let _gateScene        = null;   // { name, cleanup, scrim, container }
let _workingScene     = null;   // { name, cleanup, container }
const _transactionalStack = []; // [{ name, cleanup, scrim, frame, container }]
let _interruptScene   = null;   // { name, cleanup, scrim, frame, container }

// ── DOM Containers ────────────────────────────────
let _layerGate        = null;
let _layerWorking     = null;
let _layerTransactional = null;
let _layerSummary     = null;
let _layerInterrupt   = null;
let _headerBar        = null;

// ── Event Bus ─────────────────────────────────────
const _bus = {};

// ── Transition Hooks ──────────────────────────────
const _transitionHooks = [];

// ── Summary visibility ────────────────────────────
var _summaryVisible = false;

// ═══════════════════════════════════════════════════
//  REGISTRATION
// ═══════════════════════════════════════════════════

function register(scene) {
  if (!scene || !scene.name) {
    console.error('SceneManager.register: scene must have a name');
    return;
  }
  _scenes[scene.name] = scene;
}

// ═══════════════════════════════════════════════════
//  INIT — Wire DOM containers
// ═══════════════════════════════════════════════════

function init() {
  var terminal = document.getElementById('terminal');
  if (!terminal) {
    console.error('SceneManager.init: #terminal not found');
    return;
  }

  _headerBar          = document.getElementById('header');
  _layerWorking       = document.getElementById('layer-working');
  _layerTransactional = document.getElementById('layer-transactional');
  _layerSummary       = document.getElementById('order-summary');
  _layerInterrupt     = document.getElementById('layer-interrupt');
  _layerGate          = document.getElementById('layer-gate');

  _applyLayerGeometry();
  onThemeChange(function() { _applyLayerGeometry(); });
}

function _applyLayerGeometry() {
  var hH       = T.headerH + 'px';
  var bodyH    = 'calc(100% - ' + hH + ')';
  var summaryW = T.pcLeftW;
  var sceneLeft = _summaryVisible ? (summaryW + T.colGapSm) + 'px' : '0';
  var sceneW    = _summaryVisible ? 'calc(100% - ' + sceneLeft + ')' : '100%';

  if (_layerSummary) {
    _layerSummary.style.top    = hH;
    _layerSummary.style.left   = '0';
    _layerSummary.style.width  = summaryW + 'px';
    _layerSummary.style.height = bodyH;
    _layerSummary.style.zIndex = T.zSummary;
  }

  [_layerWorking, _layerTransactional, _layerInterrupt].forEach(function(el) {
    if (!el) return;
    el.style.top    = hH;
    el.style.left   = sceneLeft;
    el.style.width  = sceneW;
    el.style.height = bodyH;
  });

  // Gate — always full width (covers summary too)
  if (_layerGate) {
    _layerGate.style.top    = hH;
    _layerGate.style.left   = '0';
    _layerGate.style.width  = '100%';
    _layerGate.style.height = bodyH;
  }

  if (_layerWorking)       _layerWorking.style.zIndex       = T.zWorking;
  if (_layerTransactional) _layerTransactional.style.zIndex = T.zTransactional;
  if (_layerSummary)       _layerSummary.style.zIndex       = T.zSummary;
  if (_layerInterrupt)     _layerInterrupt.style.zIndex     = T.zInterrupt;
  if (_layerGate)          _layerGate.style.zIndex          = T.zGate;
}

// ═══════════════════════════════════════════════════
//  GATE LAYER  — login, full-screen blocks
// ═══════════════════════════════════════════════════

function openGate(sceneName) {
  var scene = _scenes[sceneName];
  if (!scene) return console.error('SceneManager.openGate: "' + sceneName + '" not registered');

  var scrim = document.createElement('div');
  scrim.className = 'layer-scrim layer-scrim-gate';
  scrim.style.cssText = 'position:absolute;inset:0;background:' + T.scrimGate + ';';
  _layerGate.appendChild(scrim);

  var container = document.createElement('div');
  container.className = 'layer-content';
  container.dataset.scene = sceneName;
  container.style.cssText = 'position:absolute;inset:0;';
  _layerGate.appendChild(container);

  _layerGate.style.pointerEvents = 'auto';

  var cleanup = scene.mount(container, {});
  _gateScene = { name: sceneName, cleanup: cleanup, scrim: scrim, container: container };
}

function closeGate(sceneName) {
  if (!_gateScene || _gateScene.name !== sceneName) return;

  var scene = _scenes[_gateScene.name];
  if (scene && scene.unmount) scene.unmount();
  if (typeof _gateScene.cleanup === 'function') _gateScene.cleanup();

  _gateScene.container.remove();
  _gateScene.scrim.remove();
  _layerGate.style.pointerEvents = 'none';
  _gateScene = null;

  _emit('gate:closed');
}

// ═══════════════════════════════════════════════════
//  WORKING LAYER  — primary scene canvas
// ═══════════════════════════════════════════════════

function mountWorking(sceneName, params) {
  if (params === undefined) params = {};

  var scene = _scenes[sceneName];
  if (!scene) return console.error('SceneManager.mountWorking: "' + sceneName + '" not registered');

  _transitionHooks.forEach(function(fn) { fn(); });

  if (_workingScene) _unmountWorkingInternal();

  var container = document.createElement('div');
  container.className = 'layer-content';
  container.dataset.scene = sceneName;
  container.style.cssText = 'position:absolute;inset:0;';
  _layerWorking.appendChild(container);

  var cleanup = scene.mount(container, params);
  _workingScene = { name: sceneName, cleanup: cleanup, container: container };

  _emit('working:mounted', { sceneName: sceneName });
}

function unmountWorking(sceneName) {
  if (!_workingScene || _workingScene.name !== sceneName) return;
  _unmountWorkingInternal();
  _emit('working:unmounted', { sceneName: sceneName });
}

function _unmountWorkingInternal() {
  if (!_workingScene) return;
  var scene = _scenes[_workingScene.name];
  if (scene && scene.unmount) scene.unmount();
  if (typeof _workingScene.cleanup === 'function') _workingScene.cleanup();
  _workingScene.container.remove();
  _workingScene = null;
}

// ═══════════════════════════════════════════════════
//  TRANSACTIONAL LAYER  — overlays above working scene
// ═══════════════════════════════════════════════════

function openTransactional(sceneName, params) {
  if (params === undefined) params = {};

  var scene = _scenes[sceneName];
  if (!scene) return console.error('SceneManager.openTransactional: "' + sceneName + '" not registered');

  _transitionHooks.forEach(function(fn) { fn(); });
  _emit('transactional:opening', { sceneName: sceneName });

  var scrim = document.createElement('div');
  scrim.className = 'layer-scrim layer-scrim-transactional';
  scrim.style.cssText = 'position:absolute;inset:0;background:' + T.scrimWorking + ';';
  _layerTransactional.appendChild(scrim);

  var frame = document.createElement('div');
  frame.className = 'layer-frame layer-frame-transactional';
  frame.style.cssText = 'position:absolute;inset:0;border:2px solid ' + T.frameTransactional + ';';
  _layerTransactional.appendChild(frame);

  var container = document.createElement('div');
  container.className = 'layer-content';
  container.dataset.scene = sceneName;
  container.style.cssText = 'width:100%;height:100%;position:relative;';
  frame.appendChild(container);

  _layerTransactional.style.pointerEvents = 'auto';

  frame.classList.add('layer-transactional-enter');
  requestAnimationFrame(function() {
    requestAnimationFrame(function() {
      frame.classList.remove('layer-transactional-enter');
    });
  });

  var cleanup = scene.mount(container, params);
  _transactionalStack.push({
    name: sceneName, cleanup: cleanup,
    scrim: scrim, frame: frame, container: container,
  });

  _emit('transactional:opened', { sceneName: sceneName });
}

function closeTransactional(sceneName) {
  var idx = -1;
  for (var i = _transactionalStack.length - 1; i >= 0; i--) {
    if (_transactionalStack[i].name === sceneName) { idx = i; break; }
  }
  if (idx === -1) return;

  var entry = _transactionalStack[idx];
  var scene = _scenes[entry.name];
  if (scene && scene.unmount) scene.unmount();
  if (typeof entry.cleanup === 'function') entry.cleanup();

  entry.frame.remove();
  entry.scrim.remove();
  _transactionalStack.splice(idx, 1);

  if (_transactionalStack.length === 0) {
    _layerTransactional.style.pointerEvents = 'none';
  }

  _emit('transactional:closed', { sceneName: sceneName });
}

function closeAllTransactional() {
  while (_transactionalStack.length > 0) {
    closeTransactional(_transactionalStack[_transactionalStack.length - 1].name);
  }
}

// ═══════════════════════════════════════════════════
//  INTERRUPT LAYER  — blocks all input until resolved
// ═══════════════════════════════════════════════════

function interruptFn(sceneName, params, onConfirm, onCancel) {
  if (params === undefined) params = {};

  var scene = _scenes[sceneName];
  if (!scene) return console.error('SceneManager.interrupt: "' + sceneName + '" not registered');

  var scrim = document.createElement('div');
  scrim.className = 'layer-scrim layer-scrim-interrupt';
  scrim.style.cssText = 'position:absolute;inset:0;background:' + T.scrimInterrupt + ';';
  _layerInterrupt.appendChild(scrim);

  var frame = document.createElement('div');
  frame.className = 'layer-frame layer-frame-interrupt';
  frame.style.cssText = 'position:absolute;inset:0;border:2px solid ' + T.frameInterruptDecision + ';';
  _layerInterrupt.appendChild(frame);

  var container = document.createElement('div');
  container.className = 'layer-content';
  container.dataset.scene = sceneName;
  container.style.cssText = 'width:100%;height:100%;position:relative;';
  frame.appendChild(container);

  _layerInterrupt.style.pointerEvents = 'auto';

  var wrappedConfirm = function() {
    resolveInterrupt(sceneName);
    if (onConfirm) onConfirm();
  };
  var wrappedCancel = function() {
    resolveInterrupt(sceneName);
    if (onCancel) onCancel();
  };

  var mountParams = Object.assign({}, params, {
    onConfirm: wrappedConfirm,
    onCancel:  wrappedCancel,
  });

  var cleanup = scene.mount(container, mountParams);
  _interruptScene = {
    name: sceneName, cleanup: cleanup,
    scrim: scrim, frame: frame, container: container,
  };

  _emit('interrupt:opened', { sceneName: sceneName });
}

function resolveInterrupt(sceneName) {
  if (!_interruptScene) return;
  if (sceneName && _interruptScene.name !== sceneName) return;

  var scene = _scenes[_interruptScene.name];
  var name  = _interruptScene.name;
  if (scene && scene.unmount) scene.unmount();
  if (typeof _interruptScene.cleanup === 'function') _interruptScene.cleanup();

  _interruptScene.frame.remove();
  _interruptScene.scrim.remove();
  _layerInterrupt.style.pointerEvents = 'none';
  _interruptScene = null;

  _emit('interrupt:resolved', { sceneName: name });
}

// ═══════════════════════════════════════════════════
//  SUMMARY LAYER  — left column order panel
// ═══════════════════════════════════════════════════

function showSummary() {
  if (!_layerSummary) return;
  _summaryVisible = true;
  _layerSummary.style.display = 'flex';
  _applyLayerGeometry();
  _emit('summary:shown');
}

function hideSummary() {
  if (!_layerSummary) return;
  _summaryVisible = false;
  _layerSummary.style.display = 'none';
  _applyLayerGeometry();
  _emit('summary:hidden');
}

function getSummaryLayer() {
  return _layerSummary;
}

// ═══════════════════════════════════════════════════
//  EVENT BUS
// ═══════════════════════════════════════════════════

function on(event, handler) {
  if (!_bus[event]) _bus[event] = [];
  _bus[event].push(handler);
}

function off(event, handler) {
  if (!_bus[event]) return;
  _bus[event] = _bus[event].filter(function(h) { return h !== handler; });
}

function _emit(event, data) {
  if (!_bus[event]) return;
  var handlers = _bus[event].slice();
  for (var i = 0; i < handlers.length; i++) {
    try { handlers[i](data); }
    catch (e) { console.error('Event handler error [' + event + ']:', e); }
  }
}

function emit(event, data) { _emit(event, data); }

// ═══════════════════════════════════════════════════
//  GETTERS
// ═══════════════════════════════════════════════════

function getActiveWorking()      { return _workingScene ? _workingScene.name : null; }
function getTransactionalStack() { return _transactionalStack.map(function(e) { return e.name; }); }
function hasInterrupt()          { return _interruptScene !== null; }

// ═══════════════════════════════════════════════════
//  TRANSITION HOOKS
// ═══════════════════════════════════════════════════

function onBeforeTransition(fn) { _transitionHooks.push(fn); }

// ═══════════════════════════════════════════════════
//  PUBLIC API
// ═══════════════════════════════════════════════════

export const SceneManager = {
  register,
  init,

  openGate,
  closeGate,

  mountWorking,
  unmountWorking,

  openTransactional,
  closeTransactional,
  closeAllTransactional,

  interrupt:        interruptFn,
  resolveInterrupt,

  showSummary,
  hideSummary,
  getSummaryLayer,

  on,
  off,
  emit,

  getActiveWorking,
  getTransactionalStack,
  hasInterrupt,

  onBeforeTransition,
};

// ═══════════════════════════════════════════════════
//  defineScene — higher-level scene API
//  Auto-manages state, event cleanup, sub-scenes.
//
//  Usage:
//    defineScene({
//      name:   'login',
//      state:  { pin: [] },
//      events: { 'auth:success': (data) => { ... } },
//      render: (container, params, state) => {
//        // build DOM, return cleanup fn
//        return function cleanup() { ... };
//      },
//      interrupts:    { 'confirm-void': { render, unmount } },
//      transactionals:{ 'tip-adjust':  { render, unmount } },
//    });
// ═══════════════════════════════════════════════════

function _deepCopy(obj) {
  if (obj === null || typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) {
    return obj.map(function(v) { return _deepCopy(v); });
  }
  var copy = {};
  var keys = Object.keys(obj);
  for (var j = 0; j < keys.length; j++) {
    copy[keys[j]] = _deepCopy(obj[keys[j]]);
  }
  return copy;
}

function _registerSubScene(name, subDef) {
  if (!subDef || !subDef.render) {
    console.error('defineScene: sub-scene "' + name + '" must have a render function');
    return;
  }
  SceneManager.register({
    name: name,
    mount: function(container, params) {
      if (params === undefined) params = {};
      return subDef.render(container, params);
    },
    unmount: function() {
      if (subDef.unmount) subDef.unmount();
    },
  });
}

export function defineScene(def) {
  if (!def || !def.name) {
    console.error('defineScene: scene must have a name');
    return;
  }
  if (!def.render) {
    console.error('defineScene: "' + def.name + '" must have a render function');
    return;
  }

  var defaultState = def.state ? _deepCopy(def.state) : {};
  var currentState = null;
  var boundEvents  = [];

  var scene = {
    name: def.name,
    mount: function(container, params) {
      if (params === undefined) params = {};
      currentState = _deepCopy(defaultState);

      if (def.events) {
        var evKeys = Object.keys(def.events);
        for (var i = 0; i < evKeys.length; i++) {
          var evName  = evKeys[i];
          var handler = def.events[evName];
          SceneManager.on(evName, handler);
          boundEvents.push({ event: evName, handler: handler });
        }
      }

      return def.render(container, params, currentState);
    },
    unmount: function() {
      for (var i = 0; i < boundEvents.length; i++) {
        SceneManager.off(boundEvents[i].event, boundEvents[i].handler);
      }
      boundEvents = [];
      if (def.unmount) def.unmount(currentState);
      currentState = null;
    },
  };

  SceneManager.register(scene);

  if (def.interrupts) {
    var intKeys = Object.keys(def.interrupts);
    for (var j = 0; j < intKeys.length; j++) {
      _registerSubScene(intKeys[j], def.interrupts[intKeys[j]]);
    }
  }
  if (def.transactionals) {
    var trKeys = Object.keys(def.transactionals);
    for (var k = 0; k < trKeys.length; k++) {
      _registerSubScene(trKeys[k], def.transactionals[trKeys[k]]);
    }
  }

  return scene;
}