// Bars 13-16: the embedded terminal. zypper's real summary scrolls in, the
// prompt waits, "y" is answered on the beat, and the install races past.

import { SCENES, T, CUTS, BEAT } from '../timeline.js';
import { css, h, ep, E, prog, lerp, sceneMotion } from '../ease.js';
import { textBlock, animateText } from './common.js';

const VISIBLE = 27;
const PROMPT = '<span class="bold">Continue? [y/n/v/...? shows all options] (y): </span>';

// [seconds after the cut, line]. The summary is the one in
// screenshots/terminal.png; the install lines follow zypper's own format.
function script() {
  const L = [];
  let at = 0.1;
  const add = (html, gap = 0.055) => { L.push([at, html]); at += gap; };
  add('Loading repository data...', 0.09);
  add('Reading installed packages...', 0.12);
  add('Computing distribution upgrade...', 0.2);
  add('');
  add('The following 3 NEW packages are going to be installed:');
  add('  kernel-default-7.2.4-1.1 python313-puremagic python313-pypdf');
  add('');
  add('The following 32 packages are going to be upgraded:');
  add('  cpupower cpupower-bash-completion expat libarchive13 libcpupower1');
  add('  libexpat1 libexpat1-32bit libldb2 openSUSE-release perl-Authen-SASL');
  add('  perl-LWP-MediaTypes perl-URI …');
  add('');
  add('<span class="purple">The following package requires a system reboot:</span>');
  add('  kernel-default-7.2.4-1.1');
  add('');
  add('<span class="green">32</span> packages to upgrade, <span class="green">3</span> new.');
  add('');
  add('Package download size:   231.0 MiB');
  add('');
  add('Package install size change:');
  add('              |     319.6 MiB  required by packages that will be installed');
  add('   229.6 MiB  |  -   89.9 MiB  released by packages that will be removed');
  add('');
  add('    <span class="teal">Note:</span> System reboot required.');
  add('');
  add('<span class="bold">Backend:  classic_rpmtrans</span>');
  const promptAt = at;
  L.push([promptAt, 'PROMPT']);

  // After the answer, the download and install race by.
  at = T.typedY - CUTS[2] + 0.12;
  const pkgs = ['kernel-default-7.2.4-1.1', 'cpupower-7.2.4-14.13', 'expat-2.8.4-1.1', 'libarchive13-3.8.9-1.1',
    'libcpupower1-7.2.4-14.13', 'libexpat1-2.8.4-1.1', 'libldb2-4.24.5', 'openSUSE-release-20260909-0',
    'perl-Authen-SASL-2.210.0-1.1', 'perl-URI-5.370.0-1.1', 'python313-pypdf-6.16.2-3.1'];
  pkgs.forEach((p, i) => {
    add(`Retrieving: ${p}.${i % 3 ? 'noarch' : 'x86_64'}.rpm ${'.'.repeat(Math.max(3, 38 - p.length))}<span class="green">[done]</span>`, 0.045);
  });
  add(`Checking for file conflicts: ${'.'.repeat(33)}<span class="green">[done]</span>`, 0.08);
  pkgs.forEach((p, i) => {
    add(`(${String(i + 1).padStart(2)}/35) Installing: ${p} ${'.'.repeat(Math.max(3, 34 - p.length))}<span class="green">[done]</span>`, 0.05);
  });
  return { lines: L, promptAt };
}

let root, tb, term, label, slots;
const { lines: LINES, promptAt: PROMPT_AT } = script();
export const span = SCENES.terminal;
const [IN, OUT] = [CUTS[2], CUTS[3]];

export function build(el) {
  root = el;
  tb = textBlock({
    eyebrow: 'Nothing hidden',
    title: ['The <em>real</em> zypper.', 'Your answers.'],
    body: 'A real terminal, built in. Answer every prompt exactly as if you had typed <code>sudo zypper dup</code> yourself.',
    x: 150, y: 330, width: 700,
  });
  term = h(`<div style="position:absolute;left:905px;top:150px;width:900px;transform-origin:30% 50%">
    <div class="label" style="font-family:var(--ui);font-size:20px;color:#fcfcfc;margin:0 0 12px 4px">Terminal (if the update asks a question, type your answer here):</div>
    <div class="term" style="position:relative;height:720px">${Array.from({ length: VISIBLE }, () => '<div class="ln"></div>').join('')}</div>
  </div>`);
  label = term.querySelector('.label');
  slots = [...term.querySelectorAll('.ln')];
  root.append(tb.el, term);
}

let lastKey = '';
export function update(t, fx) {
  const m = sceneMotion(t, IN, OUT);
  css(root, { transform: `scale(${m.scale})`, filter: `blur(${m.blur}px)`, opacity: String(m.opacity) });
  animateText(tb, t, IN + 0.15);

  const p = prog(t, IN, OUT);
  css(term, {
    transform: `perspective(2400px) rotateY(${lerp(-22, -10, E.outCubic(p))}deg) rotateX(${lerp(5, 2, p)}deg) scale(${lerp(1.1, 1.0, E.outCubic(p))})`,
  });

  // Which lines have been printed by now; the terminal shows the last few.
  const lt = t - IN;
  const shown = LINES.filter(([at]) => at <= lt).map(([, html]) => html);
  const answered = t >= T.typedY;
  const blinkOn = Math.floor((t - IN - PROMPT_AT) / (BEAT / 2)) % 2 === 0;
  const out = shown.map((html) => {
    if (html !== 'PROMPT') return html;
    return PROMPT + (answered ? 'y' : '') + (answered || blinkOn ? '<span class="cursor"></span>' : '');
  });
  // Only the last line with the cursor keeps it.
  const key = `${out.length}|${answered}|${blinkOn}`;
  if (key !== lastKey) {
    const vis = out.slice(-VISIBLE);
    for (let i = 0; i < VISIBLE; i++) {
      let html = vis[i] ?? '';
      if (i !== vis.length - 1) html = html.replace('<span class="cursor"></span>', '');
      else if (answered && !html.includes('cursor')) html += '<span class="cursor"></span>';
      slots[i].innerHTML = html;
    }
    lastKey = key;
  }
  const pl = ep(t, IN + 0.1, IN + 0.8, E.outCubic);
  css(label, { opacity: String(pl) });

  const press = Math.exp(-Math.max(0, t - T.typedY) / 0.25) * (answered ? 1 : 0);
  fx.ray = [1350, 880];
  fx.rays = (0.18 + press * 0.7) * m.opacity;
  fx.flare = (0.1 + press * 0.9) * m.opacity;
  fx.ghosts = 0.12 * m.opacity;
  fx.flareCol = [1.0, 0.45, 0.15];
  fx.nebula = 0.3 * m.opacity;
  fx.colA = [0.25, 0.08, 0.03];
  fx.colB = [0.05, 0.22, 0.2];
  fx.dust = 0.25;
  fx.dustCol = [240, 200, 170];
}
