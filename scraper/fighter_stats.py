"""Parse an athlete response without network access."""

from pathlib import Path
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from .directory import next_page
from .source import SourceError, checked_page, profile_url


def text(node, selector):
    found = node.select(selector)
    values = {tag.get_text(" ", strip=True) for tag in found}
    if len(values) > 1:
        raise SourceError(f"Conflicting {selector}: {values}")
    return next(iter(values), "") or None


def put(mapping, key, value):
    if key in mapping and mapping[key] != value:
        raise SourceError(f"Conflicting {key}: {mapping[key]!r}, {value!r}")
    mapping[key] = value


def number(value, unit=""):
    if value in (None, "", "--", "%", "N/A"):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), value, re.IGNORECASE)
    if not match:
        raise SourceError(f"Unexpected measurement {value!r} (unit {unit!r})")
    return float(match[1]) / (100 if unit == "%" else 1)


def image_url(node, base):
    if not node or not node.get("src"):
        return None
    url = urljoin(base, node["src"])
    parts = urlsplit(url)
    if (
        parts.scheme == "https"
        and parts.hostname
        and not re.search(
            r"placeholder|silhouette|no[-_]profile|no[-_]image|default[-_]athlete",
            parts.path,
            re.IGNORECASE,
        )
    ):
        return url


@dataclass
class Profile:
    fields: dict
    bouts: dict
    history_status: str
    following: str | None
    warnings: list
    signature: tuple


STATS = {
    "sig. str. landed": ("slpm", "per min"),
    "sig. str. absorbed": ("sapm", "per min"),
    "takedown avg": ("tdavg", "per 15 min"),
    "submission avg": ("subavg", "per 15 min"),
    "sig. str. defense": ("strdef", "%"),
    "takedown defense": ("tddef", "%"),
}


def missing_warning(warnings, field, raw):
    warnings.append(
        {"field": field, "raw": raw, "reason": "missing source value",
         "category": "missing_optional"}
    )


def statistics(page, fields, warnings):
    for group in page.select(".c-stat-compare__group"):
        label = (text(group, ".c-stat-compare__label") or "").casefold()
        if label in STATS:
            key, unit = STATS[label]
            suffix = text(group, ".c-stat-compare__label-suffix")
            raw = text(group, ".c-stat-compare__number")
            value = number(raw, "%" if unit == "%" else "")
            if value is None:
                missing_warning(warnings, key, raw)
            if value is not None and unit != "%" and (suffix or "").casefold() != unit:
                raise SourceError(f"Unexpected unit for {label}: {suffix}")
            put(fields, key, value)
    for chart in page.select(".overlap-athlete-content"):
        title = (text(chart, ".c-overlap--stats__title") or "").casefold()
        key = {
            "striking accuracy": "stracc",
            "takedown accuracy": "tdacc",
            "grappling accuracy": "tdacc",
        }.get(title)
        if not key:
            continue
        raw = text(chart, ".e-chart-circle__percent")
        value = number(raw, "%")
        put(fields, key, value)
        if value is None:
            missing_warning(warnings, key, raw)
        counts = {}
        for dl in chart.select("dl.c-overlap__stats"):
            put(counts, text(dl, "dt"), text(dl, "dd"))
        prefix = "Takedowns" if key == "tdacc" else "Sig. Strikes"
        landed = number(counts.get(prefix + " Landed"))
        attempted = number(counts.get(prefix + " Attempted"))
        rate = fields.get("tdavg" if key == "tdacc" else "slpm")
        missing_landed = bool(attempted) and landed is None
        over_attempts = (
            landed is not None and attempted is not None and landed > attempted
        )
        ratio_conflict = (
            bool(attempted)
            and landed is not None
            and value is not None
            and abs(landed / attempted - value) > 0.00501
        )
        no_attempts = attempted == 0 and (bool(value) or bool(rate))
        if missing_landed or over_attempts or ratio_conflict or no_attempts:
            warnings.append(
                {
                    "field": key,
                    "reported": raw,
                    "counts": counts,
                    "rate": rate,
                }
            )


