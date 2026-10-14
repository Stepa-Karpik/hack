"""Download pinned COCO annotations and selected ZIP members, without remote code."""
import hashlib
import io
import json
import random
import sys
import zipfile
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT

REVISION = "a10cd26104f054dc116a9dbc4a29c34b494eb9ae"
BASE = f"https://huggingface.co/datasets/ai-forever/school_notebooks_RU/resolve/{REVISION}/"


class RemoteZip(io.RawIOBase):
    """Seekable read-only ZIP using validated byte ranges, bounded memory."""
    def __init__(self, url, size):
        self.url, self.size, self.position = url, size, 0
        self.block_start, self.block = -1, b""

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else (self.position if whence == 1 else self.size) + offset
        if self.position < 0:
            raise ValueError("Negative position")
        return self.position

    def read(self, count=-1):
        if count < 0:
            count = self.size - self.position
        count = min(count, self.size - self.position)
        if count <= 0:
            return b""
        start, end = self.position, self.position + count
        if not (self.block_start <= start and end <= self.block_start + len(self.block)):
            stop = min(self.size, max(end, start + 2 * 1024 * 1024))
            response = requests.get(self.url, headers={"Range": f"bytes={start}-{stop-1}"}, timeout=60)
            response.raise_for_status()
            if response.status_code != 206 or response.headers.get("Content-Range") != f"bytes {start}-{stop-1}/{self.size}":
                raise ValueError("Server did not honor exact ZIP byte range")
            self.block_start, self.block = start, response.content
            if len(self.block) != stop-start:
                raise ValueError("Incomplete range")
        result = self.block[start-self.block_start:end-self.block_start]
        self.position = end
        return result


def main():
    target = Path("work/notebook-sample") if sys.platform == "win32" else ROOT/"data/external/notebooks"
    target.mkdir(parents=True, exist_ok=True)
    rows, seen, annotation_hashes = [], set(), {}
    with zipfile.ZipFile(RemoteZip(BASE+"images.zip", 2877174569)) as archive:
        names = {Path(n).name: n for n in archive.namelist() if not n.endswith("/")}
        for split, source, wanted in [("train", "train", 60), ("validation", "val", 24), ("test", "test", 24)]:
            path = target/f"annotations_{source}.json"
            if not path.exists():
                with requests.get(BASE+path.name, stream=True, timeout=60) as response:
                    response.raise_for_status()
                    with path.open("wb") as output:
                        for chunk in response.iter_content(1024*1024):
                            output.write(chunk)
            annotation_hashes[split] = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = {"train": "9436135b4fed7ee05e04d4ae32b9edfb46dd75fae7d022726ac23d1bf42aeee6", "validation": "58906cc9cdad2514597a20ec9dfb2ff9663f14e65f67f7c2af6b8706ccd398e7", "test": "5f79f099af410328ce563a424faac3c69170fcd42f89d9d0c65f02a3ffc46018"}
            if annotation_hashes[split] != expected[split]:
                raise ValueError("Source annotation hash mismatch")
            data = json.loads(path.read_text(encoding="utf-8"))
            images = {r["id"]: r for r in data["images"]}
            annotations = list(data["annotations"])
            random.Random(20261012).shuffle(annotations)
            count = 0
            for entry in annotations:
                text = entry.get("attributes", {}).get("translation")
                if not isinstance(text, str) or not 3 <= len(text.strip()) <= 60:
                    continue
                points = entry.get("segmentation", [])
                if points and isinstance(points[0], list):
                    points = points[0]
                if len(points) < 6:
                    continue
                source_image = images[entry["image_id"]]
                name = Path(source_image["file_name"]).name
                member = names.get(name)
                if member is None:
                    continue
                image_path = target/"pages"/name
                if not image_path.exists():
                    image_path.parent.mkdir(exist_ok=True)
                    image_path.write_bytes(archive.read(member))
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                # One crop per document; reject identical pages across splits.
                if digest in seen:
                    continue
                image = Image.open(image_path).convert("RGB")
                xs, ys = points[::2], points[1::2]
                box = [max(0, int(min(xs))-3), max(0, int(min(ys))-3), min(image.width, int(max(xs))+4), min(image.height, int(max(ys))+4)]
                if box[2]-box[0] < 12 or box[3]-box[1] < 8:
                    continue
                seen.add(digest)
                crop_path = target/"crops"/f"{split}_{count:03}.png"
                crop_path.parent.mkdir(exist_ok=True)
                image.crop(box).save(crop_path)
                rows.append({"id": f"{split}_{count:03}", "split": split, "image": str(crop_path), "text": text.strip(), "document_sha256": digest,
                             "crop_sha256": hashlib.sha256(crop_path.read_bytes()).hexdigest(), "source_member": member, "annotation_id": entry.get("id"), "bbox": box,
                             "approved": False, "review": "pending visual transcription and crop check"})
                count += 1
                print(split, count, flush=True)
                if count == wanted:
                    break
    manifest = target/"manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    report = {"source": "https://huggingface.co/datasets/ai-forever/school_notebooks_RU", "revision": REVISION, "license": "MIT per dataset card",
              "annotation_sha256": annotation_hashes, "manifest": str(manifest), "counts": {s: sum(r["split"] == s for r in rows) for s in ["train", "validation", "test"]},
              "scope": "One handwritten crop per distinct source-page hash. Original splits preserved; writer independence unknown. Pending review, not production training.", "originals_redistributed": False}
    (ROOT/"artifacts/notebook_sample_sources.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
