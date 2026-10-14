import hashlib
import json

import pytest
from PIL import Image

from scripts.train_mixed_ocr import read_verified_manifest


def manifest(tmp_path):
    rows = []
    for index, split in enumerate(["train", "validation", "test"]):
        image = tmp_path/f"{split}.png"
        Image.new("L", (20+index, 12), 255-index).save(image)
        rows.append({"split": split, "image": image.name, "text": "12", "approved": True,
                     "crop_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "document_sha256": str(index)})
    path = tmp_path/"manifest.jsonl"
    return path, rows


def save(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_reviewed_manifest_resolves_relative_images(tmp_path):
    path, rows = manifest(tmp_path)
    save(path, rows)
    assert len(read_verified_manifest(path, "12")) == 3


def test_document_leakage_is_rejected(tmp_path):
    path, rows = manifest(tmp_path)
    rows[1]["document_sha256"] = rows[0]["document_sha256"]
    save(path, rows)
    with pytest.raises(ValueError, match="crosses splits"):
        read_verified_manifest(path, "12")


def test_changed_reviewed_crop_is_rejected(tmp_path):
    path, rows = manifest(tmp_path)
    save(path, rows)
    Image.new("L", (20, 12), 0).save(tmp_path/"train.png")
    with pytest.raises(ValueError, match="changed"):
        read_verified_manifest(path, "12")


def test_unreviewed_training_is_rejected(tmp_path):
    path, rows = manifest(tmp_path)
    rows[0]["approved"] = False
    save(path, rows)
    with pytest.raises(ValueError, match="No approved train"):
        read_verified_manifest(path, "12")


def test_unsupported_characters_are_not_silently_removed(tmp_path):
    path, rows = manifest(tmp_path)
    rows[0]["text"] = "12?"
    save(path, rows)
    with pytest.raises(ValueError, match="unsupported"):
        read_verified_manifest(path, "12")
