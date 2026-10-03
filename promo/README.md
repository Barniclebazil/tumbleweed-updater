# Promotional video

A 45-second promotional video for Tumbleweed Updater, 1920x1080 at 60 fps, with a synthesised score. The copy in the video is deliberately overblown; the claims in it are all true of the app.

## Render

Run these from the repository root. They need `chromium`, `node` (22 or later) and `ffmpeg`, all from the main openSUSE repositories. No npm packages are used.

```sh
node promo/render.mjs                  # full render into promo/out/ (about 5 minutes)
node promo/render.mjs --draft          # 960x540, 30 fps preview in promo/build/draft.mp4 (under a minute)
node promo/render.mjs --stills         # PNG stills at key moments in promo/build/stills/
node promo/render.mjs --stills 9,20.5  # stills at chosen times, in seconds
node promo/render.mjs --only audio     # just the score, in promo/build/score-norm.wav
```

Further options:

1. `--workers N` sets how many browsers render in parallel (default 4).
2. `--samples N` sets motion-blur sub-frames per frame (default 4; 1 turns it off).
3. `--keep` keeps the lossless intermediate segments in `promo/build/`.
4. `--only video|audio|poster` renders one part.

A full render produces:

1. `out/tumbleweed-updater-promo.mp4`: H.264 and AAC, for anywhere.
2. `out/tumbleweed-updater-promo-av1.mp4`: 10-bit AV1 and AAC, smaller and with less banding.
3. `out/poster.png`: a 3840x2160 still of the end card.

## Watch it in a browser

The page fetches the app's icon from `data/icons/`, so serve the repository root rather than opening the file directly:

```sh
python3 -m http.server 8000
```

Then open `http://localhost:8000/promo/scene/index.html?play` and click. `?t=12.5` shows a single frame.

## How it works

1. `scene/index.html` is a 1920x1080 stage. Every frame is a function of the time alone: CSS animations and transitions are switched off, and randomness is seeded.
2. `scene/timeline.js` is the one clock. It places every scene and hit on a 128 BPM bar grid (1 bar = 1.875 s), and both the picture and the score read their cue times from it. Moving a cue there moves the cut and its sound together.
3. `scene/scenes/*.js` are the eight scenes. Each builds its elements once and sets their styles for a given time.
4. `scene/fx.js` draws the WebGL background (nebula, light rays, lens flare) and the particles.
5. `scene/score.js` synthesises the score with Web Audio in an `OfflineAudioContext`.
6. `render.mjs` serves the repository, drives Chromium over the DevTools protocol, takes four screenshots per frame spread across half a frame (a 180-degree film shutter), and has ffmpeg average them into motion-blurred frames. The score is brought to -14 LUFS with a single gain, so its quiet and loud passages keep their difference.

The logo is read from `data/icons/styles/tumbleweed.svg`. The window, terminal, tray and snapshot mock-ups use the app's real strings and the colours of the screenshots in `screenshots/`. If those strings change in the app, update the scenes to match.

## Optional software

Nothing else is required. Kdenlive (`sudo zypper install kdenlive`) is useful for trimming the result or laying a voice or other music over it.
