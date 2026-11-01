# /// script
# requires-python = ">=3.12"
# dependencies = ["silpo-py-mcp"]
# ///
"""Check how far back offline history goes by asking for windows before 2026-08-03."""
import asyncio, json
from pathlib import Path
from silpo_py_mcp import SilpoClient
ctx = json.load(open(Path(__file__).resolve().parent.parent / "probe-output/offline_orders_all.json"))["context"]
async def main():
    async with SilpoClient.for_real_server() as c:
        for start, end in [("2026-05-01T00:00:00","2026-08-02T23:59:59"), ("2026-01-01T00:00:00","2026-04-30T23:59:59"), ("2025-01-01T00:00:00","2025-12-31T23:59:59")]:
            r = await c.call_tool("silpo_get_my_offline_orders", dict(ctx, limit=10, offset=0, dateStart=start, dateEnd=end))
            print(f"{start[:10]}..{end[:10]}: total={r.get('meta',{}).get('total')} summary={r.get('summary')!r}")
asyncio.run(main())
