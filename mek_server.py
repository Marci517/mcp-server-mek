from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from fastmcp import FastMCP

# A MEK jelenlegi publikus teljes szövegű keresője ezen az útvonalon érhető el,
# ezért minden lekérés ehhez az endpointhez fut be.
BASE_URL = "https://mek.oszk.hu"
FULLTEXT_SEARCH_URL = urljoin(BASE_URL, "/hu/search/elfulltext/")
REQUEST_TIMEOUT_SECONDS = 30
# Saját User-Agentet küldök, hogy a forgalom azonosítható és kulturált legyen.
USER_AGENT = "mcp-server-mek/1.0 (+https://mek.oszk.hu)"
# Felső korlát a lapozásra, hogy a tool ne töltsön be kontroll nélkül túl sok oldalt.
MAX_SEARCH_PAGES = 5

# A bal oldali kulcsok kényelmi aliasok, a jobb oldali értékek viszont a MEK űrlap
# tényleges `option value` sztringjei. Így a kliens barátságosabb neveket adhat meg,
# mi pedig biztosan a MEK által várt paramétert küldjük tovább.
COLLECTION_MAP = {
    "": "",
    "all": "",
    "teljes gyujtemeny": "",
    "teljes gyűjtemény": "",
    "termeszettudomanyok": "természettudományok és matematika",
    "természettudományok": "természettudományok és matematika",
    "muszaki tudomanyok": "műszaki tudományok, gazdasági ágazatok",
    "műszaki tudományok": "műszaki tudományok, gazdasági ágazatok",
    "tarsadalomtudomanyok": "társadalomtudományok",
    "társadalomtudományok": "társadalomtudományok",
    "human temak, irodalom": "humán területek, kultúra, irodalom",
    "humán témák, irodalom": "humán területek, kultúra, irodalom",
    "kezikonyvek, egyeb": "kézikönyvek és egyéb műfajok",
    "kézikönyvek, egyéb": "kézikönyvek és egyéb műfajok",
}

# A MEK XML rekordokban nyelvkódok szerepelnek, ez a tábla ezek emberbarát feloldását adja.
# Ettől az AI kliens a nyelvi szűrést kódra és köznyelvi névre is kényelmesen elvégezheti.
LANGUAGE_LABELS = {
    "hun": "magyar",
    "eng": "angol",
    "ger": "német",
    "deu": "német",
    "fre": "francia",
    "fra": "francia",
    "ita": "olasz",
    "spa": "spanyol",
    "lat": "latin",
    "slk": "szlovák",
    "ces": "cseh",
    "rom": "román",
    "ron": "román",
}

# Ezek saját tool-szintű szűrési módok. A MEK publikus felülete nem kínál ilyen finom
# mezőválasztást, ezért ezeket a saját utószűrési logikánkhoz vezettem be.
VALID_SEARCH_TYPES = {"raw", "all_words", "any_words", "exact_phrase"}
VALID_MATCH_FIELDS = {"fulltext", "title", "author", "subject", "type", "any_metadata", "any"}

# A FastMCP szerver objektum a tool-regisztráció központi helye.
mcp = FastMCP("MEK Fulltext Search Server")


class MekClientError(RuntimeError):
    """Egységes kivétel a MEK-hívásokhoz, hogy a kliensoldalon könnyebb legyen kezelni a hibákat."""


def _normalize_text(value: str) -> str:
    """Normalizálja a szöveget ékezet- és kisbetűfüggetlen összehasonlításhoz."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _clean_text(value: str | None) -> str:
    """Leegyszerűsíti a whitespace-t, hogy a MEK HTML/XML szövegek konzisztensen kezelhetők legyenek."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _unique_preserve_order(values: list[str]) -> list[str]:
    """Duplikátumokat szűr ki úgy, hogy az eredeti sorrend megmaradjon."""
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        marker = _normalize_text(cleaned)
        if marker in seen:
            continue
        seen.add(marker)
        unique_values.append(cleaned)
    return unique_values


