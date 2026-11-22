# -*- coding: utf-8 -*-
"""Turn Wikidata triples into the filming-city / story-city / film tables."""

import csv
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
QUERY = ROOT / "_batch.rq"
RESPONSE = ROOT / "_batch.csv"
TRIPLES = ROOT / "triples.csv"
TYPES = ROOT / "place_types.csv"
CACHE = ROOT / "lookup.jsonl"
ALL_TSV = ROOT / "film_city_story.tsv"
CITY_TSV = ROOT / "film_city_story_cities.tsv"
COUNTS = ROOT / "city_pair_counts.tsv"
SUMMARY = ROOT / "summary.json"
README = ROOT / "README.md"
ENDPOINT = "https://qlever.dev/api/wikidata"

CITY_RE = re.compile(
    r"\b(city|town|municipality|commune|comune|capital|metropolis|urban municipality)\b",
    re.I,
)
POINT_RE = re.compile(r"POINT\(([-\d.]+)\s+([-\d.]+)\)", re.I)

FIELDS = [
    "film_qid",
    "film_zh",
    "film_en",
    "year",
    "shot_qid",
    "shot_zh",
    "shot_en",
    "shot_country_qid",
    "shot_country_zh",
    "shot_country_en",
    "shot_lat",
    "shot_lon",
    "shot_kind",
    "story_qid",
    "story_zh",
    "story_en",
    "story_country_qid",
    "story_country_zh",
    "story_country_en",
    "story_lat",
    "story_lon",
    "story_kind",
    "source",
]


def qid(uri):
    if not uri:
        return ""
    return uri.rstrip("/").split("/")[-1]


class QueryError(RuntimeError):
    pass


def qlever(query):
    last = ""
    for attempt in range(8):
        query_path = ROOT / f"_q_{attempt}.rq"
        out = ROOT / f"_batch_{attempt}.csv"
        query_path.write_text(query, encoding="utf-8", newline="\n")
        if query_path.read_text(encoding="utf-8") != query:
            print("query write mismatch", attempt, flush=True)
            time.sleep(1)
            continue
        proc = subprocess.run(
            [
                "curl.exe",
                "--ssl-no-revoke",
                "--ipv4",
                "-sS",
                "--compressed",
                "--max-time",
                "90",
                "-A",
                "euro-film-cities/1.0",
                "-o",
                str(out),
                "-w",
                "%{http_code}",
                "--data-urlencode",
                f"query@{query_path}",
                "-H",
                "Accept: text/csv",
                ENDPOINT,
            ],
            capture_output=True,
            text=True,
        )
        code = (proc.stdout or "").strip() or "0"
        body = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        if code == "200" and body and not body.lstrip().startswith("{") and not body.lstrip().startswith("<"):
            return list(csv.DictReader(body.splitlines()))
        last = f"{code} {(proc.stderr or '')[:80]} {body[:160]}"
        print("retry", attempt + 1, last[:180], flush=True)
        if code == "400" or "Invalid SPARQL" in body:
            if attempt >= 1:
                raise QueryError(last)
            time.sleep(2)
            continue
        if code == "429":
            time.sleep(15)
        elif "handshake" in last or code == "0":
            time.sleep(8)
        else:
            time.sleep(min(20, 3 * (attempt + 1)))
    raise RuntimeError(last)


def mark(entity, tag):
    seen = set(entity.get("seen") or [])
    seen.add(tag)
    entity["seen"] = sorted(seen)


def values(ids):
    return " ".join(f"wd:{item}" for item in ids)


def load_cache():
    found = {}
    if not CACHE.exists():
        return found
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            found[row["id"]] = row
    return found


def blank(item):
    return {
        "id": item,
        "zh": "",
        "en": "",
        "year": "",
        "lat": "",
        "lon": "",
        "country": "",
    }


def ensure(cache, item):
    if item not in cache:
        cache[item] = blank(item)
    return cache[item]


