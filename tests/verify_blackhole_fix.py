"""Verify the black-hole fix: end-animation segments must carry NO glitch transition."""
import json, sys
from pathlib import Path

sys.path.insert(0, r"D:\capcut-auto")

proj = Path(r"C:\Users\diago_dev\AppData\Local\Temp\cta_overlap_8of7fzj3\CTA_Overlap_Test")
d = json.loads((proj / "draft_content.json").read_text(encoding="utf-8"))

anim_ids = set()
for a in d["materials"].get("material_animations", []):
    for an in a.get("animations", []):
        if an.get("type") == "out":
            anim_ids.add(a["id"])

trans_ids = {t["id"] for t in d["materials"].get("transitions", [])}
main_segs = []
for tr in d["tracks"]:
    if tr.get("type") == "video" and tr.get("flag", 0) == 0:
        main_segs = tr.get("segments", [])

print("total main segments:", len(main_segs))
anim_segs = []
for i, s in enumerate(main_segs):
    refs = s.get("extra_material_refs", [])
    has_anim = any(r in anim_ids for r in refs)
    has_trans = any(r in trans_ids for r in refs)
    tr_ = s["target_timerange"]
    if has_anim or has_trans:
        tag = "<== END ANIM" + (" + GLITCH (CONFLICT!)" if has_trans else " (clean)")
        print("  seg[{}] start={} dur={} anim={} trans={} {}".format(
            i, tr_["start"], tr_["duration"], has_anim, has_trans, tag))
    if has_anim:
        anim_segs.append(s)

conflict = any(any(r in trans_ids for r in s.get("extra_material_refs", [])) for s in anim_segs)
if anim_segs and not conflict:
    print("RESULT: FIX OK - end-animation segment carries NO glitch transition")
    sys.exit(0)
elif not anim_segs:
    print("RESULT: NO end animation found (check test setup)")
    sys.exit(1)
else:
    print("RESULT: CONFLICT PRESENT - glitch transition on end-animation segment")
    sys.exit(1)