def _normalize_record_url(url: str) -> str:
    """Egységes HTTPS rekord-URL-t készít, hogy a cache és az összehasonlítás stabil legyen."""
    cleaned = _clean_text(url)
    if not cleaned:
        return ""
    return cleaned.replace("http://", "https://", 1)


def _make_session() -> requests.Session:
    """Újrahasznosítható HTTP sessiont hoz létre a gyorsabb és következetesebb MEK-kérésekhez."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _resolve_collection(collection: str) -> str:
    """A kliensbarát gyűjteménynévből a MEK űrlap által várt pontos értéket állítja elő."""
    normalized = _normalize_text(collection)
    if normalized not in COLLECTION_MAP:
        allowed = ", ".join(
            [
                "all",
                "természettudományok",
                "műszaki tudományok",
                "társadalomtudományok",
                "humán témák, irodalom",
                "kézikönyvek, egyéb",
            ]
        )
        raise ValueError(f"Ismeretlen gyűjtemény: {collection!r}. Elfogadott értékek: {allowed}.")
    return COLLECTION_MAP[normalized]


def _validate_search_type(search_type: str) -> str:
    """Őrzi, hogy csak a támogatott lokális keresési módok fussanak le."""
    if search_type not in VALID_SEARCH_TYPES:
        raise ValueError(
            f"Ismeretlen search_type: {search_type!r}. Elfogadott értékek: {sorted(VALID_SEARCH_TYPES)}."
        )
    return search_type


def _validate_match_field(match_field: str) -> str:
    """Őrzi, hogy csak létező mezőalapú utószűrés történjen."""
    if match_field not in VALID_MATCH_FIELDS:
        raise ValueError(
            f"Ismeretlen match_field: {match_field!r}. Elfogadott értékek: {sorted(VALID_MATCH_FIELDS)}."
        )
    return match_field


def _coerce_limit(limit: int) -> int:
    """Biztonsági korlátot tart a visszaadott elemszámra."""
    if limit < 1 or limit > 100:
        raise ValueError("A limit értéke 1 és 100 közé kell essen.")
    return limit


def _coerce_offset(offset: int) -> int:
    """Negatív lapozási értéket nem enged, mert a MEK ilyen állapotot nem tud kezelni."""
    if offset < 0:
        raise ValueError("Az offset nem lehet negatív.")
    return offset


def _needs_post_filtering(
    search_type: str,
    match_field: str,
    language: str | None,
    excluded_phrases: list[str],
    deduplicate_records: bool,
) -> bool:
    """Eldönti, hogy kell-e a nyers MEK-találatok után extra helyi szűrés."""
    return any(
        [
            search_type != "raw",
            match_field != "fulltext",
            bool(language),
            bool(excluded_phrases),
            deduplicate_records,
        ]
    )


def _choose_page_size(limit: int, needs_post_filtering: bool) -> int:
    """A várható szűrési veszteséghez igazítja a MEK-től kért oldal méretét."""
    if limit <= 10 and not needs_post_filtering:
        return 10
    if limit <= 50:
        return 50
    return 100


def _fetch_search_page(
    session: requests.Session,
    *,
    keyword: str,
    collection_value: str,
    offset: int,
    page_size: int,
) -> str:
    """Lefuttat egy MEK teljes szövegű keresést és nyers HTML-t ad vissza."""
    response = session.post(
        FULLTEXT_SEARCH_URL,
        data={
            "body": keyword,
            "broadtopic": collection_value,
            "size": str(page_size),
            "sort": "",
            "from": str(offset) if offset else "",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.content.decode("utf-8", errors="replace")


def _parse_search_results(page_html: str) -> dict[str, Any]:
    """A MEK találati HTML-ből kiszedi a nyers találatokat és a következő lap offsetjét."""
    soup = BeautifulSoup(page_html, "html.parser")
    total_hits = 0
    total_node = soup.select_one("h4.numberofhits")
    if total_node:
        match = re.search(r"(\d[\d\s]*)", total_node.get_text(" ", strip=True))
        if match:
            total_hits = int(match.group(1).replace(" ", ""))

    hits: list[dict[str, Any]] = []
    # A MEK listanézete nem teljes bibliográfiai rekordot ad, ezért itt csak azokat a
    # mezőket szedjük ki, amelyek közvetlenül jelen vannak a találati blokkon belül.
    for index, hit_node in enumerate(soup.select("div.elful.results div.hit"), start=1):
        record_link = hit_node.select_one("a.etitem")
        title_node = hit_node.select_one("div.dctitle")
        author_node = hit_node.select_one("div.dcauthor")
        snippet_node = hit_node.select_one("div.foundtext")
        hit_link = hit_node.select_one("a.mekfound")

        record_url = _normalize_record_url(record_link["href"]) if record_link and record_link.has_attr("href") else ""
        hit_url = ""
        if hit_link and hit_link.has_attr("href"):
            hit_url = urljoin(BASE_URL, hit_link["href"])

        hits.append(
            {
                "page_rank": index,
                "title": _clean_text(title_node.get_text(" ", strip=True) if title_node else ""),
                "author": _clean_text(author_node.get_text(" ", strip=True) if author_node else ""),
                "record_url": record_url,
                "record_id": _extract_record_id(record_url),
                "hit_url": hit_url,
                "snippet": _clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else ""),
            }
        )

    next_offset = None
    # A lapozás nem linkekkel, hanem inline JS-hívással van megadva, ezért regexszel olvassuk ki.
    next_button = soup.select_one("input.nextp[onclick]")
    if next_button and next_button.has_attr("onclick"):
        match = re.search(r"pageNextPrev\('(\d+)'\)", next_button["onclick"])
        if match:
            next_offset = int(match.group(1))

    return {
        "total_hits": total_hits,
        "hits": hits,
        "next_offset": next_offset,
    }


def _extract_record_id(record_url: str) -> str:
    """A MEK rekord URL-jéből előállít egy stabil, emberbarát rekordazonosítót."""
    match = re.search(r"/(\d{5})/?$", record_url)
    if match:
        return f"MEK-{match.group(1)}"
    return ""


def _record_xml_url(record_url: str) -> str:
    """A rekord fő URL-jéből az XML metaadat-forrás URL-jét állítja elő."""
    return f"{record_url.rstrip('/')}/index.xml"


def _text_or_empty(element: ElementTree.Element | None) -> str:
    """Biztonságosan olvas XML szöveget, hogy hiányzó node-ok se dobjanak hibát."""
    if element is None or element.text is None:
        return ""
    return _clean_text(element.text)


def _parse_contributors(root: ElementTree.Element) -> list[dict[str, str]]:
    """A rekord XML contributor mezőit egységes név-szerep struktúrává alakítja."""
    contributors: list[dict[str, str]] = []
    for contributor in root.findall("dc_contributor"):
        family_name = _text_or_empty(contributor.find("FamilyName"))
        given_name = _text_or_empty(contributor.find("GivenName"))
        # A MEK rekordok nem mindenhol ugyanúgy töltöttek, ezért többféle névforrást próbálunk.
        fallback_name = _clean_text(" ".join(part for part in [family_name, given_name] if part))
        name = fallback_name or _text_or_empty(contributor.find("name")) or _clean_text(" ".join(contributor.itertext()))
        role = _text_or_empty(contributor.find("role"))
        if name:
            contributors.append({"name": name, "role": role})
    return contributors


def _parse_topics(root: ElementTree.Element) -> list[dict[str, str]]:
    """A témastruktúrát külön mezőkben és egy összevont útvonalként is visszaadja."""
    topics: list[dict[str, str]] = []
    for topic_group in root.findall("dc_subject/topicgroup"):
        broadtopic = _text_or_empty(topic_group.find("broadtopic"))
        topic = _text_or_empty(topic_group.find("topic"))
        subtopic = _text_or_empty(topic_group.find("subtopic"))
        if broadtopic or topic or subtopic:
            topics.append(
                {
                    "broadtopic": broadtopic,
                    "topic": topic,
                    "subtopic": subtopic,
                    "path": " > ".join(part for part in [broadtopic, topic, subtopic] if part),
                }
            )
    return topics


def _language_payload(root: ElementTree.Element) -> dict[str, Any]:
    """A rekord nyelvi metaadatait egyszerre kódként és feloldott címkeként állítja elő."""
    codes = _unique_preserve_order([_text_or_empty(lang) for lang in root.findall("dc_language/lang")])
    labels = _unique_preserve_order([LANGUAGE_LABELS.get(code, code) for code in codes])
    return {"codes": codes, "labels": labels}


def _fetch_record_metadata(
    session: requests.Session,
    record_url: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Letölti és cache-eli egy rekord XML metaadatait, hogy több találatnál ne kérjük le újra ugyanazt."""
    if record_url in cache:
        return cache[record_url]

    metadata: dict[str, Any] = {
        "record_url": record_url,
        "record_id": _extract_record_id(record_url),
        "title": "",
        "contributors": [],
        "subject_keywords": [],
        "document_types": [],
        "formats": [],
        "language_codes": [],
        "language_labels": [],
        "topics": [],
        "metadata_source": _record_xml_url(record_url),
    }

    # A részletes bibliográfiai mezők csak az XML nézetben vannak meg elég strukturáltan,
    # ezért a találatlista után minden rekordot innen dúsítunk tovább.
    response = session.get(_record_xml_url(record_url), timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)

    metadata["title"] = _text_or_empty(root.find("dc_title/main")) or _text_or_empty(root.find("dc_title/uniform"))
    metadata["contributors"] = _parse_contributors(root)
    metadata["subject_keywords"] = _unique_preserve_order(
        [_text_or_empty(keyword) for keyword in root.findall("dc_subject/keyword")]
        + [_text_or_empty(keyword) for keyword in root.findall("dc_subject/geographic")]
    )
    metadata["document_types"] = _unique_preserve_order(
        [_text_or_empty(doc_type) for doc_type in root.findall("dc_type")]
    )
    metadata["formats"] = _unique_preserve_order([_text_or_empty(fmt) for fmt in root.findall("dc_format/name")])
    metadata["topics"] = _parse_topics(root)

    language_payload = _language_payload(root)
    metadata["language_codes"] = language_payload["codes"]
    metadata["language_labels"] = language_payload["labels"]

    # A szerző mező a MEK-ben nem mindig egységesen van feltöltve, ezért a contributor lista
    # az elsődleges forrás, és csak utána esünk vissza a lazább creator mezőre.
    creator_names = _unique_preserve_order([_clean_text(" ".join(root.findtext("dc_creator", default="").split()))])
    contributor_names = _unique_preserve_order([entry["name"] for entry in metadata["contributors"]])
    metadata["author"] = " | ".join(contributor_names or creator_names)

    identifier_url = _normalize_record_url(_text_or_empty(root.find("dc_identifier/URL")))
    if identifier_url:
        metadata["record_url"] = identifier_url

    cache[record_url] = metadata
    return metadata


