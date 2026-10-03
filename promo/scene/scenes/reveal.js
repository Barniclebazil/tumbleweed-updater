// Bars 4-7: the reveal. The mark draws itself in green light on the first
// hit, fills, lifts, and the wordmark and tagline arrive under it.

import { SCENES, T, CUTS } from '../timeline.js';
import { css, h, ep, E, prog, lerp, decay } from '../ease.js';
import { LOGO_VIEWBOX } from './common.js';

let root, logoBox, svg, strokePath, fillPath, sweep, tip, len;
let ring, intro, wmWrap, wm, wmSweep, tag1, tag2;

export const span = SCENES.reveal;
const OUT = CUTS[0];

// Where the logo sits: big and central, then lifted into the lock-up.
const BIG = { cy: 500, w: 640 };
const LOCK = { cy: 360, w: 400 };

export function build(el, shared) {
  root = el;
  logoBox = h(`<div style="position:absolute;left:${960 - BIG.w / 2}px;top:${BIG.cy - BIG.w / 4}px;width:${BIG.w}px;height:${BIG.w / 2}px;transform-origin:50% 50%">
    <svg viewBox="${LOGO_VIEWBOX}" style="width:100%;height:100%;overflow:visible" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="rvFill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#c9f79a"/><stop offset=".45" stop-color="#8fd13f"/><stop offset="1" stop-color="#4f9419"/>
        </linearGradient>
        <linearGradient id="rvSweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
        </linearGradient>
        <clipPath id="rvClip"><path transform="${shared.logoTransform}" d="${shared.logoPath}"/></clipPath>
      </defs>
      <g transform="${shared.logoTransform}">
        <path class="fill" d="${shared.logoPath}" fill="url(#rvFill)" opacity="0"/>
        <path class="stroke" d="${shared.logoPath}" fill="none" stroke="#d8ffb0" stroke-width="0.85" stroke-linejoin="round" stroke-linecap="round"/>
        <circle class="tip" r="1.5" fill="#fff"/>
      </g>
      <g clip-path="url(#rvClip)"><rect class="sweep" x="-60" y="20" width="36" height="90" fill="url(#rvSweep)"/></g>
    </svg>
  </div>`);
  svg = logoBox.querySelector('svg');
  strokePath = svg.querySelector('.stroke');
  fillPath = svg.querySelector('.fill');
  sweep = svg.querySelector('.sweep');
  tip = svg.querySelector('.tip');

  ring = h(`<div style="position:absolute;left:960px;top:${BIG.cy}px;width:240px;height:240px;margin:-120px 0 0 -120px;border-radius:50%;border:3px solid rgba(214,255,170,.95);box-shadow:0 0 40px rgba(166,227,95,.8),inset 0 0 40px rgba(166,227,95,.5);opacity:0"></div>`);

  intro = h(`<div style="position:absolute;left:0;right:0;top:522px;text-align:center;font-size:22px;font-weight:600;letter-spacing:.6em;padding-left:.6em;color:#a6e35f;opacity:0">INTRODUCING</div>`);

  // The wordmark twice: the metal fill, and a highlight that sweeps across.
  wmWrap = h(`<div style="position:absolute;left:0;right:0;top:562px;text-align:center"></div>`);
  const wmStyle = 'display:inline-block;font-family:var(--display);font-size:104px;font-weight:800;line-height:1.1;white-space:nowrap;-webkit-background-clip:text;background-clip:text;color:transparent';
  wm = h(`<div style="${wmStyle};background-image:linear-gradient(180deg,#ffffff 20%,#dfe6ea 55%,#8f9ba4 100%)">TUMBLEWEED UPDATER</div>`);
  wmSweep = h(`<div style="${wmStyle};position:absolute;left:0;right:0;background-image:linear-gradient(100deg,transparent 42%,rgba(255,255,255,.95) 50%,transparent 58%);background-size:300% 100%;filter:drop-shadow(0 0 10px rgba(200,255,150,.6))">TUMBLEWEED UPDATER</div>`);
  wmWrap.append(wm, wmSweep);

  const tagStyle = 'position:absolute;top:718px;font-family:var(--display);font-size:40px;font-weight:300;letter-spacing:.04em;white-space:nowrap;opacity:0';
  tag1 = h(`<div style="${tagStyle};right:968px;color:#dbe3e8">Staying current.</div>`);
  tag2 = h(`<div style="${tagStyle};left:968px;color:#a6e35f;font-weight:500">Perfected.</div>`);

  root.append(ring, logoBox, intro, wmWrap, tag1, tag2);
  len = strokePath.getTotalLength();
  strokePath.setAttribute('stroke-dasharray', `${len} ${len}`);
}

