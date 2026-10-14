"""Train/evaluate the isolated single-network pilot with immutable output folders."""
import argparse
import hashlib
import importlib.metadata
import json
import random
import time
from pathlib import Path
from scripts.unified.model import UnifiedModel, read_image

def package_version(name):
    try:return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:return None


def rows(data, split):
    return [json.loads(line) for line in (data/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]


def evaluate(net, data, split, output, limit):
    records = rows(data,split)
    if limit:
        records = records[:limit]
    results=[]
    exact=total=invalid=0
    for i, row in enumerate(records):
        file=data/row['image']; assert hashlib.sha256(file.read_bytes()).hexdigest()==row['sha256']
        result = net.predict(read_image(file)); prediction=result['prediction']
        correct=0
        for key, value in row['target']['fields'].items():
            total+=1
            if prediction and prediction['document_type']==row['target']['document_type']:
                correct+=prediction['fields'].get(key)==value
        exact+=correct;invalid+=prediction is None
        results.append({'image':row['image'],'sha256':row['sha256'],'expected':row['target'],
                        **result,'fields_correct':correct})
        print(f'{split} {i+1}/{len(records)} correct={correct}/{len(row["target"]["fields"])} invalid={prediction is None} seconds={result["seconds"]:.2f}',flush=True)
        output.write_text(json.dumps({'scope':'fresh renderer synthetic pilot; not real-world accuracy',
                                      'count':len(results),'planned_count':len(records),'complete':len(results)==len(records),
                                      'fields_correct':exact,'fields_total':total,
                                      'invalid_json':invalid,'records':results},ensure_ascii=False,indent=2),encoding='utf-8')


def train(net, data, output, steps, accumulation, vision_lora=False,
          rehearsal_data=None, learning_rate=5e-5, checkpoint_every=8, warmup_steps=0, semantic_loss=False,
          mark_weight=4.,missing_weight=2.,type_weight=1.,key_weight=1.):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    torch.manual_seed(42); random.seed(42)
    net.model = prepare_model_for_kbit_training(net.model,use_gradient_checkpointing=True,
                                               gradient_checkpointing_kwargs={'use_reentrant':False})
    # Frozen unquantized embeddings/vision need not stay FP32 on this small GPU.
    for name,param in net.model.named_parameters():
        if not param.requires_grad and param.dtype==torch.float32 and 'lora_' not in name:
            param.data=param.data.to(torch.bfloat16)
    if not getattr(net.model,'is_loaded_in_4bit',False):
        net.model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    modules=net.lora_modules(vision_lora) if hasattr(net,'lora_modules') else ['q_proj','v_proj'] + (['qkv'] if vision_lora else [])
    if hasattr(net.model,'peft_config'):
        # Weight continuation starts a NEW optimizer; never claim exact resume.
        actual_modules=set(net.model.peft_config['default'].target_modules)
        if actual_modules != set(modules):raise ValueError('Continuation LoRA module profile mismatch')
        for name,param in net.model.named_parameters():
            if 'lora_' in name:param.requires_grad_(True)
    else:
        net.model = get_peft_model(net.model,LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,
                                                     target_modules=modules,task_type='CAUSAL_LM'))
    net.model.config.use_cache=False
    net.model.train()
    parameters=[p for p in net.model.parameters() if p.requires_grad]
    optimizer=torch.optim.AdamW(parameters,lr=learning_rate,weight_decay=.01)
    records=[(data,row) for row in rows(data,'train')]
    if rehearsal_data is not None:
        records.extend((rehearsal_data,row) for row in rows(rehearsal_data,'train'))
    if not records: raise ValueError('Training partition is empty')
    random.shuffle(records)
    history=[];optimizer.zero_grad(set_to_none=True);started=time.perf_counter()
    for step in range(steps):
        losses=[]
        for micro in range(accumulation):
            root,row=records[(step*accumulation+micro)%len(records)]
            file=root/row['image'];assert hashlib.sha256(file.read_bytes()).hexdigest()==row['sha256']
            batch=net.inputs(read_image(file),row['target'])
            with torch.autocast('cuda',dtype=torch.bfloat16):
                if semantic_loss:
                    from scripts.unified.loss import semantic_weights,weighted_causal_loss
                    labels=batch.pop('labels')
                    weights=semantic_weights(net.processor.tokenizer,labels,row['target'],mark_weight,missing_weight,
                                             type_weight=type_weight,key_weight=key_weight)
                    result=net.model(**batch)
                    loss=weighted_causal_loss(result.logits,labels,weights)
                    del result,labels,weights
                else:
                    loss=net.model(**batch).loss
            if not torch.isfinite(loss):
                raise RuntimeError('Nonfinite loss; checkpoint not promoted')
            (loss/accumulation).backward();losses.append(float(loss.detach()))
            del batch,loss
        effective_lr=learning_rate*min(1.,(step+1)/warmup_steps) if warmup_steps else learning_rate
        for group in optimizer.param_groups: group['lr']=effective_lr
        torch.nn.utils.clip_grad_norm_(parameters,1.0);optimizer.step();optimizer.zero_grad(set_to_none=True)
        history.append({'step':step+1,'loss':sum(losses)/len(losses),'seconds':time.perf_counter()-started,
                        'peak_cuda_allocated_bytes':torch.cuda.max_memory_allocated()})
        (output/'training.json').write_text(json.dumps({'seed':42,'optimizer':'AdamW','lr':learning_rate,
            'warmup_steps':warmup_steps,'training_records':len(records),'checkpoint_every':checkpoint_every,
            'semantic_loss':semantic_loss,'scalar_weights':{'marks':mark_weight,'missing_text':missing_weight,'text_values':2,'other':1} if semantic_loss else None,
            'binding_weights':{'document_type':type_weight,'field_keys':key_weight},
            'rank':8,'alpha':16,'dropout':.05,'accumulation':accumulation,'lora_modules':modules,
            'trainable_parameters':sum(p.numel() for p in parameters),'steps':history},indent=2),encoding='utf-8')
        print(json.dumps(history[-1]),flush=True)
        if (step+1)%checkpoint_every==0 or step+1==steps:
            checkpoint=output/f'step-{step+1:04d}';net.model.save_pretrained(checkpoint)
            net.processor.save_pretrained(checkpoint)
    net.model.config.use_cache=True;net.model.eval()


