// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Login Scene  (Vz2.0)
//  Gate layer — split layout, store branding + numpad
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

import { defineScene, SceneManager } from '../scene-manager.js';
import { T }                          from '../tokens.js';
import {
  buildPillButton,
  buildSectionLabel,
  buildDivider,
  hexToRgba,
} from '../theme-manager.js';

// Inline helper — darken a hex color by pct (0–1)
function darkenHex(hex, pct) {
  hex = hex.replace('#', '');
  if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
  var r = Math.max(0, Math.round(parseInt(hex.slice(0,2),16) * (1-pct)));
  var g = Math.max(0, Math.round(parseInt(hex.slice(2,4),16) * (1-pct)));
  var b = Math.max(0, Math.round(parseInt(hex.slice(4,6),16) * (1-pct)));
  return '#' + [r,g,b].map(function(v){ return v.toString(16).padStart(2,'0'); }).join('');
}
import { buildNumpad } from '../numpad.js';

// ── Constants ─────────────────────────────────────
const PIN_LENGTH = 4;

// ── Clock ─────────────────────────────────────────
function _startClock(timeEl, dateEl, dayEl) {
  function _tick() {
    var now  = new Date();
    var h    = now.getHours() % 12 || 12;
    var m    = String(now.getMinutes()).padStart(2, '0');
    var ampm = now.getHours() >= 12 ? 'pm' : 'am';
    var day  = now.toLocaleDateString([], { weekday: 'long' });
    var date = now.toLocaleDateString([], { month: 'long', day: 'numeric', year: 'numeric' });

    if (timeEl) timeEl.textContent = String(h).padStart(2, '0') + ':' + m;
    if (dateEl) dateEl.textContent = date;
    if (dayEl)  dayEl.textContent  = day;

    // Update am/pm suffix separately so it can be styled smaller
    var suffix = timeEl ? timeEl.parentElement.querySelector('.login-ampm') : null;
    if (suffix) suffix.textContent = ampm;
  }
  _tick();
  return setInterval(_tick, 1000);
}

// ── Auth ──────────────────────────────────────────
async function _attemptLogin(pin, onSuccess, onFail) {
  try {
    console.log('[login] attempting auth...');
    var res = await fetch('/api/v1/auth/verify-pin', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ pin: pin }),
    });
    console.log('[login] response status:', res.status);
    if (res.ok) {
      var data = await res.json();
      if (data.valid) {
        onSuccess(data);
      } else {
        onFail();
      }
    } else {
      onFail();
    }
  } catch (e) {
    console.error('[login] Auth error:', e);
    onFail();
  }
}

