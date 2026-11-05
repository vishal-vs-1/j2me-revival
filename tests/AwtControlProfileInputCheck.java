import java.awt.Canvas;
import java.awt.event.KeyEvent;
import java.util.ArrayList;
import java.util.List;
import org.recompile.mobile.AwtControlProfileInput;
import org.recompile.mobile.ControlProfileBindings;

public final class AwtControlProfileInputCheck {
    private static final class Recorder implements AwtControlProfileInput.Dispatcher {
        final List<String> events = new ArrayList<String>();
        boolean loaded = true;
        public boolean gameLoaded() { return loaded; }
        public void pressMapped(int index) { events.add("press:" + index); }
        public void releaseMapped(int index, boolean repeat) { events.add("release:" + index + ":" + repeat); }
        public void legacyPress(KeyEvent event) { events.add("legacy-press:" + event.getKeyCode()); }
        public void legacyRelease(KeyEvent event) { events.add("legacy-release:" + event.getKeyCode()); }
    }

    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static KeyEvent key(int id, int modifiers, int code, int location) {
        return new KeyEvent(new Canvas(), id, System.currentTimeMillis(), modifiers, code,
                KeyEvent.CHAR_UNDEFINED, location);
    }

    private static void checkLostShortcutRelease(String wire, int shortcutKey, String hashBinding) {
        String boundWire = wire.replace("FIRE=ENTER", "FIRE=KEY_" + (char)shortcutKey)
                .replace("HASH=KEY_R", "HASH=" + hashBinding);
        Recorder recorder = new Recorder();
        AwtControlProfileInput input = new AwtControlProfileInput(
                ControlProfileBindings.parse(boundWire), recorder);
        require(input.isCustom(), "focus fixture uses valid custom bindings");
        int start = recorder.events.size();
        input.keyPressed(key(KeyEvent.KEY_PRESSED,
                KeyEvent.CTRL_DOWN_MASK | KeyEvent.ALT_DOWN_MASK,
                shortcutKey, KeyEvent.KEY_LOCATION_STANDARD));
        input.releaseHeldKeys();

        int afterCleanup = recorder.events.size();
        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, shortcutKey, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, shortcutKey, KeyEvent.KEY_LOCATION_STANDARD));
        require(recorder.events.subList(afterCleanup, recorder.events.size())
                        .toString().equals("[press:7, release:7:true]"),
                "focus cleanup forgets a shortcut whose key-up was lost");
        require(recorder.events.subList(start, afterCleanup).toString()
                        .equals("[legacy-press:" + shortcutKey + "]"),
                "focus cleanup does not synthesize a vendor shortcut release");

        int beforeHeldCleanup = recorder.events.size();
        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, shortcutKey, KeyEvent.KEY_LOCATION_STANDARD));
        input.releaseHeldKeys();
        require(recorder.events.subList(beforeHeldCleanup, recorder.events.size())
                        .toString().equals("[press:7, release:7:false]"),
                "focus cleanup releases held custom input without repeating remaining keys");
        int beforeRepeatedCleanup = recorder.events.size();
        input.releaseHeldKeys();
        input.releaseHeldKeys();
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, shortcutKey, KeyEvent.KEY_LOCATION_STANDARD));
        require(recorder.events.size() == beforeRepeatedCleanup,
                "repeated cleanup and a late orphan release do not duplicate input");
    }

    public static void main(String[] args) {
        String fixture = args[0];
        String remappedWire = fixture.replace("SOFT_RIGHT=KEY_W", "SOFT_RIGHT=KEY_T")
                .replace("UP=ARROW_UP", "UP=KEY_W").replace("DOWN=ARROW_DOWN", "DOWN=KEY_S")
                .replace("FIRE=ENTER", "FIRE=NUMPAD_ENTER");
        Recorder recorder = new Recorder();
        AwtControlProfileInput input = new AwtControlProfileInput(
                ControlProfileBindings.parse(remappedWire), recorder);
        require(input.isCustom(), "custom adapter active");

        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_W, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_W, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, KeyEvent.CTRL_DOWN_MASK,
                KeyEvent.VK_W, KeyEvent.KEY_LOCATION_STANDARD));
        require(recorder.events.toString().equals("[press:0, press:0, release:0:true]"),
                "repeat is forwarded and release uses the acquired index after modifiers change");

        input.keyPressed(key(KeyEvent.KEY_PRESSED, KeyEvent.CTRL_DOWN_MASK,
                KeyEvent.VK_S, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, KeyEvent.VK_S, KeyEvent.KEY_LOCATION_STANDARD));
        require(recorder.events.size() == 3, "modified custom key is ignored");

        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_ENTER, KeyEvent.KEY_LOCATION_NUMPAD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, KeyEvent.VK_ENTER, KeyEvent.KEY_LOCATION_NUMPAD));
        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_ENTER, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, KeyEvent.VK_ENTER, KeyEvent.KEY_LOCATION_STANDARD));
        require(recorder.events.subList(3, 5).toString().equals("[press:7, release:7:true]"),
                "keypad Enter is distinct and ordinary Enter is unbound");

        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_S, KeyEvent.KEY_LOCATION_STANDARD));
        input.releaseHeldKeys();
        require(recorder.events.get(6).equals("release:1:false"),
                "focus cleanup releases held input without repeating remaining keys");

        input.keyPressed(key(KeyEvent.KEY_PRESSED, KeyEvent.CTRL_DOWN_MASK | KeyEvent.ALT_DOWN_MASK,
                KeyEvent.VK_F, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, KeyEvent.VK_F, KeyEvent.KEY_LOCATION_STANDARD));
        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_ADD, KeyEvent.KEY_LOCATION_NUMPAD));
        input.keyReleased(key(KeyEvent.KEY_RELEASED, 0, KeyEvent.VK_ADD, KeyEvent.KEY_LOCATION_NUMPAD));
        require(recorder.events.contains("legacy-press:" + KeyEvent.VK_F)
                && recorder.events.contains("legacy-release:" + KeyEvent.VK_F)
                && recorder.events.contains("legacy-press:" + KeyEvent.VK_ADD)
                && recorder.events.contains("legacy-release:" + KeyEvent.VK_ADD),
                "fullscreen and scale shortcuts keep the vendor path");

        checkLostShortcutRelease(fixture, KeyEvent.VK_F, "KEY_Y");
        checkLostShortcutRelease(fixture, KeyEvent.VK_R, "KEY_Y");

        AwtControlProfileInput invalid = new AwtControlProfileInput(
                ControlProfileBindings.parse("v1|broken"), recorder);
        require(!invalid.isCustom(), "invalid profile falls back to original listener");
        require(!invalid.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_UP,
                KeyEvent.KEY_LOCATION_STANDARD)), "fallback event is left to original listener");
        recorder.loaded = false;
        int before = recorder.events.size();
        input.keyPressed(key(KeyEvent.KEY_PRESSED, 0, KeyEvent.VK_W, KeyEvent.KEY_LOCATION_STANDARD));
        require(recorder.events.size() == before, "input is ignored before a game is loaded");
        System.out.println("AWT control profile checks passed");
    }
}
