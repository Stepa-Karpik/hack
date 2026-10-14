"""Isolated, non-independent compatibility diagnostic for a handwriting base.

Requires reviewed upstream PARSeq sources and timm 0.9.16 outside production.
Does not download/execute model hub code or change deployed weights.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def distance(left, right):
    previous = list(range(len(right)+1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(a != b)))
        previous = current
    return previous[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope',choices=['school','hwr200'],default='school')
    for name in ['weights', 'source', 'deps', 'manifest', 'report']:
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    asset_manifest = json.loads((args.weights.parent/'asset_manifest.json').read_text(encoding='utf-8'))
    if asset_manifest['model_revision'] != '7ee349c4aa082a3ea6a694263b329ae613ce4dcd' or asset_manifest['code_revision'] != '1902db043c029a7e03a3818c616c06600af574be':
        raise ValueError('Unexpected experimental asset revisions')
    if hashlib.sha256(args.weights.read_bytes()).hexdigest() != '740c14f3eb61c97faa652a26a8c3f3521fcc9d8a8b202cd2be38aa838161799c':
        raise ValueError('Unexpected model weights')
    for relative, expected in asset_manifest['assets'].items():
        if relative.startswith('source/'):
            source_file = args.source/relative.removeprefix('source/')
            if hashlib.sha256(source_file.read_bytes()).hexdigest() != expected['sha256']:
                raise ValueError('Experimental source changed')
    sys.path[:0] = [str(args.deps), str(args.source)]
    import cv2
    import numpy as np
    import torch
    from PIL import Image
    from strhub.data.utils import Tokenizer
    from strhub.models.parseq.model import PARSeq

    torch.set_num_threads(4)
    start = time.perf_counter()
    payload = torch.load(args.weights, map_location='cpu', weights_only=True)
    config, charset = payload['config'], payload['charset']
    tokenizer = Tokenizer(charset)
    model = PARSeq(num_tokens=len(tokenizer), img_size=(config['img_height'], config['img_width']),
                   **{key: config[key] for key in ['max_label_length', 'patch_size', 'embed_dim', 'enc_num_heads',
                       'enc_mlp_ratio', 'enc_depth', 'dec_num_heads', 'dec_mlp_ratio', 'dec_depth',
                       'decode_ar', 'refine_iters', 'dropout']})
    # Strict loading is essential: a vaguely similar architecture is insufficient.
    model.load_state_dict(payload['model_state'], strict=True)
    model.eval().cuda()
    torch.cuda.synchronize()
    startup = time.perf_counter()-start
    rows, seen, document_splits = [], set(), {}
    for line in args.manifest.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        if record.get('approved') is not True or record['split'] not in ['validation', 'test']:
            continue
        image_path = Path(record['image'])
        if not image_path.is_absolute():
            image_path = args.manifest.parent/image_path
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest != record['crop_sha256'] or digest in seen:
            raise ValueError('Changed or duplicate reviewed crop')
        seen.add(digest)
        document = record['document_sha256']
        if document in document_splits and document_splits[document] != record['split']:
            raise ValueError('Source page crosses evaluated splits')
        document_splits[document] = record['split']
        if any(c not in charset for c in record['text']):
            raise ValueError('Unsupported label: do not silently alter transcription')
        image = np.asarray(Image.open(image_path).convert('RGB'))
        interpolation = cv2.INTER_AREA if image.shape[0] > config['img_height'] or image.shape[1] > config['img_width'] else cv2.INTER_LINEAR
        image = cv2.resize(image, (config['img_width'], config['img_height']), interpolation=interpolation)
        tensor = torch.from_numpy(image.copy()).permute(2,0,1).float().unsqueeze(0).cuda()/127.5-1
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            probabilities = model(tokenizer, tensor).softmax(-1)
            texts, confidence = tokenizer.decode(probabilities)
        torch.cuda.synchronize()
        prediction = texts[0]
        row = {key: record[key] for key in ['id', 'split', 'text', 'crop_sha256', 'document_sha256']}
        row.update(prediction=prediction, exact_match=prediction == record['text'],
                   edit_distance=distance(prediction, record['text']),
                   mean_token_confidence=float(confidence[0].mean()), seconds=time.perf_counter()-start)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    groups = {}
    for split in ['validation', 'test']:
        subset = [r for r in rows if r['split'] == split]
        if not subset:
            raise ValueError('Missing evaluated split')
        groups[split] = {'examples':len(subset), 'exact_match':sum(r['exact_match'] for r in subset)/len(subset),
                         'cer':sum(r['edit_distance'] for r in subset)/sum(len(r['text']) for r in subset),
                         'median_seconds':float(np.median([r['seconds'] for r in subset]))}
    scope = ('Compatibility diagnostic on 31 reviewed school-notebook crops. This dataset was included in upstream model pretraining; not an independent evaluation, not student-document accuracy.' if args.scope == 'school' else 'Nine manually cropped/transcribed HWR200 lines from three writers. HWR200 is not listed in model card training sources, but absence of pretraining overlap is not proven. Small general-handwriting diagnostic, not student-document accuracy; single assistant review.')
    report = {'scope':scope+' No fine-tuning or deployment.',
              'model_revision':'7ee349c4aa082a3ea6a694263b329ae613ce4dcd',
              'source_revision':'1902db043c029a7e03a3818c616c06600af574be',
              'weights_sha256':hashlib.sha256(args.weights.read_bytes()).hexdigest(),
              'manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              'startup_seconds':startup, 'strict_state_dict':'passed', 'groups':groups, 'rows':rows}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(groups,ensure_ascii=False))


if __name__ == '__main__':
    main()