def _language_matches(requested_language: str, result: dict[str, Any]) -> bool:
    """Nyelvi szűrés kódokra és feloldott nyelvnevekre is."""
    if not requested_language:
        return True
    requested = _normalize_text(requested_language)
    candidate_values = result.get("language_codes", []) + result.get("language_labels", [])
    return any(_normalize_text(candidate) == requested for candidate in candidate_values)


def _keyword_target_text(result: dict[str, Any], match_field: str) -> str:
    """A kiválasztott logikai mezőnek megfelelően összerakja azt a szöveget, amin a keresés fusson."""
    if match_field == "fulltext":
        return " ".join([result.get("snippet", ""), result.get("title", "")])
    if match_field == "title":
        return result.get("title", "")
    if match_field == "author":
        return " ".join(
            [result.get("author", "")]
            + [entry.get("name", "") for entry in result.get("contributors", [])]
        )
    if match_field == "subject":
        return " ".join(
            result.get("subject_keywords", [])
            + [topic.get("path", "") for topic in result.get("topics", [])]
        )
    if match_field == "type":
        return " ".join(result.get("document_types", []))
    if match_field == "any_metadata":
        return " ".join(
            [result.get("title", ""), result.get("author", "")]
            + result.get("subject_keywords", [])
            + result.get("document_types", [])
            + result.get("language_labels", [])
            + [topic.get("path", "") for topic in result.get("topics", [])]
        )
    if match_field == "any":
        return " ".join(
            [
                result.get("title", ""),
                result.get("author", ""),
                result.get("snippet", ""),
            ]
            + result.get("subject_keywords", [])
            + result.get("document_types", [])
            + result.get("language_labels", [])
            + [topic.get("path", "") for topic in result.get("topics", [])]
        )
    return result.get("snippet", "")


