"""The external tool: a short Wikipedia summary for a study topic (public REST API, no key)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

USER_AGENT = "study-planner-ruth/1.0 (course exercise)"


class WikiError(Exception):
    pass


def _get_json(url: str, opener=urllib.request.urlopen) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with opener(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wiki_summary(topic: str, lang: str = "en", max_chars: int = 600, opener=urllib.request.urlopen) -> str:
    """Resolve `topic` to the best-matching article and return a trimmed summary.

    Output is capped at `max_chars` characters of article text: the model only
    needs a starting point, not the whole article.
    """
    search = ("https://%s.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0&format=json&search=%s"
              % (lang, urllib.parse.quote(topic)))
    try:
        found = _get_json(search, opener)
        if not found[1]:
            raise WikiError(f"no Wikipedia article found for '{topic}'")
        title = found[1][0]
        page = _get_json("https://%s.wikipedia.org/api/rest_v1/page/summary/%s"
                         % (lang, urllib.parse.quote(title.replace(" ", "_"))), opener)
    except WikiError:
        raise
    except Exception as e:  # network errors, HTTP errors, bad JSON
        raise WikiError(f"Wikipedia request failed: {e}") from e
    extract = " ".join((page.get("extract") or "").split())
    if len(extract) > max_chars:
        extract = extract[:max_chars].rsplit(" ", 1)[0] + "..."
    url = page.get("content_urls", {}).get("desktop", {}).get("page", "")
    return f"{page.get('title', title)}: {extract}\nsource: {url}"
