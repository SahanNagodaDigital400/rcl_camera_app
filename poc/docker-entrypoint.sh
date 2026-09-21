#!/bin/sh
set -e

# The index is fetched at start rather than baked into the image, because it is
# rebuilt every time the catalogue changes and coupling that to a ~1 GB image
# rebuild would hurt. It lands on the ephemeral disk (4 GiB available; the
# archive is about 86 MB), so this runs again on every restart.
if [ ! -f index/meta.json ]; then
    if [ -z "$INDEX_URL" ]; then
        echo "No index/meta.json and INDEX_URL is unset." >&2
        echo "  Build it with 'make index', pack it with" >&2
        echo "  'tar -czf index.tgz -C index meta.json vectors.npz refs thumbs'," >&2
        echo "  upload that, and set INDEX_URL to its URL." >&2
        exit 1
    fi
    # Query string stripped: a signed URL carries credentials, and this line
    # goes to the deploy log.
    echo "fetching index from ${INDEX_URL%%\?*}"
    # Downloaded whole, then extracted. Piping curl into tar loses curl's exit
    # status — POSIX sh has no pipefail — so a 403 on a private object would
    # surface as "tar: unexpected EOF" or, worse, a half-written index.
    if ! curl -fsSL "$INDEX_URL" -o /tmp/index.tgz; then
        echo "index download failed: is the object public-read, or has the" >&2
        echo "  signed URL expired?" >&2
        exit 1
    fi
    mkdir -p index
    tar -xzf /tmp/index.tgz -C index
    rm -f /tmp/index.tgz
    if [ ! -f index/meta.json ]; then
        echo "archive extracted but index/meta.json is missing: pack it with" >&2
        echo "  'tar -czf index.tgz -C index ...' so the members sit at the root." >&2
        exit 1
    fi
    echo "index ready"
fi

# `python -m tilematch.server`, not `uvicorn tilematch.server:app`: warm_up() is
# called from main(), and importing the app directly skips it — the first scan
# after every deploy would then pay the ONNX session build and first forward
# pass, which reads as "the app is broken" rather than "the app is cold".
exec python -m tilematch.server --host 0.0.0.0 --port "${PORT:-8080}"
