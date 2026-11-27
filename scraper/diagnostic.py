"""Check two public HTML responses and optionally inspect the hero image headers."""

from datetime import UTC, datetime
import time

import requests

from .directory import parse_directory
from .fighter_stats import parse_profile
from .source import DIRECTORY, Client, SourceError, approved


def probe_image(client, url):
    if not url:
        print("Hero portrait absent")
        return
    try:
        target, seen = approved(url), set()
        for _ in range(6):
            if target in seen:
                raise SourceError(f"Image redirect loop at {target}")
            seen.add(target)
            client.pause(max(0, client.next_request - time.monotonic()), target)
            client.next_request = time.monotonic() + client.pace
            remaining = max(0.01, client.deadline - time.monotonic())
            with client.session.get(
                target, stream=True,
                timeout=(min(5, remaining), min(10, remaining)),
                allow_redirects=False,
            ) as r:
                if r.status_code in {301, 302, 303, 307, 308} and r.headers.get("Location"):
                    target = approved(r.headers["Location"], target)
                    continue
                mime = r.headers.get("Content-Type", "")
                available = r.status_code == 200 and mime.lower().startswith("image/")
                result = "image" if available else "unavailable"
                print(f"Hero portrait {result}: {target} HTTP {r.status_code} {mime}")
                return {
                    "url": target, "status": r.status_code, "content_type": mime,
                    "available": available, "redirects": len(seen) - 1,
                }
        raise SourceError(f"Image redirect limit at {target}")
    except (requests.RequestException, SourceError) as exc:
        print(f"Hero portrait unavailable: {type(exc).__name__}: {exc}")
        return {"available": False, "error": str(exc)}


def main(argv=None):
    import argparse
    from pathlib import Path
    from .events import LISTING, parse_listing, parse_event
    from .publication import write_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", action="store_true")
    parser.add_argument("--evidence", type=Path, default=Path("diagnostic-evidence"))
    parser.add_argument("--budget", type=int, default=90)
    args = parser.parse_args(argv)
    args.evidence.mkdir(parents=True, exist_ok=True)
    client = Client(pace=1, budget=args.budget, attempts=1)
    client.evidence_dir = args.evidence
    result = {"started": datetime.now(UTC).isoformat(), "checks": [], "success": False}
    try:
        if args.events:
            html, final = client.get(LISTING)
            listed, following = parse_listing(html, final)
            result["checks"].append({"url":final, "listed_events":len(listed), "next":following})
            html, final = client.get(listed[0]["url"])
            event = parse_event(html, final, datetime.now(UTC))
            result["checks"].append({"url":final, "event":event})
        html, final = client.get(DIRECTORY)
        profiles, following = parse_directory(html, final)
        result["checks"].append({"url":final, "directory_profiles":len(profiles)})
        html, final = client.get("https://www.ufc.com/athlete/kayla-harrison")
        fields = parse_profile(html, final, datetime.now(UTC).date()).fields
        if fields["name"] != "Kayla Harrison":
            raise SourceError("Unexpected sampled identity")
        result["checks"].append({"url":final, "name":fields["name"], "source_id":fields.get("source_id")})
        result["optional_image"] = probe_image(client, fields.get("portrait_url"))
        result["success"] = True
        if (result.get("optional_image") or {}).get("status") in {401, 403}:
            result.update(success=False, error="Optional image access denied; required HTML checks succeeded")
    except (ValueError, requests.RequestException) as exc:
        result["error"] = str(exc)
        result["failure_evidence"] = client.save_failure(args.evidence / "failure")
        print(f"Diagnostic failed: {exc}")
    finally:
        client.session.close()
        result["completed"] = datetime.now(UTC).isoformat()
        write_json(args.evidence / "summary.json", result)
    print(result)
    return int(not result["success"])


if __name__ == "__main__":
    raise SystemExit(main())
