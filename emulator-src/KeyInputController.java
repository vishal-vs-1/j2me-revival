/* Held-key state independent of the native window, graphics and emulator. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.util.*;
import java.util.function.IntUnaryOperator;

public final class KeyInputController {
    public static final int RELEASE=0,PRESS=1,REPEAT=2;
    public interface Sink {
        void press(int key);void release(int key);void repeat(int key);
        boolean restoreMovementAfterRelease();
    }
    private final IntUnaryOperator mapping;
    private final Sink sink;
    private final LinkedHashMap<Integer,Integer> held=new LinkedHashMap<Integer,Integer>();
    public KeyInputController(IntUnaryOperator mapping,Sink sink){this.mapping=mapping;this.sink=sink;}
    private static boolean movement(int key){return key>=-4&&key<=-1||key==50||key==52||key==54||key==56;}
    public void handle(int physicalKey,int action) {
        int phone=mapping.applyAsInt(physicalKey);if(phone==Integer.MIN_VALUE)return;
        if(action==PRESS) {
            if(held.containsKey(physicalKey))return;
            boolean alreadyHeld=held.containsValue(phone);held.put(physicalKey,phone);
            if(!alreadyHeld)sink.press(phone);
        }else if(action==REPEAT) {
            if(held.containsKey(physicalKey))sink.repeat(phone);
        }else if(action==RELEASE) {
            if(held.remove(physicalKey)==null||held.containsValue(phone))return;
            sink.release(phone);
            // A game-specific single-direction reset policy must never add menu navigation.
            if(sink.restoreMovementAfterRelease())for(int key:new LinkedHashSet<Integer>(held.values()))if(movement(key))sink.press(key);
        }
    }
    public void releaseAll() {
        Set<Integer> keys=new LinkedHashSet<Integer>(held.values());held.clear();
        for(int key:keys)sink.release(key);
    }
}