// ── Scene definition ──────────────────────────────
defineScene({
  name: 'login',

  state: {
    pin:    [],
    locked: false,
  },

  render: function(container, params, state) {

    // ── Root layout ────────────────────────────────
    var root = document.createElement('div');
    root.style.cssText = [
      'position:absolute;inset:0;',
      'display:flex;',
      'background:' + T.bg + ';',
      'font-family:' + T.fb + ';',
    ].join('');
    container.appendChild(root);

    // ── Left panel — store branding ────────────────
    var leftWrap = document.createElement('div');
    leftWrap.style.cssText = [
      'width:42%;',
      'border-right:1px solid ' + T.border + ';',
      'display:flex;flex-direction:column;',
      'padding:56px 60px 40px;',
      'position:relative;',
      'background:linear-gradient(160deg,' + T.bg + ' 0%,' + hexToRgba(T.well, 0.6) + ' 100%);',
    ].join('');
    root.appendChild(leftWrap);

    // Logo slot
    var logoSlot = document.createElement('div');
    logoSlot.style.cssText = [
      'width:100%;height:140px;',
      'border:1px solid ' + hexToRgba(T.storePrimary || T.green, 0.6) + ';',
      'display:flex;align-items:center;justify-content:center;',
      'margin-bottom:20px;',
      'background:' + hexToRgba(T.storePrimary || T.green, 0.08) + ';',
      'position:relative;',
      'font-family:' + T.fb + ';',
      'font-size:' + T.fsB3 + ';',
      'color:' + hexToRgba(T.storePrimary || T.green, 0.5) + ';',
      'letter-spacing:0.15em;',
      'flex-shrink:0;',
    ].join('');

    if (T.storeLogoUrl) {
      var img = document.createElement('img');
      img.src = T.storeLogoUrl;
      img.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain;';
      logoSlot.appendChild(img);
    } else {
      logoSlot.textContent = 'LOGO';
    }
    leftWrap.appendChild(logoSlot);

    // Store name
    var storeName = document.createElement('div');
    storeName.textContent  = T.storeName || 'Store Name';
    storeName.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-size:56px;',
      'font-weight:' + T.fwBold + ';',
      'color:' + T.text + ';',
      'letter-spacing:0.06em;',
      'line-height:1.1;',
      'margin-bottom:24px;',
      'text-align:center;',
    ].join('');
    leftWrap.appendChild(storeName);

    // Divider
    leftWrap.appendChild(buildDivider('0 0 20px'));

    // Clock block
    var clockBlock = document.createElement('div');
    clockBlock.style.cssText = 'flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;';
    leftWrap.appendChild(clockBlock);

    var timeRow = document.createElement('div');
    timeRow.style.cssText = 'display:flex;align-items:baseline;gap:6px;';
    clockBlock.appendChild(timeRow);

    var timeEl = document.createElement('span');
    timeEl.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-style:italic;',
      'font-size:104px;',
      'font-weight:' + T.fwBold + ';',
      'color:' + T.green + ';',
      'line-height:1;',
      'text-shadow:0 0 28px ' + hexToRgba(T.green, 0.4) + ';',
    ].join('');
    timeRow.appendChild(timeEl);

    var ampmEl = document.createElement('span');
    ampmEl.className = 'login-ampm';
    ampmEl.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-style:italic;',
      'font-size:40px;',
      'color:' + T.green + ';',
      'opacity:0.65;',
    ].join('');
    timeRow.appendChild(ampmEl);

    var dayEl = document.createElement('div');
    dayEl.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-style:italic;',
      'font-size:28px;',
      'color:' + T.text + ';',
      'letter-spacing:0.06em;',
      'margin-top:6px;',
      'opacity:0.75;',
    ].join('');
    clockBlock.appendChild(dayEl);

    var dateEl = document.createElement('div');
    dateEl.style.cssText = [
      'font-family:' + T.fh + ';',
      'font-style:italic;',
      'font-size:28px;',
      'color:' + T.green + ';',
      'letter-spacing:0.06em;',
      'margin-top:2px;',
      'opacity:0.65;',
    ].join('');
    clockBlock.appendChild(dateEl);

    // Bottom buttons
    var btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;flex-direction:column;gap:8px;margin-top:20px;';
    leftWrap.appendChild(btnRow);

    var clockBtn = buildPillButton({
      label:   'Clock In / Out',
      color:   T.green,
      darkBg:  T.greenDk,
      onClick: function() {
        if (state.pin.length === PIN_LENGTH) {
          // PIN already entered — auth and always show timeclock (clock in OR out)
          if (state.locked) return;
          state.locked = true;
          _attemptLogin(
            state.pin.join(''),
            function(data) { state.locked = false; _showTimeclock(data); },
            function()     { state.locked = false; numpad.setError('INVALID PIN'); }
          );
        } else {
          // No PIN yet — show overlay prompting for PIN entry
          _showTimeclock(null);
        }
      },
    });
    btnRow.appendChild(clockBtn);

    var configBtn = buildPillButton({
      label:   'Configuration',
      color:   T.border,
      darkBg:  T.well,
      onClick: function() {
        SceneManager.mountWorking('settings', { tab: 'TERMINAL' });
        SceneManager.closeGate('login');
      },
    });
    btnRow.appendChild(configBtn);

    // Version stamp — bottom right of full screen
    var version = document.createElement('div');
    version.textContent  = 'KINDpos/lite_Vz1.5';
    version.style.cssText = [
      'position:absolute;bottom:16px;right:24px;',
      'font-family:' + T.fb + ';',
      'font-size:' + T.fsB2 + ';',
      'color:' + T.text + ';',
      'letter-spacing:0.12em;',
      'opacity:0.6;',
      'z-index:1;',
    ].join('');
    root.appendChild(version);

    // ── Right panel — PIN entry ────────────────────
    var rightWrap = document.createElement('div');
    rightWrap.style.cssText = [
      'flex:1;',
      'position:relative;',
      'display:flex;flex-direction:column;',
      'align-items:center;justify-content:center;',
      'padding:48px 72px;',
      'gap:36px;',
    ].join('');
    root.appendChild(rightWrap);

    // ── Timeclock overlay — slides over left panel ──────
    function _showTimeclock(emp) {
      var overlay = document.createElement('div');
      overlay.style.cssText = [
        'position:absolute;inset:0;',
        'background:' + T.card + ';',
        'border-right:1px solid ' + T.green + ';',
        'display:flex;flex-direction:column;',
        'transform:translateX(-100%);',
        'transition:transform 0.25s ease;',
        'z-index:10;',
      ].join('');
      leftWrap.appendChild(overlay);
      requestAnimationFrame(function() {
        requestAnimationFrame(function() {
          overlay.style.transform = 'translateX(0)';
        });
      });

      function _closeOverlay() {
        overlay.style.transform = 'translateX(-100%)';
        setTimeout(function() { overlay.remove(); }, 260);
      }

      function _buildContent(empData) {
        overlay.innerHTML = '';
        var empId   = empData ? (empData.employee_id || empData.id || '') : '';
        var empName = empData ? (empData.name || 'Team Member') : '';
        var roles   = empData ? (empData.roles || ['server']) : [];

        // Header
        var hdr = document.createElement('div');
        hdr.style.cssText = 'background:' + T.green + ';height:40px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 20px;';
        var hdrL = document.createElement('span');
        hdrL.textContent = 'TIMECLOCK';
        hdrL.style.cssText = 'font-family:' + T.fb + ';font-size:12px;font-weight:700;letter-spacing:3px;color:' + T.well + ';';
        var hdrR = document.createElement('span');
        hdrR.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.well + ';opacity:0.7;cursor:pointer;';
        hdrR.textContent = '✕';
        hdrR.addEventListener('pointerup', _closeOverlay);
        hdr.appendChild(hdrL); hdr.appendChild(hdrR);
        overlay.appendChild(hdr);

        if (!empData) {
          // No emp yet — prompt to enter PIN
          var msg = document.createElement('div');
          msg.style.cssText = 'flex:1;display:flex;align-items:center;justify-content:center;font-family:' + T.fb + ';font-size:11px;letter-spacing:2px;color:' + T.border + ';text-align:center;padding:20px;';
          msg.textContent = 'ENTER YOUR PIN ON THE RIGHT TO CONTINUE';
          overlay.appendChild(msg);
          return;
        }

        // Body
        var body = document.createElement('div');
        body.style.cssText = 'flex:1;display:flex;flex-direction:column;padding:20px;gap:14px;overflow:hidden;';
        overlay.appendChild(body);

        var greet = document.createElement('div');
        greet.textContent = _greetingText() + ', ' + empName.split(' ')[0] + '.';
        greet.style.cssText = 'font-family:' + T.fh + ';font-size:26px;font-weight:800;color:' + T.text + ';flex-shrink:0;';
        body.appendChild(greet);

        var sub = document.createElement('div');
        sub.textContent = 'Select a role to clock in';
        sub.style.cssText = 'font-family:' + T.fb + ';font-size:10px;letter-spacing:2px;color:' + T.border + ';text-transform:uppercase;flex-shrink:0;';
        body.appendChild(sub);

        // Role buttons
        var roleGrid = document.createElement('div');
        roleGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;align-content:center;flex:1;';
        body.appendChild(roleGrid);

        var selectedRole = null;
        var roleBtns = [];
        roles.forEach(function(role) {
          var rc = (T.roles && T.roles[role]) || T.elec;
          var rd = darkenHex(rc, 0.35);
          var btn = buildPillButton({
            label:    role.toUpperCase(),
            color:    hexToRgba(rc, 0.15),
            darkBg:   hexToRgba(rc, 0.08),
            fontSize: T.fsB3,
            onClick:  (function(r, rcc, rdd) { return function() {
              selectedRole = r;
              roleBtns.forEach(function(rb) {
                var sel = rb._role === r;
                rb.style.background = sel ? rb._rc : hexToRgba(rb._rc, 0.15);
                rb.style.color      = sel ? T.well  : rb._rc;
                rb.style.boxShadow  = sel ? '0 6px 0 ' + rb._rd : '0 6px 0 ' + hexToRgba(rb._rc, 0.08);
              });
              clockInBtn.style.opacity       = '1';
              clockInBtn.style.pointerEvents = 'auto';
            }; })(role, rc, rd),
          });
          btn.style.color = rc; btn.style.boxShadow = '0 6px 0 ' + hexToRgba(rc, 0.08);
          btn._role = role; btn._rc = rc; btn._rd = rd;
          roleBtns.push(btn);
          roleGrid.appendChild(btn);
        });

        // Hours card
        var hrsWrap = document.createElement('div');
        hrsWrap.style.cssText = 'flex-shrink:0;display:flex;align-items:baseline;gap:8px;padding:10px 14px;background:' + T.well + ';border-radius:8px;border-left:3px solid ' + T.gold + ';';
        var hrsVal = document.createElement('span');
        hrsVal.textContent = '–';
        hrsVal.style.cssText = 'font-family:' + T.fh + ';font-size:28px;font-weight:800;color:' + T.gold + ';';
        var hrsLbl = document.createElement('span');
        hrsLbl.textContent = 'hours this week';
        hrsLbl.style.cssText = 'font-family:' + T.fb + ';font-size:10px;color:' + T.border + ';';
        hrsWrap.appendChild(hrsVal); hrsWrap.appendChild(hrsLbl);
        body.appendChild(hrsWrap);

        // Action buttons
        var clockInBtn = buildPillButton({ label: 'CLOCK IN', color: T.greenWarm, darkBg: T.greenWarmDk, fontSize: T.fsB3 });
        clockInBtn.style.width = '100%'; clockInBtn.style.opacity = '0.35'; clockInBtn.style.pointerEvents = 'none';
        body.appendChild(clockInBtn);

        var clockOutBtn = buildPillButton({ label: 'CLOCK OUT', color: T.verm, darkBg: T.vermDk, fontSize: T.fsB3 });
        clockOutBtn.style.width = '100%'; clockOutBtn.style.display = 'none';
        body.appendChild(clockOutBtn);

        var cancelBtn = buildPillButton({ label: 'CANCEL', color: T.border, darkBg: T.well, fontSize: T.fsB3 });
        cancelBtn.style.width = '100%';
        cancelBtn.addEventListener('pointerup', _closeOverlay);
        body.appendChild(cancelBtn);

        // Clocked-in check
        fetch('/api/v1/servers/clocked-in').then(function(r) { return r.json(); }).then(function(d) {
          var match = (d.staff || []).find(function(s) { return s.employee_id === empId; });
          if (match) {
            sub.textContent = 'You are currently clocked in';
            greet.style.color = T.green;
            roleGrid.style.display = 'none';
            clockInBtn.style.display = 'none';
            clockOutBtn.style.display = '';
          }
        }).catch(function() {});

        // Hours fetch
        var today = new Date();
        var ds = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');
        fetch('/api/v1/reports/labor-summary?date=' + ds + '&server_id=' + encodeURIComponent(empId))
          .then(function(r){return r.json();})
          .then(function(d){ hrsVal.textContent = (d.weekly_hours||d.total_hours||0).toFixed(2)+'h'; })
          .catch(function(){ hrsVal.textContent = '0.00h'; });

        // Clock In action
        clockInBtn.addEventListener('pointerup', function() {
          if (!selectedRole) return;
          clockInBtn.style.opacity = '0.35'; clockInBtn.style.pointerEvents = 'none';
          fetch('/api/v1/servers/clock-in', { method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ employee_id: empId, employee_name: empName, role: selectedRole }),
          }).then(function(r) {
            if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail||'Failed'); });
            return r.json();
          }).then(function() {
            showToast(empName + ' clocked in as ' + selectedRole.toUpperCase(), { bg: T.greenWarm, duration: 3000 });
            _closeOverlay();
          }).catch(function(e) {
            showToast(e.message||'Clock-in failed', { bg: T.verm, duration: 3000 });
            clockInBtn.style.opacity = '1'; clockInBtn.style.pointerEvents = 'auto';
          });
        });

        // Clock Out action
        clockOutBtn.addEventListener('pointerup', function() {
          clockOutBtn.style.opacity = '0.35'; clockOutBtn.style.pointerEvents = 'none';
          fetch('/api/v1/servers/clock-out', { method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ employee_id: empId, employee_name: empName }),
          }).then(function(r) {
            if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail||'Failed'); });
            return r.json();
          }).then(function() {
            showToast(empName + ' clocked out', { bg: T.greenWarm, duration: 3000 });
            _closeOverlay();
          }).catch(function(e) {
            showToast(e.message||'Clock-out failed', { bg: T.verm, duration: 3000 });
            clockOutBtn.style.opacity = '1'; clockOutBtn.style.pointerEvents = 'auto';
          });
        });
      }

      _buildContent(emp);
    }

    function _greetingText() {
      var h = new Date().getHours();
      if (h < 12) return 'Good Morning';
      if (h < 17) return 'Good Afternoon';
      return 'Good Evening';
    }

    // Shared auth → routes to landing or shows timeclock overlay
    function _doLogin(pin) {
      if (state.locked) return;
      state.locked = true;
      _attemptLogin(
        pin,
        function onSuccess(data) {
          var empId = data.employee_id || data.id || '';
          fetch('/api/v1/servers/clocked-in')
            .then(function(r) { return r.json(); })
            .then(function(clockData) {
              var isClockedIn = (clockData.staff || []).some(function(s) { return s.employee_id === empId; });
              if (!isClockedIn) {
                state.locked = false;
                _showTimeclock(data);
                return;
              }
              SceneManager.closeGate('login');
              var role = (data.roles || []).indexOf('manager') !== -1 ? 'manager' : 'server';
              if (role === 'manager') {
                SceneManager.mountWorking('manager-landing', { staff: data });
              } else {
                SceneManager.mountWorking('server-landing', { staff: data });
              }
            })
            .catch(function() {
              state.locked = false;
              SceneManager.closeGate('login');
              var role = (data.roles || []).indexOf('manager') !== -1 ? 'manager' : 'server';
              SceneManager.mountWorking(role === 'manager' ? 'manager-landing' : 'server-landing', { staff: data });
            });
        },
        function onFail() {
          state.locked = false;
          numpad.setError('INVALID PIN');
        }
      );
    }

    // Numpad — display + chassis built together
    var numpad = buildNumpad({
      masked:      true,
      maxDigits:   PIN_LENGTH,
      submitLabel: '>>>',
      canSubmit:   function(p) { return p.length === PIN_LENGTH; },
      onSubmit:    function(pin) { _doLogin(pin); },
      onChange:    function(p)   { state.pin = p.split(''); },
    });
    rightWrap.appendChild(numpad);

    // Terminal ID — bottom of right panel, readable
    var termId = document.createElement('div');
    termId.textContent  = 'T-001';
    termId.style.cssText = [
      'position:absolute;bottom:16px;left:24px;',
      'font-family:' + T.fb + ';',
      'font-size:' + T.fsB2 + ';',
      'color:' + T.green + ';',
      'letter-spacing:0.2em;',
      'text-transform:uppercase;',
      'opacity:0.6;',
    ].join('');
    rightWrap.appendChild(termId);

    // ── Start clock ────────────────────────────────
    var clockInterval = _startClock(timeEl, dateEl, dayEl);

    // ── Cleanup ────────────────────────────────────
    return function cleanup() {
      clearInterval(clockInterval);
    };
  },
});