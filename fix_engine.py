import json
import re

with open('backend/engine.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix get_calibration_clips
pattern = re.compile(r'def get_calibration_clips\(n: int = 3.*?return list\(best_combo\)', re.DOTALL)
replacement = '''def get_calibration_clips(n: int = 8, session_key: str = "") -> list:
    \"\"\"
    Return n clips dynamically, ensuring a spread across the 4 primary energy/valence quadrants.
    \"\"\"
    import random
    all_ids = list(_CLIP_FEATURES.keys())
    preferred = [c for c in all_ids if c.startswith("cal_")]
    if not preferred:
        preferred = all_ids

    quadrants = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    
    for cid in preferred:
        f = _CLIP_FEATURES[cid]["features"]
        e = f.get("energy", 0.0)
        v = f.get("valence", 0.0)
        if e >= 0 and v >= 0:
            quadrants["Q1"].append(cid)
        elif e < 0 and v >= 0:
            quadrants["Q2"].append(cid)
        elif e < 0 and v < 0:
            quadrants["Q3"].append(cid)
        else:
            quadrants["Q4"].append(cid)

    selected = []
    q_keys = list(quadrants.keys())
    
    for q in q_keys:
        random.shuffle(quadrants[q])
        
    idx = 0
    while len(selected) < n:
        added_in_round = False
        for q in q_keys:
            if len(selected) >= n:
                break
            if idx < len(quadrants[q]):
                selected.append(quadrants[q][idx])
                added_in_round = True
        idx += 1
        if not added_in_round:
            break
            
    if len(selected) < n:
        remaining = list(set(all_ids) - set(selected))
        random.shuffle(remaining)
        selected.extend(remaining[:n - len(selected)])
        
    random.shuffle(selected)
    return selected'''

text = pattern.sub(replacement, text)

with open('backend/engine.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Replaced get_calibration_clips")
