"""
Downloads the small on-device models MXB's voice features use, with SHA-256 checks.

- voice_id : NVIDIA TitaNet-small speaker embeddings (40 MB, ONNX, via sherpa-onnx). Tells your voice
             from other voices in the room.
- kws      : open-vocabulary keyword spotter (zipformer, GigaSpeech, 18 MB). Hears "MXB" in the audio
             itself, so nothing is transcribed until you say it.

Both come from the sherpa-onnx GitHub releases (Apache-2.0) and run on the CPU.

    python -m utils.fetch_models voice_id kws
"""
import hashlib
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import requests

_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
MODELS = {
    "voice_id": {
        "url": f"{_RELEASES}/speaker-recongition-models/nemo_en_titanet_small.onnx",
        "sha256": "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e",
        "files": ["nemo_en_titanet_small.onnx"],
        "mb": 40,
    },
    "kws": {
        "url": f"{_RELEASES}/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2",
        "sha256": "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a",
        "files": ["encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx", "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
                  "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx", "tokens.txt", "bpe.model"],
        "mb": 18,
    },
}


def models_dir() -> Path:
    from utils.paths import data_dir
    return data_dir() / "models"


def model_path(name: str) -> Path:
    return models_dir() / name


def is_ready(name: str) -> bool:
    folder = model_path(name)
    return all((folder / f).exists() for f in MODELS[name]["files"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(name: str, progress=print, session=requests) -> Path:
    """Downloads and verifies one model (no-op when present). Returns its folder."""
    spec = MODELS[name]
    folder = model_path(name)
    if is_ready(name):
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        tmp = Path(tmp)
        download = tmp / spec["url"].rsplit("/", 1)[-1]
        progress(f"Downloading the {name} model ({spec['mb']} MB) ...")
        with session.get(spec["url"], stream=True, timeout=(10, 120)) as resp:
            resp.raise_for_status()
            with open(download, "wb") as f:
                for block in resp.iter_content(1 << 16):
                    f.write(block)
        digest = _sha256(download)
        if digest != spec["sha256"]:
            raise RuntimeError(f"{name} model failed its integrity check (sha256 {digest[:12]}...); not installed.")
        if download.suffix == ".bz2":
            with tarfile.open(download, "r:bz2") as tar:
                for member in tar.getmembers():
                    base = Path(member.name).name
                    if base in spec["files"] and member.isfile():
                        source = tar.extractfile(member)
                        with open(tmp / base, "wb") as out:
                            shutil.copyfileobj(source, out)
        for f in spec["files"]:
            src = tmp / f
            if not src.exists():
                raise RuntimeError(f"{name} model is missing {f} after download.")
            shutil.move(str(src), str(folder / f))
    progress(f"{name} model ready.")
    return folder


def main(argv=None) -> int:
    names = (argv if argv is not None else sys.argv[1:]) or list(MODELS)
    for name in names:
        if name not in MODELS:
            print(f"Unknown model {name!r}; choose from {', '.join(MODELS)}")
            return 2
        fetch(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
