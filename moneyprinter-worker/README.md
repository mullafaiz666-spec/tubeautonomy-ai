# TubeVerse × MoneyPrinterTurbo worker

This adapter makes [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) a first-class external render engine for TubeVerse AI.

**Pinned upstream:** `harry0703/MoneyPrinterTurbo@79d7d122ae09ad9e294afff787a473401026f681`  
**License:** MIT; upstream copyright/license is preserved in `LICENSE.MoneyPrinterTurbo.txt`.

## What the merged worker does

`TubeVerse queue → moneyprinter worker → MoneyPrinterTurbo API → script/TTS/materials/subtitles/BGM/FFmpeg → MP4 → TubeVerse upload → complete`

MoneyPrinterTurbo remains external compute. Netlify is only the control-plane and never runs FFmpeg/TTS/video assembly.

## Install

Linux/Colab needs Python 3.11+, Git and FFmpeg.

```bash
./install_moneyprinter.sh
python3 -m pip install -r requirements.txt
```

The installer pins the upstream commit instead of tracking `main`, then uses the upstream `uv.lock`.

## Configure

Register a TubeVerse worker with model family `moneyprinter`, copy the one-time token, and set:

```bash
export TUBEVERSE_BASE_URL=https://tubeverse-ai.netlify.app
export TUBEVERSE_WORKER_TOKEN='tvw_...'
export MONEYPRINTER_HOME="$PWD/MoneyPrinterTurbo"
python3 worker.py
```

The worker binds/autostarts MoneyPrinterTurbo only on `127.0.0.1:8080`.

Useful optional settings:

```bash
export MONEYPRINTER_VIDEO_SOURCE=pexels     # pexels | pixabay | coverr | local
export MONEYPRINTER_VOICE_NAME=en-US-AriaNeural-Female
export MONEYPRINTER_BGM_TYPE=random
export MONEYPRINTER_BGM_VOLUME=0.15
export MONEYPRINTER_PROMPT_AS_SCRIPT=1
export MONEYPRINTER_TASK_TIMEOUT=3600
```

Stock providers may require their own free API keys in `MoneyPrinterTurbo/config.toml`. `local` uses local materials instead. TubeVerse does not copy provider secrets into Netlify.

## Why the prompt is used as the script by default

A TubeVerse job already contains creator/agent output. Passing it as `video_script` avoids paying for another LLM call. The worker also derives simple local search terms, so MoneyPrinterTurbo does not need an LLM solely to derive stock-video keywords.

Set `MONEYPRINTER_PROMPT_AS_SCRIPT=0` only if you intentionally want MoneyPrinterTurbo's configured LLM to write the script.

## TubeAutonomy

TubeAutonomy can queue `model: "moneyprinter"` for finished scripts. This makes MoneyPrinterTurbo the assembly engine after Research/Script/Scene Planning, while `model: "ltx"` remains the generative-video path.
