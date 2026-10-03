// Pieces more than one scene uses: the feature text block, the logo, and the
// small line icons of a Plasma panel.

import { css, h, ep, E, lerp, prog } from '../ease.js';

// The Tumbleweed mark's path lives in data/icons/styles/tumbleweed.svg and
// is read at start-up (main.js), so the promo always draws the app's own mark.
// This viewBox crops the 128x128 icon box to the mark itself.
export const LOGO_VIEWBOX = '2 33 124 62';
export const LOGO_ASPECT = 124 / 62;

export function logoSvg(shared, { cls = '', fill = 'currentColor', inner = '' } = {}) {
  return `<svg class="${cls}" viewBox="${LOGO_VIEWBOX}" xmlns="http://www.w3.org/2000/svg">
    <g transform="${shared.logoTransform}"><path d="${shared.logoPath}" fill="${fill}"/>${inner}</g>
  </svg>`;
}

// Eyebrow, a title whose lines rise out of a mask one after another, and a
// body paragraph. `title` is an array of lines; wrap words in <em> to colour them.
export function textBlock({ eyebrow, title, body, x, y, orange = false, align = 'left', width = 760 }) {
  const el = h(`<div class="tb${orange ? ' orange' : ''}" style="left:${x}px;top:${y}px;width:${width}px;text-align:${align}">
    <div class="eyebrow" style="${align === 'center' ? 'justify-content:center' : ''}">${eyebrow}</div>
    <div class="title">${title.map((l) => `<span class="line"><span>${l}</span></span>`).join('')}</div>
    ${body ? `<div class="body" style="${align === 'center' ? 'margin-left:auto;margin-right:auto' : ''}">${body}</div>` : ''}
  </div>`);
  return {
    el,
    eyebrow: el.querySelector('.eyebrow'),
    lines: [...el.querySelectorAll('.line > span')],
    body: el.querySelector('.body'),
  };
}

export function animateText(tb, t, t0) {
  const pe = ep(t, t0, t0 + 0.8, E.outExpo);
  css(tb.eyebrow, {
    opacity: String(pe),
    transform: `translateX(${lerp(-40, 0, pe)}px)`,
    'letter-spacing': `${lerp(0.9, 0.38, pe)}em`,
  });
  tb.lines.forEach((ln, i) => {
    const p = ep(t, t0 + 0.12 + i * 0.1, t0 + 1.05 + i * 0.1, E.outExpo);
    css(ln, {
      transform: `translateY(${lerp(110, 0, p)}%) rotate(${lerp(4, 0, p)}deg)`,
      filter: `blur(${(1 - p) * 8}px)`,
    });
  });
  if (tb.body) {
    const pb = ep(t, t0 + 0.45, t0 + 1.35, E.outCubic);
    css(tb.body, {
      opacity: String(pb),
      transform: `translateY(${lerp(24, 0, pb)}px)`,
      filter: `blur(${(1 - pb) * 6}px)`,
    });
  }
}

// Line icons for a Plasma panel, 24-unit grid like the tray styles.
const ICON = (d, extra = '') =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"${extra}>${d}</svg>`;

export const ICONS = {
  clipboard: ICON('<rect x="6" y="4.5" width="12" height="16" rx="2"/><path d="M9.5 4.5V3.5h5v1"/><path d="M9 10h6M9 13.5h6M9 17h4"/>'),
  network: ICON('<path d="M3 9.5a13 13 0 0 1 18 0"/><path d="M6 13a8.5 8.5 0 0 1 12 0"/><path d="M9 16.5a4 4 0 0 1 6 0"/><circle cx="12" cy="19.5" r="0.8" fill="currentColor"/>'),
  volume: ICON('<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/><path d="M18 6.5a7.5 7.5 0 0 1 0 11"/>'),
  battery: ICON('<rect x="3" y="7.5" width="16" height="9" rx="2"/><path d="M21 10.5v3"/><rect x="5" y="9.5" width="9" height="5" rx="0.8" fill="currentColor" stroke="none"/>'),
  chevron: ICON('<path d="M7 14.5 12 9.5l5 5"/>'),
  files: ICON('<path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'),
  terminal: ICON('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 10l3 2.5L7 15M12.5 15.5h4.5"/>'),
  browser: ICON('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.8 5.2 3.8 8.5s-1.2 6.1-3.8 8.5c-2.6-2.4-3.8-5.2-3.8-8.5S9.4 5.9 12 3.5z"/>'),
  launcher: ICON('<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>'),
  cursor: `<svg viewBox="0 0 24 24"><path d="M5 2.5v17.2l4.6-4.3 3 6.6 3-1.4-3-6.4h6.2z" fill="#fff" stroke="#111" stroke-width="1.3" stroke-linejoin="round"/></svg>`,
};

// Ripple rings for an alert: n rings starting at t0, `gap` apart.
export function ringState(t, t0, i, gap = 0.22, life = 0.9) {
  const p = prog(t, t0 + i * gap, t0 + i * gap + life);
  return { scale: lerp(0.3, 3.2, E.outCubic(p)), opacity: p > 0 && p < 1 ? (1 - p) * 0.9 : 0 };
}
