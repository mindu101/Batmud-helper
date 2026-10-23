package local.batbridge;

import com.mythicscape.batclient.interfaces.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import javax.swing.SwingUtilities;

/** Loopback-only, authenticated bridge. No model or game credentials are loaded. */
public final class AgentBridge extends BatClientPlugin implements BatClientPluginTrigger, BatClientPluginUtil {
    private static final int PORT=18765, CAPACITY=2000;
    private final Deque<String> events=new ArrayDeque<String>();
    private long seq=0, commands=0;
    private volatile boolean running=false;
    private ServerSocket server;
    private String token;
    private final String session=UUID.randomUUID().toString();
    public String getName(){return "AgentBridge";}
    public void loadPlugin(){
        // Excelsior JET can crash when a plugin touches the native Swing UI
        // while the splash screen is still being torn down. Defer all setup.
        Thread startup=new Thread(new Runnable(){public void run(){
            try { Thread.sleep(2500L); } catch (InterruptedException e) { return; }
            initialize();
        }},"BatMUD-AgentBridge-startup");
        startup.setDaemon(true);
        startup.start();
    }
    private void initialize(){
        try {
            Path dir=Paths.get(getBaseDirectory(),"agent-bridge"); Files.createDirectories(dir);
            Path key=dir.resolve("token.txt");
            if(Files.exists(key)) token=new String(Files.readAllBytes(key),StandardCharsets.UTF_8).trim();
            else {token=UUID.randomUUID().toString()+UUID.randomUUID().toString(); Files.write(key,token.getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);}
            if(token.length()<32)throw new IOException("Invalid bridge token");
            server=new ServerSocket();server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),PORT));
            running=true;
            Thread worker=new Thread(new Runnable(){public void run(){serve();}},"BatMUD-AgentBridge");worker.setDaemon(true);worker.start();
            SwingUtilities.invokeLater(new Runnable(){public void run(){
                if(running)getClientGUI().printText("generic","AgentBridge ready: 127.0.0.1:"+PORT+" (authenticated)\n",false);
            }});
        } catch(final Exception e){
            clientExit();
            SwingUtilities.invokeLater(new Runnable(){public void run(){
                getClientGUI().printText("generic","AgentBridge startup failed: "+e.getClass().getSimpleName()+": "+e.getMessage()+"\n",false);
            }});
        }
    }
    public ParsedResult trigger(ParsedResult input){
        if(input!=null && running) record(input.getStrippedText(),input.getOriginalText());
        return input;
    }
    private synchronized void record(String text,String raw){
        long id=++seq;
        events.addLast("{\"seq\":"+id+",\"time_ms\":"+System.currentTimeMillis()+",\"text\":"+quote(text)+",\"raw\":"+quote(raw)+"}");
        while(events.size()>CAPACITY)events.removeFirst();
    }
    private synchronized String status(){return "{\"version\":\"0.1.0\",\"session\":"+quote(session)+",\"connected\":"+getNet().isConnected()+",\"latest_seq\":"+seq+",\"commands_sent\":"+commands+"}";}
    private synchronized String output(long after){
        long oldest=seq-events.size()+1, id=oldest;StringBuilder b=new StringBuilder();
        b.append("{\"session\":").append(quote(session)).append(",\"latest_seq\":").append(seq).append(",\"oldest_seq\":").append(oldest).append(",\"truncated\":").append(after<oldest-1).append(",\"events\":[");
        boolean first=true;for(String event:events){if(id++<=after)continue;if(!first)b.append(',');first=false;b.append(event);}return b.append("]}").toString();
    }
    private void serve(){
        while(running){try(Socket s=server.accept()){s.setSoTimeout(3000);handle(s);}catch(Exception e){/* A malformed or closed connection never stops game callbacks. */}}
    }
    private String line(InputStream in)throws IOException{
        ByteArrayOutputStream b=new ByteArrayOutputStream();int c;
        while((c=in.read())!=-1){if(c=='\n')return new String(b.toByteArray(),StandardCharsets.US_ASCII).replace("\r","");if(b.size()>=8192)throw new IOException("Header too long");b.write(c);}throw new EOFException();
    }
    private void handle(Socket s)throws Exception{
        InputStream in=s.getInputStream();String[] request=line(in).split(" ");
        if(request.length!=3){reply(s,400,"{\"error\":\"invalid_request\"}");return;}
        Map<String,String> headers=new HashMap<String,String>();
        for(int i=0;;i++){String h=line(in);if(h.length()==0)break;if(i>=32)throw new IOException("Too many headers");int n=h.indexOf(':');if(n>0)headers.put(h.substring(0,n).trim().toLowerCase(Locale.ROOT),h.substring(n+1).trim());}
        String auth=headers.get("authorization");
        if(auth==null||!MessageDigest.isEqual(("Bearer "+token).getBytes(StandardCharsets.UTF_8),auth.getBytes(StandardCharsets.UTF_8))){reply(s,401,"{\"error\":\"unauthorized\"}");return;}
        if(headers.containsKey("origin")){reply(s,403,"{\"error\":\"browser_origin_not_allowed\"}");return;}
        URI uri=new URI(request[1]);String path=uri.getPath();
        if("GET".equals(request[0])&&"/status".equals(path)){reply(s,200,status());return;}
        if("GET".equals(request[0])&&"/events".equals(path)){
            long after=0;String q=uri.getRawQuery();
            if(q!=null){if(!q.matches("after=[0-9]{1,18}")){reply(s,400,"{\"error\":\"invalid_cursor\"}");return;}after=Long.parseLong(q.substring(6));}
            reply(s,200,output(after));return;
        }
        if("POST".equals(request[0])&&"/command".equals(path)){
            if(!getNet().isConnected()){reply(s,409,"{\"error\":\"not_connected\"}");return;}
            int len;try{len=Integer.parseInt(headers.get("content-length"));}catch(Exception e){reply(s,411,"{\"error\":\"content_length_required\"}");return;}
            if(len<1||len>1024||headers.containsKey("transfer-encoding")){reply(s,400,"{\"error\":\"invalid_length\"}");return;}
            byte[] bytes=new byte[len];new DataInputStream(in).readFully(bytes);
            final String command=new String(bytes,StandardCharsets.UTF_8).trim();
            if(command.isEmpty()||command.length()>500||command.matches("(?s).*[\\x00-\\x1f\\x7f].*")){reply(s,400,"{\"error\":\"single_line_required\"}");return;}
            final long before; synchronized(this){before=seq;}
            FutureTask<Boolean> task=new FutureTask<Boolean>(new Callable<Boolean>(){public Boolean call(){if(!getNet().isConnected())return false;getClientGUI().doCommand(command);synchronized(AgentBridge.this){commands++;}return true;}});
            SwingUtilities.invokeLater(task);
            try {
                if(!task.get(5,TimeUnit.SECONDS)){reply(s,409,"{\"error\":\"disconnected_before_send\"}");return;}
                reply(s,200,"{\"dispatched\":true,\"after_seq\":"+before+",\"session\":"+quote(session)+"}");
            } catch(TimeoutException e){task.cancel(false);reply(s,504,"{\"error\":\"dispatch_timeout_outcome_unknown_do_not_retry_blindly\"}");}
            return;
        }
        reply(s,404,"{\"error\":\"not_found\"}");
    }
    private void reply(Socket s,int code,String json)throws IOException{
        byte[] body=json.getBytes(StandardCharsets.UTF_8);OutputStream out=s.getOutputStream();
        out.write(("HTTP/1.1 "+code+" Response\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: "+body.length+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(body);out.flush();
    }
    static String quote(String s){if(s==null)return "null";StringBuilder b=new StringBuilder("\"");for(char c:s.toCharArray()){switch(c){case '"':b.append("\\\"");break;case '\\':b.append("\\\\");break;case '\n':b.append("\\n");break;case '\r':b.append("\\r");break;case '\t':b.append("\\t");break;default:if(c<32)b.append(String.format("\\u%04x",(int)c));else b.append(c);}}return b.append('"').toString();}
    public void clientExit(){running=false;try{if(server!=null)server.close();}catch(IOException ignored){}}
}
