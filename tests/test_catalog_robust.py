"""Looking things up when MusicBrainz is slow or down: asked again after a pause, a
site that failed rests a while (lookups behind it fail at once), and an answer kept
from earlier is shown rather than an error."""

from __future__ import annotations

import httpx
import pytest
import respx

from beetbox import catalog, discography
from beetbox.catalog import Catalog, CatalogError

RG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
URL = f"https://musicbrainz.org/ws/2/release-group/{RG}"
GROUP = {"id": RG, "title": "Big Album", "primary-type": "Album", "artist-credit": []}


@pytest.fixture
def pauses(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("beetbox.discography.time.sleep", slept.append)
    return slept


@respx.mock
def test_asks_again_after_a_timeout_or_a_busy_answer(pauses):
    route = respx.get(URL).mock(
        side_effect=[
            httpx.ConnectTimeout("slow"),
            httpx.Response(503, headers={"Retry-After": "3"}),
            httpx.Response(200, json=GROUP),
        ]
    )
    data = discography.Client(attempts=3).get(URL, {}, interval=0)
    assert data["title"] == "Big Album" and route.call_count == 3
    assert pauses == [1.0, 3.0]  # 1s, then what the site said


@respx.mock
def test_pauses_grow_and_stay_short(pauses):
    respx.get(URL).mock(return_value=httpx.Response(502, headers={"Retry-After": "120"}))
    with pytest.raises(httpx.HTTPStatusError):
        discography.Client(attempts=3).get(URL, {}, interval=0)
    assert pauses == [discography.MAX_PAUSE] * 2
    assert discography._pause(0) == 1 and discography._pause(2) == 4
    assert discography._pause(9) == discography.MAX_PAUSE


@respx.mock
def test_a_site_that_failed_rests_and_comes_back(pauses, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("beetbox.catalog.time.monotonic", lambda: now[0])
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    cat = Catalog(state=None)
    with pytest.raises(CatalogError, match="couldn't be reached"):
        cat.release("musicbrainz", RG)
    assert route.call_count == 2  # asked once more, not ATTEMPTS times
    # Resting: said at once, MusicBrainz not asked.
    with pytest.raises(CatalogError, match="didn't answer just now"):
        cat.search("musicbrainz", "releases", "big album")
    assert route.call_count == 2
    # Other sites are asked meanwhile.
    respx.get("https://api.deezer.com/search/album").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    assert cat.search("deezer", "releases", "big album") == []
    # Rested: asked again.
    now[0] += catalog.REST + 1
    route.side_effect = None
    route.return_value = httpx.Response(200, json=GROUP)
    assert cat.release("musicbrainz", RG)["title"] == "Big Album"


@respx.mock
def test_a_500_is_asked_again_but_does_not_rest_the_site(pauses):
    respx.get("https://musicbrainz.org/ws/2/release-group").mock(return_value=httpx.Response(500))
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=GROUP))
    cat = Catalog(state=None)
    with pytest.raises(CatalogError, match="answered 500"):
        cat.search("musicbrainz", "releases", "odd query")
    assert cat.release("musicbrainz", RG)["title"] == "Big Album" and route.called


@respx.mock
def test_an_old_answer_beats_an_error(pauses, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("beetbox.catalog.time.monotonic", lambda: now[0])
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=GROUP))
    cat = Catalog(state=None)
    assert cat.release("musicbrainz", RG)["title"] == "Big Album"
    now[0] += catalog.LOOKUP_KEEP + 1  # too old to keep, but better than nothing
    route.return_value = httpx.Response(503)
    assert cat.release("musicbrainz", RG)["title"] == "Big Album"
    # Gone from MusicBrainz: said so, the old answer isn't kept up.
    now[0] += catalog.REST + 1
    route.return_value = httpx.Response(404)
    with pytest.raises(CatalogError, match="not found"):
        cat.release("musicbrainz", RG)


def test_kept_answers_are_bounded():
    cat = Catalog(state=None)
    for i in range(catalog.MAX_KEPT + 5):
        cat._kept(("k", i), 60, lambda i=i: i)
    assert len(cat._cache) <= catalog.MAX_KEPT
    assert ("k", catalog.MAX_KEPT + 4) in cat._cache


@respx.mock
def test_a_busy_site_is_asked_within_a_budget(pauses, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("beetbox.discography.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "beetbox.discography.time.sleep", lambda s: clock.__setitem__(0, clock[0] + s)
    )
    busy = httpx.Response(503, headers={"Retry-After": "4"})
    route = respx.get(URL).mock(return_value=busy)
    with pytest.raises(httpx.HTTPStatusError):
        discography.Client(attempts=9, budget=10).get(URL, {}, interval=0)
    assert route.call_count == 3 and clock[0] == 8  # a third pause would pass 10s
    # Busy now and then (MusicBrainz under load): got on a later try.
    route.side_effect = [busy, busy, busy, httpx.Response(200, json=GROUP)]
    clock[0] = 0
    assert discography.Client(attempts=5).get(URL, {}, interval=0)["title"] == "Big Album"


@respx.mock
def test_a_site_still_busy_rests_briefly(pauses, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("beetbox.catalog.time.monotonic", lambda: now[0])
    respx.route(host="musicbrainz.org").mock(return_value=httpx.Response(503))
    cat = Catalog(state=None)
    with pytest.raises(CatalogError, match="answered 503"):
        cat.release("musicbrainz", RG)
    with pytest.raises(CatalogError, match="asking again in 10s"):
        cat.search("musicbrainz", "artists", "x")
    now[0] += catalog.BUSY_REST + 1
    with pytest.raises(CatalogError, match="answered 503"):
        cat.search("musicbrainz", "artists", "x")
