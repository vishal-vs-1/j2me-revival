import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;
import org.recompile.mobile.ControlProfileBindings;
import org.recompile.mobile.ControlProfileBindings.Action;
import org.recompile.mobile.DesktopKeyMap;
import org.recompile.mobile.GlfwControlKeys;
import static org.lwjgl.glfw.GLFW.*;

public final class ControlProfileBindingsCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        String wire = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.US_ASCII).trim();
        ControlProfileBindings parsed = ControlProfileBindings.parse(wire);
        require(parsed.isCustom(), "shared fixture parses");
        require(parsed.tokenActions().size() == 19, "all physical assignments are exposed");
        require(parsed.mobileIndexForToken("ARROW_UP") == 0, "CPU action index");
        require(parsed.phoneCodeForToken("ARROW_UP") == -1, "GPU phone code");
        require(parsed.phoneCodeForToken("DIGIT_9") == 57, "top-row digits retain phone codes");
        String[] tokens = {"ARROW_UP", "ARROW_DOWN", "ARROW_LEFT", "ARROW_RIGHT", "ENTER",
            "KEY_Q", "KEY_W", "DIGIT_0", "DIGIT_1", "DIGIT_2", "DIGIT_3", "DIGIT_4",
            "DIGIT_5", "DIGIT_6", "DIGIT_7", "DIGIT_8", "DIGIT_9", "KEY_E", "KEY_R"};
        int[] phoneCodes = {-1, -2, -3, -4, -5, -6, -7, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 42, 35};
        int[] mobileIndexes = {0, 1, 2, 3, 7, 9, 8, 6, 10, 14, 11, 15, 18, 16, 5, 17, 4, 12, 13};
        for (int i = 0; i < tokens.length; i++) {
            require(parsed.phoneCodeForToken(tokens[i]) == phoneCodes[i], "GPU code for " + tokens[i]);
            require(parsed.mobileIndexForToken(tokens[i]) == mobileIndexes[i], "CPU index for " + tokens[i]);
        }
        for (Map.Entry<String, Action> entry : parsed.tokenActions().entrySet())
            require(entry.getValue() != null, "immutable token action entry");
        boolean immutable = false;
        try { parsed.tokenActions().put("KEY_Z", Action.UP); }
        catch (UnsupportedOperationException expected) { immutable = true; }
        require(immutable, "resolved bindings are immutable");

        require(!ControlProfileBindings.parse(null).isCustom(), "missing property selects Default");
        require(ControlProfileBindings.parse("").problem() == null, "empty property selects Default without warning");
        String[] invalid = {
            wire.replaceFirst("v1", "v2"),
            wire.replace("|HASH=KEY_R", ""),
            wire.replace("DOWN=ARROW_DOWN", "DOWN=ARROW_UP"),
            wire.replace("DOWN=ARROW_DOWN", "UP=ARROW_DOWN"),
            wire.replace("UP=ARROW_UP", "UP=KEY_1"),
            wire.replace("FIRE=ENTER", "FIRE=NONE"),
            wire + "|UNKNOWN=KEY_X",
            wire + "é",
            new String(new char[1025]).replace('\0', 'A')
        };
        for (String value : invalid) {
            ControlProfileBindings rejected = ControlProfileBindings.parse(value);
            require(!rejected.isCustom(), "invalid map must not partially apply");
            require(rejected.tokenActions().isEmpty(), "invalid map exposes no partial bindings");
            require(rejected.problem() != null, "malformed property has a diagnostic");
            require(GlfwControlKeys.mapping(rejected).applyAsInt(GLFW_KEY_UP) == -1,
                    "invalid map falls back to Default as a whole");
        }

        require("ENTER".equals(GlfwControlKeys.tokenForKey(GLFW_KEY_ENTER)), "standard Enter token");
        require("NUMPAD_ENTER".equals(GlfwControlKeys.tokenForKey(GLFW_KEY_KP_ENTER)), "keypad Enter token");
        require("DIGIT_4".equals(GlfwControlKeys.tokenForKey(GLFW_KEY_4)), "number row token");
        require("NUMPAD_4".equals(GlfwControlKeys.tokenForKey(GLFW_KEY_KP_4)), "numpad digit token");
        java.util.function.IntUnaryOperator defaults = GlfwControlKeys.mapping(ControlProfileBindings.parse(null));
        require(defaults.applyAsInt(GLFW_KEY_UP) == -1, "Default arrow mapping remains");
        require(defaults.applyAsInt(GLFW_KEY_KP_ENTER) == -5, "Default keypad Enter alias remains");

        String remappedWire = wire.replace("SOFT_RIGHT=KEY_W", "SOFT_RIGHT=KEY_T")
                .replace("UP=ARROW_UP", "UP=KEY_W").replace("DOWN=ARROW_DOWN", "DOWN=KEY_S")
                .replace("FIRE=ENTER", "FIRE=NUMPAD_ENTER").replace("NUM_5=DIGIT_5", "NUM_5=NONE");
        ControlProfileBindings remapped = ControlProfileBindings.parse(remappedWire);
        require(remapped.isCustom(), "valid remapped profile parses");
        java.util.function.IntUnaryOperator mapping = GlfwControlKeys.mapping(remapped);
        require(mapping.applyAsInt(GLFW_KEY_W) == -1, "custom Up mapping");
        require(mapping.applyAsInt(GLFW_KEY_S) == -2, "custom Down mapping");
        require(mapping.applyAsInt(GLFW_KEY_UP) == DesktopKeyMap.UNMAPPED, "custom mode has no default fallback");
        require(mapping.applyAsInt(GLFW_KEY_KP_ENTER) == -5, "custom keypad Enter mapping");
        require(mapping.applyAsInt(GLFW_KEY_5) == DesktopKeyMap.UNMAPPED, "unbound action produces no event");
        System.out.println("Control profile wire and GLFW checks passed");
    }
}