def label_query(batch, lang):
    return (
        "PREFIX wd: <http://www.wikidata.org/entity/>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT ?id ?label WHERE { VALUES ?id { "
        + values(batch)
        + ' } ?id rdfs:label ?label . FILTER(LANG(?label) = "'
        + lang
        + '") }'
    )


def store_labels(cache, batch, lang, rows, handle):
    found = {}
    for row in rows:
        item = qid(row["id"])
        if item in found:
            continue
        found[item] = row["label"]
    for item in batch:
        entity = ensure(cache, item)
        if item in found and found[item]:
            entity[lang] = found[item]
        mark(entity, lang)
        handle.write(json.dumps(entity, ensure_ascii=False) + "\n")
    handle.flush()


def fetch_label_batch(cache, batch, lang, handle):
    try:
        rows = qlever(label_query(batch, lang))
    except QueryError:
        if len(batch) == 1:
            print("skip", lang, batch[0], flush=True)
            rows = []
        else:
            mid = len(batch) // 2
            fetch_label_batch(cache, batch[:mid], lang, handle)
            fetch_label_batch(cache, batch[mid:], lang, handle)
            return
    store_labels(cache, batch, lang, rows, handle)


def fetch_labels(cache, ids, lang):
    missing = [
        item
        for item in ids
        if not cache[item].get(lang) and lang not in set(cache[item].get("seen") or [])
    ]
    print(lang, "missing", len(missing), flush=True)
    with CACHE.open("a", encoding="utf-8") as handle:
        for start in range(0, len(missing), 60):
            batch = missing[start : start + 60]
            fetch_label_batch(cache, batch, lang, handle)
            print(lang, start + len(batch), "/", len(missing), flush=True)
            time.sleep(0.6)


def fetch_plain_labels(cache, ids):
    missing = [
        item
        for item in ids
        if item in cache and not cache[item]["en"] and "plain" not in set(cache[item].get("seen") or [])
    ]
    print("plain en missing", len(missing), flush=True)

    def choose(pairs):
        ranked = []
        for text, lang in pairs:
            if not text:
                continue
            ascii_name = all(ord(ch) < 128 for ch in text) and any(ch.isalpha() for ch in text)
            latin = any("A" <= ch <= "Z" or "a" <= ch <= "z" or "\u00c0" <= ch <= "\u024f" for ch in text)
            if lang == "en" and ascii_name:
                score = 0
            elif lang in {"mul", "en-gb", "en-us", "en-ca"} and ascii_name:
                score = 1
            elif ascii_name:
                score = 2
            elif latin:
                score = 3
            else:
                continue
            ranked.append((score, len(text), text))
        if not ranked:
            return ""
        ranked.sort()
        return ranked[0][2]

    def plain_batch(batch, handle):
        query = (
            "PREFIX wd: <http://www.wikidata.org/entity/>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?id ?label (LANG(?label) AS ?lang) WHERE { VALUES ?id { "
            + values(batch)
            + " } ?id rdfs:label ?label }"
        )
        try:
            rows = qlever(query)
        except QueryError:
            if len(batch) == 1:
                print("skip plain", batch[0], flush=True)
                rows = []
            else:
                mid = len(batch) // 2
                plain_batch(batch[:mid], handle)
                plain_batch(batch[mid:], handle)
                return
        grouped = defaultdict(list)
        for row in rows:
            grouped[qid(row["id"])].append((row["label"], row.get("lang") or ""))
        for item in batch:
            picked = choose(grouped.get(item, []))
            if picked:
                cache[item]["en"] = picked
            mark(cache[item], "plain")
            handle.write(json.dumps(cache[item], ensure_ascii=False) + "\n")
        handle.flush()

    with CACHE.open("a", encoding="utf-8") as handle:
        for start in range(0, len(missing), 15):
            batch = missing[start : start + 15]
            plain_batch(batch, handle)
            print("plain", start + len(batch), "/", len(missing), flush=True)
            time.sleep(0.6)


