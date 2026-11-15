#!/bin/sh
set -e

# New names first, then the ones from when the app was called beets-ui.
BEETBOX_DATA="${BEETBOX_DATA:-${BEETSUI_DATA:-/config/beetbox}}"
export BEETBOX_DATA

# Installs from before the rename keep their state in /config/beets-ui: move it once.
if [ "$BEETBOX_DATA" = /config/beetbox ] && [ -d /config/beets-ui ] && [ ! -e /config/beetbox ]; then
    echo "beetbox: moving /config/beets-ui to /config/beetbox"
    # A folder mounted there on its own can't be moved: mount it at /config/beetbox.
    mv /config/beets-ui /config/beetbox 2>/dev/null \
        || echo "beetbox: couldn't move /config/beets-ui (a separate mount?); mount it at /config/beetbox instead"
fi

mkdir -p "$BEETSDIR" "$BEETBOX_DATA"

# First start: give beets a working config.
if [ ! -f "$BEETSDIR/config.yaml" ]; then
    echo "beetbox: no $BEETSDIR/config.yaml found, writing a default one"
    cp /usr/local/share/beetbox/config.default.yaml "$BEETSDIR/config.yaml"
fi

# Optional extra Python packages for beets plugins (persisted in /config).
if [ -n "$EXTRA_PIP_PACKAGES" ]; then
    target=/config/beetbox/pip
    marker="$target/.installed"
    if [ "$(cat "$marker" 2>/dev/null)" != "$EXTRA_PIP_PACKAGES" ]; then
        echo "beetbox: installing extra packages: $EXTRA_PIP_PACKAGES"
        rm -rf "$target"
        mkdir -p "$target"
        # shellcheck disable=SC2086
        pip install --quiet --target "$target" -c /venv/constraints.txt $EXTRA_PIP_PACKAGES
        echo "$EXTRA_PIP_PACKAGES" > "$marker"
    fi
fi

exec "$@"
