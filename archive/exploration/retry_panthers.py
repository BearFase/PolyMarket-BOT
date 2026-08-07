import requests, re
from collections import Counter

HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml"}

for variant in ("Panthers3698", "panthers3698", "PANTHERS3698"):
    r = requests.get(f"https://polymarket.com/@{variant}", headers=HDRS, timeout=15)
    wallets = Counter(re.findall(r'0x[a-fA-F0-9]{40}', r.text))
    name_hits = len(re.findall(variant, r.text, re.IGNORECASE))
    print(f"@{variant}: status {r.status_code}, name appears {name_hits}x, "
          f"top wallets: {wallets.most_common(3)}")
