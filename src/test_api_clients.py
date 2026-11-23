"""
Testing live connectivity and response shapes for AniList, Jikan, and Kitsu APIs.
"""
import urllib.request
import urllib.parse
import json

def test_anilist():
    print("Testing AniList GraphQL API...")
    query = """
    query ($page: Int, $perPage: Int) {
      Page(page: $page, perPage: $perPage) {
        pageInfo { hasNextPage currentPage lastPage total }
        characters(sort: FAVOURITES_DESC) {
          id
          name { full native alternative }
          image { large medium }
          description
          gender
          age
          dateOfBirth { year month day }
          favourites
          siteUrl
          media(type: ANIME, sort: POPULARITY_DESC, perPage: 2) {
            nodes {
              id
              idMal
              title { romaji english native }
              format
            }
          }
        }
      }
    }
    """
    payload = json.dumps({"query": query, "variables": {"page": 1, "perPage": 3}}).encode("utf-8")
    req = urllib.request.Request(
        "https://graphql.anilist.co",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "AnimeAuctionArena/2.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chars = data["data"]["Page"]["characters"]
            print(f"  [AniList SUCCESS] Retrieved {len(chars)} characters: {[c['name']['full'] for c in chars]}")
            return True
    except Exception as e:
        print(f"  [AniList ERROR] {e}")
        return False

def test_jikan():
    print("Testing Jikan v4 API...")
    url = "https://api.jikan.moe/v4/top/characters?page=1&limit=3"
    req = urllib.request.Request(url, headers={"User-Agent": "AnimeAuctionArena/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chars = data.get("data", [])
            print(f"  [Jikan SUCCESS] Retrieved {len(chars)} characters: {[c['name'] for c in chars]}")
            return True
    except Exception as e:
        print(f"  [Jikan ERROR] {e}")
        return False

def test_kitsu():
    print("Testing Kitsu API...")
    url = "https://kitsu.io/api/edge/characters?page[limit]=3&page[offset]=0"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.api+json", "User-Agent": "AnimeAuctionArena/2.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chars = data.get("data", [])
            names = [c.get("attributes", {}).get("canonicalName", "Unknown") for c in chars]
            print(f"  [Kitsu SUCCESS] Retrieved {len(chars)} characters: {names}")
            return True
    except Exception as e:
        print(f"  [Kitsu ERROR] {e}")
        return False

if __name__ == "__main__":
    test_anilist()
    test_jikan()
    test_kitsu()
