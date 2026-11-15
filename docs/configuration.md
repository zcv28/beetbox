# Configuration

beetbox is configured with environment variables, set in `docker-compose.yml`. Only a password (or LDAP) is required; everything else has a default. beets itself is configured in `/config/beets/config.yaml`, written on first start.

Variables from before the rename (`BEETSUI_*`) still work; the log says which to rename.

## Sign-in

| Variable | Default | |
|---|---|---|
| `BEETBOX_PASSWORD` | | Password for the single `admin` user. Required unless LDAP is on. |
| `BEETBOX_LDAP_ENABLED` | `false` | Sign in against LDAP instead of the password. |
| `LDAP_URL` | | Server, e.g. `ldap://lldap:3890`. Required with LDAP. |
| `LDAP_BASE_DN` | | Where users are searched, e.g. `ou=people,dc=example,dc=org`. Required with LDAP. |
| `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD` | | Account used to search for users. Empty: anonymous search. |
| `LDAP_USER_FILTER` | `(uid={username})` | Who may sign in. Must contain `{username}`; add a `memberOf` clause to limit it to a group. |
| `LDAP_START_TLS` | `false` | Upgrade the connection with StartTLS. |
| `BEETBOX_ADMIN_GROUPS` | `beetbox_admins` | Groups allowed in, comma-separated, any case. Applies to LDAP (read from `memberOf`) and proxy sign-in; the shared password ignores it. Empty: anyone who signs in. |
| `BEETBOX_TRUSTED_PROXIES` | | Proxies whose sign-in headers are believed: compose service names (e.g. `caddy`), IPs or networks. Empty: off. |
| `BEETBOX_TRUSTED_USER_HEADER` | `X-authentik-username` | Header with the signed-in user. |
| `BEETBOX_TRUSTED_GROUPS_HEADER` | `X-authentik-groups` | Header with their groups, separated by `\|`. |
| `BEETBOX_LOGOUT_URL` | | Where Log out goes after a proxy sign-in, e.g. `/outpost.goauthentik.io/sign_out`. |
| `BEETBOX_SECRET_KEY` | generated | Signs the session cookie. Generated once and kept in `/config/beetbox/secret_key`. |
| `BEETBOX_SECURE_COOKIES` | `false` | Send cookies over HTTPS only. Turn on behind an HTTPS reverse proxy. |

### Single sign-on through a proxy

Behind Authentik forward auth (or any proxy that sends the user and groups as headers), beetbox can skip its own login: set `BEETBOX_TRUSTED_PROXIES` to the proxy, and `BEETBOX_LOGOUT_URL` so Log out also signs out of the proxy. Headers are only believed when the connection itself comes from that proxy (not from `X-Forwarded-For`), so other containers on the network can't sign in by sending them. The proxy must also drop these headers when a browser sends them; with Caddy, add `request_header -X-Authentik-Username` and `request_header -X-Authentik-Groups` to the site and keep `forward_auth` inside a `route` block (as Authentik's example does), so the removal runs first: Caddy otherwise orders `forward_auth` before `request_header`, which would remove the real ones. With proxy sign-in on, `BEETBOX_PASSWORD` is optional, and LDAP or the password still work for requests that don't come through the proxy.

## Inbox and import

