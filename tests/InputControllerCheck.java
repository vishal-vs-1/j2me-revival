import java.util.*;
import org.recompile.mobile.KeyInputController;

public class InputControllerCheck {
    static class Sink implements KeyInputController.Sink {
        final List<String> events=new ArrayList<String>();boolean restore;
        public void press(int key){events.add("P"+key);}public void release(int key){events.add("U"+key);}public void repeat(int key){events.add("R"+key);}
        public boolean restoreMovementAfterRelease(){return restore;}
    }
    static void expect(Sink sink,String... values){if(!sink.events.equals(Arrays.asList(values)))throw new AssertionError(sink.events);sink.events.clear();}
    public static void main(String[] args) {
        Sink sink=new Sink();KeyInputController input=new KeyInputController(key->key==10||key==11?-5:key,sink);
        input.handle(10,1);input.handle(11,1);input.handle(10,0);expect(sink,"P-5");
        input.handle(11,0);expect(sink,"U-5");
        input.handle(-2,1);input.handle(-2,1);input.handle(-2,2);input.releaseAll();input.handle(-2,2);input.handle(-2,0);
        expect(sink,"P-2","R-2","U-2");
        sink.restore=true;input.handle(-3,1);input.handle(-4,1);input.handle(-4,0);expect(sink,"P-3","P-4","U-4","P-3");
        input.releaseAll();expect(sink,"U-3");
        System.out.println("PASS: independent held-key policy, aliases, duplicate presses, orphan events and movement restoration");
    }
}
