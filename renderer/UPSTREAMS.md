# TubeVerse upstream engines

TubeVerse uses pinned upstream projects through adapters rather than copying their full repositories into this branch.

## Active render engine

- MoneyPrinterTurbo — https://github.com/harry0703/MoneyPrinterTurbo
  - pinned commit: `cf5a3aedad1741d012152d355aa909d224fc4557`
  - role: prepared script -> Edge TTS -> subtitle timing -> local/stock materials -> FFmpeg composition -> MP4
  - license: MIT (retain upstream copyright/license when redistributing upstream code)

## Next adapters

- ShortGPT — https://github.com/RayVentura/ShortGPT
  - pinned commit: `3df4e0f7a422bf7386565d498bf4521a2544c614`
  - role: Shorts/TikTok/YouTube automation orchestration and asset workflow
  - license: MIT

- faster-whisper — https://github.com/SYSTRAN/faster-whisper
  - role: subtitle/voice transcription verification and caption repair
  - license: MIT

- Kokoro — https://github.com/hexgrad/kokoro
  - role: local/open-weight TTS alternative to network TTS
  - model weights: Apache-2.0; inference/library licensing must be preserved according to the upstream project

## Compute platform

The default TubeVerse renderer runs on standard GitHub-hosted Actions runners for this public repository. It deliberately does not require Floot, Netlify Functions, Render, Railway, or a paid GPU service for the MoneyPrinter path.
