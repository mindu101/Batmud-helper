#!/usr/bin/env python3
"""Local BatMUD bridge client. Never uses HTTP_PROXY/HTTPS_PROXY."""
import argparse,json,pathlib,urllib.request,urllib.error,time
DEFAULT=pathlib.Path.home()/'batclient/agent-bridge/token.txt'
p=argparse.ArgumentParser()
p.add_argument('--token-file',type=pathlib.Path,default=DEFAULT)
s=p.add_subparsers(dest='action',required=True)
s.add_parser('status')
r=s.add_parser('read');r.add_argument('--after',type=int,default=0)
c=s.add_parser('send');c.add_argument('command');c.add_argument('--wait',type=float,default=0)
a=p.parse_args()
def request(path,body=None):
 token=a.token_file.read_text().strip()
 req=urllib.request.Request('http://127.0.0.1:18765'+path,data=None if body is None else body.encode('utf-8'),headers={'Authorization':'Bearer '+token,'Content-Type':'text/plain; charset=utf-8'})
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 try:
  with opener.open(req,timeout=10) as res:return json.load(res)
 except urllib.error.HTTPError as e:raise SystemExit(str(e.code)+' '+e.read().decode())
if a.action=='status':result=request('/status')
elif a.action=='read':result=request('/events?after='+str(a.after))
else:
 result=request('/command',a.command)
 if a.wait>0:
  time.sleep(min(a.wait,30));result={'dispatch':result,'output':request('/events?after='+str(result['after_seq']))}
print(json.dumps(result,ensure_ascii=False,indent=2))
