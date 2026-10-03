// Bars 0-4: the cold open. Two quiet lines, then zypper's real failures slam
// in and glitch until the picture dies like an old CRT, then one line in the
// silence before the reveal.

import { SCENES, T } from '../timeline.js';
import { css, h, env, ep, E, prog, lerp, hash, noise1, clamp, decay } from '../ease.js';

// Real zypper failures, the ones this app exists to get past.
const ERRORS = [
  'System management is locked by the application with pid 38917 (zypper).',
  'Choose from above solutions by number or cancel [1/2/c/d/?] (c):',
  '…must not continue if enabled repositories fail to refresh.',
  "terminate called after throwing an instance of 'std::out_of_range'",
];
const ERR_Y = [372, 462, 552, 642];
const ERR_X = [-40, 60, -80, 30];

// Faded copies that fill the screen during the chaos bar.
const GHOSTS = Array.from({ length: 18 }, (_, i) => ({
  text: ERRORS[i % 4],
  x: hash(i, 11) * 1500 - 300,
  y: 150 + hash(i, 12) * 780,
  size: 16 + hash(i, 13) * 14,
  at: T.chaos + (i / 18) * (T.collapse - T.chaos),
}));

let root, line1, line2, errWrap, errs, ghosts, dot, better, scan;

export const span = SCENES.opening;

export function build(el) {
  root = el;
  const quiet = (text) =>
    h(`<div style="position:absolute;left:0;right:0;top:505px;text-align:center;font-family:var(--display);font-size:58px;font-weight:300;color:#e9eef2">${text}</div>`);
  line1 = quiet('Tumbleweed never stops rolling.');
  line2 = quiet('Thousands of packages. Always moving.');

  errWrap = h('<div style="position:absolute;inset:0;transform-origin:50% 50%"></div>');
  ghosts = GHOSTS.map((g) => {
    const e = h(`<div style="position:absolute;left:${g.x}px;top:${g.y}px;font-family:var(--mono);font-size:${g.size}px;color:#ff5a4a;white-space:nowrap;opacity:0">${g.text}</div>`);
    errWrap.append(e);
    return e;
  });
  errs = ERRORS.map((text, i) => {
    // Three copies: a red and a cyan one offset for the RGB split, and the
    // line itself on top; a fourth is a displaced slice.
    const e = h(`<div style="position:absolute;left:0;right:0;top:${ERR_Y[i]}px;text-align:center;font-family:var(--mono);font-size:31px;white-space:nowrap;opacity:0">
      <div class="r" style="position:absolute;left:0;right:0;color:#ff0040;mix-blend-mode:screen">${text}</div>
      <div class="c" style="position:absolute;left:0;right:0;color:#00e5ff;mix-blend-mode:screen">${text}</div>
      <div class="m" style="position:relative;color:#ff6b5e;text-shadow:0 0 18px rgba(255,70,50,.65)">${text}</div>
      <div class="s" style="position:absolute;left:0;right:0;top:0;color:#fff">${text}</div>
    </div>`);
    errWrap.append(e);
    return { e, r: e.querySelector('.r'), c: e.querySelector('.c'), m: e.querySelector('.m'), s: e.querySelector('.s') };
  });
  scan = h(`<div style="position:absolute;inset:0;opacity:0;background:repeating-linear-gradient(0deg,rgba(0,0,0,.45) 0 2px,transparent 2px 5px)"></div>`);
  dot = h(`<div style="position:absolute;left:960px;top:540px;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:#fff;box-shadow:0 0 30px 10px rgba(255,255,255,.8);opacity:0"></div>`);
  better = h(`<div style="position:absolute;left:0;right:0;top:512px;text-align:center;font-family:var(--display);font-size:46px;font-weight:300;letter-spacing:.08em;color:#e9eef2;opacity:0">There's a better way.</div>`);
  root.append(line1, line2, errWrap, scan, dot, better);
}

function quietLine(el, t, a, b) {
  const o = env(t, a, b, 0.7, 0.35, E.outCubic, E.inCubic);
  const p = prog(t, a, b);
  css(el, {
    opacity: String(o),
    filter: `blur(${(1 - ep(t, a, a + 0.9, E.outCubic)) * 14 + ep(t, b - 0.35, b, E.inCubic) * 10}px)`,
    'letter-spacing': `${lerp(0.2, 0.02, E.outCubic(p))}em`,
    transform: `scale(${lerp(1.0, 1.05, p)})`,
  });
}

