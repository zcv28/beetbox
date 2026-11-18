"""Deezer as a catalogue next to MusicBrainz, for when MusicBrainz is slow or down: Find
searches it, its artists open into their albums and its albums into their tracklist,
and Get fetches them (tagged from MusicBrainz on import, found by name)."""

# The Get tests' fixtures are imported below, which pytest needs and ruff reads as redefinitions.
# ruff: noqa: F811

from __future__ import annotations

import httpx
import pytest
import respx

from beetbox import acquire, discography
from beetbox.catalog import Catalog
from beetbox.release_covers import ReleaseCovers, remote_url
from test_catalog import FRAGMENT, PNG, musicbrainz, own_test_album

from test_get import app, client, engine, want  # noqa: F401

ARTIST = {"id": 501, "name": "Test Artist"}


def album(aid, title, kind="album", date=None, **more):
    it = {"id": aid, "title": title, "record_type": kind, "artist": ARTIST, **more}
    if date:
        it["release_date"] = date
    return it


ALBUMS = [
    album(9001, "Big Album", date="2021-05-01"),
    album(9002, "Big Album", date="2021-05-01"),  # its clean version
    album(9003, "Small EP", "ep", date="2019-02-02"),
    album(9004, "Test Album", date="2018-01-01"),
    album(9005, "Best Of", "compile", date="2022-01-01"),
]


def deezer(request: httpx.Request) -> httpx.Response:
    path, q = request.url.path, dict(request.url.params)
    if path == "/search/artist":
        return httpx.Response(200, json={"data": [{**ARTIST, "nb_album": 4}], "total": 1})
    if path == "/search/album":
        it = {k: v for k, v in ALBUMS[0].items() if k != "release_date"}
        return httpx.Response(200, json={"data": [it], "total": 1})
    if path == "/search/track":
        t = {
            "id": 77,
            "title": "Opening Song",
            "duration": 245,
            "artist": ARTIST,
            "album": {"id": 9001, "title": "Big Album"},
        }
        return httpx.Response(200, json={"data": [t], "total": 1})
    if path == "/artist/501":
        return httpx.Response(200, json={**ARTIST, "nb_album": 4})
    if path == "/artist/501/albums":
        return httpx.Response(200, json={"data": ALBUMS, "total": len(ALBUMS)})
    if path == "/album/9001":
        main = {**ARTIST, "role": "Main"}
        return httpx.Response(200, json={**ALBUMS[0], "contributors": [main]})
    if path == "/album/9001/tracks":
        start = int(q.get("index") or 0)
        songs = [{"title": f"Song {i}", "duration": 180 + i} for i in range(1, 4)]
        page = songs[start : start + 2]
        more = {"next": "more"} if start + 2 < len(songs) else {}
        return httpx.Response(200, json={"data": page, "total": len(songs), **more})
    return httpx.Response(200, json={"error": {"type": "DataException", "code": 800}})


@pytest.fixture
def web(client, app, monkeypatch):
    """The client, with Deezer answering and MusicBrainz too (or down, for "broken")."""
    monkeypatch.setattr("beetbox.discography.time.sleep", lambda s: None)
    app.state.catalog = Catalog(app.state.state)
    app.state.source.searches = lambda: []
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="api.deezer.com").mock(side_effect=deezer)
        mock.route(host="musicbrainz.org").mock(side_effect=musicbrainz)
        yield client


def test_find_searches_deezer_and_gets_an_album(web, app):
    page = web.get("/get/find?q=big+album&src=deezer").text
    assert '<option value="deezer" selected>' in page
    part = web.get("/get/find/lookup?kind=releases&q=big+album&src=deezer").text
    assert 'href="/get/release/deezer/9001"' in part
    assert 'href="/get/artist/deezer/501?name=Test%20Artist"' in part
    r = web.post(
        "/wanted/catalog", data={"source": "deezer", "release_id": "9001"}, headers=FRAGMENT
    )
    assert "Waiting to search" in r.text
    (w,) = app.state.state.wanted_list()
    # The date comes from looking the album up (a search doesn't give it); nothing to
    # look it up by on import, so beets finds it on MusicBrainz by name.
    assert (w["source"], w["release_id"], w["lookup_id"]) == ("deezer", "9001", "")
    assert (w["artist"], w["album"], w["year"]) == ("Test Artist", "Big Album", "2021")


def test_find_artists_and_tracks_on_deezer(web):
    part = web.get("/get/find/lookup?kind=artists&q=test&src=deezer").text
    assert 'href="/get/artist/deezer/501?name=Test%20Artist"' in part and "4 releases" in part
    part = web.get("/get/find/lookup?kind=tracks&q=opening&src=deezer").text
    assert "Opening Song" in part and "4:05" in part
    assert 'href="/get/release/deezer/9001"' in part


