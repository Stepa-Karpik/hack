"""Train a compact label classifier on synthetic field prefixes, with OCR noise."""
import argparse
import json
import random
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score,f1_score
from dekanat.schema import ROOT

def load(path): return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

def corrupt(text,rng):
    replacements={"о":"0","О":"0","и":"н","а":"о","е":"с","р":"p","с":"c","в":"ь"}
    return "".join(replacements.get(c,c) if rng.random()<.1 else c for c in text)

def examples(records,seed):
    rng=random.Random(seed)
    texts,labels=[],[]
    for doc in records:
        for row in doc["lines"]:
            label=row["text"].split(":" ,1)[0].split("=",1)[0]
            texts.extend([label,corrupt(label,rng)])
            labels.extend([row["field"]]*2)
        texts.extend(["УЧЕБНЫЙ ОБРАЗЕЦ","Подпись руководителя","М.П.","Заявление","Справка", "Декан факультета"])
        labels.extend(["other"]*6)
    return texts,labels

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,default=ROOT/"data")
    parser.add_argument("--output",type=Path,default=ROOT/"models"/"fields.joblib")
    args=parser.parse_args()
    x,y=examples(load(args.data/"train"/"annotations.jsonl"),42)
    model=Pipeline([("vectorizer",TfidfVectorizer(analyzer="char",ngram_range=(2,5),max_features=15000)),
                    ("classifier",LogisticRegression(C=12,max_iter=300,class_weight="balanced"))])
    model.fit(x,y)
    report={"scope":"Synthetic label-prefix classification with artificial OCR noise. Not e2e field accuracy.","train_examples":len(x),"base_weights":None}
    for split in ["val","test"]:
        xx,yy=examples(load(args.data/split/"annotations.jsonl"),73 if split=="val" else 91)
        pred=model.predict(xx)
        report[split]={"accuracy":accuracy_score(yy,pred),"macro_f1":f1_score(yy,pred,average="macro"),"examples":len(xx)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump(model,args.output)
    (ROOT/"artifacts"/"fields_metrics.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()

