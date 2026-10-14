"""Isolated synthetic fine-tune for italic captions and quoted practice fields."""
import argparse,hashlib,json,math,random,sys,time
from pathlib import Path
import torch
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from torch.utils.data import Dataset,DataLoader,ConcatDataset,Subset,Sampler
from easyocr.recognition import NormalizePAD
from easyocr.easyocr import imgH
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT
from dekanat.ocr import get_reader
from scripts.train_ocr import Crops,evaluate
from scripts.train_quote_ocr import QuoteCrops


class FormCrops(Dataset):
    def __init__(self,count,seed,split='train'):
        rng=random.Random(seed);self.rows=[];self.manifest=[];digest=hashlib.sha256()
        names={'train':['arial.ttf','ariali.ttf','times.ttf','timesi.ttf','georgia.ttf'],
               'val':['georgiai.ttf'],'test':['calibrii.ttf']}[split]
        fonts=[Path('C:/Windows/Fonts')/n for n in names]
        if not all(p.exists() for p in fonts):raise FileNotFoundError(fonts)
        self.font_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in fonts}
        captions=['(подпись)','(подпись заявителя)','(дата)','(Ф.И.О.)','(группа)','(место рождения)','(расшифровка подписи)','Руководитель практики','М.П.','']
        grades=['отлично','хорошо','удовлетворительно','неудовлетворительно','зачтено','незачтено']
        adjectives=['Прикладных','Северных','Цифровых','Региональных','Современных','Научных','Проектных']
        nouns=['технологий','систем','решений','исследований','разработок','программ','сервисов']
        for index in range(count):
            mode=rng.random()
            if mode<.35:text=rng.choice(captions);tag='caption'
            elif mode<.65:
                grade=rng.choice(grades);text=rng.choice(['«'+grade+'»','по результатам прохождения практики заслуживает оценки «'+grade+'»','Оценка за практику: «'+grade+'»']);tag='grade'
            else:
                org=rng.choice(['ООО','АО','ЗАО','ОАО'])+' «'+rng.choice(['Центр','Бюро','Лаборатория','Группа'])+' '+rng.choice(adjectives).lower()+' '+rng.choice(nouns)+'»'
                text=rng.choice([org,'производственную практику в '+org+'.','Место прохождения практики: '+org]);tag='organization'
            font_path=rng.choice(fonts);font=ImageFont.truetype(str(font_path),rng.randint(12,32))
            box=font.getbbox(text or ' ');margin=rng.randint(3,8)
            image=Image.new('L',(max(20,box[2]-box[0]+2*margin),max(16,box[3]-box[1]+2*margin)),rng.randint(240,255))
            ImageDraw.Draw(image).text((margin-box[0],margin-box[1]),text,font=font,fill=rng.randint(0,50))
            if not text and rng.random()<.5:ImageDraw.Draw(image).line((1,image.height//2,image.width-2,image.height//2),fill=70,width=1)
            if rng.random()<.25:image=image.filter(ImageFilter.GaussianBlur(rng.uniform(.1,.55)))
            width=math.ceil(imgH*image.width/image.height)
            if width>2048:continue
            digest.update(text.encode('utf-8'));digest.update(image.tobytes())
            self.rows.append((NormalizePAD((1,imgH,width))(image.resize((width,imgH),Image.Resampling.BICUBIC)),text))
            self.manifest.append({'tag':tag,'text':text,'font':font_path.name})
        self.sha256=digest.hexdigest()
    def __len__(self):return len(self.rows)
    def __getitem__(self,index):return self.rows[index]


def collate(batch):
    width=math.ceil(max(x.shape[-1] for x,_ in batch)/4)*4
    return torch.stack([torch.nn.functional.pad(x,(0,width-x.shape[-1]),mode='replicate') for x,_ in batch]),[text for _,text in batch]


class WidthBatches(Sampler):
    """Avoid mixing tiny captions and page-wide sentences in one padded batch."""
    def __init__(self,data,batch=8):
        self.indices=sorted(range(len(data)),key=lambda i:data[i][0].shape[-1]);self.batch=batch
    def __iter__(self):
        buckets=[self.indices[i:i+self.batch] for i in range(0,len(self.indices),self.batch)]
        random.shuffle(buckets)
        for bucket in buckets:
            random.shuffle(bucket);yield bucket
    def __len__(self):return math.ceil(len(self.indices)/self.batch)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--epochs',type=int,default=8)
    parser.add_argument('--count',type=int,default=2600);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.output.resolve().parent== (ROOT/'models').resolve():raise ValueError('Fresh isolated candidate path required')
    torch.manual_seed(20261025);random.seed(20261025);torch.set_num_threads(4)
    parent=ROOT/'models/ocr_quotes.pt';parent_hash=hashlib.sha256(parent.read_bytes()).hexdigest()
    reader=get_reader(True,parent,detector=False);model=getattr(reader.recognizer,'module',reader.recognizer)
    train_data=FormCrops(args.count,2026102500);val_data=FormCrops(400,2026102501,'val');test_data=FormCrops(400,2026102502,'test')
    # Empty targets stay in evaluation. Isolate their numerical behavior before training on them.
    nonempty=Subset(train_data,[i for i,(_,text) in enumerate(train_data) if text])
    mixed=ConcatDataset([nonempty,Crops(1600,2026102503,reader.character),QuoteCrops(500,2026102504)])
    train=DataLoader(mixed,batch_sampler=WidthBatches(mixed),collate_fn=collate)
    val=DataLoader(val_data,batch_size=1,collate_fn=collate);test=DataLoader(test_data,batch_size=1,collate_fn=collate)
    replay=DataLoader(Crops(480,73001,reader.character,True),batch_size=32)
    baseline=evaluate(model,val,reader.converter,reader.device);baseline_replay=evaluate(model,replay,reader.converter,reader.device)
    for parameter in model.FeatureExtraction.parameters():parameter.requires_grad=False
    for layer in [m for m in model.FeatureExtraction.modules() if isinstance(m,torch.nn.Conv2d)][-2:]:
        for parameter in layer.parameters():parameter.requires_grad=True
    optimizer=torch.optim.AdamW([{'params':[p for p in model.FeatureExtraction.parameters() if p.requires_grad],'lr':1e-6},
                                 {'params':model.SequenceModeling.parameters(),'lr':5e-6},{'params':model.Prediction.parameters(),'lr':2e-5}],weight_decay=1e-5)
    criterion=torch.nn.CTCLoss(blank=0,zero_infinity=True);history=[];best=float('inf');state=None;selected=None;began=time.perf_counter()
    failure=None
    for epoch in range(args.epochs):
        model.train();model.FeatureExtraction.eval();loss_sum=0
        for images,texts in train:
            optimizer.zero_grad(set_to_none=True);targets,lengths=reader.converter.encode(texts)
            logits=model(images.to(reader.device),None).log_softmax(2);input_lengths=torch.IntTensor([logits.shape[1]]*len(texts))
            loss=criterion(logits.permute(1,0,2),targets.to(reader.device),input_lengths.to(reader.device),lengths.to(reader.device))
            if not torch.isfinite(loss):failure={'epoch':epoch+1,'reason':'nonfinite_loss_before_update'};break
            loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),5)
            if not torch.isfinite(norm):failure={'epoch':epoch+1,'reason':'nonfinite_gradient_before_update'};break
            optimizer.step();loss_sum+=float(loss.detach())
        if failure:break
        metrics=evaluate(model,val,reader.converter,reader.device);core=evaluate(model,replay,reader.converter,reader.device)
        eligible=core['exact_match']>=baseline_replay['exact_match']-.01
        current={'epoch':epoch+1,'loss':loss_sum/len(train),'forms':metrics,'replay':core,'replay_gate':eligible};history.append(current);print(json.dumps(current),flush=True)
        score=metrics['cer']+core['cer']
        if eligible and score<best:best=score;selected=current;state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    report={'scope':'Own synthetic caption/grade/organization crops plus synthetic core and quote replay. Georgia italic validation, Calibri italic initial test, font families partially seen upstream. No institutional originals/filled derivatives or real handwriting used for weight training; not real-document accuracy.',
            'parent_sha256':parent_hash,'baseline_forms':baseline,'baseline_replay':baseline_replay,'history':history,'selected':selected,
            'recipe':{'seed':20261025,'count':len(train_data),'nonempty_form_train':len(nonempty),'core_replay_train':1600,'quote_replay_train':500,'batch':8,'width_sorted_batches':True,'evaluation_batch':1,'epochs':args.epochs,'feature_last_conv_layers':2,'feature_lr':1e-6,'sequence_lr':5e-6,'prediction_lr':2e-5,'feature_batchnorm':'evaluation','weight_decay':1e-5,'clip_grad_norm':5,'max_width':2048,'decoder_eval':'greedy','replay_em_tolerance':.01},
            'data':{split:{'count':len(data),'sha256':data.sha256,'fonts':data.font_hashes} for split,data in [('train',train_data),('val',val_data),('test',test_data)]},'deployed':False,'seconds':time.perf_counter()-began}
    report['numerical_failure']=failure;report['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if state is not None and failure is None:
        model.load_state_dict(state);report['test_forms']=evaluate(model,test,reader.converter,reader.device)
        args.output.parent.mkdir(parents=True,exist_ok=True);torch.save({'state_dict':state,'character':reader.character,'base':'Existing quote recognizer; isolated official-form synthetic adaptation','validation':selected},args.output)
        report['candidate_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
    assert parent_hash==hashlib.sha256(parent.read_bytes()).hexdigest()
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('Candidate saved' if state is not None else 'No replay-safe checkpoint',flush=True)


if __name__=='__main__':main()