def _keyword_matches(keyword: str, search_type: str, target_text: str) -> bool:
    """A saját keresési módjainknak megfelelően eldönti, hogy egy találat bent maradhat-e."""
    if search_type == "raw":
        return True

    # A normalizált összehasonlítás miatt az utószűrés kevésbé érzékeny ékezetre és kisbetűre.
    normalized_target = _normalize_text(target_text)
    normalized_keyword = _normalize_text(keyword)
    terms = [term for term in normalized_keyword.split() if term]

    if search_type == "exact_phrase":
        return normalized_keyword in normalized_target
    if search_type == "all_words":
        return all(term in normalized_target for term in terms)
    if search_type == "any_words":
        return any(term in normalized_target for term in terms)
    return True


def _contains_excluded_phrase(result: dict[str, Any], excluded_phrases: list[str]) -> bool:
    """Megnézi, hogy a kizárandó kifejezések előfordulnak-e a dúsított találat bármely fontos mezőjében."""
    if not excluded_phrases:
        return False
    # Szándékosan több mezőt összefűzve vizsgálok, hogy az AI kliensnek ne kelljen külön
    # minden részmezőn kizáráslogikát futtatnia.
    combined_text = " ".join(
        [
            result.get("title", ""),
            result.get("author", ""),
            result.get("snippet", ""),
            " ".join(result.get("subject_keywords", [])),
            " ".join(result.get("document_types", [])),
            " ".join(result.get("language_labels", [])),
            " ".join(topic.get("path", "") for topic in result.get("topics", [])),
        ]
    )
    normalized_combined = _normalize_text(combined_text)
    return any(_normalize_text(phrase) in normalized_combined for phrase in excluded_phrases if phrase)


