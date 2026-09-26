# Clipwise

A private, single-user, knowledge-first short-form interface over **timestamped sections of long-form YouTube videos**.

> We don't cut the YouTube video. We cut the viewing experience.

- **Discovery:** a fast, vertically snapping feed of *ideas* (title, hook, topic, length, source). No video loads while you browse.
- **Learning:** tap **Watch** and the original video plays inside the app, starting at the clip's start and pausing at its end. Then choose **Next**, **Continue original**, **Go deeper**, **Replay**, **Save**, or **More / Less like this**.
- The feed adapts locally to what you finish, save and rate, and always keeps a share of exploratory picks.
- Add your own clips by pasting a transcript (auto-segmented, then reviewed by you) or by entering timestamps manually.

Everything runs and is stored on your machine. No accounts, analytics or API keys.

## Install & run

Requires **Node.js 20.9+** (22 LTS recommended).

```bash
cd clipwise
npm install
npm run dev
```

Open <http://127.0.0.1:3000>. The first request creates the database and seeds demo content.

**On your phone:** `npm run dev:lan`, then open `http://<your-computer's-LAN-IP>:3000` on the phone (same Wi-Fi). Use *Share → Add to Home Screen* for the app-like PWA. Note: the dev server then listens on your whole LAN, and the app has no login.

Production mode: `npm run build && npm start`. The service worker only registers in production.

## Database

SQLite file at `clipwise/data/clipwise.db` (git-ignored). Override the location with `CLIPWISE_DB_PATH`. The schema lives in `src/lib/db/migrations.ts` and is applied automatically on startup (versioned with `PRAGMA user_version`).

## Reset

| What | How |
| --- | --- |
| Forget learned preferences (keep history and saves) | Topics → *Reset preferences*, or Settings → *Reset recommendations* |
| Delete watch history and feedback (keep saves) | Settings → *Clear history* |
| Wipe everything back to the demo content | Settings → *Reset demo database*, or `npm run db:reset` |
| Start completely fresh | stop the server, `rm -rf data/`, `npm run dev` |

## Adding videos

