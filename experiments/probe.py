# /// script
# requires-python = ">=3.12"
# dependencies = ["silpo-py-mcp"]
# ///
"""
Probe the official Silpo MCP: dump tools/list and raw order history to probe-output/.
Run from the repo root:   uv run experiments/probe.py
First run opens a browser for Silpo login; token is cached in ~/.silpo_py_mcp.
"""
import asyncio, json, sys, traceback
from pathlib import Path
from silpo_py_mcp import SilpoClient

OUT = Path(__file__).resolve().parent.parent / "probe-output"
OUT.mkdir(exist_ok=True)

def dump(name, data):
    p = OUT / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    print(f"  -> wrote {p.relative_to(OUT.parent)} ({p.stat().st_size} bytes)")

def tool_to_dict(t):
    if isinstance(t, dict):
        return t
    return {k: getattr(t, k, None) for k in ("name", "description", "inputSchema", "outputSchema")}

async def try_call(client, name, args, label):
    print(f"\n== {name} {args}")
    try:
        res = await client.call_tool(name, args)
        dump(f"{label}.json", res)
        return res
    except Exception as e:
        print(f"  !! {type(e).__name__}: {e}")
        dump(f"{label}.error.txt", {"error": str(e), "trace": traceback.format_exc()})
        return None

async def main():
    async with SilpoClient.for_real_server() as client:
        tools = [tool_to_dict(t) for t in await client.list_tools()]
        print(f"Connected. {len(tools)} tools.")
        dump("tools.json", tools)
        by_name = {t["name"]: t for t in tools}

        for name in ("silpo_get_my_offline_orders", "silpo_get_my_online_orders"):
            t = by_name.get(name)
            if not t:
                print(f"\n!! {name} not in tools/list"); continue
            print(f"\n{name} schema:\n{json.dumps(t.get('inputSchema'), ensure_ascii=False, indent=2)}")
            label = name.replace("silpo_get_my_", "")
            res = await try_call(client, name, {}, label)
            # Try a couple of common pagination shapes if the schema has them
            props = (t.get("inputSchema") or {}).get("properties", {})
            for key in ("page", "pageNumber", "offset", "skip"):
                if key in props:
                    await try_call(client, name, {key: 2 if "page" in key.lower() else 20}, f"{label}.page2")
                    break
            for key in ("limit", "pageSize", "take", "count"):
                if key in props:
                    await try_call(client, name, {key: 50}, f"{label}.limit50")
                    break

        # Cheap extras that may help tagging later
        for name in ("silpo_get_my_profile", "silpo_get_my_family", "silpo_get_my_food_restrictions",
                     "silpo_get_my_favorites", "silpo_get_loyalty_info"):
            if name in by_name:
                await try_call(client, name, {}, name.replace("silpo_get_", ""))

    print("\nDone. Output in probe-output/")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
