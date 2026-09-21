#!/bin/sh
set -e

# The index is fetched at start rather than baked into the image, because it is
# rebuilt every time the catalogue changes and coupling that to a ~1 GB image
# rebuild would hurt. It lands on the ephemeral disk (4 GiB available; the index
# is about 78 MB), so this runs again on every restart.
if [ ! -f index/meta.json ]; then
    if [ -z "$INDEX_URL" ]; then
        echo "No index/meta.json and INDEX_URL is unset." >&2
        exit 1
    fi
    echo "fetching index"
    mkdir -p index
    curl -fsSL "$INDEX_URL" | tar -xz -C index
fi

# `python -m tilematch.server`, not `uvicorn tilematch.server:app`: warm_up() is
# called from main(), and importing the app directly skips it — the first scan
# after every deploy would then pay the ONNX session build and first forward
# pass, which reads as "the app is broken" rather than "the app is cold".
exec python -m tilematch.server --host 0.0.0.0 --port "${PORT:-8080}"
