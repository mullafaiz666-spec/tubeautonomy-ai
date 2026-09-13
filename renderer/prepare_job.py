#!/usr/bin/env python3
import json, os, subprocess, sys, textwrap
from pathlib import Path

job_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
job = json.loads(job_path.read_text(encoding='utf-8'))

title = str(job.get('title') or 'TubeVerse AI').strip()[:120]
script = str(job.get('script') or job.get('prompt') or '').strip()
if len(script) < 20:
    raise SystemExit('job script/prompt must be at least 20 characters')
aspect = str(job.get('aspectRatio') or '9:16')
if aspect not in {'9:16','16:9','1:1'}:
    raise SystemExit(f'unsupported aspectRatio: {aspect}')

(out_dir/'title.txt').write_text(title, encoding='utf-8')
(out_dir/'script.txt').write_text(script, encoding='utf-8')
(out_dir/'meta.json').write_text(json.dumps({'title':title,'aspectRatio':aspect}, indent=2), encoding='utf-8')

# A deterministic local material means the first render needs no stock-footage/API key.
# MoneyPrinterTurbo will handle voiceover, subtitle timing, fitting and final composition.
size = {'9:16':'540x960','16:9':'960x540','1:1':'720x720'}[aspect]
bg = out_dir/'background.mp4'
font = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
text = title.replace('\\','\\\\').replace(':','\\:').replace("'","\\'")
filter_graph = (
    f"drawtext=fontfile={font}:text='{text}':fontcolor=white:fontsize=34:"
    "x=(w-text_w)/2:y=(h-text_h)/2-20," 
    "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
    "text='TubeVerse • autonomous render':fontcolor=0x9aa4b2:fontsize=19:"
    "x=(w-text_w)/2:y=(h-text_h)/2+34"
)
subprocess.run([
    'ffmpeg','-y','-f','lavfi','-i',f'color=c=0x10131a:s={size}:r=30:d=60',
    '-vf',filter_graph,'-c:v','libx264','-preset','veryfast','-crf','26','-pix_fmt','yuv420p',str(bg)
], check=True)
print(json.dumps({'title': title, 'aspectRatio': aspect, 'background': str(bg), 'scriptChars': len(script)}))
