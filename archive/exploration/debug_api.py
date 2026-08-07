import os, json, time, base64, requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()
API_KEY_ID = os.getenv("POLYMARKET_API_KEY")
API_SECRET = os.getenv("POLYMARKET_API_SECRET")

def auth(method, path):
    private_key_bytes = base64.b64decode(API_SECRET)[:32]
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(private_key.sign(f"{ts}{method}{path}".encode())).decode()
    return {"X-PM-Access-Key": API_KEY_ID, "X-PM-Timestamp": ts, "X-PM-Signature": sig}

resp = requests.get("https://api.polymarket.us/v1/portfolio/positions", headers=auth("GET", "/v1/portfolio/positions"))
data = resp.json().get("positions", {})
print(json.dumps(data, indent=2))
