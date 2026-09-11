# TubeAutonomy — independent YouTube AI studio

Version 0.2.0. A standalone upgrade of the uploaded project. Uses its own service,
owner token, Google OAuth client, local model and data volume. No BharatShop API,
repository, database or credentials are needed or included.

## Start here

**Lowest recurring software cost:** run on a computer you control with Docker and
Ollama. The model uses your hardware; electricity and internet still cost money.
CPU rendering and speech work without paid APIs. A 4B model needs several GB of
memory; generation speed depends on your machine. Android-only deployment is not
validated; Render is easier to manage from a phone, but does not supply free model
compute or durable video storage.

Install Node.js 22+ and Docker Desktop/Engine. In this folder:

```bash
npm run setup
docker compose up -d --build
docker compose exec ollama ollama pull gemma3:4b
```

Open http://localhost:3000/login. Use `OWNER_TOKEN` from your new `.env` to sign in.
Keep `.env` private. `npm run setup` preserves an existing configuration. The
Ollama port is internal to Docker; the studio is bound to this computer's loopback
interface. Do not expose it directly to the internet without HTTPS.

1. Create a channel in **Channels**.
2. Use **Production → Run full pipeline**. With YouTube disabled, research is
   clearly labeled AI brainstorming. The model generates ideas, a plan, script,
   review notes, thumbnails and an original narrated slide video.
3. The pipeline runs in the background. Review progress in Production and Agent
   Control. Run IDs and results persist; an interrupted run is marked failed.
4. In **Publishing**, open **Review video and sources**. Watch the actual MP4,
   inspect the script, verify claims and download files.
5. Connect Google before uploading. Approve, then click Publish now. Pipeline
   outputs default to private. Change final visibility in YouTube Studio.

### Without Docker

Install Node.js 22+, Ollama, FFmpeg (including ffprobe), and `espeak-ng` yourself.
For example, Debian/Ubuntu provides `ffmpeg espeak-ng fonts-dejavu-core` through
its package manager. Install Ollama following its official instructions, then:

```bash
npm ci
npm run setup
ollama pull gemma3:4b
npm run build
npm start
```

Ollama must be running at the `OLLAMA_BASE_URL` in `.env`. The root start command
loads `.env`, starts the API privately on port 4000 and serves the dashboard on
port 3000 (or `$PORT`). Both processes stop together. Do not launch a separate
worker or multiple app instances against this file store.

## Render deployment — separate repository

Create a NEW GitHub repository named `tubeautonomy-ai`. Put the CONTENTS of this
folder at the repository root, including package.json, Dockerfile and render.yaml.
Do not upload node_modules, .env, data or output. Do not use BharatShop's repository.

**Free preview:** in Render choose **New → Blueprint**, connect the new repository
and select `render.yaml`. It creates `tubeautonomy-preview`. After deployment,
copy its generated OWNER_TOKEN from Render's Environment page, then sign in at
`https://YOUR-SERVICE.onrender.com/login`. This is a DEMO, visibly marked. Its
uploads and metrics are simulations; its local data can disappear on restart.
No Google credentials should be added to this free preview.

**Live service:** `render-live.yaml` is an OPTIONAL PAID configuration, not the
default. Review pricing first. It defines a separate service and persistent disk
mounted at `/var/tube`. Use the same repository, Docker runtime, Dockerfile at
root, health check `/api/health`, and the environment values in that file. You
must provide a reachable, authenticated HTTPS Ollama gateway; localhost on Render
is not your home computer. Do not expose an unprotected Ollama server publicly.
Alternatively choose a supported paid LLM explicitly. Rendering memory/CPU needs
may exceed the smallest plan. This configuration has not been deployed or load-tested.

Render free web services sleep after 15 minutes without traffic, lose local files
on restart, and cannot attach a persistent disk. Free compute hours are shared at
workspace level, so an additional service can consume hours also used by other
free services. Do not promise 24/7 automation on the free plan.

Source: https://render.com/docs/free

## Connect your YouTube channel

