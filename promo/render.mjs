#!/usr/bin/env node
// Renders the promo video from promo/scene/ with headless Chromium and ffmpeg.
// No npm packages: Node's own http server, fetch and WebSocket are enough to
// drive Chromium over the DevTools protocol.
//
//   node promo/render.mjs                  full render into promo/out/
//   node promo/render.mjs --draft          quick 960x540 30 fps preview (build/draft.mp4)
//   node promo/render.mjs --stills [t,..]  PNG stills into build/stills/
//   node promo/render.mjs --only audio     just the score (build/score.wav)
//
// Other options: --workers N (parallel browsers, default 4), --samples N
// (motion-blur sub-frames per frame, default 4), --keep (keep the lossless
// intermediate segments), --only video|audio|poster.

import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const PROMO = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(PROMO);
const BUILD = path.join(PROMO, 'build');
const OUT = path.join(PROMO, 'out');
const CHROME = process.env.CHROMIUM || 'chromium';

const DEFAULT_STILLS = [1.2, 2.6, 4.5, 5.9, 6.9, 7.8, 9.0, 10.4, 12.4, 14.4, 16.5, 20.3, 23.0, 25.5, 27.6, 31.2,
  33.2, 34.6, 35.8, 37.3, 39.6, 40.9, 41.35, 44.2];

// ---- Options ----

function parseArgs(argv) {
  const o = { mode: 'full', workers: 4, samples: 4, keep: false, only: null, stills: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--draft') o.mode = 'draft';
    else if (a === '--stills') {
      o.mode = 'stills';
      const next = argv[i + 1];
      o.stills = next && !next.startsWith('--') ? (i++, next.split(',').map(Number)) : DEFAULT_STILLS;
    } else if (a === '--workers') o.workers = parseInt(argv[++i], 10);
    else if (a === '--samples') o.samples = parseInt(argv[++i], 10);
    else if (a === '--keep') o.keep = true;
    else if (a === '--only') o.only = argv[++i];
    else throw new Error(`Unknown option: ${a}`);
  }
  return o;
}

// ---- Static file server for the repository root ----
// The scene reads data/icons/ straight from the checkout, so it serves the root.

const TYPES = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
};

