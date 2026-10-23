package com.mythicscape.batclient.interfaces;
public class BatClientPlugin {
    private Net net;
    private ClientGUI gui;
    public void init(Object a, Object b, Object c, Net n, Object e, ClientGUI g){net=n;gui=g;}
    protected Net getNet(){return net;}
    protected ClientGUI getClientGUI(){return gui;}
    protected String getBaseDirectory(){return ".";}
    public void clientExit(){}
}
