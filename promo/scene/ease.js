// Small pure helpers shared by every scene. A frame must depend on the time
// alone, so nothing here keeps state except the style cache in css().

export const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
export const lerp = (a, b, p) => a + (b - a) * p;

// Linear progress of t through [a, b], clamped to 0..1.
export const prog = (t, a, b) => clamp((t - a) / (b - a));

export const E = {
  linear: (p) => p,
  inQuad: (p) => p * p,
  outQuad: (p) => 1 - (1 - p) * (1 - p),
  inCubic: (p) => p * p * p,
  outCubic: (p) => 1 - Math.pow(1 - p, 3),
  inOutCubic: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  outQuint: (p) => 1 - Math.pow(1 - p, 5),
  inExpo: (p) => (p === 0 ? 0 : Math.pow(2, 10 * p - 10)),
  outExpo: (p) => (p === 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  inOutExpo: (p) =>
    p === 0 ? 0 : p === 1 ? 1 : p < 0.5 ? Math.pow(2, 20 * p - 10) / 2 : (2 - Math.pow(2, -20 * p + 10)) / 2,
  outBack: (p) => {
    const c1 = 1.70158, c3 = c1 + 1;
    return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2);
  },
};

// Eased progress of t through [a, b].
export const ep = (t, a, b, f = E.outExpo) => f(prog(t, a, b));

// 0 before a, rises over `fin` seconds, holds, falls over the last `fout`
// seconds before b. Used for anything that comes and goes.
export function env(t, a, b, fin = 0.3, fout = 0.3, fi = E.outCubic, fo = E.inCubic) {
  if (t <= a || t >= b) return 0;
  const up = fin > 0 ? fi(prog(t, a, a + fin)) : 1;
  const down = fout > 0 ? 1 - fo(prog(t, b - fout, b)) : 1;
  return Math.min(up, down);
}

// Exponential decay after a hit at tc (0 before it).
export const decay = (t, tc, tau) => (t < tc ? 0 : Math.exp(-(t - tc) / tau));

// Seeded random numbers, so particles and glitches are identical every render.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Stateless hash of an integer and a seed to 0..1.
export function hash(n, seed = 0) {
  let x = (Math.imul(n | 0, 374761393) + Math.imul(seed | 0, 668265263)) >>> 0;
  x = Math.imul(x ^ (x >>> 13), 1274126177) >>> 0;
  return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
}

// Smooth 1-D value noise in -1..1, for shakes and flicker.
export function noise1(x, seed = 0) {
  const i = Math.floor(x), f = x - i;
  const u = f * f * (3 - 2 * f);
  return lerp(hash(i, seed), hash(i + 1, seed), u) * 2 - 1;
}

// Set inline styles, skipping any that have not changed since the last frame.
export function css(el, props) {
  const cache = el.__css || (el.__css = {});
  for (const k in props) {
    const v = props[k];
    if (cache[k] !== v) {
      el.style.setProperty(k, v);
      cache[k] = v;
    }
  }
}

// Build an element from an HTML string.
export function h(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild;
}

// Common transition for a feature scene, given the cuts that bring it in and
// take it out: it zooms in out of a blur, then flies past the camera into one.
export function sceneMotion(t, cutIn, cutOut) {
  const pin = ep(t, cutIn - 0.05, cutIn + 0.65, E.outExpo);
  const pout = ep(t, cutOut - 0.3, cutOut + 0.12, E.inExpo);
  return {
    scale: lerp(0.78, 1, pin) * lerp(1, 1.7, pout),
    blur: (1 - pin) * 22 + pout * 34,
    opacity: Math.min(prog(t, cutIn - 0.05, cutIn + 0.18), 1 - prog(t, cutOut - 0.06, cutOut + 0.12)),
  };
}