CARD = ".c-card-event--athlete-results"
OUTCOMES = {
    "win": "win",
    "loss": "loss",
    "draw": "draw",
    "nc": "no contest",
    "no contest": "no contest",
    "no-contest": "no contest",
}
OBSERVED_UFC_PATHS = frozenset(
    p.casefold() for p in json.loads(
        (Path(__file__).with_name("ufc_event_paths.json")).read_text(encoding="utf-8")
    )["paths"]
)


def is_ufc_event(path):
    return bool(UFC_EVENT.match(path)) or path.casefold() in OBSERVED_UFC_PATHS


UFC_EVENT = re.compile(
    r"/event/(?:ufc-(?:[0-9]+(?:-|$)|fight-night-|on-|fight-for-the-troops|freedom-250)|ufn-)",
    re.IGNORECASE,
)


def outcome(card, corner):
    labels = [
        *corner.get("class", []),
        (text(corner, CARD + "__plaque") or "").casefold(),
    ]
    outcomes = {OUTCOMES[label] for label in labels if label in OUTCOMES}
    # UFC also renders class="... no contest" with no plaque on either corner.
    if {"no", "contest"}.issubset(corner.get("class", [])):
        outcomes.add("no contest")
    for result in card.select(CARD + "__result"):
        if text(result, CARD + "__result-label") == "Method":
            method = (text(result, CARD + "__result-text") or "").casefold()
            if method in {"draw", "nc", "no contest", "no-contest"}:
                outcomes.add(OUTCOMES[method])
    return outcomes.pop() if len(outcomes) == 1 else None


def bout_key(event, card, url):
    if event.fragment.isdigit():
        return "bout:" + event.fragment
    participants = sorted(
        profile_url(a["href"], url) for a in card.select(CARD + "__headline a[href]")
    )
    if len(set(participants)) == 2:
        return "|".join([event.path, *participants])


def history(page, url, today, fields, warnings):
    view = page.select_one("#athlete-record .view-id-athlete_results")
    if not view:
        return {}, "unknown", None, ()
    cards = view.select("article" + CARD)
    empty = text(view, ".view-empty")
    known_empty = empty and re.search(
        r"no (?:fights|results|bouts)", empty, re.IGNORECASE
    )
    state = "complete" if cards or known_empty else "unknown"
    bouts, signature = {}, []
    for card in cards:
        date_text = text(card, CARD + "__date") or ""
        events = {
            urljoin(url, a["href"])
            for a in card.select("a[href]")
            if "/event/" in a["href"]
        }
        signature.append(
            (date_text, tuple(sorted(events)), text(card, CARD + "__headline"))
        )
        try:
            day = datetime.strptime(
                date_text.replace(".", "").replace("Sept ", "Sep "), "%b %d, %Y"
            ).date()
        except ValueError:
            day = None
        if day and day > today:
            continue
        corners = [
            c
            for c in card.select(CARD + "__image")
            if any(
                profile_url(a["href"], url) == fields["url"]
                for a in c.select('a[href*="/athlete/"]')
            )
        ]
        event = urlsplit(next(iter(events))) if len(events) == 1 else None
        if event and event.hostname in {"ufc.com", "www.ufc.com"}:
            if re.match(
                r"/event/(?:pride-|strikeforce-|wec-)", event.path, re.IGNORECASE
            ):
                continue
            if len(corners) == 1 and day and is_ufc_event(event.path):
                corner = corners[0]
                if not fields.get("headshot_url"):
                    fields["headshot_url"] = image_url(
                        corner.select_one(
                            "img.image-style-event-results-athlete-headshot"
                        ),
                        url,
                    )
                result = outcome(card, corner)
                key = bout_key(event, card, url)
                if result and key:
                    put(bouts, key, (day, result))
                    continue
        state = "incomplete"
        warnings.append(
            {
                "field": "history",
                "date": date_text,
                "events": sorted(events),
                "reason": "unresolved bout",
            }
        )
    return bouts, state, next_page(view, url), tuple(signature)


