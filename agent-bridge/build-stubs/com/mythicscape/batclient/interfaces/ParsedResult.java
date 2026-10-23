package com.mythicscape.batclient.interfaces;
public class ParsedResult {
    private final String text;
    public ParsedResult(String s){text=s;}
    public String getStrippedText(){return text;}
    public String getOriginalText(){return text;}
}
