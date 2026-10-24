package com.mythicscape.batclient.interfaces;
public class BatClientPlugin {
    private Net net;
    private ClientGUI gui;
    private String base = ".";
    // The real client supplies its base directory through init(); the exact
    // slot is not public, so accept a String in any Object position. This
    // stub is a compile/test double only and never ships inside the plugin.
    public void init(Object a, Object b, Object c, Net n, Object e, ClientGUI g){
        net=n;gui=g;
        if(a instanceof String) base=(String)a;
        if(c instanceof String) base=(String)c;
        if(e instanceof String) base=(String)e;
    }
    protected Net getNet(){return net;}
    protected ClientGUI getClientGUI(){return gui;}
    protected String getBaseDirectory(){return base;}
    public void clientExit(){}
}
