from __future__ import annotations

import json

from mek_server import search_mek_fulltext


def main() -> None:
    result = search_mek_fulltext(
        keyword="magyar",
        limit=2,
        deduplicate_records=True,
        match_field="any",
        search_type="all_words",
    )

    assert "summary" in result
    assert "results" in result
    assert result["summary"]["returned_hits"] <= 2
    assert result["results"], "A smoke teszt legalább egy találatot vár."

    first_result = result["results"][0]
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

    print("Smoke test OK")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
