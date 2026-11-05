/* GLFW-to-profile key translation. GPL-3.0-or-later. */
package org.recompile.mobile;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.function.IntUnaryOperator;
import static org.lwjgl.glfw.GLFW.*;

/** Builds one immutable native-key lookup for a player launch. */
public final class GlfwControlKeys {
    private static final Map<Integer, String> TOKENS = createTokens();

    private GlfwControlKeys() { }

    private static Map<Integer, String> createTokens() {
        Map<Integer, String> tokens = new HashMap<Integer, String>();
        tokens.put(GLFW_KEY_UP, "ARROW_UP");
        tokens.put(GLFW_KEY_DOWN, "ARROW_DOWN");
        tokens.put(GLFW_KEY_LEFT, "ARROW_LEFT");
        tokens.put(GLFW_KEY_RIGHT, "ARROW_RIGHT");
        tokens.put(GLFW_KEY_ENTER, "ENTER");
        tokens.put(GLFW_KEY_KP_ENTER, "NUMPAD_ENTER");
        tokens.put(GLFW_KEY_SPACE, "SPACE");
        for (int i = 0; i < 26; i++) tokens.put(GLFW_KEY_A + i, "KEY_" + (char)('A' + i));
        for (int i = 0; i < 10; i++) {
            tokens.put(GLFW_KEY_0 + i, "DIGIT_" + i);
            tokens.put(GLFW_KEY_KP_0 + i, "NUMPAD_" + i);
        }
        return Collections.unmodifiableMap(tokens);
    }

    public static String tokenForKey(int key) { return TOKENS.get(key); }

    /** Default retains every historical alias; custom input accepts only saved keys. */
    public static IntUnaryOperator mapping(ControlProfileBindings profile) {
        if (profile == null || !profile.isCustom()) return DesktopKeyMap::toPhone;
        Map<Integer, Integer> mapped = new HashMap<Integer, Integer>();
        for (Map.Entry<Integer, String> entry : TOKENS.entrySet()) {
            int phoneCode = profile.phoneCodeForToken(entry.getValue());
            if (phoneCode != Integer.MIN_VALUE) mapped.put(entry.getKey(), phoneCode);
        }
        final Map<Integer, Integer> immutable = Collections.unmodifiableMap(mapped);
        return key -> {
            Integer phoneCode = immutable.get(key);
            return phoneCode == null ? DesktopKeyMap.UNMAPPED : phoneCode;
        };
    }
}
