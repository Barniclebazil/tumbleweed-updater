// Bars 16-19: snapshots. Pre/post pairs on a glowing timeline; the camera
// travels forward to now, then rewinds to the moment before the last update.

import { SCENES, T, CUTS } from '../timeline.js';
import { css, h, ep, E, prog, lerp, decay, hash } from '../ease.js';
import { textBlock, animateText } from './common.js';

// What snapper-zypp-plugin leaves behind: a pre and a post around each update.
const SNAPS = [
  [398, 'pre', '06/09/2026 09:14'], [399, 'post', '06/09/2026 09:21'],
  [402, 'pre', '12/09/2026 18:40'], [403, 'post', '12/09/2026 18:52'],
  [406, 'pre', '19/09/2026 08:03'], [407, 'post', '19/09/2026 08:11'],
  [412, 'pre', '26/09/2026 10:02'], [413, 'post', '26/09/2026 10:09'],
];
const X0 = 420;          // strip x of the first snapshot
const GAP_IN = 190;      // pre to post
const GAP_OUT = 330;     // one update to the next
const LINE_Y = 720;
const TARGET = 6;        // #412 pre, where the rewind lands

const xs = SNAPS.map((_, i) => X0 + Math.floor(i / 2) * (GAP_IN + GAP_OUT) + (i % 2) * GAP_IN);
const NOW_X = xs[xs.length - 1] + 300;

let root, tb, strip, cards, target, button, rew, scan;
export const span = SCENES.snapshots;
const IN = CUTS[3];
const OUT = SCENES.snapshots[1];

export function build(el) {
  root = el;
  tb = textBlock({
    eyebrow: 'Fearless',
    title: ['Every update comes with', 'a <em>time machine.</em>'],
    body: 'Btrfs snapshots before and after every update. Browse them, compare them, roll back to one.',
    x: 160, y: 120, width: 1600, align: 'center',
  });
  css(tb.el.querySelector('.body'), { 'max-width': '900px' });

  strip = h(`<div style="position:absolute;left:0;top:0;width:${NOW_X + 800}px;height:1080px">
    <div style="position:absolute;left:0;width:${NOW_X}px;top:${LINE_Y - 1.5}px;height:3px;
      background:linear-gradient(90deg,transparent,rgba(166,227,95,.9) 8%,rgba(166,227,95,.9) 92%,#fff);
      box-shadow:0 0 18px rgba(115,186,37,.9),0 0 60px rgba(115,186,37,.5)"></div>
    <div style="position:absolute;left:${NOW_X}px;top:${LINE_Y}px;width:26px;height:26px;margin:-13px;border-radius:50%;background:#fff;box-shadow:0 0 30px 8px rgba(166,227,95,.9)"></div>
    <div style="position:absolute;left:${NOW_X - 100}px;width:200px;top:${LINE_Y + 34}px;text-align:center;font-size:20px;font-weight:700;letter-spacing:.4em;padding-left:.4em;color:#a6e35f">NOW</div>
  </div>`);
  cards = SNAPS.map(([n, type, date], i) => {
    const up = i % 2 === 0;
    const c = h(`<div style="position:absolute;left:${xs[i]}px;top:${LINE_Y}px">
      <div class="dot" style="position:absolute;width:18px;height:18px;margin:-9px;border-radius:50%;background:${type === 'pre' ? '#a6e35f' : '#fff'};box-shadow:0 0 20px rgba(166,227,95,.9)"></div>
      <div class="stem" style="position:absolute;left:-1px;width:2px;${up ? 'bottom:12px' : 'top:12px'};height:44px;background:rgba(166,227,95,.5)"></div>
      <div class="card" style="position:absolute;left:-120px;width:240px;${up ? 'bottom:58px' : 'top:58px'};padding:14px 16px;border-radius:12px;
          background:rgba(24,30,28,.88);border:1px solid rgba(166,227,95,.28);font-family:var(--ui);color:#fcfcfc;
          box-shadow:0 20px 50px rgba(0,0,0,.5)">
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <span style="font-size:28px;font-weight:700">#${n}</span>
          <span style="font-size:16px;letter-spacing:.2em;text-transform:uppercase;color:${type === 'pre' ? '#a6e35f' : '#dfe6ea'}">${type}</span>
        </div>
        <div style="font-size:16px;opacity:.7;margin-top:4px">${date}</div>
        <div style="font-family:var(--mono);font-size:14px;opacity:.55;margin-top:2px">zypp(zypper)</div>
      </div>
    </div>`);
    strip.append(c);
    return c;
  });
  // Pre and post of one update joined by an arc.
  for (let i = 0; i < SNAPS.length; i += 2) {
    strip.append(h(`<div style="position:absolute;left:${xs[i]}px;top:${LINE_Y - 34}px;width:${GAP_IN}px;height:34px;border:2px solid rgba(166,227,95,.35);border-bottom:none;border-radius:40px 40px 0 0"></div>`));
  }
  target = cards[TARGET].querySelector('.card');
  button = h(`<div style="position:absolute;left:175px;top:-138px;width:300px;text-align:center;font-family:var(--ui);font-size:19px;padding:10px 0;border-radius:6px;
      background:#43302c;border:1px solid #e95420;color:#fcfcfc;box-shadow:0 0 30px rgba(233,84,32,.5);opacity:0">Set as default on next boot…</div>`);
  cards[TARGET].append(button);

  // The rewind: a big double-arrow and tape lines.
  rew = h(`<div style="position:absolute;left:0;right:0;top:880px;text-align:center;font-size:130px;font-weight:800;color:#fff;opacity:0;letter-spacing:-.12em">◀◀</div>`);
  scan = h(`<div style="position:absolute;inset:0;opacity:0;background:repeating-linear-gradient(0deg,rgba(255,255,255,.07) 0 2px,transparent 2px 7px)"></div>`);
  root.append(strip, tb.el, rew, scan);
}