**Transcript ingest** (Add → *From transcript*)
1. Paste a YouTube URL (`watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `live/` all work). Title and channel are fetched from YouTube's public oEmbed endpoint when online. The video length is optional.
2. Paste a timestamped transcript. Supported: `0:32 text`, `[01:02:11] text`, `(1:25) text`, YouTube's *Show transcript* copy (time on its own line), SRT and WebVTT. *Paste a sample* fills in an example.
3. **Generate candidate clips**, then review each one: edit the title, hook, times, topic, tags and summary, **Preview** it in an inline player, delete bad ones, and **Approve** the good ones.
4. **Save approved clips**. Only approved clips reach the feed.

**Manual clip** (Add → *Manual clip*): pick a video already in your library (or paste a new URL), then enter title, hook, topic, start, end, tags and summary. **Preview** checks the timestamps. After saving, the form stays on the same video and starts the next clip where the last one ended.

**Library** (Add → *Library*, or Settings): every video with its clips. Here you can edit or delete clips, add a clip to a video, or delete a video.

## Demo content

Six real, public educational videos (Ray Dalio, CGP Grey, 3Blue1Brown, Veritasium, Kurzgesagt, and a Roman-inflation explainer) with 20 clips across economics, political power, machine learning, physics, philosophy and ancient Rome. The video IDs and titles were checked against public web indexes. **YouTube itself was unreachable from the build environment**, so:

- Clip boundaries are **approximate** except the 3Blue1Brown clips taken from that video's published chapter markers. Unverified clips show an *Approximate timestamps* badge in Watch mode that links to the editor. Saving an edit marks the clip as verified.
- One video's channel is unknown and gets filled in from YouTube the first time you watch it. Durations are also filled in from the player.

## Optional AI

Off by default, and the app never needs it. In **Settings → Optional AI enrichment** you can point transcript ingest at:

- **Ollama** (e.g. `http://127.0.0.1:11434`, model `llama3.1:8b`), or
- any **OpenAI-compatible** endpoint (LM Studio, llama.cpp server, OpenAI…). A key, if one is needed, goes in the `CLIPWISE_AI_API_KEY` environment variable and is never stored in the database.

When enabled and reachable, the model rewrites each segment's title, hook, summary, topic and tags. If it's unreachable, or fails for a segment, the heuristic output is used and the review screen says so.

## How recommendations work

All local and deterministic (`src/lib/recommend/engine.ts`):

- **Profile** (derived from interactions, never stored). Each interaction adds a weight to its clip's topic and (×0.6) to its tags, decayed with a 21-day half-life and squashed to −1…1 with `tanh`. Weights: opened +0.5, completed +1.5 (× completion), continued original +1.5, saved +2.5, more-like-this +3, skipped −1, unsaved −1, less-like-this −3.5.
- **Score** = quality + 1.2·topic affinity + 0.8·mean tag affinity + 0.6·relatedness to recently watched clips + 0.25·novelty − watched penalty (1.5 completed / 0.6 opened, fading over ~a month) − 0.15 per recent impression − 2 if you said *less like this* to that exact clip − 0.3 if already saved + small seeded jitter.
- **Serendipity:** by default 25% of slots (adjustable 0–50% in Settings) are filled from topics you have *not* shown affinity for. Runs of 3+ cards on one topic are broken up when a close alternative exists.
- **Go deeper** ranks explicit clip relationships first, then shared tags, same topic, and the next clip in the same video.

The Topics screen shows the learned weights as coarse arrows (↑ ↗ → ↘ ↓), not numbers.

## Architecture

```
src/
  app/                 Next.js App Router pages + JSON route handlers (app/api/**)
  components/          Client UI: feed/, watch/, player/ (YouTube IFrame API), ingest/, …
  lib/
    domain/            Pure helpers: timestamps, YouTube URL parsing, clip validation
    db/                better-sqlite3 connection, migrations, demo seed
    repo/              Small SQL data-access functions (take a db handle; easy to test)
    recommend/         Pure scoring/feed engine + a thin DB-backed service
    ingest/            transcript → cues → segments → enrichment pipeline; optional LLM providers
    server/            API error handling, same-origin guard, oEmbed lookup
tests/unit/            Vitest: parsing, validation, segmentation, recommendations, DB, player boundary logic
tests/e2e/             Playwright acceptance flow (uses a fake IFrame API; see below)
```

Key decisions:
- **YouTube stays intact.** The app stores `videoId + start + end` and drives the official IFrame Player (via `youtube-nocookie.com`). A 250 ms poll pauses playback at the end marker. `SourceVideo.mediaKind` (`youtube` | `local`) is the seam for user-owned media and real clip rendering later.
- **One player per Watch session.** *Next* and *Go deeper* swap the clip in place (`loadVideoById`, or a seek within the same video), so mobile browsers keep the tap gesture and autoplay keeps working. The boundary only arms once the playhead is seen inside the segment, so a stale position just after a load can't end a clip early.
- **Boring persistence.** One SQLite file, hand-written SQL, versioned migrations, all data-access functions take a db handle. There is no ORM, and no services beyond Next.js itself.
- **Pluggable ingest stages.** The parser, segmenter (`segmentTranscript`) and enricher are separate functions. An AI segmenter, Whisper transcription or automatic transcript fetching can replace a stage without touching the rest.
- **Local-only safety.** The server binds to 127.0.0.1 by default. Mutating API calls must be JSON and same-origin, so other websites can't reset your data. No third-party scripts run except YouTube's player.

## Scripts

```bash
npm run dev          # dev server on 127.0.0.1:3000
npm run dev:lan      # dev server reachable from your phone
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npm test             # unit tests (vitest)
npm run test:e2e     # Playwright acceptance tests (own DB + port 3100)
npm run build        # production build
npm run check        # typecheck + lint + unit tests + build
npm run db:reset     # wipe data, restore demo content
```

The E2E suite swaps `https://www.youtube.com/iframe_api` for a fake player (`tests/e2e/fake-youtube.js`) that runs 30× faster. It needs no network and checks the app's player logic end to end. It does not test YouTube itself. Playwright uses its own Chromium (`npx playwright install chromium`), or set `CHROMIUM_PATH`.

## Known limitations

- **Needs internet for playback**, and some videos disallow embedding. The app detects this (errors 101/150) and offers *Open on YouTube* instead.
- **Autoplay on mobile:** iOS/Safari may block playback with sound after navigation. The app then asks you to tap the video once. *Next* and *Go deeper* reuse the same player, so they usually keep playing.
- **End-of-segment precision** is about ±0.25 s (polling). YouTube also seeks to the nearest keyframe, so starts can be up to a second early.
- **Heuristic segmentation** works best with headed or chaptered transcripts. On raw speech it produces sensible 30 s–5 min chunks, but titles are drafted from sentences and usually need editing. Transcripts must be pasted; there's no automatic retrieval yet.
- **Demo timestamps are approximate** (see above).
- Recommendations are intentionally simple (topic/tag affinities). There are no embeddings, so "related" means shared tags, topics or explicit links.
- Single user, no auth: don't expose `dev:lan` on untrusted networks.
- Real YouTube playback was not testable in the build sandbox (YouTube was blocked by its network policy). The player logic was tested against a faithful fake of the IFrame API.
