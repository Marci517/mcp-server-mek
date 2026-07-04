# mcp-server-mek

FastMCP-alapú Python MCP szerver a Magyar Elektronikus Könyvtár teljes szövegű keresőjéhez.

## Fájlok

- `mek_server.py`: a futtatható MCP szerver és a `search_mek_fulltext` tool
- `example_client.py`: minimál FastMCP kliensminta a tool meghívásához
- `smoke_test.py`: gyors helyi ellenőrző script a tool alapválaszára
- `requirements.txt`: a használt Python csomagok rögzített verziói
- `mcp_config.json`: hordozható MCP-konfiguráció
- `.vscode/mcp.json`: workspace-szintű auto-load konfiguráció VS Code-kompatibilis kliensekhez

## Gyors futtatás

Példakliens:

`python3 example_client.py`

Gyors smoke teszt:

`python3 smoke_test.py`

## Folyamat

```mermaid
flowchart TD
    A[User prompts AI] --> B[AI client]
    B --> C[FastMCP server]
    C --> D[search_mek_fulltext]

    D --> E[clean and validate input]
    E --> F[_clean_text]
    E --> G[_validate_search_type]
    E --> H[_validate_match_field]
    E --> I[_resolve_collection]
    E --> J[_needs_post_filtering]
    J --> K[_choose_page_size]

    D --> L[_make_session]
    L --> M[_fetch_search_page]
    M --> N[_parse_search_results]

    N --> O{record url exists}
    O -- yes --> P[_fetch_record_metadata]
    P --> Q[_record_xml_url]
    P --> R[_parse_contributors]
    P --> S[_parse_topics]
    P --> T[_language_payload]
    P --> U[_text_or_empty]

    P --> V[_enrich_hit]
    N --> V

    V --> W[_language_matches]
    W --> X[_contains_excluded_phrase]
    X --> Y[_keyword_target_text]
    Y --> Z[_keyword_matches]

    Z --> AA[results summary notes]
    AA --> AB[AI receives tool output]
    AB --> AC[AI groups and summarizes]
    AC --> AD[Final answer to user]

    AE[MekClientError class] -. error path .-> D
```

## Megjegyzés

A MEK jelenlegi publikus teljes szövegű keresőútvonala:

`https://mek.oszk.hu/hu/search/elfulltext/`

A feladatban megadott `https://mek.oszk.hu/hu/search/elfull/` oldal jelenleg az egyszerű keresést szolgálja ki.