export function update(t, fx) {
  // Slow push-in over the quiet bars.
  css(root, { transform: `scale(${lerp(1, 1.06, prog(t, 0, T.errors[0]))})` });

  quietLine(line1, t, T.line1, T.line2 - 0.05);
  quietLine(line2, t, T.line2, T.errors[0] - 0.02);

  // Errors: each slams in on its beat, and they all glitch harder as the
  // chaos bar builds. Glitch offsets change 24 times a second, like bad video.
  const q = Math.floor(t * 24);
  const chaos = ep(t, T.chaos, T.collapse, E.inQuad);
  errs.forEach((er, i) => {
    const t0 = T.errors[i];
    if (t < t0 || t > T.betterWay) { css(er.e, { opacity: '0' }); return; }
    const slam = ep(t, t0, t0 + 0.18, E.outExpo);
    const g = decay(t, t0, 0.22) * 0.9 + chaos * 1.2 + 0.08;
    const split = g * 12 * (0.5 + hash(q, i));
    const jx = noise1(t * 9, i) * chaos * 40 + (hash(q, i + 20) - 0.5) * g * 18;
    css(er.e, {
      opacity: '1',
      transform: `translate(${ERR_X[i] + jx}px, 0) scale(${lerp(1.4, 1, slam) * (1 + chaos * 0.06 * noise1(t * 13, i + 5))})`,
      filter: `blur(${(1 - slam) * 10}px)`,
    });
    css(er.r, { transform: `translateX(${-split}px)`, opacity: String(clamp(g)) });
    css(er.c, { transform: `translateX(${split}px)`, opacity: String(clamp(g)) });
    // A horizontal slice torn sideways.
    const band = hash(q, i + 40);
    const on = hash(q, i + 60) < 0.25 + chaos * 0.6;
    css(er.s, {
      opacity: on ? '0.9' : '0',
      'clip-path': `inset(${band * 70}% 0 ${Math.max(0, 100 - band * 70 - 25)}% 0)`,
      transform: `translateX(${(hash(q, i + 80) - 0.5) * 90 * g}px)`,
    });
  });

  ghosts.forEach((e, i) => {
    const g = GHOSTS[i];
    const vis = t >= g.at && t < T.collapse + 0.1;
    css(e, { opacity: vis ? String(0.25 + hash(q, i + 100) * 0.35) : '0', transform: `translateX(${(hash(q, i + 120) - 0.5) * 30}px)` });
  });

  // CRT power-off: squash to a line, then to a dot, then nothing.
  const squash = ep(t, T.collapse, T.collapse + 0.07, E.inExpo);
  const thin = ep(t, T.collapse + 0.07, T.collapse + 0.19, E.inExpo);
  const gone = t >= T.collapse + 0.19;
  css(errWrap, {
    transform: `scale(${lerp(1, 0.001, thin)}, ${lerp(1, 0.004, squash)})`,
    filter: `brightness(${1 + squash * 4})`,
    visibility: gone ? 'hidden' : 'visible',
  });
  css(scan, { opacity: String(t >= T.errors[0] && !gone ? 0.35 + chaos * 0.5 : 0) });
  css(dot, {
    opacity: String(env(t, T.collapse + 0.14, T.betterWay + 0.02, 0.03, 0.18)),
    transform: `scale(${lerp(1.6, 0.2, prog(t, T.collapse + 0.14, T.betterWay))})`,
  });

  // "There's a better way." in the silence, then pulled into the reveal.
  const bIn = ep(t, T.betterWay + 0.05, T.betterWay + 0.6, E.outCubic);
  const bOut = ep(t, T.reveal - 0.3, T.reveal, E.inExpo);
  css(better, {
    opacity: String(bIn * (1 - bOut)),
    filter: `blur(${(1 - bIn) * 10 + bOut * 12}px)`,
    transform: `scale(${lerp(1.04, 1, bIn) * lerp(1, 0.55, bOut)})`,
  });

  // The world under the errors turns faintly red as it falls apart.
  if (t < T.collapse + 0.1) {
    fx.dust = 0.45 * (1 - chaos);
    fx.dustCol = [200, 220, 235];
    fx.nebula = chaos * 0.55 + (t > T.errors[0] ? 0.08 : 0);
    fx.colA = [0.55, 0.04, 0.03];
    fx.colB = [0.35, 0.02, 0.12];
  }
}
