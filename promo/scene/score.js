// The soundtrack, synthesised with Web Audio in an OfflineAudioContext.
//
// Every hit is scheduled from the same named moments the picture uses
// (timeline.js), so a cut and its sound cannot drift apart. The instruments
// below are small node graphs: oscillators and filtered noise with envelopes.

import { BEAT, bar, DURATION, T, CUTS, PROGRESSION } from './timeline.js';
import { mulberry32 } from './ease.js';

const SR = 48000;

// Note name to frequency: 'A1', 'C#3', ...
const SEMI = { C: 0, 'C#': 1, D: 2, 'D#': 3, E: 4, F: 5, 'F#': 6, G: 7, 'G#': 8, A: 9, 'A#': 10, B: 11 };
const hz = (n) => {
  const m = n.match(/^([A-G]#?)(-?\d)$/);
  return 440 * Math.pow(2, (SEMI[m[1]] + (parseInt(m[2]) + 1) * 12 - 69) / 12);
};

// Voicings. Pads sit in octave 3, bass roots in octave 1.
const CHORD = {
  Am: { pad: ['A2', 'E3', 'A3', 'C4', 'E4'], root: 'A1', arp: ['A3', 'E4', 'A4', 'C5'] },
  F:  { pad: ['F2', 'C3', 'F3', 'A3', 'C4'], root: 'F1', arp: ['F3', 'C4', 'F4', 'A4'] },
  C:  { pad: ['C3', 'G3', 'C4', 'E4', 'G4'], root: 'C2', arp: ['C4', 'G4', 'C5', 'E5'] },
  G:  { pad: ['G2', 'D3', 'G3', 'B3', 'D4'], root: 'G1', arp: ['G3', 'D4', 'G4', 'B4'] },
  A:  { pad: ['A2', 'E3', 'A3', 'C#4', 'E4'], root: 'A1', arp: ['A3', 'E4', 'A4', 'C#5'] },
};

export async function renderScore() {
  const ctx = new OfflineAudioContext({ numberOfChannels: 2, length: Math.ceil(DURATION * SR), sampleRate: SR });
  const rnd = mulberry32(2026);

  // ---- Buses: everything feeds a dry sum and a shared reverb; the master
  // goes through a compressor and a soft clipper.
  const master = ctx.createGain();
  master.gain.setValueAtTime(0.5, 0);
  master.gain.setValueAtTime(0.5, T.fadeOut);
  master.gain.linearRampToValueAtTime(0.0001, DURATION);
  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -16;
  comp.knee.value = 10;
  comp.ratio.value = 5;
  comp.attack.value = 0.004;
  comp.release.value = 0.25;
  const clip = ctx.createWaveShaper();
  clip.curve = shaper(1.4);
  clip.oversample = '4x';
  master.connect(comp).connect(clip).connect(ctx.destination);

  const verb = ctx.createConvolver();
  verb.buffer = impulse(ctx, 3.8, rnd);
  const verbIn = ctx.createGain();
  verbIn.gain.value = 1;
  const verbOut = ctx.createGain();
  verbOut.gain.value = 0.55;
  verbIn.connect(verb).connect(verbOut).connect(master);

  // Connect a source to the mix with a dry level and a reverb send.
  const out = (node, dry = 1, wet = 0.2, pan = 0) => {
    let n = node;
    if (pan) {
      const p = ctx.createStereoPanner();
      p.pan.value = pan;
      n.connect(p);
      n = p;
    }
    if (dry) { const g = ctx.createGain(); g.gain.value = dry; n.connect(g).connect(master); }
    if (wet) { const g = ctx.createGain(); g.gain.value = wet; n.connect(g).connect(verbIn); }
  };

  const noiseBuf = ctx.createBuffer(2, SR * 4, SR);
  for (let c = 0; c < 2; c++) {
    const d = noiseBuf.getChannelData(c);
    for (let i = 0; i < d.length; i++) d[i] = rnd() * 2 - 1;
  }
  const noise = (t, dur) => {
    const s = ctx.createBufferSource();
    s.buffer = noiseBuf;
    s.loop = true;
    s.start(t, rnd() * 3);
    s.stop(t + dur + 0.05);
    return s;
  };
  const osc = (type, f, t, dur, detune = 0) => {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(f, t);
    o.detune.setValueAtTime(detune, t);
    o.start(t);
    o.stop(t + dur + 0.05);
    return o;
  };
  const filt = (type, f, q = 0.7) => {
    const b = ctx.createBiquadFilter();
    b.type = type;
    b.frequency.value = f;
    b.Q.value = q;
    return b;
  };
  // Gain envelope: attack, then exponential decay to silence by t + dur.
  const env = (t, level, attack, dur, curve = 'exp') => {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(level, t + attack);
    if (curve === 'exp') g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    else g.gain.linearRampToValueAtTime(0.0001, t + dur);
    g.gain.setValueAtTime(0, t + dur + 0.01);
    return g;
  };

  // ---- Instruments ----

  // Low drone of detuned saws under a slowly breathing low-pass.
  function drone(t0, t1, notes, level) {
    const lp = filt('lowpass', 220, 1.2);
    const lfo = osc('sine', 0.18, t0, t1 - t0);
    const lfoAmt = ctx.createGain();
    lfoAmt.gain.value = 90;
    lfo.connect(lfoAmt).connect(lp.frequency);
    lp.frequency.setValueAtTime(160, t0);
    lp.frequency.linearRampToValueAtTime(520, t1);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.linearRampToValueAtTime(level * 0.6, t0 + 2.5);
    g.gain.linearRampToValueAtTime(level, t1 - 0.05);
    g.gain.linearRampToValueAtTime(0, t1);
    for (const n of notes) for (const d of [-9, 0, 7]) osc('sawtooth', hz(n), t0, t1 - t0, d).connect(lp);
    osc('sine', hz(notes[0]) / 2, t0, t1 - t0).connect(lp);
    lp.connect(g);
    out(g, 1, 0.3);
  }

  // Clock tick: a filtered click and a short high ping.
  function tick(t, level, high) {
    out(noise(t, 0.02).connect(filt('highpass', 5000)).connect(env(t, level, 0.001, 0.015)), 1, 0.15);
    const o = osc('sine', high ? 2400 : 1900, t, 0.05);
    out(o.connect(env(t, level * 0.5, 0.001, 0.04)), 1, 0.2);
  }

  // A glitch: a low thud, and a burst of squares hopping between pitches.
  function glitch(t, level, seed) {
    const r = mulberry32(seed);
    const th = osc('sine', 110, t, 0.4);
    th.frequency.exponentialRampToValueAtTime(38, t + 0.3);
    out(th.connect(env(t, level * 1.1, 0.002, 0.35)), 1, 0.15);
    const sq = osc('square', 300, t, 0.3);
    for (let k = 0; k < 12; k++) sq.frequency.setValueAtTime(120 + r() * 2400, t + k * 0.022);
    const crush = ctx.createWaveShaper();
    crush.curve = stepped(6);
    const bp = filt('bandpass', 1800, 0.8);
    out(sq.connect(crush).connect(bp).connect(env(t, level * 0.35, 0.002, 0.28, 'lin')), 1, 0.2, r() * 1.2 - 0.6);
    const n = noise(t, 0.12);
    out(n.connect(filt('highpass', 3000)).connect(env(t, level * 0.4, 0.001, 0.1)), 1, 0.25);
  }

  // Riser: band-passed noise sweeping up, and saws gliding up an octave or two.
  function riser(t0, t1, level, top = 9000) {
    const n = noise(t0, t1 - t0);
    const bp = filt('bandpass', 300, 1.6);
    bp.frequency.setValueAtTime(300, t0);
    bp.frequency.exponentialRampToValueAtTime(top, t1);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(level, t1 - 0.01);
    g.gain.setValueAtTime(0, t1);
    out(n.connect(bp).connect(g), 1, 0.35);
    const lp = filt('lowpass', 800, 2);
    lp.frequency.setValueAtTime(400, t0);
    lp.frequency.exponentialRampToValueAtTime(5000, t1);
    const g2 = ctx.createGain();
    g2.gain.setValueAtTime(0.0001, t0);
    g2.gain.exponentialRampToValueAtTime(level * 0.4, t1 - 0.01);
    g2.gain.setValueAtTime(0, t1);
    for (const d of [-12, 12]) {
      const o = osc('sawtooth', hz('A2'), t0, t1 - t0, d);
      o.frequency.exponentialRampToValueAtTime(hz('A4'), t1);
      o.connect(lp);
    }
    out(lp.connect(g2), 1, 0.3);
  }

  // Reverse swell: noise rising to a hard stop, the sound of a breath in.
  function swell(t0, t1, level) {
    const n = noise(t0, t1 - t0);
    const hp = filt('highpass', 1500, 0.5);
    hp.frequency.setValueAtTime(600, t0);
    hp.frequency.exponentialRampToValueAtTime(4000, t1);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(level, t1 - 0.005);
    g.gain.setValueAtTime(0, t1);
    out(n.connect(hp).connect(g), 1, 0.4);
  }

  // The BRAAAM: stacked detuned saws, driven hard, under a resonant low-pass
  // that snaps open and closes over a few seconds.
  function braam(t, notes, level, dur = 4.5) {
    const sum = ctx.createGain();
    sum.gain.value = 0.35;
    for (const n of notes) {
      for (const d of [-11, 0, 9]) {
        const o = osc('sawtooth', hz(n), t, dur, d - 40);
        o.detune.linearRampToValueAtTime(d, t + 0.18);
        o.connect(sum);
      }
    }
    osc('square', hz(notes[0]) / 2, t, dur).connect(sum);
    const drive = ctx.createWaveShaper();
    drive.curve = shaper(3.5);
    const lp = filt('lowpass', 120, 5);
    lp.frequency.setValueAtTime(120, t);
    lp.frequency.exponentialRampToValueAtTime(2600, t + 0.12);
    lp.frequency.exponentialRampToValueAtTime(700, t + 1.1);
    lp.frequency.exponentialRampToValueAtTime(200, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(level, t + 0.03);
    g.gain.setValueAtTime(level, t + 0.6);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    out(sum.connect(drive).connect(lp).connect(g), 1, 0.6);
  }

  // Impact: a falling sine thump with a burst of dark noise.
  function impact(t, level, low = 32) {
    const o = osc('sine', 120, t, 2.2);
    o.frequency.exponentialRampToValueAtTime(low, t + 0.7);
    out(o.connect(env(t, level, 0.003, 2.0)), 1, 0.25);
    const n = noise(t, 1.0);
    const lp = filt('lowpass', 2500, 0.5);
    lp.frequency.setValueAtTime(3500, t);
    lp.frequency.exponentialRampToValueAtTime(300, t + 0.8);
    out(n.connect(lp).connect(env(t, level * 0.5, 0.002, 0.9)), 1, 0.6);
  }

  function subDrop(t, level, dur = 2.6) {
    const o = osc('sine', 95, t, dur);
    o.frequency.exponentialRampToValueAtTime(27, t + dur);
    out(o.connect(env(t, level, 0.01, dur)), 1, 0);
  }

  // Whoosh through a cut: builds before it, peaks on it, sweeps across.
  function whoosh(t, level) {
    const t0 = t - 0.4, t1 = t + 0.35;
    const n = noise(t0, t1 - t0);
    const bp = filt('bandpass', 500, 1.4);
    bp.frequency.setValueAtTime(400, t0);
    bp.frequency.exponentialRampToValueAtTime(5000, t);
    bp.frequency.exponentialRampToValueAtTime(900, t1);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(level, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t1);
    const p = ctx.createStereoPanner();
    p.pan.setValueAtTime(-0.8, t0);
    p.pan.linearRampToValueAtTime(0.8, t1);
    out(n.connect(bp).connect(g).connect(p), 1, 0.35);
  }

  function crash(t, level) {
    const n = noise(t, 1.8);
    out(n.connect(filt('highpass', 5500, 0.4)).connect(env(t, level, 0.002, 1.7)), 1, 0.5);
  }

  // Low tom, closer to a taiko than a kick.
  function tom(t, level) {
    const o = osc('sine', 150, t, 0.6);
    o.frequency.exponentialRampToValueAtTime(48, t + 0.18);
    out(o.connect(env(t, level, 0.002, 0.55)), 1, 0.22);
    const n = noise(t, 0.05);
    out(n.connect(filt('lowpass', 1800)).connect(env(t, level * 0.25, 0.001, 0.04)), 1, 0.1);
  }

  function clap(t, level) {
    const bp = filt('bandpass', 1300, 0.9);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t);
    for (let k = 0; k < 3; k++) {
      g.gain.setValueAtTime(level, t + k * 0.011);
      g.gain.exponentialRampToValueAtTime(level * 0.15, t + k * 0.011 + 0.009);
    }
    g.gain.setValueAtTime(level * 0.6, t + 0.034);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
    out(noise(t, 0.25).connect(bp).connect(g), 1, 0.5);
  }

  function hat(t, level) {
    out(noise(t, 0.06).connect(filt('highpass', 8000)).connect(env(t, level, 0.001, 0.045)), 1, 0.08, rnd() * 0.6 - 0.3);
  }

  function snare(t, level) {
    out(noise(t, 0.2).connect(filt('bandpass', 2200, 0.7)).connect(env(t, level, 0.001, 0.16)), 1, 0.35);
    out(osc('triangle', 190, t, 0.1).connect(env(t, level * 0.6, 0.001, 0.08)), 1, 0.2);
  }

  // Snare roll speeding up from eighths to thirty-seconds, getting louder.
  function roll(t0, t1, from, to) {
    let t = t0;
    while (t < t1 - 0.01) {
      const p = (t - t0) / (t1 - t0);
      snare(t, from + (to - from) * p);
      t += BEAT / (2 + Math.floor(p * 3) * 2);
    }
  }

  // Ostinato pluck: saw and square under a snapping low-pass.
  function pluck(t, f, level, cutoff, pan) {
    const lp = filt('lowpass', cutoff * 4, 3);
    lp.frequency.setValueAtTime(cutoff * 4, t);
    lp.frequency.exponentialRampToValueAtTime(cutoff, t + 0.16);
    osc('sawtooth', f, t, 0.25).connect(lp);
    osc('square', f, t, 0.25, -8).connect(lp);
    out(lp.connect(env(t, level, 0.003, 0.22)), 1, 0.25, pan);
  }

  // Supersaw pad over a span.
  function pad(t0, t1, notes, level, cutoff = 1500) {
    const lp = filt('lowpass', cutoff, 0.5);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.linearRampToValueAtTime(level, t0 + 0.25);
    g.gain.setValueAtTime(level, t1 - 0.12);
    g.gain.linearRampToValueAtTime(0.0001, t1);
    notes.forEach((n, i) => {
      for (const d of [-14, -6, 0, 6, 14]) {
        const o = osc('sawtooth', hz(n), t0, t1 - t0, d);
        const p = ctx.createStereoPanner();
        p.pan.value = ((i % 2) * 2 - 1) * 0.3 + d / 60;
        o.connect(p).connect(lp);
      }
    });
    out(lp.connect(g), 1, 0.45);
  }

  // Bass: root in eighths, ducked on each beat like a pumping sidechain.
  function bass(t0, t1, note, level) {
    const lp = filt('lowpass', 380, 1);
    osc('sawtooth', hz(note), t0, t1 - t0).connect(lp);
    osc('sine', hz(note), t0, t1 - t0).connect(lp);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    for (let t = t0; t < t1 - 0.01; t += BEAT / 2) {
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(level, t + 0.04);
      g.gain.exponentialRampToValueAtTime(level * 0.2, t + BEAT / 2 - 0.01);
    }
    g.gain.setValueAtTime(0, t1);
    out(lp.connect(g), 1, 0.05);
  }

  function stab(t, notes, level) {
    const lp = filt('lowpass', 4000, 2);
    lp.frequency.setValueAtTime(5000, t);
    lp.frequency.exponentialRampToValueAtTime(700, t + 0.3);
    for (const n of notes) for (const d of [-10, 10]) osc('sawtooth', hz(n), t, 0.45, d).connect(lp);
    out(lp.connect(env(t, level, 0.004, 0.42)), 1, 0.5);
  }

  // Choir: saws through two vowel formants, with a slow vibrato.
  function choir(t0, t1, notes, level) {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.linearRampToValueAtTime(level, t0 + 0.9);
    g.gain.setValueAtTime(level, t1 - 1.2);
    g.gain.linearRampToValueAtTime(0.0001, t1);
    const f1 = filt('bandpass', 750, 6), f2 = filt('bandpass', 1150, 7), f3 = filt('bandpass', 2600, 8);
    const sum = ctx.createGain();
    sum.connect(f1); sum.connect(f2); sum.connect(f3);
    const vib = osc('sine', 5.2, t0, t1 - t0);
    const va = ctx.createGain();
    va.gain.value = 7;
    vib.connect(va);
    for (const n of notes) for (const d of [-8, 8]) {
      const o = osc('sawtooth', hz(n), t0, t1 - t0, d);
      va.connect(o.detune);
      o.connect(sum);
    }
    const mix = ctx.createGain();
    mix.gain.value = 3;
    f1.connect(mix); f2.connect(mix); f3.connect(mix);
    out(mix.connect(g), 1, 0.7);
  }

  // Bell: inharmonic sine partials with a long ring.
  function bell(t, notes, level, dur = 2.8) {
    for (const n of notes) for (const [ratio, amp] of [[1, 1], [2.76, 0.4], [5.4, 0.18]]) {
      out(osc('sine', hz(n) * ratio, t, dur).connect(env(t, level * amp, 0.004, dur / ratio)), 1, 0.45);
    }
  }

  function chime(t, level) {
    [['E6', 0], ['A6', 0.11]].forEach(([n, dt]) => {
      out(osc('sine', hz(n), t + dt, 1.0).connect(env(t + dt, level, 0.003, 0.9)), 1, 0.35);
      out(osc('triangle', hz(n) * 2, t + dt, 0.4).connect(env(t + dt, level * 0.25, 0.003, 0.3)), 1, 0.3);
    });
  }

  function keyClick(t, level) {
    out(noise(t, 0.03).connect(filt('bandpass', 3500, 2)).connect(env(t, level, 0.001, 0.025)), 1, 0.1);
    out(osc('sine', 180, t, 0.05).connect(env(t, level * 0.6, 0.001, 0.04)), 1, 0);
  }

  // Data chatter: quiet random high blips while zypper prints.
  function chatter(t0, t1, level) {
    for (let t = t0; t < t1; t += BEAT / 4) {
      const f = 1800 + rnd() * 3000;
      out(osc('square', f, t, 0.03).connect(filt('bandpass', f, 4)).connect(env(t, level, 0.001, 0.025)), 1, 0.1, rnd() - 0.5);
    }
  }

  // Tape rewind: chirps sweeping upward faster and faster.
  function rewind(t0, t1, level) {
    for (let t = t0, k = 0; t < t1 - 0.02; k++) {
      const d = Math.max(0.03, 0.09 - k * 0.006);
      const o = osc('sawtooth', 700, t, d);
      o.frequency.exponentialRampToValueAtTime(2800 + k * 150, t + d);
      out(o.connect(filt('bandpass', 2000, 1.5)).connect(env(t, level, 0.002, d, 'lin')), 1, 0.2, Math.sin(k) * 0.5);
      t += d;
    }
  }

  // Power-off: a quick downward zap.
  function zap(t, level) {
    const o = osc('sawtooth', 2400, t, 0.25);
    o.frequency.exponentialRampToValueAtTime(40, t + 0.22);
    out(o.connect(filt('lowpass', 3000)).connect(env(t, level, 0.002, 0.22)), 1, 0.3);
  }

  // ---- Arrangement ----

  // Cold open: drone, a clock speeding up, lines punctuated with soft booms.
  drone(0, T.betterWay, ['A1', 'E2'], 0.07);
  for (let t = 0.05, k = 0; t < T.collapse; k++) {
    const step = t < T.errors[0] ? BEAT : t < T.chaos ? BEAT / 2 : BEAT / 4;
    tick(t, t < T.errors[0] ? 0.08 : 0.13, k % 2 === 0);
    t += step;
  }
  impact(T.line1, 0.22, 30);
  impact(T.line2, 0.25, 30);
  bell(T.line1, ['A5'], 0.05, 3);
  T.errors.forEach((t, i) => glitch(t, 0.55 + i * 0.05, 100 + i));
  for (let k = 0; k < 4; k++) glitch(T.chaos + k * (BEAT / 4) * 1.5, 0.35, 200 + k);
  riser(T.errors[0], T.collapse, 0.4);
  zap(T.collapse, 0.4);
  swell(T.betterWay + 0.2, T.reveal - 0.02, 0.4);
  subDrop(T.betterWay + 0.4, 0.12, 1.2);

  // Reveal.
  braam(T.reveal, ['A1', 'E2', 'A2', 'C3', 'E3'], 0.75, 4.8);
  impact(T.reveal, 1.0);
  subDrop(T.reveal, 0.7);
  crash(T.reveal, 0.25);
  pad(T.reveal + 0.4, bar(7), CHORD.Am.pad, 0.07, 900);
  bell(T.wordmark, ['A5', 'E6', 'C7'], 0.07);
  whoosh(T.wordmark, 0.25);
  impact(T.tagline, 0.3, 36);
  bell(T.tagline + BEAT, ['E6'], 0.05);
  roll(bar(6, 2), bar(7), 0.05, 0.35);
  riser(bar(6), bar(7), 0.3);

  // Feature groove: bars 7-18, one chord per bar.
  for (let b = 7; b <= 18; b++) {
    const ch = CHORD[PROGRESSION[(b - 7) % 4]];
    const t0 = bar(b), t1 = bar(b + 1);
    // Half a bar of tape rewind instead of the groove.
    const rewindBar = b === 17;
    const grooveEnd = rewindBar ? T.rewind : t1;
    pad(t0, t1, ch.pad, 0.035, 1100 + (b - 7) * 120);
    bass(t0, grooveEnd, ch.root, 0.14);
    const cutoff = 900 + (b - 7) * 160;
    for (let s = 0; s < 16; s++) {
      const t = t0 + s * (BEAT / 4);
      if (t >= grooveEnd) break;
      const f = hz(ch.arp[[0, 1, 2, 1, 3, 1, 2, 1][s % 8]]);
      pluck(t, f, s % 4 === 0 ? 0.05 : 0.034, cutoff, s % 2 ? 0.35 : -0.35);
      if (b >= 10) hat(t, s % 2 ? 0.05 : 0.025);
    }
    for (const beat of [0, 2, 2.5]) if (bar(b, beat) < grooveEnd) tom(bar(b, beat), beat === 0 ? 0.48 : 0.34);
    for (const beat of [1, 3]) if (bar(b, beat) < grooveEnd) clap(bar(b, beat), 0.18);
  }
  for (const c of CUTS) {
    whoosh(c, 0.35);
    if (c !== CUTS[0]) crash(c, 0.13);
    impact(c, 0.35, 40);
  }
  chime(T.trayAlert, 0.16);
  chatter(CUTS[2] + 0.1, T.terminalPrompt, 0.012);
  keyClick(T.typedY, 0.35);
  chatter(T.typedY + 0.1, T.typedY + 1.2, 0.015);
  rewind(T.rewind, T.rewindLand - 0.05, 0.08);
  swell(T.rewind + 0.2, T.rewindLand, 0.3);
  impact(T.rewindLand, 0.45, 38);
  bell(T.rewindLand, ['A5', 'E6'], 0.05);

  // Stats: a stab and a tom on every beat, a roll into an eighth of silence.
  for (let i = 0; i < 8; i++) {
    const t = bar(19, i);
    const ch = i < 4 ? CHORD.F : CHORD.G;
    stab(t, ch.pad.slice(1), 0.12 + i * 0.012);
    tom(t, 0.55);
    if (i === 0) impact(t, 0.45, 40);
  }
  pad(bar(19), bar(20), CHORD.F.pad, 0.03, 2000);
  pad(bar(20), T.dropout, CHORD.G.pad, 0.04, 2600);
  roll(bar(20), T.dropout, 0.08, 0.4);
  riser(bar(19, 2), T.dropout, 0.5, 11000);

  // Finale: the last hit resolves to A major.
  braam(T.finale, ['A1', 'E2', 'A2', 'C#3', 'E3'], 0.8, 5.5);
  impact(T.finale, 1.0);
  subDrop(T.finale, 0.7, 3);
  crash(T.finale, 0.3);
  choir(T.finale, DURATION, ['A3', 'C#4', 'E4', 'A4'], 0.08);
  pad(T.finale + 0.3, DURATION, CHORD.A.pad, 0.035, 1600);
  bell(T.finale, ['A5', 'C#6', 'E6'], 0.07, 4);
  keyClick(T.click, 0.4);
  impact(T.click, 0.5, 45);
  bell(T.click, ['C#6', 'E6', 'A6'], 0.08, 3.5);
  whoosh(T.click + 0.05, 0.2);
  tom(T.endCard, 0.3);

  return ctx.startRendering();
}

// tanh drive curve; k sets how hard it bites.
function shaper(k) {
  const n = 2048, c = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    c[i] = Math.tanh(k * x) / Math.tanh(k);
  }
  return c;
}

// Staircase curve, a cheap bit-crusher.
function stepped(levels) {
  const n = 2048, c = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    c[i] = Math.round(x * levels) / levels;
  }
  return c;
}

// Stereo reverb impulse: decaying noise that darkens as it fades, with a few
// early reflections.
function impulse(ctx, seconds, rnd) {
  const len = Math.floor(seconds * SR);
  const buf = ctx.createBuffer(2, len, SR);
  for (let c = 0; c < 2; c++) {
    const d = buf.getChannelData(c);
    let lp = 0;
    for (let i = 0; i < len; i++) {
      const tt = i / SR;
      const amp = Math.exp((-6.9 * tt) / seconds);
      const a = 0.25 + 0.7 * Math.exp(-tt * 1.5);   // one-pole coefficient: bright, then dark
      lp += a * ((rnd() * 2 - 1) - lp);
      d[i] = lp * amp * (tt < 0.012 ? tt / 0.012 : 1);
    }
    for (const [ms, g] of [[11, 0.5], [19, 0.35], [29, 0.3], [43, 0.2]]) {
      d[Math.floor(((ms + c * 3) / 1000) * SR)] += g;
    }
  }
  return buf;
}

