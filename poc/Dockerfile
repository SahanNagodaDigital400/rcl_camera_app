# DigitalOcean App Platform prefers a Dockerfile over any buildpack, which solves
# both reasons the buildpack build failed: nothing here is auto-detectable (uv.lock
# lives at the repo root, outside this source directory), and the two runtime
# artifacts — models/ and index/ — are gitignored, so a git-based build cannot see
# them. The model is baked in below; the index is fetched at start.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# curl for the index fetch in the entrypoint.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies before source, so editing tilematch/ does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The same three files `make model` fetches, to the path vision.py expects.
# Baked in at build rather than downloaded at start, so restarts are fast and
# every instance is identical. The Hub cache is dropped in the same layer —
# left behind it would double the 346 MB of weights in the image.
RUN python -c "from huggingface_hub import hf_hub_download as d; import shutil, os; os.makedirs('models', exist_ok=True); [shutil.copyfile(d('Xenova/dinov2-base', f), os.path.join('models', os.path.basename(f))) for f in ['onnx/model.onnx', 'preprocessor_config.json', 'config.json']]" \
 && rm -rf /root/.cache/huggingface

COPY tilematch ./tilematch
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# App Platform injects PORT; this is the default the entrypoint falls back to.
ENV PORT=8080
EXPOSE 8080
CMD ["./docker-entrypoint.sh"]
