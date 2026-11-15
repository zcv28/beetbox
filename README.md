# beetbox

A light web frontend for [beets](https://beets.io). It finds albums missing from your library, downloads them (Soulseek through [slskd](https://github.com/slskd/slskd)), imports them with beets and keeps the library tidy: covers, artist pictures, romanized names, synced lyrics and upgrades. Suggestions come from [ListenBrainz](https://listenbrainz.org); discographies from MusicBrainz, VocaDB, TouhouDB and UtaiteDB.

## Install

Docker Compose is the only supported install:

```sh
curl -O https://raw.githubusercontent.com/zcv28/beetbox/main/docker-compose.yml
# edit the password, paths and slskd settings, then
docker compose up -d
```

Open http://localhost:8337. Your beets config is created at `./config/beets/config.yaml` on first start.

Settings are environment variables (`BEETBOX_*`, `SLSKD_*`, `LDAP_*`); see `docker-compose.yml` and `src/beetbox/settings.py`.

## Development

```sh
uv sync --extra dev
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE). Includes htmx (BSD-2-Clause), component CSS from [shadcn-html](https://github.com/codylindley/shadcn-html) (MIT) and icons from [Lucide](https://lucide.dev) (ISC); see `src/beetbox/static/ds/LICENSES.md`.
