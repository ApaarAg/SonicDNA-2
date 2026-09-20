import re

with open('backend/engine.py', 'r', encoding='utf-8') as f:
    text = f.read()

prompt_old = '''  "tempo": <float>,              // -2=very slow, +2=very fast
  "reasoning": "<1-2 sentence explanation of your analysis>"
}

No markdown, no extra text. Just the JSON."""'''
prompt_new = '''  "tempo": <float>,              // -2=very slow, +2=very fast
  "reasoning": "<1-2 sentence explanation of your analysis>"
}

First, analyze the user's input. If the input consists of keyboard mashes, single letters, or non-sensical gibberish, return ONLY the exact word 'INVALID_INPUT'.
No markdown, no extra text. Just the JSON or INVALID_INPUT."""'''
text = text.replace(prompt_old, prompt_new)

json_load_old = '''    raw_text = message.choices[0].message.content.strip()

    try:'''
json_load_new = '''    raw_text = message.choices[0].message.content.strip()

    if raw_text == "INVALID_INPUT":
        raise ValueError("INVALID_INPUT")

    try:'''
text = text.replace(json_load_old, json_load_new)

# 3. Replace get_calibration_clips safely
old_cal = '''def get_calibration_clips(n: int = 3, session_key: str = "") -> list:
    """
    Return n maximally diverse clips for round 1.
    Diversity = maximize minimum pairwise distance.
    """
    all_ids = list(_CLIP_FEATURES.keys())
    if n <= 1:
        return select_round_clip_ids(_CLIP_FEATURES, max(0, n), session_key=session_key)

    cal_ids = [c for c in all_ids if c.startswith("cal_")]
    preferred = cal_ids if len(cal_ids) >= n else all_ids

    best_combo = None
    best_score = -1

    # Keep the existing feature-distance diversity, then rotate ties/categories
    # through the explicit session key so repeated browser sessions cover more
    # of the library without hidden server state.
    for combo in itertools.combinations(preferred, n):
        clips  = [_CLIP_FEATURES[c] for c in combo]
        # Min pairwise distance (bottleneck diversity)
        dists  = [
            _clip_feature_distance(clips[i], clips[j])
            for i in range(len(clips))
            for j in range(i+1, len(clips))
        ]
        score  = min(dists)
        if score > best_score:
            best_score  = score
            best_combo  = combo

    if not best_combo:
        best_combo = list(preferred[:n])
    return list(best_combo)'''

replacement = '''def get_calibration_clips(n: int = 8, session_key: str = "") -> list:
    """
    Return n clips dynamically, ensuring a spread across the 4 primary energy/valence quadrants.
    """
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

text = text.replace(old_cal, replacement)

with open('backend/engine.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Replaced all correctly in engine.py")