| Variable | Default | |
|---|---|---|
| `BEETBOX_INBOX` | `/inbox` | Folder watched for new music (slskd's downloads folder). |
| `BEETBOX_SCAN_INTERVAL` | `30` | Seconds between inbox scans (at least 5). |
| `BEETBOX_DEBOUNCE` | `30` | Seconds a folder must stay unchanged before it is looked up. |
| `BEETBOX_AUTO_PREVIEW` | `true` | Look up new inbox folders on their own. Folders asked for in Get are always looked up. |
| `BEETBOX_AUTO_IMPORT` | `0` | Import inbox folders on their own when every match is at least this % (0: never). |
| `BEETBOX_GET_AUTO_IMPORT` | `90` | The same for albums asked for in Get (0: always wait for review). |
| `BEETBOX_DELETE_AFTER_IMPORT` | `false` | Delete the inbox folder once imported. beets copies by default, so the download stays otherwise. |
| `BEETBOX_PRIMARY_ARTIST` | `false` | Reduce album artists to the main artist on import (e.g. `A feat. B` to `A`). |
| `BEETBOX_ROMANIZE` | `false` | Romanize Japanese names on import, keeping the originals alongside. |

## Get (downloads)

| Variable | Default | |
|---|---|---|
| `SLSKD_URL` | | slskd address, e.g. `http://slskd:5030`. Get is off without it. |
| `SLSKD_API_KEY` | | An API key from slskd's settings. |
| `BEETBOX_STALL_MINUTES` | `15` | Minutes a download may make no progress before another uploader is tried (0: never). |
| `LISTENBRAINZ_USER` | | ListenBrainz user whose recommendations and fresh releases Get › Discover shows. |

## Artwork

| Variable | Default | |
|---|---|---|
| `BEETBOX_COVER_SOURCES` | `coverartarchive,fanarttv,theaudiodb,deezer,itunes,discogs,vocadb,touhoudb,utaitedb` | Where album covers are looked for, in order. |
| `BEETBOX_ARTIST_SOURCES` | `fanarttv,wikidata,theaudiodb,deezer,discogs,vocadb,touhoudb,utaitedb` | Where artist pictures are looked for, in order. |
| `BEETBOX_ARTWORK_OVERWRITE` | `false` | Replace existing covers and pictures when fetching. |
| `BEETBOX_MIN_COVER_PX` | `500` | Covers smaller than this on either side are listed as low resolution. |
| `BEETBOX_ARTIST_IMAGE_NAME` | `folder.jpg` | File name of artist pictures in the artist folder (Jellyfin reads `folder.jpg`). Several, comma-separated: the first is written. |
| `FANARTTV_API_KEY` | | Enables fanart.tv. |
| `THEAUDIODB_API_KEY` | `2` | TheAudioDB key; `2` is its free public key. |
| `DISCOGS_TOKEN` | | Enables Discogs (also used by beets' discogs plugin). |

## Lyrics and listening

| Variable | Default | |
|---|---|---|
| `BEETBOX_LYRICS_ROMAJI` | `below` | Romaji in Japanese synced lyrics: `below` each line, `inline` after it, `only` romaji, or `off`. |
| `JELLYFIN_URL`, `JELLYFIN_API_KEY` | | Read play counts and favourites from Jellyfin (Insights › Listening). |
| `JELLYFIN_USER` | | Whose play counts. Empty: the only user, or the first administrator. |

## Backups

| Variable | Default | |
|---|---|---|
| `BEETBOX_BACKUP_HOURS` | `24` | Hours between copies of the beets library database and beetbox's state (0: none). |
| `BEETBOX_BACKUP_KEEP` | `7` | How many copies to keep. |

Copies go to `/config/beetbox/backups/<date>_<time>/` (`library.db` and `state.db`) and are safe to take while beets is writing. They live on the same disk as the originals: they protect against bad changes, not a failed disk, so include `/config` in your normal backups too.

To restore one, stop the container, copy its `library.db` over `/config/beets/library.db` (and `state.db` over `/config/beetbox/state.db` if wanted), and start it again.

## Container

| Variable | Default | |
|---|---|---|
| `TZ` | `UTC` | Time zone for times shown in the app and backup names. |
| `BEETBOX_PORT` | `8337` | Port to listen on. |
| `BEETBOX_HOST` | `0.0.0.0` | Address to listen on. |
| `BEETBOX_DATA` | `/config/beetbox` | beetbox's own state, generated key, covers cache and backups. |
| `BEETSDIR` | `/config/beets` | beets config and library. |
| `EXTRA_PIP_PACKAGES` | | Extra Python packages for beets plugins, installed into `/config` on start. |
