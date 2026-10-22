"""Steam content descriptors for the apps found in the public files (public GetItems, no key). Read-only.
Descriptor ids (Steam): 1 some nudity or sexual content, 2 frequent violence or gore, 3 adult only sexual content,
4 frequent nudity or sexual content, 5 general mature content."""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

where = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
wish = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
wish_ids = {str(g["app_id"]) for g in wish["games"]}
apps = sorted(where, key=int)
URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"
items = {}
with httpx.Client(timeout=30, headers={"User-Agent": "SweetSpot content check (one-off)"}) as client:
    for i in range(0, len(apps), 100):
        batch = apps[i:i + 100]
        body = {"ids": [{"appid": int(a)} for a in batch], "context": {"language": "tchinese", "country_code": "TW"},
                "data_request": {"include_basic_info": True}}
        r = client.get(URL, params={"input_json": json.dumps(body)})
        r.raise_for_status()
        for it in r.json().get("response", {}).get("store_items", []):
            items[str(it.get("appid") or it.get("id"))] = it
        time.sleep(1.5)

SEX = {1: "部分裸露或性內容", 3: "成人性內容", 4: "頻繁裸露或性內容"}
rows, counts = [], Counter()
for a in apps:
    it = items.get(a)
    if not it or it.get("success") != 1:
        counts["not an app / not found"] += 1
        continue
    ids = set(it.get("content_descriptorids") or [])
    sex = sorted(ids & set(SEX))
    level = "成人性內容" if 3 in ids else "頻繁裸露或性內容" if 4 in ids else "部分裸露或性內容" if 1 in ids else None
    counts[level or "none"] += 1
    if level:
        tests = [r for r in where[a] if r.startswith("tests/")]
        others = [r for r in where[a] if not r.startswith("tests/")]
        rows.append((level, it.get("name"), a, a in wish_ids, len(tests), len(others), tests[:3]))
print("apps checked:", len(apps), dict(counts))
order = {"成人性內容": 0, "頻繁裸露或性內容": 1, "部分裸露或性內容": 2}
for level, name, a, w, nt, no, sample in sorted(rows, key=lambda r: (order[r[0]], -r[4])):
    print(f"{level}\t{name}\t[{a}]\twishlist={'Y' if w else '-'}\ttests={nt}\tother={no}\t{', '.join(sample)}")