def _enrich_hit(raw_hit: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Összefésüli a találati listából és az XML rekordból érkező adatokat egy egységes payloadba."""
    title = metadata.get("title") or raw_hit.get("title", "")
    author = raw_hit.get("author") or metadata.get("author", "")
    return {
        **raw_hit,
        "title": title,
        "author": author,
        "record_url": metadata.get("record_url") or raw_hit.get("record_url", ""),
        "record_id": metadata.get("record_id") or raw_hit.get("record_id", ""),
        "contributors": metadata.get("contributors", []),
        "subject_keywords": metadata.get("subject_keywords", []),
        "document_types": metadata.get("document_types", []),
        "formats": metadata.get("formats", []),
        "language_codes": metadata.get("language_codes", []),
        "language_labels": metadata.get("language_labels", []),
        "topics": metadata.get("topics", []),
        "metadata_source": metadata.get("metadata_source", ""),
        "metadata_error": metadata.get("metadata_error"),
    }


@mcp.tool
def search_mek_fulltext(
    keyword: str,
    search_type: str = "raw",
    match_field: str = "fulltext",
    collection: str = "all",
    language: str | None = None,
    excluded_phrases: list[str] | None = None,
    limit: int = 10,
    offset: int = 0,
    deduplicate_records: bool = False,
) -> dict[str, Any]:
    """Keres a Magyar Elektronikus Könyvtár teljes szövegű indexében és strukturált, AI-barát találatlistát ad vissza.

    Paraméterek:
        keyword:
            Kötelező keresőkifejezés. Ezt a szerver a MEK teljes szövegű keresőjének `body` mezőjébe továbbítja.
        search_type:
            A lokális finomszűrés módja. Értékek:
            `raw` - a MEK nyers találatait adja vissza további kulcsszó-ellenőrzés nélkül;
            `all_words` - minden szó szerepeljen a kiválasztott mezőben;
            `any_words` - legalább egy szó szerepeljen;
            `exact_phrase` - a teljes kifejezés szerepeljen.
        match_field:
            A mező, amelyen a lokális finomszűrés történik. Értékek:
            `fulltext`, `title`, `author`, `subject`, `type`, `any_metadata`, `any`.
            Fontos: a MEK publikus felülete jelenleg egyetlen teljes szövegű keresőmezőt kínál,
            ezért a `match_field`, a `language` és az `excluded_phrases` a MEK által visszaadott találati halmazon
            belül kerülnek alkalmazásra szerveroldali utószűrésként.
        collection:
            Gyűjtemény-szűrő. Elfogadott barátságos értékek:
            `all`, `természettudományok`, `műszaki tudományok`,
            `társadalomtudományok`, `humán témák, irodalom`, `kézikönyvek, egyéb`.
        language:
            Opcionális nyelvi szűrő a rekord XML metaadata alapján.
            Megadható például `hun`, `magyar`, `eng`, `angol`.
        excluded_phrases:
            Opcionális kizáró kifejezéslista. Ha bármelyik kifejezés előfordul a címben, szerzőben,
            találati kivonatban vagy a rekord metaadataiban, az adott találat kikerül az eredményből.
        limit:
            A visszaadott találatok maximális száma 1 és 100 között.
        offset:
            A MEK nyers találati listáján belüli induló eltolás. Ez a lapozás alapja, nem a lokálisan szűrt lista indexe.
        deduplicate_records:
            Ha `True`, azonos rekord-URL-ből csak az első találat marad meg. Ez akkor hasznos,
            ha ugyanabból a műből több külön találati hely érkezik vissza.

    Visszatérés:
        Olyan szótár, amely tartalmazza a keresés körülményeit, a nyers találatszámot,
        a bejárt lapok számát és a strukturált találatokat. A találatokban külön mezőként szerepel a cím,
        szerző, rekord-URL, találati hely linkje, tárgyszavak, típusok, nyelvek, témakategóriák és formátumok listája.
    """

    # A bemeneti normalizálás és validálás azért történik itt központilag, hogy a tool
    # bármilyen kliensből ugyanúgy, kiszámítható szabályokkal viselkedjen.
    cleaned_keyword = _clean_text(keyword)
    if not cleaned_keyword:
        raise ValueError("A keyword paraméter nem lehet üres.")

    search_type = _validate_search_type(search_type)
    match_field = _validate_match_field(match_field)
    limit = _coerce_limit(limit)
    offset = _coerce_offset(offset)
    excluded_phrases = [phrase for phrase in (excluded_phrases or []) if _clean_text(phrase)]
    collection_value = _resolve_collection(collection)

    needs_post_filtering = _needs_post_filtering(
        search_type=search_type,
        match_field=match_field,
        language=language,
        excluded_phrases=excluded_phrases,
        deduplicate_records=deduplicate_records,
    )
    # Ha sok helyi szűrés várható, eleve nagyobb oldalméretet kérünk, így kevesebb
    # MEK-kéréssel is össze tudjuk gyűjteni a felhasználó által valóban kért találatokat.
    page_size = _choose_page_size(limit, needs_post_filtering)

    session = _make_session()
    metadata_cache: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    seen_record_urls: set[str] = set()
    raw_hits_considered = 0
    pages_scanned = 0
    total_hits = 0
    next_offset = offset
    truncated = False

    try:
        # A MEK saját lapozásán megyünk végig, közben minden találatot XML-ből dúsítunk,
        # majd a saját logikánk szerint szűrünk tovább.
        while len(results) < limit and pages_scanned < MAX_SEARCH_PAGES:
            page_html = _fetch_search_page(
                session,
                keyword=cleaned_keyword,
                collection_value=collection_value,
                offset=next_offset,
                page_size=page_size,
            )
            page_payload = _parse_search_results(page_html)
            total_hits = max(total_hits, page_payload["total_hits"])
            raw_hits = page_payload["hits"]
            pages_scanned += 1

            if not raw_hits:
                break

            for raw_hit in raw_hits:
                raw_hits_considered += 1
                if not raw_hit["record_url"]:
                    continue

                try:
                    metadata = _fetch_record_metadata(session, raw_hit["record_url"], metadata_cache)
                except (requests.RequestException, ElementTree.ParseError) as exc:
                    # A rekord-metaadat hibája ne törje meg a teljes keresést; ilyenkor a nyers találatot
                    # megtartjuk, és mellé odatesszük a metaadat-hiba szövegét diagnosztikához.
                    metadata = {
                        "record_url": raw_hit["record_url"],
                        "record_id": raw_hit["record_id"],
                        "title": raw_hit["title"],
                        "contributors": [],
                        "subject_keywords": [],
                        "document_types": [],
                        "formats": [],
                        "language_codes": [],
                        "language_labels": [],
                        "topics": [],
                        "metadata_source": _record_xml_url(raw_hit["record_url"]),
                        "metadata_error": str(exc),
                    }
                enriched_hit = _enrich_hit(raw_hit, metadata)

                if deduplicate_records and enriched_hit["record_url"] in seen_record_urls:
                    continue
                if not _language_matches(language or "", enriched_hit):
                    continue
                if _contains_excluded_phrase(enriched_hit, excluded_phrases):
                    continue
                if not _keyword_matches(
                    cleaned_keyword,
                    search_type,
                    _keyword_target_text(enriched_hit, match_field),
                ):
                    continue

                results.append(enriched_hit)
                seen_record_urls.add(enriched_hit["record_url"])
                if len(results) >= limit:
                    break

            computed_next_offset = page_payload["next_offset"]
            if computed_next_offset is None or computed_next_offset <= next_offset:
                break
            next_offset = computed_next_offset

        # Jelöljük, ha az eredmény azért nem teljes, mert a saját védőkorlátunk miatt
        # nem mentünk végig minden MEK oldalon.
        if len(results) < limit and pages_scanned >= MAX_SEARCH_PAGES and next_offset < total_hits:
            truncated = True
    except requests.RequestException as exc:
        raise MekClientError(f"MEK HTTP hiba: {exc}") from exc
    except ElementTree.ParseError as exc:
        raise MekClientError(f"MEK XML feldolgozási hiba: {exc}") from exc

    return {
        # A visszaadott lekérdezési blokk szándékosan részletes, hogy az AI kliens vissza tudja
        # követni, pontosan milyen paraméterezéssel készült az eredményhalmaz.
        "query": {
            "keyword": cleaned_keyword,
            "search_type": search_type,
            "match_field": match_field,
            "collection": collection or "all",
            "language": language,
            "excluded_phrases": excluded_phrases,
            "limit": limit,
            "offset": offset,
            "deduplicate_records": deduplicate_records,
            "mek_endpoint": FULLTEXT_SEARCH_URL,
        },
        "summary": {
            "total_hits": total_hits,
            "returned_hits": len(results),
            "raw_hits_considered": raw_hits_considered,
            "pages_scanned": pages_scanned,
            "page_size_used": page_size,
            "truncated_by_page_cap": truncated,
        },
        "notes": [
            "A MEK jelenlegi teljes szövegű keresőútvonala: https://mek.oszk.hu/hu/search/elfulltext/.",
            "A feladatban megadott https://mek.oszk.hu/hu/search/elfull/ oldal jelenleg az egyszerű keresést szolgálja ki.",
            "A nyelv, a mezőalapú szűrés és a kizáró kifejezések a MEK által visszaadott találatokon belül kerülnek alkalmazásra.",
        ],
        "results": results[:limit],
    }


if __name__ == "__main__":
    """Közvetlen futtatáskor stdio MCP szerverként indul el."""
    mcp.run()