def fetch_facts(cache, ids, query, apply, tag):
    pending = [item for item in ids if tag not in set(cache[item].get("seen") or [])]
    print("facts", tag, len(pending), flush=True)

    def fact_batch(batch, handle):
        try:
            rows = qlever(query.format(values=values(batch)))
        except QueryError:
            if len(batch) == 1:
                print("skip", tag, batch[0], flush=True)
                rows = []
            else:
                mid = len(batch) // 2
                fact_batch(batch[:mid], handle)
                fact_batch(batch[mid:], handle)
                return
        for row in rows:
            item = qid(row["id"])
            if item not in cache and item not in batch:
                continue
            apply(ensure(cache, item), row)
        for item in batch:
            mark(ensure(cache, item), tag)
            handle.write(json.dumps(cache[item], ensure_ascii=False) + "\n")
        handle.flush()

    with CACHE.open("a", encoding="utf-8") as handle:
        for start in range(0, len(pending), 60):
            batch = pending[start : start + 60]
            fact_batch(batch, handle)
            print("facts", tag, start + len(batch), "/", len(pending), flush=True)
            time.sleep(0.6)


def load_types():
    types = defaultdict(list)
    with TYPES.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            types[qid(row["place"])].append((qid(row["type"]), row.get("typeEn") or ""))
    return types


def kind(item, types):
    rows = types.get(item, [])
    names = " ".join(name.lower() for _, name in rows)
    if "fictional" in names:
        return "虚构"
    if CITY_RE.search(names):
        return "城市"
    if rows:
        return "其他地点"
    return ""


def year_of(text):
    digits = str(text).lstrip("+-")[:4]
    return digits if digits.isdigit() else ""


def coord(text):
    match = POINT_RE.search(text or "")
    if not match:
        return "", ""
    return match.group(2), match.group(1)


def show(entity, fallback):
    if not entity:
        return fallback, ""
    zh = entity.get("zh") or entity.get("en") or fallback
    en = entity.get("en") or ""
    return zh, en


