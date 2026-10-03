// Background effects. A WebGL nebula with god rays, an anamorphic flare and
// lens ghosts, plus a 2-D canvas of dust and burst particles drawn additively.
// Scenes do not draw here directly: each one writes what it wants into the
// shared `fx` state, and draw() renders that state for the current time.

import { mulberry32, clamp } from './ease.js';

// What the scenes can ask for. main.js resets this every frame.
export function freshState() {
  return {
    nebula: 0,                 // brightness of the nebula, 0..1
    colA: [0.05, 0.35, 0.3],   // nebula colours
    colB: [0.25, 0.55, 0.1],
    rays: 0,                   // god-ray strength
    ray: [960, 540],           // light source, CSS px
    flare: 0,                  // anamorphic streak strength
    ghosts: 0,                 // lens ghosts
    flareCol: [0.55, 0.9, 0.3],
    dust: 0,                   // dust density 0..1
    dustCol: [180, 230, 160],
    bursts: [],                // { t0, x, y, n, seed, col, speed }
  };
}

const VERT = `#version 300 es
in vec2 p;
void main() { gl_Position = vec4(p, 0.0, 1.0); }`;

const FRAG = `#version 300 es
precision highp float;
uniform vec2 uRes;
uniform float uScale, uTime, uNebula, uRays, uFlare, uGhosts;
uniform vec3 uColA, uColB, uFlareCol;
uniform vec2 uRay;
out vec4 o;

float hash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x),
             mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
  float s = 0.0, a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 6; i++) { s += a * vnoise(p); p = m * p; a *= 0.5; }
  return s;
}

void main() {
  // CSS pixels with a top-left origin, whatever the device pixel ratio.
  vec2 px = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y) / uScale;
  vec2 uv = px / 1080.0;
  float t = uTime;

  // Domain-warped nebula.
  vec2 q = vec2(fbm(uv * 1.3 + vec2(0.0, t * 0.03)),
                fbm(uv * 1.3 + vec2(5.2, 1.3) - vec2(t * 0.02, 0.0)));
  float n = fbm(uv * 1.1 + 1.7 * q + vec2(t * 0.015, -t * 0.01));
  vec3 col = mix(uColA, uColB, smoothstep(0.25, 0.75, q.y)) * pow(n, 2.6) * 2.4 * uNebula;
  col += vec3(0.008, 0.010, 0.013);

  // God rays: noise sampled round a circle, so there is no seam.
  vec2 d = (px - uRay) / 1080.0;
  float r = length(d);
  vec2 dir = d / max(r, 1e-4);
  float rays = vnoise(dir * 4.0 + vec2(t * 0.35, 3.0)) * 0.55
             + vnoise(dir * 11.0 - vec2(t * 0.5, 0.0)) * 0.45;
  rays = pow(rays, 2.4);
  col += uFlareCol * uRays * (rays * 1.7 * exp(-r * 1.7) + 0.6 * exp(-r * 7.0) + 0.22 * exp(-r * 2.4));

  // Anamorphic streak through the light.
  float streak = exp(-abs(d.y) * 150.0) * exp(-abs(d.x) * 1.0)
               + exp(-abs(d.y) * 38.0) * exp(-abs(d.x) * 2.6) * 0.35;
  col += mix(uFlareCol, vec3(0.6, 0.85, 1.0), 0.5) * streak * uFlare;

  // Lens ghosts on the line from the light through the centre of frame.
  vec2 c = vec2(960.0, 540.0);
  float ks[4] = float[4](0.45, 0.85, 1.35, 1.8);
  float rs[4] = float[4](70.0, 26.0, 110.0, 44.0);
  for (int i = 0; i < 4; i++) {
    vec2 gp = c + (c - uRay) * ks[i];
    float gd = length(px - gp) / rs[i];
    float g = smoothstep(1.0, 0.82, gd) * 0.05 + exp(-gd * gd) * 0.05 + smoothstep(0.06, 0.0, abs(gd - 1.0)) * 0.05;
    col += mix(uFlareCol, vec3(0.5, 0.6, 1.0), float(i) / 3.0) * g * uGhosts;
  }

  vec2 vv = px / vec2(1920.0, 1080.0) - 0.5;
  col *= 1.0 - dot(vv, vv) * 1.25;
  o = vec4(max(col, 0.0), 1.0);
}`;

let gl, prog, uni, dpr;
let ctx, dust;
export let renderer = 'none';

