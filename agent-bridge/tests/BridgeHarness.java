import local.batbridge.AgentBridge;
import com.mythicscape.batclient.interfaces.*;
import java.lang.reflect.*;
public class BridgeHarness {
 public static void main(final String[] args)throws Exception{
  final AgentBridge b=new AgentBridge();
  ClientGUI gui=(ClientGUI)Proxy.newProxyInstance(BridgeHarness.class.getClassLoader(),new Class[]{ClientGUI.class},new InvocationHandler(){public Object invoke(Object p,Method m,Object[] a){
   if(m.getName().equals("getBaseDirectory"))return args[0];
   if(m.getName().equals("doCommand"))b.trigger(new ParsedResult("ROOM: "+a[0]));return null;}});
  Net net=(Net)Proxy.newProxyInstance(BridgeHarness.class.getClassLoader(),new Class[]{Net.class},new InvocationHandler(){public Object invoke(Object p,Method m,Object[] a){return m.getReturnType()==boolean.class?true:null;}});
  b.init(args[0],null,null,net,null,gui);b.loadPlugin();
  Thread.sleep(3000L); // let the deferred plugin startup finish before capturing events
  ParsedResult input=new ParsedResult("hello \"world\"\n中文");if(b.trigger(input)!=input)throw new AssertionError("Mutated input");
  Thread.sleep(60000);b.clientExit();
 }
}
