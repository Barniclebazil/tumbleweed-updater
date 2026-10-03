// The one clock both the picture and the score read from.
//
// Everything is placed on a 128 BPM bar grid, so a cut in the picture and a
// hit in the score land on the same sample: 1 bar = 1.875 s, 24 bars = 45 s.

export const BPM = 128;
export const BEAT = 60 / BPM;
export const BAR = 4 * BEAT;

// Time in seconds of bar `b`, plus `beat` beats (fractions allowed).
export const bar = (b, beat = 0) => b * BAR + beat * BEAT;

export const DURATION = bar(24);

// When each scene is on screen. Neighbours overlap slightly so that one can
// leave while the next arrives; each scene handles its own way in and out.
export const SCENES = {
  opening:   [0, bar(4) + 0.05],
  reveal:    [bar(4), bar(7) + 0.12],
  tray:      [bar(7) - 0.05, bar(10) + 0.12],
  list:      [bar(10) - 0.05, bar(13) + 0.12],
  terminal:  [bar(13) - 0.05, bar(16) + 0.12],
  snapshots: [bar(16) - 0.05, bar(19) + 0.05],
  stats:     [bar(19), bar(21) + 0.05],
  finale:    [bar(21), bar(24)],
};

// Named moments. The score schedules its hits from these and the scenes time
// their motion from them, which is what keeps the two in step.
export const T = {
  line1: 0.35,
  line2: bar(1),
  errors: [bar(2, 0), bar(2, 1), bar(2, 2), bar(2, 3)],
  chaos: bar(3),
  collapse: bar(3, 1),
  betterWay: bar(3, 1.5),
  reveal: bar(4),
  introducing: bar(4, 3),
  wordmark: bar(5),
  tagline: bar(6),
  groove: bar(7),
  trayAlert: bar(8),
  listRows: bar(10, 0.5),
  terminalPrompt: bar(14),
  typedY: bar(14, 2),
  rewind: bar(17, 2),
  rewindLand: bar(18),
  stats: bar(19),
  dropout: bar(20, 3.5),
  finale: bar(21),
  cursor: bar(21, 2),
  click: bar(22),
  endCard: bar(22, 1),
  fadeOut: bar(23, 2.75),
};

// Scene changes that get a whoosh and a zoom-blur.
export const CUTS = [bar(7), bar(10), bar(13), bar(16)];

// Hits that flash and shake the picture: [time, strength 0..1].
export const IMPACTS = [
  [T.errors[0], 0.25], [T.errors[1], 0.25], [T.errors[2], 0.3], [T.errors[3], 0.35],
  [T.chaos, 0.4],
  [T.reveal, 1.0],
  [T.trayAlert, 0.18],
  [T.rewindLand, 0.3],
  ...Array.from({ length: 8 }, (_, i) => [bar(19, i), i === 0 ? 0.5 : 0.22]),
  [T.finale, 1.0],
  [T.click, 0.7],
];

// One chord per bar through the feature section: i-VI-III-VII in A minor.
export const PROGRESSION = ['Am', 'F', 'C', 'G'];
