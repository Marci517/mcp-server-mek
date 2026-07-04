from __future__ import annotations

import asyncio
import json

from fastmcp import Client

from mek_server import mcp


async def main() -> None:
    client = Client(mcp)

    async with client:
        tools = await client.list_tools()
        print("Available tools:")
        for tool in tools:
            print(f"- {tool.name}")

        result = await client.call_tool(
            "search_mek_fulltext",
            {
                "keyword": "magyar",
                "limit": 3,
                "deduplicate_records": True,
                "match_field": "any",
                "search_type": "all_words",
            },
        )

    payload = result.structured_content or {}
    print()
    print("Search summary:")
    print(json.dumps(payload.get("summary", {}), ensure_ascii=False, indent=2))

    if payload.get("results"):
        print()
        print("First result:")
        print(json.dumps(payload["results"][0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
