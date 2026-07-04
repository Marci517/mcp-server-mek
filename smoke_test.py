from __future__ import annotations

import json

from mek_server import search_mek_fulltext


def main() -> None:
    """Nagyon gyors, hálózatos smoke teszt a tool alapműködésének ellenőrzésére."""
    # Ez szándékosan nem teljes tesztrendszer, hanem egy rövid ellenőrzés arra,
    # hogy a fő lekérdezési útvonal most éppen él-e és strukturált adatot ad-e vissza.
    result = search_mek_fulltext(
        keyword="magyar",
        limit=2,
        deduplicate_records=True,
        match_field="any",
        search_type="all_words",
    )

    # Ezek az alap assertek azt fogják meg, hogy a tool payload váza ne törjön el
    # egy későbbi refaktor vagy parsing-változás során.
    assert "summary" in result
    assert "results" in result
    assert result["summary"]["returned_hits"] <= 2
    assert result["results"], "A smoke teszt legalább egy találatot vár."

    first_result = result["results"][0]
    # A kötelező mezők listája azokat a kulcsokat reprezentálja, amelyekre a kliensoldali
    # feldolgozás leginkább támaszkodik.
    required_fields = [
        "title",
        "author",
        "record_url",
        "record_id",
        "subject_keywords",
        "document_types",
        "language_codes",
        "language_labels",
    ]
    for field_name in required_fields:
        assert field_name in first_result, f"Hiányzó mező: {field_name}"

    # Rövid, emberi olvasásra alkalmas kimenet, hogy terminálból azonnal látszódjon az állapot.
    print("Smoke test OK")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    """Közvetlen futtatáskor lefuttatja a smoke tesztet."""
    main()
