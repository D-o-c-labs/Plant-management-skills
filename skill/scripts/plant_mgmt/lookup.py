"""External API cascade for plant species lookup and care recommendations.

Cascade order: Trefle → Perenual → OpenPlantbook → Tavily (web search fallback).
Each API is skipped if its key is not configured.
Results are normalized to a common format regardless of source.
"""

import json
from urllib.parse import quote

import requests

from . import config


CACHE_FILENAME = "lookup_cache.json"


# ---------------------------------------------------------------------------
# Normalized result format
# ---------------------------------------------------------------------------

def _empty_result(query):
    return {
        "query": query,
        "found": False,
        "source": None,
        "species": None,
        "care": None,
    }


def _cache_key(kind, query):
    return f"{kind}:{query.strip().lower()}"


def _load_cache():
    try:
        path = config.get_data_dir() / CACHE_FILENAME
    except EnvironmentError:
        return {}
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache):
    try:
        path = config.get_data_dir() / CACHE_FILENAME
    except EnvironmentError:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        key: value
        for key, value in cache.items()
        if not (isinstance(value, dict) and value.get("found") is False)
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _get_cached_result(kind, query):
    cache = _load_cache()
    result = cache.get(_cache_key(kind, query))
    if isinstance(result, dict) and result.get("found") is False:
        return None
    return result


def _set_cached_result(kind, query, result):
    cache = _load_cache()
    if isinstance(result, dict) and result.get("found") is False:
        cache.pop(_cache_key(kind, query), None)
    else:
        cache[_cache_key(kind, query)] = result
    _save_cache(cache)


def _species_result(query, source, *, common_name=None, scientific_name=None,
                    family=None, genus=None, image_url=None, extra=None):
    return {
        "query": query,
        "found": True,
        "source": source,
        "species": {
            "commonName": common_name,
            "scientificName": scientific_name,
            "family": family,
            "genus": genus,
            "imageUrl": image_url,
            "extra": extra or {},
        },
        "care": None,
    }


def _care_result(query, source, *, common_name=None, scientific_name=None,
                 watering=None, sunlight=None, min_temp_c=None, max_temp_c=None,
                 humidity=None, fertilization=None, extra=None):
    return {
        "query": query,
        "found": True,
        "source": source,
        "species": {
            "commonName": common_name,
            "scientificName": scientific_name,
        },
        "care": {
            "watering": watering,
            "sunlight": sunlight,
            "minTempC": min_temp_c,
            "maxTempC": max_temp_c,
            "humidity": humidity,
            "fertilization": fertilization,
            "extra": extra or {},
        },
    }


# ---------------------------------------------------------------------------
# Trefle API client
# ---------------------------------------------------------------------------

