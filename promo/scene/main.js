// Boots the stage and exposes window.promo, the interface render.mjs drives:
//   await promo.ready                 fonts, logo, shader, first frame
//   await promo.setTime(t)            draw the frame at t seconds
//   await promo.renderAudio()         render the score; returns chunk count
//   promo.audioChunk(i)               base64 float32 PCM, interleaved stereo
//   promo.info()                      which GPU and typeface were used

import { DURATION, IMPACTS, CUTS, T } from './timeline.js';
import { css, h, decay, noise1, ep, E, clamp, prog } from './ease.js';
import * as fx from './fx.js';
import { renderScore } from './score.js';
import * as opening from './scenes/opening.js';
import * as reveal from './scenes/reveal.js';
import * as tray from './scenes/tray.js';
import * as list from './scenes/list.js';
import * as terminal from './scenes/terminal.js';
import * as snapshots from './scenes/snapshots.js';
import * as stats from './scenes/stats.js';
import * as finale from './scenes/finale.js';

const SCENES = [opening, reveal, tray, list, terminal, snapshots, stats, finale];
const $ = (s) => document.querySelector(s);
const world = $('#world');
const flash = $('#flash');
const [lbTop, lbBottom] = [$('#letterbox .top'), $('#letterbox .bottom')];
const stage = $('#stage');
const streak = h(`<div style="position:absolute;left:-10%;right:-10%;top:540px;height:4px;margin-top:-2px;opacity:0;pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(210,255,170,.9) 30%,#fff 50%,rgba(210,255,170,.9) 70%,transparent);
  box-shadow:0 0 30px 8px rgba(166,227,95,.6),0 0 120px 30px rgba(115,186,37,.35)"></div>`);
const fade = h('<div style="position:absolute;inset:0;background:#000;opacity:0;pointer-events:none"></div>');
stage.append(streak, fade);

let sceneEls = [];

async function boot() {
  // The mark is read from the app's own icon so the promo cannot drift from it.
  const svgText = await (await fetch('/data/icons/styles/tumbleweed.svg')).text();
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
  const shared = {
    logoPath: doc.querySelector('path').getAttribute('d').replace(/\s+/g, ' ').trim(),
    logoTransform: doc.querySelector('g')?.getAttribute('transform') || '',
  };

  fx.init($('#bg'), $('#particles'));
  sceneEls = SCENES.map((s) => {
    const el = h('<section class="scene"></section>');
    $('#scenes').append(el);
    el.style.display = 'block';   // so build() can measure (getTotalLength)
    s.build(el, shared);
    el.style.display = 'none';
    return el;
  });
  await document.fonts.ready;
  render(0);
  await nextFrame();
}

const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r()));

export function render(t) {
  const state = fx.freshState();

  SCENES.forEach((s, i) => {
    const [a, b] = s.span;
    const on = t >= a && t < b;
    css(sceneEls[i], { display: on ? 'block' : 'none' });
    if (on) s.update(t, state);
  });

  // Every impact flashes, shakes and punches in a little.
  let fl = 0, shake = 0, punch = 0;
  for (const [tc, s] of IMPACTS) {
    fl += s * decay(t, tc, 0.08);
    shake += s * decay(t, tc, 0.22);
    punch += s * decay(t, tc, 0.4);
  }
  const sx = noise1(t * 36, 1) * shake * 22;
  const sy = noise1(t * 36, 2) * shake * 15;
  const rot = noise1(t * 28, 3) * shake * 0.5;
  css(world, { transform: `translate(${sx}px, ${sy}px) rotate(${rot}deg) scale(${1.03 + punch * 0.03})` });
  css(flash, { opacity: String(clamp(fl * 0.85)) });

  // A light streak across the frame on each scene change.
  let st = 0;
  for (const c of CUTS) st += Math.exp(-Math.pow((t - c) / 0.1, 2));
  css(streak, { opacity: String(clamp(st)), transform: `scaleX(${0.4 + st * 0.6})` });

  // Scope bars during the cold open, drawn back on the reveal.
  const open = ep(t, T.reveal, T.reveal + 0.9, E.outExpo);
  css(lbTop, { transform: `translateY(${-open * 140}px)` });
  css(lbBottom, { transform: `translateY(${open * 140}px)` });

  css(fade, { opacity: String(ep(t, T.fadeOut, DURATION, E.inOutCubic)) });
  state.nebula *= 1 - prog(t, T.fadeOut, DURATION);

  fx.draw(t, state);
}

// Which typefaces the page actually got: Inter (and Inter Display for large
// type) if installed, else Poppins.
function fontInUse() {
  const c = document.createElement('canvas').getContext('2d');
  const w = (f) => { c.font = `800 64px ${f}`; return c.measureText('Tumbleweed Updater 0123').width; };
  const found = ['Inter Display', 'Inter Variable', 'Inter', 'Poppins'].filter((f) => w(`"${f}", monospace`) !== w('monospace'));
  return found.join(', ') || 'fallback';
}

// Audio goes back to the driver in chunks; one CDP message of the whole score
// would be tens of megabytes.
const CHUNK = 1 << 21;
let pcm = null;

async function renderAudio() {
  const buf = await renderScore();
  const L = buf.getChannelData(0), R = buf.getChannelData(1);
  const f = new Float32Array(L.length * 2);
  for (let i = 0; i < L.length; i++) { f[2 * i] = L[i]; f[2 * i + 1] = R[i]; }
  pcm = new Uint8Array(f.buffer);
  return { sampleRate: buf.sampleRate, frames: L.length, chunks: Math.ceil(pcm.length / CHUNK) };
}

function audioChunk(i) {
  const part = pcm.subarray(i * CHUNK, (i + 1) * CHUNK);
  let s = '';
  for (let j = 0; j < part.length; j += 0x8000) s += String.fromCharCode.apply(null, part.subarray(j, j + 0x8000));
  return btoa(s);
}

const ready = boot();
window.promo = {
  duration: DURATION,
  ready,
  setTime: async (t) => { render(t); await nextFrame(); },
  renderAudio,
  audioChunk,
  info: () => ({ renderer: fx.renderer, font: fontInUse(), dpr: window.devicePixelRatio }),
};

// ?t=12.5 shows one frame; ?play plays it in real time with the score.
const params = new URLSearchParams(location.search);
ready.then(async () => {
  if (params.has('t')) render(parseFloat(params.get('t')));
  if (!params.has('play')) return;
  const go = h('<div style="position:absolute;inset:0;display:grid;place-items:center;font-size:40px;cursor:pointer;background:rgba(0,0,0,.6)">Click to play</div>');
  stage.append(go);
  go.addEventListener('click', async () => {
    go.textContent = 'Rendering the score…';
    const buf = await renderScore();
    go.remove();
    const ctx = new AudioContext();
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const start = ctx.currentTime + 0.1;
    src.start(start);
    const loop = () => {
      const t = ctx.currentTime - start;
      render(Math.max(0, t));
      if (t < DURATION) requestAnimationFrame(loop);
    };
    loop();
  });
});

