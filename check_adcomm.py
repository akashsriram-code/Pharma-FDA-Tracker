import json

with open('data/data.json') as f:
    d = json.load(f)

print("Title matches for Vaccines:")
for e in d:
    if 'Vaccines' in e.get('title', '') and e.get('type') == 'AdComm Meeting':
        print("-", e['title'], "| date:", e.get('date'))

print("\nAll AdComm future dates:")
for e in d:
    if e.get('type') == 'AdComm Meeting' and e.get('date', '') > '2026-02-26':
        print("-", e['title'], "| date:", e.get('date'))
