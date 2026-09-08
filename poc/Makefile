PY := .venv/bin/python
.DEFAULT_GOAL := help

help:
	@echo "  make setup       create .venv (python 3.13) and install deps"
	@echo "  make model       download DINOv2-base ONNX weights (~346 MB)"
	@echo "  make prep        normalize Tiles/ into Tiles-prepared/ (fast re-indexing)"
	@echo "  make index       build the vector index (runs prep first)"
	@echo "  make thumbs      regenerate candidate + reference images (no re-embedding)"
	@echo "  make serve       run the demo at http://localhost:8000"
	@echo "  make lan         reachable from a phone on the LAN (http; use the"
	@echo "                   'Choose / take photo' button, not the live preview)"
	@echo "  make lan-https   same but HTTPS, so the live camera preview works too"
	@echo "  make match IMG=path/to/photo.jpg"
	@echo "  make eval        synthetic leave-one-out accuracy"
	@echo "  make eval-sanity pipeline wiring check (expect ~100%)"
	@echo "  make eval-real   accuracy on real photos in queries/"
	@echo "  make test        unit tests (includes the AD-1 symmetry check)"

setup:
	uv venv --python 3.13
	uv pip install onnxruntime pillow numpy fastapi uvicorn python-multipart huggingface-hub pytest

model:
	@mkdir -p models
	$(PY) -c "from huggingface_hub import hf_hub_download as d; import shutil,os; \
	[shutil.copyfile(d('Xenova/dinov2-base',f), os.path.join('models',os.path.basename(f))) \
	 for f in ['onnx/model.onnx','preprocessor_config.json','config.json']]; print('model ready')"

prep:
	$(PY) -m tilematch.prepare

index: prep
	$(PY) -m tilematch.index

thumbs:
	$(PY) -m tilematch.index --thumbs-only

serve:
	$(PY) -m tilematch.server

lan:
	$(PY) -m tilematch.server --host 0.0.0.0

lan-https:
	$(PY) -m tilematch.server --host 0.0.0.0 --tls

match:
	@test -n "$(IMG)" || (echo "usage: make match IMG=path/to/photo.jpg"; exit 1)
	$(PY) -m tilematch.match "$(IMG)"

eval:
	$(PY) -m tilematch.evaluate --mode synthetic --report index/eval-synthetic.json

eval-sanity:
	$(PY) -m tilematch.evaluate --mode sanity --limit 40

eval-real:
	$(PY) -m tilematch.evaluate --mode real --report index/eval-real.json

test:
	$(PY) -m pytest -q

clean:
	rm -rf index/vectors.npz index/meta.json index/thumbs index/refs index/*.jpg index/*.json

.PHONY: help setup model prep index thumbs serve lan lan-https match eval eval-sanity eval-real test clean
