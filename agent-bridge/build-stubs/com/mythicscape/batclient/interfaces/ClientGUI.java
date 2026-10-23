package com.mythicscape.batclient.interfaces;
public interface ClientGUI {
    void printText(String type, String text, boolean newline);
    void doCommand(String command);
}