def test_musicbrainz_down_points_to_deezer(web):
    part = web.get("/get/find/lookup?kind=releases&q=broken&src=musicbrainz").text
    assert "musicbrainz.org answered 500" in part
    assert 'href="/get/find?q=broken&src=deezer">search Deezer instead' in part
    part = web.get("/get/find/lookup?kind=releases&q=zzz&src=deezer").text
    assert "search Deezer instead" not in part


def test_release_page_and_tracklist(web):
    page = web.get("/get/release/deezer/9001").text
    assert "Big Album" in page and "2021-05-01" in page and "from Deezer" in page
    assert 'href="https://www.deezer.com/album/9001"' in page
    tracks = web.get("/get/release/deezer/9001/tracks").text
    assert all(f"Song {i}" in tracks for i in (1, 2, 3))  # over two pages
    assert web.get("/get/release/deezer/404").status_code == 404
    assert web.get("/get/release/deezer/not-a-number").status_code == 404


def test_artist_page_lists_their_albums_once(web, app):
    own_test_album(app)
    page = web.get("/get/artist/deezer/501?name=Test+Artist").text
    assert "from Deezer" in page and 'href="https://www.deezer.com/artist/501"' in page
    part = web.get(
        "/get/artist/deezer/501/releases?name=Test+Artist&kinds=album&kinds=ep&kinds=compilation"
    ).text
    assert part.count('href="/get/release/deezer/9001"') == 1
    assert "/get/release/deezer/9002" not in part  # the clean version of Big Album
    assert "Small EP" in part and "Best Of" in part
    # In the library by name (it was tagged elsewhere).
    releases, _ = app.state.catalog.discography("deezer", "501")
    owned = next(r for r in releases if r["id"] == "9004")
    assert owned["title"] == "Test Album"
    assert 'value="9004"' not in part


def test_deezer_ids_never_match_library_ids():
    assert discography.owned_ids("deezer", "302127") == []
    assert discography.owned_ids("vocadb", "302127", "") == ["302127"]


@respx.mock
def test_deezer_errors_in_the_body(monkeypatch):
    monkeypatch.setattr("beetbox.discography.time.sleep", lambda s: None)
    route = respx.get("https://api.deezer.com/artist/1/albums").mock(
        side_effect=[
            httpx.Response(200, json={"error": {"type": "Exception", "code": 4}}),
            httpx.Response(200, json={"data": [album(1, "A", date="2020")], "total": 1}),
        ]
    )
    (row,) = discography.fetch_deezer(discography.Client(), "1")
    assert row["title"] == "A" and route.call_count == 2
    respx.get("https://api.deezer.com/artist/2/albums").mock(
        return_value=httpx.Response(200, json={"error": {"code": 800}})
    )
    with pytest.raises(discography.DiscographyError, match="not found"):
        discography.fetch_deezer(discography.Client(), "2")


@respx.mock
def test_tracklist_for_get(monkeypatch):
    monkeypatch.setattr("beetbox.discography.time.sleep", lambda s: None)
    respx.route(host="api.deezer.com").mock(side_effect=deezer)
    tracks, lookup = acquire.tracklist(discography.Client(), "deezer", "9001")
    assert [t["title"] for t in tracks] == ["Song 1", "Song 2", "Song 3"] and lookup == ""


@respx.mock
def test_deezer_covers_skip_its_blank_one(tmp_path):
    assert remote_url("deezer", "9001") == "https://api.deezer.com/album/9001/image?size=big"
    assert remote_url("deezer", "x") is None
    respx.get("https://api.deezer.com/album/1/image?size=big").mock(
        return_value=httpx.Response(302, headers={"location": "https://cdn/images/cover/ab/1.jpg"})
    )
    respx.get("https://cdn/images/cover/ab/1.jpg").mock(
        return_value=httpx.Response(200, content=PNG)
    )
    respx.get("https://api.deezer.com/album/2/image?size=big").mock(
        return_value=httpx.Response(302, headers={"location": "https://cdn/images/cover//2.jpg"})
    )
    respx.get("https://cdn/images/cover//2.jpg").mock(return_value=httpx.Response(200, content=PNG))
    covers = ReleaseCovers(tmp_path)
    assert covers.get("deezer", "1")[1] == "image/png"
    assert covers.get("deezer", "2") is None
    assert covers.full_url("deezer", "1") == "https://api.deezer.com/album/1/image?size=xl"


def test_a_slow_musicbrainz_does_not_hold_up_deezer():
    import threading

    from beetbox.catalog import _Shared

    stuck, done = threading.Event(), threading.Event()

    def answer(request):
        if request.url.host == "musicbrainz.org":
            stuck.wait(5)
        return httpx.Response(200, json={"ok": True})

    shared = _Shared(httpx.Client(transport=httpx.MockTransport(answer)))
    slow = threading.Thread(target=shared.get, args=("https://musicbrainz.org/ws/2/x", {}, 0))
    slow.start()

    def fast():
        shared.get("https://api.deezer.com/x", {}, 0)
        done.set()

    threading.Thread(target=fast).start()
    assert done.wait(2)  # answered while MusicBrainz still hangs
    stuck.set()
    slow.join()
