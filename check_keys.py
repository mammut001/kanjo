import re
import os

languages = ["en", "fr", "zh-Hans"]
base_path = "/private/tmp/claude-501/-Users-dogecoin-Documents-GitHub-token-usage/97a6d7b8-8f80-4f8d-bed5-d5e7e02ace2b/scratchpad/wt-share/ui/Sources/KanjoCore/Resources/"

keys = {}

for lang in languages:
    path = os.path.join(base_path, f"{lang}.lproj/Localizable.strings")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        # Find all keys starting with "share."
        share_keys = re.findall(r'"(share\.[^"]+)"', content)
        keys[lang] = set(share_keys)

all_share_keys = set().union(*keys.values())

for lang in languages:
    missing = all_share_keys - keys[lang]
    if missing:
        print(f"Language {lang} is missing keys: {missing}")
    else:
        print(f"Language {lang} has all share keys.")
