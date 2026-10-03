// Bars 10-13: the update list. The main window, rebuilt from the real
// screenshot, floats in perspective while its rows cascade in and the count
// rolls up to 36.

import { SCENES, T, CUTS } from '../timeline.js';
import { css, h, ep, E, prog, lerp, sceneMotion } from '../ease.js';
import { textBlock, animateText } from './common.js';

// The rows in screenshots/update-list.png.
const ROWS = [
  ['kernel-default', 'new · 7.2.4-1.1', 'x86_64'],
  ['python313-puremagic', 'new · 2.2.0-2.2', 'noarch'],
  ['python313-pypdf', 'new · 6.16.2-3.1', 'noarch'],
  ['cpupower', 'upgrade · 7.2.3-14.12 → 7.2.4-14.13', 'x86_64'],
  ['cpupower-bash-completion', 'upgrade · 7.2.3-14.12 → 7.2.4-14.13', 'noarch'],
  ['expat', 'upgrade · 2.8.2-1.1 → 2.8.4-1.1', 'x86_64'],
  ['libarchive13', 'upgrade · 3.8.7-1.4 → 3.8.9-1.1', 'x86_64'],
  ['libcpupower1', 'upgrade · 7.2.3-14.12 → 7.2.4-14.13', 'x86_64'],
  ['libexpat1', 'upgrade · 2.8.2-1.1 → 2.8.4-1.1', 'x86_64'],
  ['libexpat1-32bit', 'upgrade · 2.8.2-1.1 → 2.8.4-1.1', 'x86_64'],
  ['libldb2', 'upgrade · 4.24.5+git.481.dba78dbdea-1…', 'x86_64'],
  ['openSUSE-release', 'upgrade · 20260908-4291.1 → 20260909-…', 'x86_64'],
  ['openSUSE-release-ftp', 'upgrade · 20260908-4291.1 → 20260909-…', 'x86_64'],
  ['perl-Authen-SASL', 'upgrade · 2.200.0-1.3 → 2.210.0-1.1', 'noarch'],
  ['perl-LWP-MediaTypes', 'upgrade · 6.04-1.29 → 6.50.0-1.1', 'noarch'],
  ['perl-URI', 'upgrade · 5.360.0-1.1 → 5.370.0-1.1', 'noarch'],
];

let root, tb, win, headline, rows, shine, updBtn;
export const span = SCENES.list;
const [IN, OUT] = [CUTS[1], CUTS[2]];

export function build(el) {
  root = el;
  tb = textBlock({
    eyebrow: 'Total clarity',
    title: ['Every package.', 'Every version.', '<em>One glance.</em>'],
    body: 'System packages and Flatpaks, each with its version change and architecture, before anything is touched.',
    x: 1185, y: 290, width: 640,
  });

  const dots = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="#fcfcfc" stroke-width="1.3">';
  win = h(`<div class="win" style="left:175px;top:150px;transform-origin:50% 50%">
    <div class="titlebar">
      <div class="l">${dots}<circle cx="7" cy="7" r="5"/></svg>${dots}<circle cx="7" cy="7" r="5"/><circle cx="7" cy="7" r="1.2" fill="#fcfcfc"/></svg>${dots}<rect x="2" y="2" width="4" height="4"/><rect x="8" y="2" width="4" height="4"/><rect x="2" y="8" width="4" height="4"/><rect x="8" y="8" width="4" height="4"/></svg></div>
      Tumbleweed Updater
      <div class="r">${dots}<path d="M3 10h8"/></svg>${dots}<rect x="3" y="3" width="8" height="8"/></svg>${dots}<path d="M3 3l8 8M11 3l-8 8"/></svg></div>
    </div>
    <div class="menubar">Menu</div>
    <div class="content">
      <div class="headline">0 updates available</div>
      <div class="subline">Last checked just now · 231.0 MiB to download · uses 229.6 MiB more disk space</div>
      <div class="check"><span class="box on"></span>System updates</div>
      <div class="check dim"><span class="box"></span>Flatpak updates</div>
      <div class="tree">
        <div class="thead"><div>Package</div><div>Change</div><div>Details</div></div>
        <div class="rows">
          <div class="row group"><div class="pkg">⌄&nbsp;&nbsp;System updates: 36 packages</div><div></div><div></div></div>
          ${ROWS.map((r) => `<div class="row"><div class="pkg">${r[0]}</div><div>${r[1]}</div><div>${r[2]}</div></div>`).join('')}
        </div>
      </div>
      <div class="buttons"><span class="btn">Check now</span><span class="btn default">Update now…</span></div>
    </div>
    <div class="status"></div>
    <div class="shine" style="position:absolute;inset:0;pointer-events:none;background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,.10) 48%,rgba(255,255,255,.02) 52%,transparent 60%);background-size:300% 100%"></div>
  </div>`);
  headline = win.querySelector('.headline');
  rows = [...win.querySelectorAll('.row')];
  shine = win.querySelector('.shine');
  updBtn = win.querySelector('.btn.default');
  root.append(win, tb.el);
}

let lastCount = -1;
export function update(t, fx) {
  const m = sceneMotion(t, IN, OUT);
  css(root, { transform: `scale(${m.scale})`, filter: `blur(${m.blur}px)`, opacity: String(m.opacity) });
  animateText(tb, t, IN + 0.3);

  const p = prog(t, IN, OUT);
  css(win, {
    transform: `perspective(2400px) rotateY(${lerp(24, 9, E.outCubic(p))}deg) rotateX(${lerp(6, 2, p)}deg) scale(${lerp(1.08, 1.2, E.outCubic(p))}) translateY(${lerp(30, 0, E.outCubic(p))}px)`,
  });

  rows.forEach((r, i) => {
    const pr = ep(t, T.listRows + i * 0.045, T.listRows + i * 0.045 + 0.5, E.outExpo);
    css(r, { opacity: String(pr), transform: `translateX(${lerp(-40, 0, pr)}px)` });
  });

  const n = Math.round(36 * ep(t, T.listRows, T.listRows + 1.2, E.outCubic));
  if (n !== lastCount) {
    headline.textContent = `${n} update${n === 1 ? '' : 's'} available`;
    lastCount = n;
  }
  css(shine, { 'background-position': `${lerp(120, -20, ep(t, T.listRows + 1.3, T.listRows + 2.6, E.inOutCubic))}% 0` });
  const pulse = ep(t, T.listRows + 1.2, T.listRows + 1.8, E.outCubic);
  css(updBtn, { 'box-shadow': `0 0 ${pulse * 26}px rgba(233,84,32,${pulse * 0.7})`, 'border-color': pulse > 0.5 ? '#e95420' : '#7e4b3b' });

  fx.ray = [520, 250];
  fx.rays = 0.22 * m.opacity;
  fx.flare = 0.12 * m.opacity;
  fx.ghosts = 0.15 * m.opacity;
  fx.flareCol = [0.55, 0.85, 0.35];
  fx.nebula = 0.36 * m.opacity;
  fx.colA = [0.02, 0.2, 0.25];
  fx.colB = [0.15, 0.4, 0.06];
  fx.dust = 0.3;
  fx.dustCol = [170, 230, 200];
}
