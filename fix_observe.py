import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Lines 2344, 2548, 3053, 5962 have 'observeReveals();' without the typeof check
text = text.replace('      observeReveals();', "      if (typeof observeReveals === 'function') observeReveals();")
text = text.replace('        observeReveals();', "        if (typeof observeReveals === 'function') observeReveals();")
text = text.replace('    observeReveals();', "    if (typeof observeReveals === 'function') observeReveals();")

# Remove the console error for missing map asset to clean up logs since it's an expected fallback
text = text.replace('console.error("[SonicDNA Atlas] Failed to load world-map.svg outline:", err.message);', '/* world-map.svg missing, falling back to basic rendering */')

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(text)