1. Create a separate project in Google Cloud Console. Enable YouTube Data API v3.
2. Configure the OAuth consent screen. For a testing application, add your Google
   account as a test user. Create a **Web application** OAuth client.
3. Add exactly `http://localhost:3000/api/auth/youtube/callback` for local use,
   or `https://YOUR-SERVICE.onrender.com/api/auth/youtube/callback` for live hosting.
4. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI and
   YOUTUBE_PROVIDER=google in `.env` or the new Render service's environment.
   Preserve JWT_SECRET: changing it makes existing encrypted tokens unreadable.
5. For public trend lookups also set a YouTube Data API key as YOUTUBE_API_KEY.
6. Restart the studio, click **Connect YouTube** on the appropriate channel and
   complete Google's consent screen. State values are single-use and expire.

OAuth exchanges and refreshes tokens server-side; tokens are AES-256-GCM encrypted
in the data store. YouTube quota, OAuth testing expiry, API project verification
and YouTube upload restrictions still apply. An unverified API project may restrict
uploaded videos to private. No Google credentials were supplied with this build,
so actual account connection and upload have NOT been verified.

Upload uses Google's resumable-session initiation followed by a single upload.
It does not resume automatically after network failure. If an upload result is
uncertain, check YouTube Studio before taking further action; the queue prevents
automatic reapproval/retry and stores a returned video ID for reconciliation.
Review audience designation: this release sends `selfDeclaredMadeForKids=false`;
only use its uploader for content you have determined is not made for kids.
For child-directed content, upload and set the audience manually in YouTube Studio.

## What works and what remains limited

| Area | This release |
|---|---|
| Owner access | Shared single-owner token, per-tab browser session; not a multi-user SaaS |
| Agents | 22 registered task roles; status, counters, logs and enable/pause controls |
| Local AI | Ollama/Gemma adapter with JSON contracts, validation and deadlines |
| Voice | Free espeak-ng speech; optional existing paid TTS adapters |
| Video | Actual FFmpeg MP4 with generated slide cards, audio and proportional SRT timing |
| Thumbnails | Three original PNG typography/shape designs; not cinematic AI artwork |
| Research | Public YouTube metadata when configured; otherwise labeled brainstorming |
| Fact-check | AI assessment for an editor; not independently verified facts |
| Publishing | Google OAuth, encrypted refresh tokens, private-first upload, approval gate |
| Analytics | Live lifetime views, likes and comments; other fields unavailable |
| Competitors | Live frequency/engagement analysis is not implemented; demo mode simulates it |
| Optimization | Requires CTR and retention; does not infer these from missing live data |
| Experiments/revenue | Planning/manual tracking and demo logic; no autonomous A/B platform |
| Storage | Single-process JSON, serialized atomic saves; persistent volume required |
| Queues | Background pipeline status persisted; no Redis/distributed worker implementation |
| Scheduler | Disabled by default; optional in-process schedules only while app is running |

Subtitle timing is proportional to narration word count, not forced alignment.
The generated video uses slide cards, not licensed stock footage or video-gen.
Automated checks cannot certify originality, copyright clearance or accuracy.
Google Analytics windowed reports, revenue ingestion, playlists and automatic
caption uploads are not implemented. S3, PostgreSQL and Redis configuration is
rejected explicitly; the old SQL file is only a reference schema and is never run.

Do not run multiple replicas against the JSON store. A pipeline interrupted by a
restart does not resume automatically. Manual long-running stage requests may
outlast a hosted proxy; use the background full pipeline on Render.
Keep backups of the data volume and media. Demo artifacts and credentials are
excluded from this package.

## Commands and validation

```bash
npm ci
npm run build
npm test
npm run demo
```

`npm test` exercises the demo pipeline, real MP4 rendering, API authentication,
channel-update isolation, approval restrictions, encryption and Google HTTP
adapter behavior using controlled responses. FFmpeg is required for the media
test. Tests write only to temporary directories. `npm run demo` uses an isolated
temporary store and explicit mock providers; it never touches live data.

See `docs/VERIFICATION.md` for the exact checks completed for this package.
