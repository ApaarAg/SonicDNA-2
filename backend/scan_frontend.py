import re

with open('../index.html', encoding='utf-8') as f:
    html = f.read()

# Patterns to find API endpoints
patterns = [
    (r"apiCall\('([^']+)'", 'apiCall single'),
    (r'apiCall\("([^"]+)"', 'apiCall double'),
    (r'apiCall\(`([^`]+)`', 'apiCall template'),
    (r"fetch\('(http[^']+)'", 'fetch single'),
    (r'fetch\("(http[^"]+)"', 'fetch double'),
]

all_endpoints = set()
for pattern, label in patterns:
    matches = re.findall(pattern, html)
    for m in matches:
        all_endpoints.add(m)

# Also find section/panel IDs to understand the structure
sections = re.findall(r'id=["\']([^"\']*(?:section|panel|tab|page|view)[^"\']*)["\']', html, re.IGNORECASE)

print("=== All API endpoints called from frontend ===")
for ep in sorted(all_endpoints):
    print(f"  {ep}")

print(f"\nTotal: {len(all_endpoints)} unique endpoints")

print("\n=== UI Sections found ===")
for s in sorted(set(sections))[:30]:
    print(f"  {s}")
