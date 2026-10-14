"""Isolated prose service CLI; does not require the participant-kit folder."""
from pathlib import Path
import sys,json,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.participantkit.service_prose import analyze_document
from scripts.participantkit.format_v1 import KINDS


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path)
    parser.add_argument('--type',choices=list(KINDS),required=True)
    parser.add_argument('--question',action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cpu',action='store_true')
    args=parser.parse_args()
    if args.output.exists():raise RuntimeError('Choose a new output; previous results are preserved')
    result=analyze_document(args.input.read_bytes(),args.input.name,args.type,
        [{'question_id':f'q{i+1}','question':text} for i,text in enumerate(args.question)],gpu=not args.cpu)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=lambda v:v.tolist()),encoding='utf-8')
    print(result['result']['validation']['status'],round(result['seconds'],3),'seconds')


if __name__=='__main__':main()
