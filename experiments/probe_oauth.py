# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Check Silpo OAuth metadata + whether Dynamic Client Registration accepts HA's redirect URI."""
import httpx, json
BASE = "https://mcp.silpo.ua"
HA_REDIRECT = "https://my.home-assistant.io/redirect/oauth"
with httpx.Client(timeout=20) as c:
    r = c.get(f"{BASE}/mcp"); print("GET /mcp ->", r.status_code, dict(r.headers).get("www-authenticate"))
    for p in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
        r = c.get(BASE + p); print(f"\n{p} -> {r.status_code}")
        if r.status_code == 200: print(json.dumps(r.json(), indent=1)[:2500]); meta = r.json() if "authorization_endpoint" in r.json() else globals().get("meta")
    reg = meta.get("registration_endpoint") if meta else f"{BASE}/register"
    body = {"client_name": "Home Assistant Silpo", "redirect_uris": [HA_REDIRECT], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"}
    r = c.post(reg, json=body); print(f"\nPOST {reg} -> {r.status_code}\n{r.text[:1500]}")
