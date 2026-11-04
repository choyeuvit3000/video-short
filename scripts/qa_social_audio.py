"""Local ASR evidence for review; never reports that audio was listened to."""
import argparse
import json
from pathlib import Path
from faster_whisper import WhisperModel

ap=argparse.ArgumentParser()
ap.add_argument('video',type=Path)
args=ap.parse_args()
snapshot=next(Path('D:/studio-node/hf/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots').iterdir())
model=WhisperModel(str(snapshot),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
segments,info=model.transcribe(str(args.video),language='vi',vad_filter=False,beam_size=3)
result={'method':'local ASR + automated loudness/peak, not auditory listening',
        'language':info.language,'segments':[]}
for seg in segments:
    result['segments'].append({'start':seg.start,'end':seg.end,'text':seg.text})
    print(round(seg.start,2),seg.text,flush=True)
args.video.with_suffix('.asr.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
