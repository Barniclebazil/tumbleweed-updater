// Bars 19-21: eight facts, one per beat, then an eighth of silence before the
// finale lands.

import { SCENES, T, bar } from '../timeline.js';
import { css, h, ep, E, lerp, prog } from '../ease.js';

// Each is true of the app: the check needs no password, one button runs
// both kinds of update, the helpers wait for PackageKit, a missing source
// no longer blocks the upgrade, the title-bar icon was measured at 14 px,
// and it is Python under the GPL.
const CARDS = [
  { big: '0', small: 'passwords to check for updates', bg: '#05070a', fg: '#fff', accent: '#a6e35f' },
  { big: '1', small: 'button to update everything', bg: '#73ba25', fg: '#0b1206', accent: '#0b1206' },
  { big: 'zypper + Flatpak', small: 'in one window', bg: '#05070a', fg: '#fff', accent: '#ffffff', size: 190 },
  { big: 'Waits', small: 'for PackageKit instead of failing', bg: '#f67400', fg: '#1a0c00', accent: '#1a0c00' },
  { big: 'Server down?', small: 'The update still runs.', bg: '#05070a', fg: '#fff', accent: '#ffb066', size: 200 },
  { big: '14 px', small: 'title-bar icon, measured pixel by pixel', bg: '#73ba25', fg: '#0b1206', accent: '#0b1206' },
  { big: '100%', small: 'Python. No compiled code.', bg: '#05070a', fg: '#fff', accent: '#a6e35f' },
  { big: 'GPL-3.0', small: 'Free software.', bg: '#f4f6f7', fg: '#05070a', accent: '#05070a' },
];

let root, cards;
export const span = SCENES.stats;

export function build(el) {
  root = el;
  cards = CARDS.map((c, i) => {
    const glow = c.bg === '#05070a' ? `radial-gradient(40% 45% at 50% 50%, ${c.accent}2e, transparent 70%),` : 'radial-gradient(50% 55% at 50% 50%, rgba(255,255,255,.22), transparent 75%),';
    const e = h(`<div style="position:absolute;inset:0;background:${glow}${c.bg};display:none">
      <div style="position:absolute;left:70px;top:60px;font-size:18px;font-weight:700;letter-spacing:.4em;color:${c.fg};opacity:.55">TUMBLEWEED UPDATER</div>
      <div style="position:absolute;right:70px;top:60px;font-family:var(--mono);font-size:18px;color:${c.fg};opacity:.55">${String(i + 1).padStart(2, '0')} / 08</div>
      <div class="inner" style="position:absolute;left:0;right:0;top:50%;text-align:center;transform-origin:50% 50%">
        <div style="font-family:var(--display);font-size:${c.size || 300}px;font-weight:800;letter-spacing:-.045em;line-height:1;color:${c.accent};white-space:nowrap">${c.big}</div>
        <div style="margin-top:30px;font-size:44px;font-weight:500;letter-spacing:-.01em;color:${c.fg}">${c.small}</div>
      </div>
    </div>`);
    root.append(e);
    return { e, inner: e.querySelector('.inner') };
  });
}

export function update(t, fx) {
  const idx = Math.floor((t - T.stats) / (bar(0, 1)));
  const silent = t >= T.dropout;
  cards.forEach((c, i) => {
    const on = i === idx && !silent && t >= T.stats;
    css(c.e, { display: on ? 'block' : 'none' });
    if (!on) return;
    const t0 = bar(19, i);
    const p = ep(t, t0, t0 + 0.16, E.outExpo);
    const drift = prog(t, t0, t0 + bar(0, 1));
    css(c.inner, {
      transform: `translateY(-50%) scale(${lerp(1.3, 1, p) * lerp(1, 0.96, drift)}) rotate(${lerp(i % 2 ? 3 : -3, 0, p)}deg)`,
      filter: `blur(${(1 - p) * 14}px)`,
      opacity: String(lerp(0.2, 1, p)),
    });
  });
  // Nothing from the background shows through the cards.
  fx.nebula = 0;
  fx.rays = 0;
  fx.flare = 0;
  fx.ghosts = 0;
  fx.dust = 0;
}
