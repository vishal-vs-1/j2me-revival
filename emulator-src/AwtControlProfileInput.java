/* AWT adapter for shared control profiles. GPL-3.0-or-later. */
package org.recompile.mobile;

import java.awt.event.KeyEvent;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/** Routes custom AWT keys through FreeJ2ME's existing mobile-index dispatcher. */
public final class AwtControlProfileInput {
    public interface Dispatcher {
        boolean gameLoaded();
        void pressMapped(int mobileIndex);
        void releaseMapped(int mobileIndex, boolean repeatRemaining);
        void legacyPress(KeyEvent event);
        void legacyRelease(KeyEvent event);
    }

    private final ControlProfileBindings profile;
    private final Dispatcher dispatcher;
    private final Map<Long, Integer> held = new LinkedHashMap<Long, Integer>();
    private final Set<Long> legacyHeld = new LinkedHashSet<Long>();

    public AwtControlProfileInput(ControlProfileBindings profile, Dispatcher dispatcher) {
        this.profile = profile == null ? ControlProfileBindings.parse(null) : profile;
        this.dispatcher = dispatcher;
    }

    public static AwtControlProfileInput fromSystemProperty(Dispatcher dispatcher) {
        return new AwtControlProfileInput(ControlProfileBindings.fromSystemProperty(), dispatcher);
    }

    public boolean isCustom() { return profile.isCustom(); }

    /** Returns true when the custom listener owns this event, including unbound keys. */
    public boolean keyPressed(KeyEvent event) {
        if (!isCustom()) return false;
        long physical = physicalKey(event);
        if (legacyHeld.contains(physical)) {
            dispatcher.legacyPress(event);
            return true;
        }
        if (isLegacyShortcut(event)) {
            legacyHeld.add(physical);
            dispatcher.legacyPress(event);
            return true;
        }
        if (hasSuppressedModifier(event) || !dispatcher.gameLoaded()) return true;

        Integer mobileIndex = held.get(physical);
        if (mobileIndex == null) {
            String token = tokenForEvent(event);
            int resolved = token == null ? Integer.MIN_VALUE : profile.mobileIndexForToken(token);
            if (resolved == Integer.MIN_VALUE) return true;
            mobileIndex = Integer.valueOf(resolved);
            held.put(physical, mobileIndex);
        }
        dispatcher.pressMapped(mobileIndex.intValue());
        return true;
    }

    /** Uses the acquired index so modifier or layout state cannot change a release. */
    public boolean keyReleased(KeyEvent event) {
        if (!isCustom()) return false;
        long physical = physicalKey(event);
        if (legacyHeld.remove(physical)) {
            dispatcher.legacyRelease(event);
            return true;
        }
        Integer mobileIndex = held.remove(physical);
        if (mobileIndex != null) dispatcher.releaseMapped(mobileIndex.intValue(), true);
        return true;
    }

    /** Releases custom keys without repeating any other key during bulk cleanup. */
    public void releaseHeldKeys() {
        for (Integer mobileIndex : held.values()) dispatcher.releaseMapped(mobileIndex.intValue(), false);
        held.clear();
        // Focus loss can swallow shortcut key-up events, so release their routing latch too.
        legacyHeld.clear();
    }

    public static String tokenForEvent(KeyEvent event) {
        int key = event.getKeyCode();
        int location = event.getKeyLocation();
        if (key == KeyEvent.VK_ENTER)
            return location == KeyEvent.KEY_LOCATION_NUMPAD ? "NUMPAD_ENTER" : "ENTER";
        if (key >= KeyEvent.VK_0 && key <= KeyEvent.VK_9) {
            int digit = key - KeyEvent.VK_0;
            return location == KeyEvent.KEY_LOCATION_NUMPAD ? "NUMPAD_" + digit : "DIGIT_" + digit;
        }
        if (key >= KeyEvent.VK_NUMPAD0 && key <= KeyEvent.VK_NUMPAD9)
            return "NUMPAD_" + (key - KeyEvent.VK_NUMPAD0);
        if (key >= KeyEvent.VK_A && key <= KeyEvent.VK_Z)
            return "KEY_" + (char)('A' + key - KeyEvent.VK_A);
        switch (key) {
            case KeyEvent.VK_UP: return "ARROW_UP";
            case KeyEvent.VK_DOWN: return "ARROW_DOWN";
            case KeyEvent.VK_LEFT: return "ARROW_LEFT";
            case KeyEvent.VK_RIGHT: return "ARROW_RIGHT";
            case KeyEvent.VK_SPACE: return "SPACE";
            default: return null;
        }
    }

    private static boolean isLegacyShortcut(KeyEvent event) {
        int key = event.getKeyCode();
        if (key == KeyEvent.VK_EQUALS || key == KeyEvent.VK_ADD
                || key == KeyEvent.VK_MINUS || key == KeyEvent.VK_SUBTRACT) return true;
        return event.isControlDown() && event.isAltDown()
                && (key == KeyEvent.VK_F || key == KeyEvent.VK_R);
    }

    private static boolean hasSuppressedModifier(KeyEvent event) {
        return event.isControlDown() || event.isAltDown() || event.isMetaDown();
    }

    private static long physicalKey(KeyEvent event) {
        return (((long) event.getKeyCode()) << 8) | (event.getKeyLocation() & 0xff);
    }
}