export function update(t, fx) {
  const out = ep(t, OUT - 0.3, OUT + 0.12, E.inExpo);
  css(root, {
    transform: `scale(${lerp(1, 1.7, out)})`,
    filter: `blur(${out * 34}px)`,
    opacity: String(1 - prog(t, OUT - 0.06, OUT + 0.12)),
  });

  // Draw the outline, with a bright point riding the tip, then fill it.
  const draw = ep(t, T.reveal, T.reveal + 1.5, E.inOutCubic);
  strokePath.setAttribute('stroke-dashoffset', String(len * (1 - draw)));
  const pt = strokePath.getPointAtLength(len * draw);
  tip.setAttribute('cx', pt.x);
  tip.setAttribute('cy', pt.y);
  tip.setAttribute('opacity', String(draw > 0 && draw < 1 ? 1 : 0));
  const fill = ep(t, T.reveal + 1.05, T.reveal + 1.75, E.outCubic);
  fillPath.setAttribute('opacity', String(fill));
  strokePath.setAttribute('opacity', String(1 - fill * 0.85));
  sweep.setAttribute('x', String(lerp(-60, 150, ep(t, T.wordmark + 0.1, T.wordmark + 1.0, E.inOutCubic))));

  // Lift into the lock-up on the wordmark's bar.
  const lift = ep(t, T.wordmark - 0.1, T.wordmark + 0.9, E.inOutExpo);
  const cy = lerp(BIG.cy, LOCK.cy, lift);
  const sc = lerp(1, LOCK.w / BIG.w, lift) * lerp(0.9, 1, ep(t, T.reveal, T.reveal + 2.5, E.outCubic));
  const glow = 1 + decay(t, T.reveal, 0.6) * 2;
  css(logoBox, {
    transform: `translateY(${cy - BIG.cy}px) scale(${sc})`,
    filter: `drop-shadow(0 0 ${6 * glow}px rgba(190,245,130,.9)) drop-shadow(0 0 ${30 * glow}px rgba(115,186,37,.65))`,
  });

  const rp = prog(t, T.reveal, T.reveal + 1.1);
  css(ring, {
    opacity: String(rp > 0 && rp < 1 ? (1 - rp) * 0.9 : 0),
    transform: `scale(${lerp(0.2, 9, E.outCubic(rp))})`,
  });

  const pi = ep(t, T.wordmark - 0.25, T.wordmark + 0.8, E.outExpo);
  css(intro, { opacity: String(pi), 'letter-spacing': `${lerp(1.2, 0.6, pi)}em`, filter: `blur(${(1 - pi) * 8}px)` });

  // Wordmark: tracks in from wide spacing; padding-left keeps it centred,
  // since letter-spacing also adds space after the last letter.
  const pw = ep(t, T.wordmark, T.wordmark + 1.6, E.outExpo);
  const ls = lerp(0.55, 0.05, pw);
  for (const e of [wm, wmSweep]) css(e, { 'letter-spacing': `${ls}em`, 'padding-left': `${ls}em` });
  css(wmWrap, { opacity: String(ep(t, T.wordmark, T.wordmark + 0.5, E.outCubic)), filter: `blur(${(1 - pw) * 14}px)` });
  css(wmSweep, { 'background-position': `${lerp(110, -10, ep(t, T.wordmark + 0.5, T.wordmark + 1.6, E.inOutCubic))}% 0` });

  const p1 = ep(t, T.tagline, T.tagline + 0.9, E.outExpo);
  const p2 = ep(t, T.tagline + 0.47, T.tagline + 1.3, E.outExpo);
  css(tag1, { opacity: String(p1), transform: `translateX(${lerp(-30, 0, p1)}px)`, filter: `blur(${(1 - p1) * 10}px)` });
  css(tag2, { opacity: String(p2), transform: `translateX(${lerp(30, 0, p2)}px) scale(${lerp(1.3, 1, p2)})`, filter: `blur(${(1 - p2) * 10}px)` });

  // Light: a blast on the hit, settling into a steady glow behind the mark.
  const hit = decay(t, T.reveal, 0.45);
  const settle = ep(t, T.reveal, T.reveal + 0.8, E.outCubic);
  const leave = 1 - out;
  fx.ray = [960, cy];
  fx.rays = (hit * 1.6 + settle * 0.42 + decay(t, T.wordmark, 0.5) * 0.4) * leave;
  fx.flare = (hit * 1.8 + settle * 0.22 + decay(t, T.wordmark, 0.35) * 0.9) * leave;
  fx.ghosts = (hit * 1.2 + settle * 0.35) * leave;
  fx.flareCol = [0.55, 0.92, 0.28];
  fx.nebula = settle * 0.42 * leave;
  fx.colA = [0.02, 0.28, 0.22];
  fx.colB = [0.22, 0.48, 0.05];
  fx.dust = settle * 0.5;
  fx.dustCol = [190, 240, 150];
  fx.bursts.push({ t0: T.reveal, x: 960, y: BIG.cy, n: 360, seed: 3, col: [166, 227, 95], speed: 1.1 });
}
