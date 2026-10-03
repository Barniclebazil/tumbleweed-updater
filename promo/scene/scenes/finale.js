// Bars 21-24: the finale. The lock-up lands on the last hit, a cursor presses
// the real "Update now…" button, and the end card says where to get it.

import { SCENES, T } from '../timeline.js';
import { css, h, ep, E, prog, lerp, decay } from '../ease.js';
import { LOGO_VIEWBOX, ICONS } from './common.js';

let root, lock, logo, wm, btn, done, ring, cursor, tag, url, avail, fine;
export const span = SCENES.finale;

const LOGO_CY = 290;
const BTN_Y = 668;     // centre of the button
const CUR_FROM = [1580, 1020];
const CUR_TO = [1012, BTN_Y + 6];

export function build(el, shared) {
  root = el;
  lock = h(`<div style="position:absolute;inset:0;transform-origin:50% 40%"></div>`);
  logo = h(`<div style="position:absolute;left:${960 - 150}px;top:${LOGO_CY - 75}px;width:300px;height:150px">
    <svg viewBox="${LOGO_VIEWBOX}" style="width:100%;height:100%;overflow:visible" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="fnFill" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#c9f79a"/><stop offset=".45" stop-color="#8fd13f"/><stop offset="1" stop-color="#4f9419"/>
      </linearGradient></defs>
      <g transform="${shared.logoTransform}"><path d="${shared.logoPath}" fill="url(#fnFill)"/></g>
    </svg>
  </div>`);
  wm = h(`<div style="position:absolute;left:0;right:0;top:382px;text-align:center;font-family:var(--display);font-size:92px;font-weight:800;letter-spacing:.05em;padding-left:.05em;line-height:1.1;white-space:nowrap">
    <span style="-webkit-background-clip:text;background-clip:text;color:transparent;background-image:linear-gradient(180deg,#fff 20%,#dfe6ea 55%,#8f9ba4 100%)">TUMBLEWEED UPDATER</span>
  </div>`);
  lock.append(logo, wm);

  const pill = 'position:absolute;left:50%;top:' + BTN_Y + 'px;transform-origin:50% 50%;white-space:nowrap;font-family:var(--ui);border-radius:12px;';
  btn = h(`<div style="${pill}font-size:34px;padding:16px 48px;background:#43302c;border:2px solid #e95420;color:#fcfcfc;
      box-shadow:0 0 40px rgba(233,84,32,.45),0 20px 60px rgba(0,0,0,.5);opacity:0">Update now…</div>`);
  done = h(`<div style="${pill}font-size:34px;padding:16px 44px;background:rgba(115,186,37,.16);border:2px solid #73ba25;color:#fcfcfc;
      box-shadow:0 0 40px rgba(115,186,37,.45);opacity:0"><span style="color:#a6e35f;font-weight:700;margin-right:16px">✓</span>Your system is up to date</div>`);
  ring = h(`<div style="position:absolute;left:960px;top:${BTN_Y}px;width:200px;height:200px;margin:-100px 0 0 -100px;border-radius:50%;border:3px solid rgba(255,190,120,.95);box-shadow:0 0 40px rgba(246,116,0,.8);opacity:0"></div>`);
  cursor = h(`<div style="position:absolute;left:0;top:0;width:54px;height:54px;transform-origin:20% 10%;filter:drop-shadow(0 6px 10px rgba(0,0,0,.6));opacity:0">${ICONS.cursor}</div>`);

  tag = h(`<div style="position:absolute;left:0;right:0;top:522px;text-align:center;font-family:var(--display);font-size:40px;font-weight:300;letter-spacing:.03em;color:#dbe3e8;opacity:0">The future of staying current.</div>`);
  url = h(`<div style="position:absolute;left:50%;top:790px;white-space:nowrap;font-family:var(--mono);font-size:27px;color:#fcfcfc;padding:14px 30px;border-radius:40px;
      border:1px solid rgba(255,255,255,.22);background:rgba(255,255,255,.05);opacity:0">github.com/barniclebazil/tumbleweed-updater</div>`);
  avail = h(`<div style="position:absolute;left:0;right:0;top:880px;text-align:center;font-size:19px;font-weight:600;letter-spacing:.42em;padding-left:.42em;color:#a6e35f;opacity:0">AVAILABLE NOW FOR OPENSUSE TUMBLEWEED</div>`);
  fine = h(`<div style="position:absolute;left:0;right:0;bottom:36px;text-align:center;font-size:15px;color:rgba(255,255,255,.38);opacity:0">openSUSE and Tumbleweed are trademarks of SUSE LLC. Tumbleweed Updater is an independent GPL-3.0 project.</div>`);
  root.append(lock, ring, tag, btn, done, url, avail, fine, cursor);
}