def main():
    triples = []
    with TRIPLES.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            triples.append(
                {
                    "film": qid(row["film"]),
                    "shot": qid(row["shot"]),
                    "story": qid(row["story"]),
                    "shot_country": qid(row["shotCountry"]),
                }
            )
    print("triples", len(triples), flush=True)
    ids = set()
    for row in triples:
        ids.update(item for item in row.values() if item)
    cache = load_cache()
    for item in ids:
        ensure(cache, item)
    fetch_labels(cache, sorted(ids), "en")
    fetch_labels(cache, sorted(ids), "zh")
    fetch_plain_labels(cache, sorted(ids))
    films = sorted({row["film"] for row in triples})
    places = sorted({row["shot"] for row in triples} | {row["story"] for row in triples})
    fetch_facts(
        cache,
        [item for item in films if not cache[item]["year"]],
        "PREFIX wd: <http://www.wikidata.org/entity/>\n"
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
        "SELECT ?id ?year WHERE {{ VALUES ?id {{ {values} }} ?id wdt:P577 ?year }}",
        lambda entity, row: entity.__setitem__(
            "year",
            min(filter(None, [entity["year"], year_of(row["year"])]), default=""),
        ),
        "year",
    )
    fetch_facts(
        cache,
        [item for item in places if not cache[item]["lat"]],
        "PREFIX wd: <http://www.wikidata.org/entity/>\n"
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
        "SELECT ?id ?geo WHERE {{ VALUES ?id {{ {values} }} ?id wdt:P625 ?geo }}",
        lambda entity, row: entity.update(
            dict(zip(("lat", "lon"), coord(row["geo"])))
        )
        if not entity["lat"]
        else None,
        "geo",
    )
    need_country = [item for item in places if not cache[item]["country"]]
    fetch_facts(
        cache,
        need_country,
        "PREFIX wd: <http://www.wikidata.org/entity/>\n"
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
        "SELECT ?id ?country WHERE {{ VALUES ?id {{ {values} }} ?id wdt:P17 ?country }}",
        lambda entity, row: entity.__setitem__("country", entity["country"] or qid(row["country"])),
        "country",
    )
    country_ids = {row["shot_country"] for row in triples}
    country_ids.update(cache[item]["country"] for item in places if cache[item]["country"])
    for item in country_ids:
        ensure(cache, item)
    fetch_labels(cache, sorted(country_ids), "en")
    fetch_labels(cache, sorted(country_ids), "zh")
    types = load_types()
    rows = []
    seen = set()
    for triple in triples:
        key = (triple["film"], triple["shot"], triple["story"])
        if key in seen:
            continue
        seen.add(key)
        film = cache[triple["film"]]
        shot = cache[triple["shot"]]
        story = cache[triple["story"]]
        shot_country_id = triple["shot_country"] or shot["country"]
        story_country_id = story["country"]
        film_zh, film_en = show(film, triple["film"])
        shot_zh, shot_en = show(shot, triple["shot"])
        story_zh, story_en = show(story, triple["story"])
        shot_country_zh, shot_country_en = show(cache.get(shot_country_id), shot_country_id)
        story_country_zh, story_country_en = show(cache.get(story_country_id), story_country_id)
        rows.append(
            {
                "film_qid": triple["film"],
                "film_zh": film_zh,
                "film_en": film_en,
                "year": film["year"],
                "shot_qid": triple["shot"],
                "shot_zh": shot_zh,
                "shot_en": shot_en,
                "shot_country_qid": shot_country_id,
                "shot_country_zh": shot_country_zh,
                "shot_country_en": shot_country_en,
                "shot_lat": shot["lat"],
                "shot_lon": shot["lon"],
                "shot_kind": kind(triple["shot"], types),
                "story_qid": triple["story"],
                "story_zh": story_zh,
                "story_en": story_en,
                "story_country_qid": story_country_id,
                "story_country_zh": story_country_zh,
                "story_country_en": story_country_en,
                "story_lat": story["lat"],
                "story_lon": story["lon"],
                "story_kind": kind(triple["story"], types),
                "source": "Wikidata P915/P840",
            }
        )
    rows.sort(key=lambda row: (row["shot_en"].lower(), row["story_en"].lower(), row["year"], row["film_en"].lower()))
    city_rows = [row for row in rows if row["shot_kind"] == "城市" and row["story_kind"] == "城市"]
    for path, subset in ((ALL_TSV, rows), (CITY_TSV, city_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
            writer.writeheader()
            writer.writerows(subset)
    grouped = defaultdict(set)
    meta = {}
    for row in city_rows:
        key = (row["shot_qid"], row["story_qid"])
        grouped[key].add(row["film_qid"])
        meta[key] = row
    ranked = sorted(grouped.items(), key=lambda item: (-len(item[1]), meta[item[0]]["shot_en"], meta[item[0]]["story_en"]))
    with COUNTS.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            ["films", "shot_qid", "shot_zh", "shot_en", "shot_country_zh", "story_qid", "story_zh", "story_en", "story_country_zh"]
        )
        for key, films in ranked:
            row = meta[key]
            writer.writerow(
                [
                    len(films),
                    row["shot_qid"],
                    row["shot_zh"],
                    row["shot_en"],
                    row["shot_country_zh"],
                    row["story_qid"],
                    row["story_zh"],
                    row["story_en"],
                    row["story_country_zh"],
                ]
            )
    summary = {
        "pairs": len(rows),
        "films": len({row["film_qid"] for row in rows}),
        "city_rows": len(city_rows),
        "city_films": len({row["film_qid"] for row in city_rows}),
        "city_pair_types": len(ranked),
        "top": [
            {
                "films": len(films),
                "shot": meta[key]["shot_zh"],
                "shot_en": meta[key]["shot_en"],
                "story": meta[key]["story_zh"],
                "story_en": meta[key]["story_en"],
            }
            for key, films in ranked[:12]
        ],
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
