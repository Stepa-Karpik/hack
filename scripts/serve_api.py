"""Start local-only prototype. No dependencies beyond existing runtime."""
from pathlib import Path
import sys,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.participantkit.http_api import make_server

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    server=make_server(args.port)
    print(f'Local API: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();server.job_store.close()

if __name__=='__main__':main()
