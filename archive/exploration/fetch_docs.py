import requests
r = requests.get("https://docs.polymarket.us/llms.txt", timeout=15,
                 headers={"User-Agent": "Mozilla/5.0"})
print("status:", r.status_code)
print(r.text.encode("ascii", "replace").decode())