function serve() {
  const server = http.createServer(async (req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    const file = path.join(ROOT, path.normalize(rel));
    if (!file.startsWith(ROOT + path.sep)) { res.writeHead(403).end(); return; }
    try {
      const body = await fsp.readFile(file);
      res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
      res.end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

// ---- Chromium over the DevTools protocol ----

const GPU_FLAGS = ['--use-angle=vulkan', '--enable-features=Vulkan', '--ignore-gpu-blocklist', '--enable-gpu-rasterization'];
const SOFT_FLAGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];

async function launch(name, gpu) {
  const profile = path.join(BUILD, 'profiles', name);
  await fsp.rm(profile, { recursive: true, force: true });
  const proc = spawn(CHROME, [
    '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--hide-scrollbars',
    '--mute-audio', '--force-color-profile=srgb', '--window-size=1920,1080',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows',
    ...(gpu ? GPU_FLAGS : SOFT_FLAGS), 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => reject(new Error('Chromium did not start')), 30000);
    proc.stderr.on('data', (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) { clearTimeout(timer); resolve(m[1]); }
    });
    proc.on('exit', (code) => reject(new Error(`Chromium exited (${code}): ${buf.slice(-500)}`)));
  });
  const port = new URL(wsUrl).port;
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = await connect(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  return { proc, page };
}

function connect(url) {
  const ws = new WebSocket(url);
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (!msg.id || !pending.has(msg.id)) return;
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  };
  const page = {
    send: (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    }),
    // Evaluate an expression in the page, awaiting promises.
    async eval(expression) {
      const r = await page.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(`Page error: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
      return r.result.value;
    },
    async screenshot() {
      const r = await page.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true });
      return Buffer.from(r.data, 'base64');
    },
    close: () => ws.close(),
  };
  return new Promise((resolve, reject) => { ws.onopen = () => resolve(page); ws.onerror = reject; });
}

// Open the scene at a device pixel ratio and wait for it to be ready.
// Falls back to software rendering if the GPU path gives no WebGL.
async function openScene(server, name, dpr, gpu = true) {
  const { proc, page } = await launch(name, gpu);
  await page.send('Page.enable');
  await page.send('Runtime.enable');
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: dpr, mobile: false });
  await page.send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/promo/scene/index.html` });
  for (let i = 0; i < 200; i++) {
    if (await page.eval('typeof window.promo === "object"').catch(() => false)) break;
    await new Promise((r) => setTimeout(r, 50));
  }
  await page.eval('promo.ready');
  const info = await page.eval('promo.info()');
  if (gpu && (info.renderer === 'none' || /swiftshader/i.test(info.renderer))) {
    await stop(page, proc);
    console.warn(`[${name}] no GPU WebGL (${info.renderer}); using software rendering`);
    return openScene(server, name, dpr, false);
  }
  return { proc, page, info, close: () => stop(page, proc) };
}

// Close the connection and wait for Chromium to exit, so its profile
// directory is no longer being written when it is deleted.
function stop(page, proc) {
  page.close();
  if (proc.exitCode !== null) return Promise.resolve();
  const exited = new Promise((r) => proc.once('exit', r));
  proc.kill();
  return exited;
}

// ---- ffmpeg ----

function run(cmd, args, { stdin = false, quiet = true } = {}) {
  const proc = spawn(cmd, args, { stdio: [stdin ? 'pipe' : 'ignore', 'ignore', 'pipe'] });
  let err = '';
  proc.stderr.on('data', (d) => { err += d; if (err.length > 200000) err = err.slice(-100000); });
  const done = new Promise((resolve, reject) => {
    proc.on('exit', (code) => (code === 0 ? resolve(err) : reject(new Error(`${cmd} failed (${code}):\n${err.slice(-3000)}`))));
  });
  if (!quiet) proc.stderr.pipe(process.stderr);
  return { proc, done };
}

function write(stream, buf) {
  return stream.write(buf) ? Promise.resolve() : new Promise((r) => stream.once('drain', r));
}

// ---- Rendering ----

// Each worker renders whole output frames [f0, f1): `samples` screenshots
// spread over half a frame (a 180-degree shutter), which ffmpeg averages
// into one motion-blurred frame and stores losslessly.
async function renderSegment(server, idx, f0, f1, o, progress) {
  const scene = await openScene(server, `w${idx}`, o.dpr);
  if (idx === 0) console.log(`WebGL: ${scene.info.renderer}\nTypeface: ${scene.info.font}`);
  const N = o.samples;
  const seg = path.join(BUILD, `seg-${String(idx).padStart(2, '0')}.mkv`);
  const blur = N > 1
    ? `format=gbrp16le,tmix=frames=${N},select='eq(mod(n\\,${N})\\,${N - 1})',setpts=N/(${o.fps}*TB),`
    : '';
  const ff = run('ffmpeg', [
    '-y', '-hide_banner', '-f', 'image2pipe', '-framerate', String(o.fps * N), '-c:v', 'png', '-i', '-',
    '-vf', `${blur}format=gbrp10le`, '-fps_mode', 'passthrough',
    '-c:v', 'ffv1', '-level', '3', '-slices', '16', '-g', '1', seg,
  ], { stdin: true });
  for (let f = f0; f < f1; f++) {
    for (let s = 0; s < N; s++) {
      const off = N > 1 ? ((s + 0.5) / N - 0.5) * 0.5 : 0;
      const t = Math.min(Math.max((f + off) / o.fps, 0), o.duration - 1e-4);
      await scene.page.eval(`promo.setTime(${t})`);
      await write(ff.proc.stdin, await scene.page.screenshot());
    }
    progress();
  }
  ff.proc.stdin.end();
  await ff.done;
  await scene.close();
  return seg;
}

async function renderVideo(server, o) {
  const total = Math.round(o.duration * o.fps);
  const per = Math.ceil(total / o.workers);
  let done = 0;
  const started = Date.now();
  const tick = setInterval(() => {
    const el = (Date.now() - started) / 1000;
    const eta = done ? (el / done) * (total - done) : 0;
    process.stdout.write(`\r  frames ${done}/${total}  ${el.toFixed(0)} s elapsed, ~${eta.toFixed(0)} s to go   `);
  }, 2000);
  const segs = await Promise.all(Array.from({ length: o.workers }, (_, i) => {
    const f0 = i * per, f1 = Math.min(total, f0 + per);
    return renderSegment(server, i, f0, f1, o, () => done++);
  }));
  clearInterval(tick);
  console.log(`\r  frames ${total}/${total} in ${((Date.now() - started) / 1000).toFixed(0)} s`);
  const list = path.join(BUILD, 'segments.txt');
  await fsp.writeFile(list, segs.map((s) => `file '${s}'`).join('\n') + '\n');
  return { list, segs };
}

async function renderAudio(server) {
  const scene = await openScene(server, 'audio', 1);
  const meta = await scene.page.eval('promo.renderAudio()');
  const parts = [];
  for (let i = 0; i < meta.chunks; i++) parts.push(Buffer.from(await scene.page.eval(`promo.audioChunk(${i})`), 'base64'));
  await scene.close();
  const data = Buffer.concat(parts);
  // 32-bit float WAV header.
  const hdr = Buffer.alloc(44);
  hdr.write('RIFF', 0); hdr.writeUInt32LE(36 + data.length, 4); hdr.write('WAVE', 8);
  hdr.write('fmt ', 12); hdr.writeUInt32LE(16, 16); hdr.writeUInt16LE(3, 20); hdr.writeUInt16LE(2, 22);
  hdr.writeUInt32LE(meta.sampleRate, 24); hdr.writeUInt32LE(meta.sampleRate * 8, 28); hdr.writeUInt16LE(8, 32);
  hdr.writeUInt16LE(32, 34); hdr.write('data', 36); hdr.writeUInt32LE(data.length, 40);
  const raw = path.join(BUILD, 'score.wav');
  await fsp.writeFile(raw, Buffer.concat([hdr, data]));

  // Bring it to -14 LUFS with one fixed gain, so the score keeps its
  // dynamics (loudnorm's dynamic mode flattened the quiet open into the
  // groove). A limiter catches any peak the gain pushes past -1 dBFS.
  const measure = await run('ffmpeg', ['-hide_banner', '-i', raw, '-af', 'ebur128=peak=true', '-f', 'null', '-']).done;
  const summary = measure.slice(measure.lastIndexOf('Summary:'));
  const I = parseFloat(summary.match(/I:\s+(-?[\d.]+) LUFS/)[1]);
  const peak = parseFloat(summary.match(/Peak:\s+(-?[\d.]+) dBFS/)[1]);
  const gain = -14 - I;
  const norm = path.join(BUILD, 'score-norm.wav');
  await run('ffmpeg', ['-y', '-hide_banner', '-i', raw, '-af',
    `volume=${gain.toFixed(2)}dB,alimiter=limit=0.89:attack=2:release=60:level=disabled`,
    '-c:a', 'pcm_s24le', norm]).done;
  console.log(`  score: ${I} LUFS, true peak ${peak} dBTP; gain ${gain.toFixed(1)} dB to -14 LUFS`);
  return norm;
}

const COLOUR = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv'];

// Every segment's timestamps start at zero and the concat demuxer overlaps
// them by a frame at each join, so frames are re-stamped by index; without
// this the picture drifts ahead of the score by a frame per join. The colour
// tags go on the frames too, since the encoders take them from there.
const restamp = (fps) =>
  `setpts=N/(${fps}*TB),scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,` +
  'setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv';

async function encodeFinal(list, audio, fps) {
  await fsp.mkdir(OUT, { recursive: true });
  const h264 = path.join(OUT, 'tumbleweed-updater-promo.mp4');
  const av1 = path.join(OUT, 'tumbleweed-updater-promo-av1.mp4');
  await run('ffmpeg', [
    '-y', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', list, '-i', audio,
    '-filter_complex',
    `[0:v]${restamp(fps)},split[a][b];` +
    '[a]format=yuv420p,noise=c0s=3:c0f=t[h];[b]format=yuv420p10le[v]',
    '-map', '[h]', '-map', '1:a', '-c:v', 'libopenh264', '-profile:v', 'high', '-rc_mode', 'bitrate',
    '-b:v', '16M', '-maxrate', '24M', '-g', '120', '-r', String(fps), ...COLOUR,
    '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', '-shortest', h264,
    '-map', '[v]', '-map', '1:a', '-c:v', 'libsvtav1', '-preset', '5', '-crf', '22', '-g', '120', '-r', String(fps), ...COLOUR,
    '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', '-shortest', av1,
  ]).done;
  return [h264, av1];
}

async function encodeDraft(list, audio, fps) {
  const draft = path.join(BUILD, 'draft.mp4');
  await run('ffmpeg', [
    '-y', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', list, '-i', audio,
    '-vf', `${restamp(fps)},format=yuv420p`, '-r', String(fps),
    '-c:v', 'libopenh264', '-rc_mode', 'bitrate', '-b:v', '6M', ...COLOUR,
    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', draft,
  ]).done;
  return draft;
}

async function stills(server, times) {
  const dir = path.join(BUILD, 'stills');
  await fsp.mkdir(dir, { recursive: true });
  const scene = await openScene(server, 'stills', 1);
  console.log(`WebGL: ${scene.info.renderer}\nTypeface: ${scene.info.font}`);
  for (const t of times) {
    await scene.page.eval(`promo.setTime(${t})`);
    const file = path.join(dir, `t${t.toFixed(2).padStart(5, '0')}.png`);
    await fsp.writeFile(file, await scene.page.screenshot());
    console.log(`  ${path.relative(ROOT, file)}`);
  }
  await scene.close();
}

async function poster(server, duration) {
  await fsp.mkdir(OUT, { recursive: true });
  const scene = await openScene(server, 'poster', 2);
  await scene.page.eval(`promo.setTime(${Math.min(44.2, duration)})`);
  const file = path.join(OUT, 'poster.png');
  await fsp.writeFile(file, await scene.page.screenshot());
  await scene.close();
  return file;
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  await fsp.mkdir(BUILD, { recursive: true });
  const server = await serve();
  try {
    if (o.mode === 'stills') { await stills(server, o.stills); return; }

    // Read the duration from the scene itself, so there is one source of truth.
    const probe = await openScene(server, 'probe', 0.25);
    o.duration = await probe.page.eval('promo.duration');
    await probe.close();

    if (o.mode === 'draft') Object.assign(o, { dpr: 0.5, fps: 30, samples: 1 });
    else Object.assign(o, { dpr: 1, fps: 60 });

    let audio = path.join(BUILD, 'score-norm.wav');
    if (!o.only || o.only === 'audio') {
      console.log('Rendering the score');
      audio = await renderAudio(server);
    }
    if (o.only === 'audio') return;

    if (!o.only || o.only === 'video') {
      console.log(`Rendering ${o.duration} s at ${1920 * o.dpr}x${1080 * o.dpr}, ${o.fps} fps, ${o.samples} samples/frame, ${o.workers} workers`);
      const { list, segs } = await renderVideo(server, o);
      console.log('Encoding');
      const files = o.mode === 'draft' ? [await encodeDraft(list, audio, o.fps)] : await encodeFinal(list, audio, o.fps);
      if (!o.keep) for (const s of segs) await fsp.rm(s, { force: true });
      for (const f of files) console.log(`  ${path.relative(ROOT, f)}  ${(fs.statSync(f).size / 1e6).toFixed(1)} MB`);
    }
    if (o.mode === 'full' && (!o.only || o.only === 'poster')) {
      console.log(`  ${path.relative(ROOT, await poster(server, o.duration))}`);
    }
  } finally {
    server.close();
    await fsp.rm(path.join(BUILD, 'profiles'), { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

main().catch((e) => { console.error(e.message || e); process.exit(1); });