export function init(bgCanvas, ptCanvas) {
  dpr = window.devicePixelRatio || 1;
  for (const c of [bgCanvas, ptCanvas]) {
    c.width = Math.round(1920 * dpr);
    c.height = Math.round(1080 * dpr);
  }

  gl = bgCanvas.getContext('webgl2', { antialias: false, preserveDrawingBuffer: true });
  if (gl) {
    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    uni = {};
    for (const name of ['uRes', 'uScale', 'uTime', 'uNebula', 'uRays', 'uFlare', 'uGhosts',
                        'uColA', 'uColB', 'uFlareCol', 'uRay']) {
      uni[name] = gl.getUniformLocation(prog, name);
    }
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  }

  ctx = ptCanvas.getContext('2d');

  // Dust motes: fixed seeded positions and drift, so any frame can be drawn
  // on its own.
  const rnd = mulberry32(7);
  dust = Array.from({ length: 240 }, () => ({
    x: rnd() * 1920, y: rnd() * 1080, z: 0.15 + rnd() * 0.85,
    vx: (rnd() - 0.5) * 18, vy: -6 - rnd() * 16, ph: rnd() * 6.28, tw: 0.6 + rnd() * 1.6,
  }));
}

function drawGL(t, s) {
  if (!gl) return;
  gl.viewport(0, 0, gl.canvas.width, gl.canvas.height);
  gl.uniform2f(uni.uRes, gl.canvas.width, gl.canvas.height);
  gl.uniform1f(uni.uScale, dpr);
  gl.uniform1f(uni.uTime, t);
  gl.uniform1f(uni.uNebula, s.nebula);
  gl.uniform1f(uni.uRays, s.rays);
  gl.uniform1f(uni.uFlare, s.flare);
  gl.uniform1f(uni.uGhosts, s.ghosts);
  gl.uniform3fv(uni.uColA, s.colA);
  gl.uniform3fv(uni.uColB, s.colB);
  gl.uniform3fv(uni.uFlareCol, s.flareCol);
  gl.uniform2fv(uni.uRay, s.ray);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}

function drawParticles(t, s) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.globalCompositeOperation = 'lighter';

  if (s.dust > 0.001) {
    const [r, g, b] = s.dustCol;
    for (const p of dust) {
      const x = ((p.x + p.vx * t * p.z) % 1920 + 1920) % 1920;
      const y = ((p.y + p.vy * t * p.z) % 1080 + 1080) % 1080;
      const tw = 0.55 + 0.45 * Math.sin(t * p.tw + p.ph);
      const a = s.dust * tw * (0.12 + 0.5 * p.z * p.z);
      const rad = 1.2 + 3.6 * p.z;
      const grd = ctx.createRadialGradient(x, y, 0, x, y, rad * 2.2);
      grd.addColorStop(0, `rgba(${r},${g},${b},${a})`);
      grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = grd;
      ctx.fillRect(x - rad * 2.2, y - rad * 2.2, rad * 4.4, rad * 4.4);
    }
  }

  // Bursts: particles thrown out from a point with drag, drawn as short
  // streaks between where they were a moment ago and where they are now.
  ctx.lineCap = 'round';
  for (const bu of s.bursts) {
    const dt = t - bu.t0;
    if (dt < 0 || dt > 3.2) continue;
    const rnd = mulberry32(bu.seed);
    for (let i = 0; i < bu.n; i++) {
      const ang = rnd() * Math.PI * 2;
      const v = (250 + Math.pow(rnd(), 1.6) * 1500) * (bu.speed || 1);
      const k = 1.8 + rnd() * 1.6;
      const life = 1.0 + rnd() * 2.0;
      const w = 1 + rnd() * 2.4;
      const tint = rnd();
      if (dt > life) continue;
      const pos = (tt) => (v * (1 - Math.exp(-k * Math.max(tt, 0)))) / k;
      const d1 = pos(dt), d0 = pos(dt - 0.035);
      const cx = Math.cos(ang), cy = Math.sin(ang) * 0.75;
      const a = Math.pow(1 - dt / life, 1.6);
      const [r, g, b] = tint < 0.35 ? [255, 255, 255] : bu.col;
      ctx.strokeStyle = `rgba(${r},${g},${b},${clamp(a)})`;
      ctx.lineWidth = w;
      ctx.beginPath();
      ctx.moveTo(bu.x + cx * d0, bu.y + cy * d0 + dt * dt * 30);
      ctx.lineTo(bu.x + cx * d1 + 0.01, bu.y + cy * d1 + dt * dt * 30);
      ctx.stroke();
    }
  }
  ctx.globalCompositeOperation = 'source-over';
}

export function draw(t, s) {
  drawGL(t, s);
  drawParticles(t, s);
}
