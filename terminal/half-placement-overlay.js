/**
 * Half Placement Overlay
 *
 * Interrupt overlay that lets the user assign a modifier to the
 * Left or Right half of an item. Uses the interrupt pattern from
 * scene-manager.js.
 */

import { T } from './tokens.js';
import { buildStyledButton } from './sm2-shim.js';
import { SceneManager } from './scene-manager.js';

/**
 * Show the half-placement overlay.
 *
 * @param {string}  itemName    — name of the ticket item
 * @param {string}  modName     — modifier being placed
 * @param {number}  modPrice    — full modifier price
 * @param {number|null} halfPrice — half price (null = free)
 * @param {Array}   currentMods — current mods on the item [{name, price, prefix, ...}]
 * @returns {Promise<{side: "Left"|"Right"}>}  resolves on pick, rejects on cancel
 */
export function showHalfPlacementOverlay(itemName, modName, modPrice, halfPrice, currentMods) {
  return new Promise(function(resolve, reject) {
    SceneManager.interrupt('half-placement', {
      onConfirm: function(result) { resolve(result); },
      onCancel: function() { reject(new Error('Interrupt cancelled')); },
      params: { itemName: itemName, modName: modName, modPrice: modPrice, halfPrice: halfPrice, currentMods: currentMods },
    });
  });
}

SceneManager.register({
  name: 'half-placement',
  mount: function(container, params) {
    _buildOverlay(container, params.itemName, params.modName, params.modPrice, params.halfPrice, params.currentMods, params.onConfirm, params.onCancel);
  },
  unmount: function() {},
});

function _buildOverlay(el, itemName, modName, modPrice, halfPrice, currentMods, onConfirm, onCancel) {
  var panel = document.createElement('div');
  panel.style.cssText = [
    'width:90%;max-width:900px;',
    'background:' + T.bg + ';',
    'border:3px solid ' + T.border + ';',
    'clip-path:polygon(8px 0%,calc(100% - 8px) 0%,100% 8px,100% calc(100% - 8px),calc(100% - 8px) 100%,8px 100%,0% calc(100% - 8px),0% 8px);',
    'display:flex;flex-direction:column;',
    'font-family:' + T.fb + ';',
    'overflow:hidden;',
  ].join('');

  // ── Header strip ──
  var header = document.createElement('div');
  header.style.cssText = [
    'display:flex;align-items:center;justify-content:space-between;',
    'padding:10px 16px;',
    'background:' + T.bgDark + ';',
    'border-bottom:2px solid ' + T.border + ';',
  ].join('');

  var titleSpan = document.createElement('span');
  titleSpan.style.cssText = 'color:' + T.gold + ';font-size:' + T.fsBtnSm + ';font-family:' + T.fb + ';';
  titleSpan.textContent = itemName + '  \u2014  ' + modName;
  header.appendChild(titleSpan);

  // CANCEL button (Style D dark)
  var cancelPair = buildStyledButton(T.darkBtn);
  cancelPair.wrap.style.cssText += 'width:100px;height:40px;';
  cancelPair.inner.textContent = 'CANCEL';
  cancelPair.inner.style.color = T.mint;
  cancelPair.inner.style.fontSize = T.fsSmall;
  cancelPair.inner.style.fontFamily = T.fb;
  cancelPair.wrap.addEventListener('pointerup', function() {
    onCancel();
  });
  header.appendChild(cancelPair.wrap);
  panel.appendChild(header);

  // ── Body: two columns with vertical wall ──
  var body = document.createElement('div');
  body.style.cssText = [
    'display:flex;flex:1;min-height:200px;',
  ].join('');

  // Separate left and right current mods
  var leftMods  = currentMods.filter(function(m) { return m.prefix === 'Left'; });
  var rightMods = currentMods.filter(function(m) { return m.prefix === 'Right'; });
  var wholeMods = currentMods.filter(function(m) { return !m.prefix; });
  var wholeNames = {};
  wholeMods.forEach(function(m) { wholeNames[m.name] = true; });

  // Left column
  var leftCol = _buildColumn('LEFT', leftMods, wholeNames, function() {
    onConfirm({ side: 'Left' });
  });
  body.appendChild(leftCol);

  // Vertical wall divider
  var wall = document.createElement('div');
  wall.style.cssText = [
    'width:7px;',
    'background:' + T.bgDark + ';',
    'flex-shrink:0;',
  ].join('');
  body.appendChild(wall);

  // Right column
  var rightCol = _buildColumn('RIGHT', rightMods, wholeNames, function() {
    onConfirm({ side: 'Right' });
  });
  body.appendChild(rightCol);

  panel.appendChild(body);
  el.appendChild(panel);
}

function _buildColumn(label, mods, wholeNames, onTap) {
  var col = document.createElement('div');
  col.style.cssText = [
    'flex:1;display:flex;flex-direction:column;padding:12px;',
  ].join('');

  // Side button (Style D dark with mint shadow)
  var btnPair = buildStyledButton(T.darkBtn);
  btnPair.wrap.style.cssText += 'width:100%;height:56px;margin-bottom:12px;';
  btnPair.inner.textContent = label;
  btnPair.inner.style.color = T.mint;
  btnPair.inner.style.fontSize = T.fsBtn;
  btnPair.inner.style.fontFamily = T.fb;
  btnPair.wrap.addEventListener('pointerup', onTap);
  col.appendChild(btnPair.wrap);

  // Live modifier list
  var list = document.createElement('div');
  list.style.cssText = [
    'flex:1;overflow-y:auto;',
    'font-family:' + T.fb + ';',
    'font-size:' + T.fsSmall + ';',
  ].join('');

  if (mods.length === 0) {
    var placeholder = document.createElement('div');
    placeholder.style.cssText = 'color:' + T.dimText + ';padding:4px 0;';
    placeholder.textContent = 'Nothing on ' + label.toLowerCase();
    list.appendChild(placeholder);
  } else {
    mods.forEach(function(m) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;padding:3px 0;';

      var nameSpan = document.createElement('span');
      var isExtra = wholeNames[m.name];
      if (isExtra) {
        nameSpan.style.color = T.gold;
        nameSpan.textContent = '\u2022 Xtra ' + m.name;
      } else {
        nameSpan.style.color = T.mint;
        nameSpan.textContent = '\u2022 ' + m.name;
      }
      row.appendChild(nameSpan);

      var price = m.half_price != null ? m.half_price : m.price;
      if (price > 0) {
        var priceSpan = document.createElement('span');
        priceSpan.style.color = T.gold;
        priceSpan.textContent = '$' + price.toFixed(2);
        row.appendChild(priceSpan);
      }

      list.appendChild(row);
    });
  }

  col.appendChild(list);
  return col;
}