def parse_profile(html, url, today):
    page = checked_page(html, url)
    name = text(page, ".hero-profile__name")
    canonicals = {
        profile_url(a["href"], url) for a in page.select("link[rel~=canonical][href]")
    }
    if (
        canonicals != {profile_url(url)}
        or not name
        or not page.select_one(".c-bio__field,.hero-profile__division-body")
    ):
        raise SourceError(f"Missing or conflicting athlete identity at {url}")
    fields = {"name": name, "url": canonicals.pop(), "source": "UFC.com"}
    warnings = []
    for tag in page.select('script[data-drupal-selector="drupal-settings-json"]'):
        path = json.loads(tag.string).get("path", {}).get("currentPath", "")
        match = re.fullmatch(r"node/(\d+)", path)
        if match:
            put(fields, "source_id", match[1])
    for tag in page.select('script[type="application/ld+json"]'):
        obj = json.loads(tag.string)
        nodes = obj if isinstance(obj, list) else obj.get("@graph", [obj])
        for node in nodes:
            entity = node.get("mainEntity", {})
            if isinstance(entity, dict) and entity.get("@type") == "Person":
                if (
                    entity.get("url")
                    and profile_url(entity["url"], url) != fields["url"]
                    or entity.get("name", name).casefold() != name.casefold()
                ):
                    raise SourceError(f"Conflicting JSON-LD identity at {url}")
                if entity.get("birthDate"):
                    raw = entity["birthDate"]
                    put(fields, "dob", None if raw in ("--", "N/A") else raw)
                    if raw in ("--", "N/A"):
                        missing_warning(warnings, "dob", raw)
    division = text(page, ".hero-profile__division-title")
    fields["weight_class"] = division.removesuffix(" Division") if division else None
    record = text(page, ".hero-profile__division-body")
    fields.update(record=None, fight_count=None)
    match = re.fullmatch(r"(\d+-\d+-\d+)\s*\(W-L-D\)", record or "")
    if match:
        fields.update(record=match[1], fight_count=sum(map(int, match[1].split("-"))))
    elif record in (None, "--", "N/A") or re.fullmatch(
        r"\d*-\d*-\d*\s*\(W-L-D\)", record
    ):
        missing_warning(warnings, "record", record)
    else:
        raise SourceError(f"Unknown record format {record} at {url}")
    for field in page.select(".c-bio__field"):
        key = (text(field, ".c-bio__label") or "").lower()
        raw = text(field, ".c-bio__text")
        if key in {"height", "reach", "weight"}:
            value = number(
                re.sub(r"\s*lbs\.?$", "", raw, flags=re.IGNORECASE)
                if raw and key == "weight" else raw
            )
            if key == "height" and value == 0:
                warnings.append({
                    "field": key, "raw": raw, "category": "source_inconsistency",
                    "reason": "unusable zero source height",
                })
                value = None
            elif value is None:
                missing_warning(warnings, key, raw)
            put(fields, key, value)
        if key in {"stance", "status"}:
            put(fields, key, None if raw in ("--", "N/A") else raw)
            if raw in (None, "--", "N/A"):
                missing_warning(warnings, key, raw)
    for portrait in page.select("img.hero-profile__image"):
        put(fields, "portrait_url", image_url(portrait, url))
    statistics(page, fields, warnings)
    if not page.select_one(".c-stat-compare__group,.overlap-athlete-content"):
        warnings.append({"field": "statistics", "reason": "statistics section absent"})
    elif page.select_one(".c-stat-compare__group") and not any(
        key in fields for key, _ in STATS.values()
    ):
        raise SourceError(f"Unrecognized statistics layout at {url}")
    bouts, state, following, signature = history(page, url, today, fields, warnings)
    return Profile(fields, bouts, state, following, warnings, signature)
