from __future__ import annotations

import asyncio
import json

from fastmcp import Client

from mek_server import mcp


async def main() -> None:
    """Minimál példa arra, hogyan lehet in-process FastMCP klienssel meghívni a toolt."""
    # Az in-process kliens a legegyszerűbb fejlesztői minta: nem kell külön szerverprocesszt
    # indítani, mégis ugyanazon a tool API-n keresztül dolgozunk.
    client = Client(mcp)

    async with client:
        # Először kilistázzuk a toolokat, hogy rögtön látszódjon: a kliens valóban kapcsolódott.
        tools = await client.list_tools()
        print("Available tools:")
        for tool in tools:
            print(f"- {tool.name}")

        # A hívás direkt olyan paraméterekkel megy, amelyek megmutatják a saját utószűrési
        # logikát is: deduplikálás, mezőválasztás és all_words egyezés.
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

    # A Python kliens objektum snake_case mezőneveket használ, ezért itt a structured_content a jó mező.
    payload = result.structured_content or {}
    print()
    print("Search summary:")
    print(json.dumps(payload.get("summary", {}), ensure_ascii=False, indent=2))

    # Csak az első találatot írjuk ki teljesen, hogy a példa rövid maradjon, de a struktúra látszódjon.
    if payload.get("results"):
        print()
        print("First result:")
        print(json.dumps(payload["results"][0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    """CLI futtatáskor elindítja az aszinkron mintaklienst."""
    asyncio.run(main())
