import pathlib,subprocess,tempfile,time,urllib.request,urllib.error,json
root=pathlib.Path(__file__).resolve().parents[2]
java=next((root/'runtime').glob('*/Contents/Home/bin/java'))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory() as temp:
 p=subprocess.Popen([str(java),'-Djava.awt.headless=true','-cp',':'.join(str(root/x) for x in ['downloads/bat_interfaces.jar','agent-bridge/build','agent-bridge/tests']),'BridgeHarness',temp],stdout=subprocess.DEVNULL)
 try:
  tokenfile=pathlib.Path(temp)/'agent-bridge/token.txt'
  for _ in range(100):
   if tokenfile.exists():break
   time.sleep(.05)
  token=tokenfile.read_text()
  def req(path,body=None,auth=True,extra=None):
   h={'Authorization':'Bearer '+token} if auth else {}
   h.update(extra or {})
   r=urllib.request.Request('http://127.0.0.1:18765'+path,data=body,headers=h)
   try:
    with opener.open(r,timeout=8) as x:return x.status,json.load(x)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  for _ in range(20):
   try: status=req('/status');break
   except OSError:time.sleep(.05)
  assert status[0]==200
  assert req('/status',auth=False)[0]==401
  assert req('/status',extra={'Origin':'https://example.com'})[0]==403
  initial=req('/events?after=0')[1];assert '中文' in initial['events'][0]['text']
  assert req('/command',b'look\nscore')[0]==400
  sent=req('/command',b'look');assert sent[0]==200 and sent[1]['dispatched']
  events=req('/events?after='+str(sent[1]['after_seq']))[1]['events'];assert any(e['text']=='ROOM: look' for e in events)
  assert req('/status')[1]['commands_sent']==1
  print('PASS: auth, browser-origin rejection, Unicode output, input preservation, multiline rejection, command dispatch and cursor readback')
 finally:p.terminate();p.wait(timeout=5)