def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--train-steps',type=int,default=0);p.add_argument('--accumulation',type=int,default=3)
    p.add_argument('--limit',type=int,default=3);p.add_argument('--adapter',type=Path)
    p.add_argument('--max-pixels',type=int,default=512*28*28)
    p.add_argument('--constrained',action='store_true')
    p.add_argument('--vision-lora',action='store_true')
    p.add_argument('--transfer-data',type=Path)
    p.add_argument('--rehearsal-data',type=Path)
    p.add_argument('--learning-rate',type=float,default=5e-5)
    p.add_argument('--checkpoint-every',type=int,default=8)
    p.add_argument('--warmup-steps',type=int,default=0)
    p.add_argument('--continue-adapter',action='store_true')
    p.add_argument('--semantic-loss',action='store_true')
    p.add_argument('--training-token-budget',type=int,default=2048)
    p.add_argument('--geometry-abstention',action='store_true')
    p.add_argument('--precision',choices=['nf4','vision_bf16','bf16'],default='nf4')
    p.add_argument('--family',choices=['qwen','paddle'],default='qwen')
    p.add_argument('--mark-loss-weight',type=float,default=4.)
    p.add_argument('--missing-loss-weight',type=float,default=2.)
    p.add_argument('--type-loss-weight',type=float,default=1.)
    p.add_argument('--key-loss-weight',type=float,default=1.)
    args=p.parse_args()
    if (args.train_steps<0 or args.accumulation<1 or args.limit<0 or
        not 0 < args.learning_rate <= .001 or args.checkpoint_every<1 or args.warmup_steps<0 or
        args.training_token_budget<1024 or args.max_pixels<=0 or
        not 0<args.mark_loss_weight<=100 or not 0<args.missing_loss_weight<=100 or
        not 1<=args.type_loss_weight<=100 or not 1<=args.key_loss_weight<=100):
        raise ValueError('Invalid step, accumulation or evaluation budget')
    if (args.type_loss_weight!=1 or args.key_loss_weight!=1) and not args.semantic_loss:
        raise ValueError('Binding weights require explicit semantic loss')
    if args.adapter and args.train_steps and not args.continue_adapter:
        raise ValueError('Adapter training requires explicit --continue-adapter; optimizer is reset')
    if args.continue_adapter and (not args.adapter or not args.train_steps):
        raise ValueError('Continuation requires an adapter and positive training budget')
    if args.output.exists():raise ValueError('Use a fresh experiment output folder')
    args.output.mkdir(parents=True)
    (args.output/'environment.json').write_text(json.dumps({name:package_version(name) for name in
        ['torch','transformers','peft','accelerate','bitsandbytes','huggingface_hub']},indent=2),encoding='utf-8')
    (args.output/'run-config.json').write_text(json.dumps({'base_revision':args.base.name,
        'adapter_checkpoint':args.adapter.name if args.adapter else None,
        'dataset_manifest_sha256':hashlib.sha256((args.data/'manifest.json').read_bytes()).hexdigest(),
        'contract_sha256':hashlib.sha256(Path(__file__).with_name('contract.py').read_bytes()).hexdigest(),
        'training_runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_loader_sha256':hashlib.sha256(Path(__file__).with_name('model.py').read_bytes()).hexdigest(),
        'family_loader_sha256':hashlib.sha256(Path(__file__).with_name('paddle_model.py').read_bytes()).hexdigest()
            if args.family=='paddle' else None,
        'train_steps':args.train_steps,'accumulation':args.accumulation,'evaluation_limit':args.limit,
        'max_pixels':args.max_pixels,'constrained_decoding':args.constrained,
        'vision_lora':args.vision_lora,
        'learning_rate':args.learning_rate,'warmup_steps':args.warmup_steps,
        'checkpoint_every':args.checkpoint_every,
        'adapter_weight_continuation':args.continue_adapter,'optimizer_state_resumed':False,
        'semantic_loss':args.semantic_loss,
        'training_token_budget':args.training_token_budget,
        'geometry_abstention':args.geometry_abstention,
        'precision_profile':args.precision,
        'model_family':args.family,
        'mark_loss_weight':args.mark_loss_weight,'missing_loss_weight':args.missing_loss_weight,
        'type_loss_weight':args.type_loss_weight,'key_loss_weight':args.key_loss_weight,
        'adapter_sha256':hashlib.sha256((args.adapter/'adapter_model.safetensors').read_bytes()).hexdigest()
            if args.adapter else None,
        'rehearsal_manifest_sha256':hashlib.sha256((args.rehearsal_data/'manifest.json').read_bytes()).hexdigest()
            if args.rehearsal_data else None,
        'transfer_manifest_sha256':hashlib.sha256((args.transfer_data/'manifest.json').read_bytes()).hexdigest()
            if args.transfer_data else None},indent=2),encoding='utf-8')
    model_class=UnifiedModel
    if args.family=='paddle':
        from scripts.unified.paddle_model import PaddleDocumentModel
        model_class=PaddleDocumentModel
    net=model_class(args.base,args.adapter,args.max_pixels,constrained=args.constrained,
                     adapter_trainable=args.continue_adapter,training_token_budget=args.training_token_budget,
                     geometry_abstention=args.geometry_abstention,precision=args.precision)
    print('Loaded one network',flush=True)
    evaluate(net,args.data,'val',args.output/('adapter-val.json' if args.adapter else 'baseline-val.json'),args.limit)
    if args.adapter and not args.train_steps:
        evaluate(net,args.data,'test',args.output/'adapter-test.json',args.limit)
    if args.train_steps:
        train(net,args.data,args.output,args.train_steps,args.accumulation,args.vision_lora,
              args.rehearsal_data,args.learning_rate,args.checkpoint_every,args.warmup_steps,args.semantic_loss,
              args.mark_loss_weight,args.missing_loss_weight,args.type_loss_weight,args.key_loss_weight)
        evaluate(net,args.data,'val',args.output/'trained-val.json',args.limit)
        evaluate(net,args.data,'test',args.output/'trained-test.json',args.limit)
    if args.transfer_data:
        evaluate(net,args.transfer_data,'val',args.output/'transfer-val.json',0)


if __name__=='__main__':main()
