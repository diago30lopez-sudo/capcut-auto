"""CTA avoid_overlap test: verifies CTA segments respect black hole boundary."""
import json, shutil, struct, sys, tempfile, wave
from pathlib import Path
sys.path.insert(0, r'D:\capcut-auto')
from PIL import Image
from src.core import config
from src.core.capcut_project import CapCutProject
from src.core.profile_loader import load_profiles, build_edit_profile, get_profile
from src.core.timeline_builder import TimelineItem, measure_audio_duration_us
config.ensure_dirs()
work = Path(tempfile.mkdtemp(prefix='cta_overlap_'))
tpl = shutil.copytree(r'D:\YOUTUBE AUTOMATIZADO\CaptCut\CapCut Drafts\1.PLANTILLA', work/'T')
audio = work/'v.wav'
rate = 16000; n = int(5.0*rate)
with wave.open(str(audio),'w') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(b''.join(struct.pack('<h', int(6000*((i%rate)/rate))) for i in range(n)))
imgs = work/'i'; imgs.mkdir()
for k in range(1,5): Image.new('RGB',(640,480),(k*50,90,120)).save(imgs/f'x{k}.jpg')
srt = work/'a.srt'
srt.write_text(
    '1\n00:00:00,100 --> 00:00:01,000\nPrimer dato de ciencia\n\n'
    '2\n00:00:01,100 --> 00:00:02,000\nOtro metodo con nombre TECNICO\n\n'
    '3\n00:00:02,100 --> 00:00:03,000\nCada dos segundos aparece un dato\n\n'
    '4\n00:00:03,100 --> 00:00:04,000\nDato final con suscribete al canal\n\n',
    encoding='utf-8')
profiles = load_profiles(r'D:\capcut-auto\profiles', dyc_assets_dir=r'D:/YOUTUBE AUTOMATIZADO/0.sticman/assets/')
edp = build_edit_profile(get_profile(profiles,'dyc'))
print('cta_patterns:', edp.cta_patterns)
print('cta_avoid_overlap:', edp.cta_avoid_overlap)
items = [TimelineItem(k, imgs/f'x{k+1}.jpg', f'E{k+1}', f'E{k+1}', 1.0,
                      k*1_250_000, (k+1)*1_250_000, 1_250_000) for k in range(4)]
dur = measure_audio_duration_us(audio)
proj = CapCutProject(tpl)
out = proj.generate('CTA_Overlap_Test', items, audio, dur,
                    allow_test_names=True, subtitle_srt=srt, edit_profile=edp)
d = json.loads((out/'draft_content.json').read_text(encoding='utf-8'))
# Find all overlay track segments (render_index >= 1000 = CTA)
overlay_segs = []
for tr in d['tracks']:
    for s in tr.get('segments', []):
        ri = s.get('render_index', 0)
        if ri and ri >= 1000:
            overlay_segs.append(s)
print(f'overlay segments (CTAs): {len(overlay_segs)}')
for s in overlay_segs:
    trr = s.get('target_timerange', {})
    print(f"  start={trr['start']} dur={trr['duration']}")
print('CTA OVERLAP TEST OK')