export function update(t, fx) {
  // Scene in: zoom out of a blur; out: a hard cut to the stats.
  const pin = ep(t, IN - 0.05, IN + 0.65, E.outExpo);
  css(root, {
    transform: `scale(${lerp(0.78, 1, pin)})`,
    filter: `blur(${(1 - pin) * 22}px)`,
    opacity: String(Math.min(prog(t, IN - 0.05, IN + 0.18), 1 - prog(t, OUT - 0.08, OUT))),
  });
  animateText(tb, t, IN + 0.15);

  // Camera: centre of frame follows a point on the strip.
  const fwd = ep(t, IN, T.rewind, E.inOutCubic);
  const back = ep(t, T.rewind, T.rewindLand, E.inOutExpo);
  const startFocus = xs[1];
  const endFocus = NOW_X - 200;
  const focus = lerp(lerp(startFocus, endFocus, fwd), xs[TARGET], back) + (t > T.rewindLand ? (t - T.rewindLand) * 12 : 0);
  css(strip, { transform: `translateX(${960 - focus}px)` });

  // Rewind effects: speed lines, a colour split and the big symbol.
  const speed = Math.sin(Math.PI * back);
  const q = Math.floor(t * 30);
  css(strip, { filter: speed > 0.02 ? `blur(${speed * 6}px) drop-shadow(${speed * 14}px 0 0 rgba(255,0,60,.6)) drop-shadow(${-speed * 14}px 0 0 rgba(0,220,255,.6))` : 'none' });
  css(rew, { opacity: String(speed * 0.85), transform: `scale(${1 + speed * 0.1}) translateX(${(hash(q, 5) - 0.5) * speed * 20}px)` });
  css(tb.el, { opacity: String(1 - speed * 0.85) });   // the copy steps back while the symbol is up
  css(scan, { opacity: String(speed), transform: `translateY(${(q % 7) * 2}px)` });

  // Cards pop in as the camera reaches them.
  cards.forEach((c, i) => {
    const sx = xs[i] + 960 - focus;
    const seen = sx < 1920 + 100 ? 1 : 0;
    const pc = ep(t, IN + 0.2 + i * 0.08, IN + 0.9 + i * 0.08, E.outExpo) * seen;
    css(c, { opacity: String(Math.max(pc, t > IN + 1.5 ? 1 : 0)) });
  });

  // Landing: the pre snapshot lights up and offers to be the one you boot.
  const land = ep(t, T.rewindLand, T.rewindLand + 0.6, E.outBack);
  const lg = decay(t, T.rewindLand, 0.4);
  css(target, {
    transform: `scale(${lerp(1, 1.18, land)})`,
    'border-color': land > 0.1 ? '#a6e35f' : 'rgba(166,227,95,.28)',
    'box-shadow': `0 20px 50px rgba(0,0,0,.5), 0 0 ${land * 50 + lg * 60}px rgba(166,227,95,${0.35 * land + lg * 0.5})`,
  });
  const pb = ep(t, T.rewindLand + 0.35, T.rewindLand + 0.9, E.outExpo);
  css(button, { opacity: String(pb), transform: `translateX(${lerp(-24, 0, pb)}px)` });

  fx.ray = [960, LINE_Y];
  fx.rays = (0.2 + lg * 0.8 + speed * 0.4);
  fx.flare = 0.3 + speed * 1.2 + lg * 0.8;
  fx.ghosts = 0.2;
  fx.flareCol = [0.6, 0.95, 0.35];
  fx.nebula = 0.34 * pin;
  fx.colA = [0.02, 0.24, 0.2];
  fx.colB = [0.1, 0.3, 0.35];
  fx.dust = 0.35;
  fx.dustCol = [190, 240, 160];
}