const rise = (el, t, t0, dur = 0.9, dy = 26, centreX = false) => {
  const p = ep(t, t0, t0 + dur, E.outExpo);
  css(el, {
    opacity: String(p),
    transform: `${centreX ? 'translateX(-50%) ' : ''}translateY(${lerp(dy, 0, p)}px)`,
    filter: `blur(${(1 - p) * 8}px)`,
  });
};

export function update(t, fx) {
  // The lock-up lands on the hit and keeps settling.
  const pl = ep(t, T.finale, T.finale + 1.4, E.outExpo);
  const hit = decay(t, T.finale, 0.5);
  css(lock, {
    transform: `translateY(${lerp(70, 0, pl)}px) scale(${lerp(1.2, 1, pl) * lerp(1, 1.02, prog(t, T.finale, 45))})`,
    filter: `blur(${(1 - pl) * 16}px)`,
  });
  css(logo, { filter: `drop-shadow(0 0 ${8 + hit * 20}px rgba(190,245,130,.9)) drop-shadow(0 0 ${36 + hit * 40}px rgba(115,186,37,.6))` });

  // Button, cursor, click.
  const clicked = t >= T.click;
  const pbIn = ep(t, T.cursor, T.cursor + 0.6, E.outExpo);
  const hover = ep(t, T.click - 0.3, T.click - 0.1, E.outCubic);
  const press = clicked ? Math.exp(-(t - T.click) / 0.08) : 0;
  const morph = ep(t, T.click + 0.05, T.click + 0.4, E.outCubic);
  css(btn, {
    opacity: String(pbIn * (1 - morph)),
    transform: `translate(-50%, -50%) translateY(${lerp(24, 0, pbIn)}px) scale(${(1 - press * 0.07) * lerp(1, 1.15, morph)})`,
    background: hover > 0.5 && !clicked ? '#5b3b31' : '#43302c',
    filter: `blur(${morph * 8}px)`,
  });
  css(done, {
    opacity: String(morph),
    transform: `translate(-50%, -50%) scale(${lerp(0.85, 1, ep(t, T.click + 0.05, T.click + 0.6, E.outBack))})`,
  });
  const rp = prog(t, T.click, T.click + 0.9);
  css(ring, { opacity: String(rp > 0 && rp < 1 ? (1 - rp) : 0), transform: `scale(${lerp(0.4, 7, E.outCubic(rp))})` });

  const move = ep(t, T.cursor + 0.15, T.click - 0.2, E.inOutCubic);
  const cx = lerp(CUR_FROM[0], CUR_TO[0], move), cy = lerp(CUR_FROM[1], CUR_TO[1], move) + Math.sin(move * Math.PI) * -60;
  css(cursor, {
    opacity: String(Math.min(ep(t, T.cursor + 0.1, T.cursor + 0.4), 1 - ep(t, T.click + 0.35, T.click + 0.8))),
    transform: `translate(${cx}px, ${cy}px) scale(${1 - press * 0.18})`,
  });

  // End card.
  rise(tag, t, T.click + 0.3);
  rise(url, t, T.endCard + 0.1, 0.9, 26, true);
  rise(avail, t, T.endCard + 0.35);
  rise(fine, t, T.endCard + 0.6, 1.2, 0);

  fx.ray = [960, LOGO_CY + lerp(70, 0, pl)];
  const settle = ep(t, T.finale, T.finale + 0.8, E.outCubic);
  const clickHit = decay(t, T.click, 0.35);
  fx.rays = hit * 1.7 + settle * 0.5 + clickHit * 0.4;
  fx.flare = hit * 2.0 + settle * 0.25 + clickHit * 1.0;
  fx.ghosts = hit * 1.2 + settle * 0.4;
  fx.flareCol = [0.55, 0.92, 0.3];
  fx.nebula = 0.45 * settle;
  fx.colA = [0.02, 0.28, 0.22];
  fx.colB = [0.3, 0.42, 0.05];
  fx.dust = 0.55 * settle;
  fx.dustCol = [200, 245, 160];
  fx.bursts.push({ t0: T.finale, x: 960, y: LOGO_CY + 70, n: 420, seed: 9, col: [166, 227, 95], speed: 1.25 });
  fx.bursts.push({ t0: T.click, x: 960, y: BTN_Y, n: 240, seed: 12, col: [255, 170, 80], speed: 0.8 });
}
