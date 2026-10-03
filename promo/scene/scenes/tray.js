// Bars 7-10: the tray. A close shot of a Plasma panel; on the downbeat the
// mark turns the app's "updates" orange and the real notification slides up.

import { SCENES, T, CUTS } from '../timeline.js';
import { css, h, ep, E, prog, lerp, decay, sceneMotion } from '../ease.js';
import { textBlock, animateText, logoSvg, ICONS, ringState } from './common.js';

let root, tb, desk, mark, rings, note, noteBar;
export const span = SCENES.tray;
const [IN, OUT] = [CUTS[0], CUTS[1]];

export function build(el, shared) {
  root = el;
  tb = textBlock({
    eyebrow: 'Always watching',
    title: ['It <em>watches.</em>', "So you don't", 'have to.'],
    body: 'Background checks, hourly to weekly, skipped on battery. Orange means updates are here.',
    x: 150, y: 285, orange: true, width: 700,
  });

  const icon = (svg, extra = '') => `<span style="width:40px;height:40px;display:inline-block;color:#fcfcfc;${extra}">${svg}</span>`;
  desk = h(`<div style="position:absolute;left:900px;top:215px;width:900px;height:640px;border-radius:24px;overflow:hidden;transform-origin:30% 50%;
      background:
        radial-gradient(60% 70% at 18% 25%, rgba(34,110,90,.85) 0%, transparent 70%),
        radial-gradient(55% 65% at 85% 60%, rgba(82,140,30,.7) 0%, transparent 70%),
        radial-gradient(40% 40% at 55% 10%, rgba(40,70,120,.6) 0%, transparent 70%),
        linear-gradient(135deg, #0b1a22, #0d140f);
      box-shadow: 0 0 0 1px rgba(255,255,255,.09), 0 50px 140px rgba(0,0,0,.8)">
    <div class="note" style="position:absolute;right:26px;bottom:118px;width:500px;padding:20px 22px 22px;border-radius:14px;
        background:rgba(40,44,48,.97);border:1px solid rgba(255,255,255,.1);font-family:var(--ui);color:#fcfcfc;
        box-shadow:0 20px 60px rgba(0,0,0,.6),0 0 50px rgba(246,116,0,.18);opacity:0">
      <div style="display:flex;align-items:center;gap:12px;font-size:19px;color:rgba(252,252,252,.72)">
        <span style="width:36px;height:18px;color:#f67400;display:inline-block">${logoSvg(shared)}</span>
        <span style="font-weight:700;color:#fcfcfc">Tumbleweed Updater</span><span>· Just now</span>
      </div>
      <div style="margin-top:14px;font-size:26px">36 updates available.</div>
      <div style="margin-top:18px;height:3px;border-radius:2px;background:rgba(255,255,255,.1);overflow:hidden">
        <div class="bar" style="height:100%;width:100%;background:#f67400;transform-origin:0 50%"></div>
      </div>
    </div>
    <div style="position:absolute;left:0;right:0;bottom:0;height:96px;background:rgba(32,35,38,.94);border-top:1px solid rgba(255,255,255,.08);
        display:flex;align-items:center;padding:0 30px;gap:34px">
      ${icon(ICONS.launcher)}
      <span style="width:62px;height:62px;border-radius:10px;background:rgba(255,255,255,.1);display:grid;place-items:center">${icon(ICONS.files)}</span>
      ${icon(ICONS.browser)}
      ${icon(ICONS.terminal)}
      <span style="flex:1"></span>
      ${icon(ICONS.clipboard)}
      ${icon(ICONS.network)}
      ${icon(ICONS.volume)}
      ${icon(ICONS.battery)}
      <span class="mark" style="position:relative;width:68px;height:34px;display:inline-block;color:#fcfcfc">
        ${[0, 1, 2].map(() => '<span class="ring" style="position:absolute;left:50%;top:50%;width:60px;height:60px;margin:-30px 0 0 -30px;border-radius:50%;border:2.5px solid #f67400;opacity:0"></span>').join('')}
        ${logoSvg(shared, { cls: 'm' })}
      </span>
      ${icon(ICONS.chevron, 'width:30px;height:30px')}
      <span style="font-family:var(--ui);text-align:center;line-height:1.15;margin-left:6px">
        <div style="font-size:30px">10:02</div><div style="font-size:17px;opacity:.75">26/09/2026</div>
      </span>
    </div>
  </div>`);
  mark = desk.querySelector('.mark');
  rings = [...desk.querySelectorAll('.ring')];
  note = desk.querySelector('.note');
  noteBar = desk.querySelector('.bar');
  root.append(tb.el, desk);
}

export function update(t, fx) {
  const m = sceneMotion(t, IN, OUT);
  css(root, { transform: `scale(${m.scale})`, filter: `blur(${m.blur}px)`, opacity: String(m.opacity) });
  animateText(tb, t, IN + 0.15);

  const p = prog(t, IN, OUT);
  css(desk, {
    transform: `perspective(2200px) rotateY(${lerp(-24, -12, E.outCubic(p))}deg) rotateX(${lerp(7, 3, p)}deg) scale(${lerp(1.12, 1.0, E.outCubic(p))}) translateX(${lerp(40, 0, p)}px)`,
  });

  // The alert: white to orange, a glow, and rings.
  const on = t >= T.trayAlert;
  const pop = decay(t, T.trayAlert, 0.35);
  css(mark, {
    color: on ? '#f67400' : '#fcfcfc',
    filter: on ? `drop-shadow(0 0 ${8 + pop * 18}px rgba(246,116,0,${0.75 + pop * 0.25}))` : 'none',
    transform: `scale(${1 + pop * 0.35})`,
  });
  rings.forEach((r, i) => {
    const s = ringState(t, T.trayAlert, i);
    css(r, { opacity: String(s.opacity), transform: `scale(${s.scale})` });
  });

  const pn = ep(t, T.trayAlert + 0.25, T.trayAlert + 0.95, E.outExpo);
  css(note, { opacity: String(pn), transform: `translateY(${lerp(50, 0, pn)}px) scale(${lerp(0.96, 1, pn)})` });
  css(noteBar, { transform: `scaleX(${1 - prog(t, T.trayAlert + 0.6, T.trayAlert + 8.6)})` });

  // Light follows the mark on screen, orange once it has something to say.
  const r = mark.getBoundingClientRect();
  fx.ray = [r.left + r.width / 2, r.top + r.height / 2];
  fx.rays = (on ? 0.32 + pop * 0.9 : 0.06) * m.opacity;
  fx.flare = (on ? 0.25 + pop * 1.2 : 0) * m.opacity;
  fx.ghosts = on ? 0.3 * m.opacity : 0;
  fx.flareCol = on ? [1.0, 0.5, 0.08] : [0.6, 0.8, 0.9];
  fx.nebula = 0.34 * m.opacity;
  fx.colA = [0.03, 0.22, 0.26];
  fx.colB = [0.3, 0.2, 0.04];
  fx.dust = 0.3;
  fx.dustCol = [230, 210, 180];
}