def _trefle_search(query, api_key):
    """Search Trefle for species name normalization."""
    try:
        url = f"https://trefle.io/api/v1/plants/search"
        resp = requests.get(url, params={"q": query, "token": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        plants = data.get("data", [])
        if not plants:
            return None

        p = plants[0]
        return _species_result(
            query, "trefle",
            common_name=p.get("common_name"),
            scientific_name=p.get("scientific_name"),
            family=p.get("family"),
            genus=p.get("genus"),
            image_url=p.get("image_url"),
            extra={"trefle_id": p.get("id"), "slug": p.get("slug")},
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Perenual API client
# ---------------------------------------------------------------------------

def _perenual_search(query, api_key):
    """Search Perenual for species info and care guide."""
    try:
        url = "https://perenual.com/api/species-list"
        resp = requests.get(url, params={"q": query, "key": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        species_list = data.get("data", [])
        if not species_list:
            return None

        s = species_list[0]
        watering = s.get("watering")
        sunlight = s.get("sunlight", [])
        if isinstance(sunlight, list):
            sunlight = ", ".join(sunlight)

        return _care_result(
            query, "perenual",
            common_name=s.get("common_name"),
            scientific_name=s.get("scientific_name", [None])[0] if isinstance(s.get("scientific_name"), list) else s.get("scientific_name"),
            watering=watering,
            sunlight=sunlight,
            extra={
                "perenual_id": s.get("id"),
                "cycle": s.get("cycle"),
                "care_level": s.get("care_level"),
            },
        )
    except Exception:
        return None


def _perenual_care(species_id, api_key):
    """Get detailed care guide from Perenual."""
    try:
        url = f"https://perenual.com/api/species-care-guide-list"
        resp = requests.get(url, params={"species_id": species_id, "key": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        guides = data.get("data", [])
        if not guides:
            return None
        return guides[0]  # Return raw for merging
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OpenPlantbook API client
# ---------------------------------------------------------------------------

def _openplantbook_search(query, client_id, client_secret):
    """Search OpenPlantbook for species and care data."""
    try:
        # Get access token
        auth_resp = requests.post(
            "https://open.plantbook.io/api/v1/token/",
            data={"grant_type": "client_credentials",
                  "client_id": client_id,
                  "client_secret": client_secret},
            timeout=10,
        )
        if auth_resp.status_code != 200:
            return None
        token = auth_resp.json().get("access_token")
        if not token:
            return None

        # Search
        headers = {"Authorization": f"Bearer {token}"}
        search_resp = requests.get(
            "https://open.plantbook.io/api/v1/plant/search",
            params={"alias": query},
            headers=headers,
            timeout=10,
        )
        if search_resp.status_code != 200:
            return None

        results = search_resp.json().get("results", [])
        if not results:
            return None

        # Get detailed info for first result
        pid = results[0].get("pid")
        if not pid:
            return None

        detail_resp = requests.get(
            f"https://open.plantbook.io/api/v1/plant/detail/{quote(pid)}/",
            headers=headers,
            timeout=10,
        )
        if detail_resp.status_code != 200:
            return None

        d = detail_resp.json()
        return _care_result(
            query, "openplantbook",
            common_name=d.get("display_pid"),
            scientific_name=d.get("pid"),
            watering=f"every {d.get('min_soil_moist')}-{d.get('max_soil_moist')} moisture units" if d.get("min_soil_moist") else None,
            sunlight=f"{d.get('min_light_lux')}-{d.get('max_light_lux')} lux" if d.get("min_light_lux") else None,
            min_temp_c=d.get("min_temp"),
            max_temp_c=d.get("max_temp"),
            humidity=f"{d.get('min_env_humid')}-{d.get('max_env_humid')}%" if d.get("min_env_humid") else None,
            extra={
                "pid": pid,
                "min_soil_moist": d.get("min_soil_moist"),
                "max_soil_moist": d.get("max_soil_moist"),
                "min_light_lux": d.get("min_light_lux"),
                "max_light_lux": d.get("max_light_lux"),
            },
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tavily web search fallback
# ---------------------------------------------------------------------------

def _tavily_search(query, api_key):
    """Fall back to Tavily web search for plant care info."""
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": f"{query} plant care guide watering sunlight",
                "search_depth": "basic",
                "max_results": 3,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        # Extract summary from first result
        top = results[0]
        return {
            "query": query,
            "found": True,
            "source": "tavily",
            "species": None,
            "care": {
                "watering": None,
                "sunlight": None,
                "summary": top.get("content", "")[:500],
                "sources": [{"title": r.get("title"), "url": r.get("url")} for r in results],
                "extra": {},
            },
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cascade orchestrator
# ---------------------------------------------------------------------------

def search(query):
    """Search for a plant species across all configured APIs.

    Returns the first successful result from the cascade.
    """
    cached = _get_cached_result("search", query)
    if cached:
        return cached

    apis = config.get_configured_apis()

    # 1. Trefle (name normalization)
    if "trefle" in apis:
        result = _trefle_search(query, apis["trefle"]["api_key"])
        if result:
            _set_cached_result("search", query, result)
            return result

    # 2. Perenual (care data)
    if "perenual" in apis:
        result = _perenual_search(query, apis["perenual"]["api_key"])
        if result:
            _set_cached_result("search", query, result)
            return result

    # 3. OpenPlantbook (care data)
    if "openplantbook" in apis:
        result = _openplantbook_search(
            query,
            apis["openplantbook"]["client_id"],
            apis["openplantbook"]["client_secret"],
        )
        if result:
            _set_cached_result("search", query, result)
            return result

    # 4. Tavily (web search fallback)
    if "tavily" in apis:
        result = _tavily_search(query, apis["tavily"]["api_key"])
        if result:
            _set_cached_result("search", query, result)
            return result

    result = _empty_result(query)
    return result


def search_care(query):
    """Search specifically for care recommendations.

    Tries Perenual and OpenPlantbook first (they return care data),
    then falls back to Tavily.
    """
    cached = _get_cached_result("care", query)
    if cached:
        return cached

    apis = config.get_configured_apis()

    if "perenual" in apis:
        result = _perenual_search(query, apis["perenual"]["api_key"])
        if result and result.get("care"):
            species_id = result.get("care", {}).get("extra", {}).get("perenual_id")
            if species_id:
                guide = _perenual_care(species_id, apis["perenual"]["api_key"])
                if guide:
                    merged = dict(result["care"])
                    merged["watering"] = merged.get("watering") or guide.get("watering")
                    merged["fertilization"] = guide.get("fertilizing")
                    merged["extra"] = {**merged.get("extra", {}), "careGuide": guide}
                    result["care"] = merged
            _set_cached_result("care", query, result)
            return result

    if "openplantbook" in apis:
        result = _openplantbook_search(
            query,
            apis["openplantbook"]["client_id"],
            apis["openplantbook"]["client_secret"],
        )
        if result and result.get("care"):
            _set_cached_result("care", query, result)
            return result

    if "tavily" in apis:
        result = _tavily_search(query, apis["tavily"]["api_key"])
        if result:
            _set_cached_result("care", query, result)
            return result

    result = _empty_result(query)
    return result


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------

def cli_lookup(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "search":
        result = search(args.query)
    elif subcmd == "species":
        result = search(args.name)
    elif subcmd == "care":
        result = search_care(args.name)
    else:
        print("Usage: plant_mgmt lookup {search|species|care} <query>")
        return

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not result.get("found"):
            apis = config.get_configured_apis()
            if not apis:
                print(f"No results for '{result['query']}' — no API keys configured.")
                print("Set TREFLE_API_KEY, PERENUAL_API_KEY, OPENPLANTBOOK_CLIENT_ID/SECRET, or TAVILY_API_KEY.")
            else:
                print(f"No results for '{result['query']}' (searched: {', '.join(apis.keys())})")
            return

        print(f"Source: {result['source']}")
        sp = result.get("species")
        if sp:
            if sp.get("commonName"):
                print(f"Common name: {sp['commonName']}")
            if sp.get("scientificName"):
                print(f"Scientific name: {sp['scientificName']}")
            if sp.get("family"):
                print(f"Family: {sp['family']}")

        care = result.get("care")
        if care:
            print("\nCare info:")
            if care.get("watering"):
                print(f"  Watering: {care['watering']}")
            if care.get("sunlight"):
                print(f"  Sunlight: {care['sunlight']}")
            if care.get("minTempC") is not None:
                print(f"  Temperature: {care['minTempC']}°C – {care.get('maxTempC', '?')}°C")
            if care.get("humidity"):
                print(f"  Humidity: {care['humidity']}")
            if care.get("summary"):
                print(f"  Summary: {care['summary'][:200]}")
            if care.get("sources"):
                print("  Sources:")
                for s in care["sources"][:3]:
                    print(f"    - {s.get('title', '?')}: {s.get('url', '?')}")
