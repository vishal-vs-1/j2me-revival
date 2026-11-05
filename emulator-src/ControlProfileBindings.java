/* Shared, validated keyboard profile wire format. GPL-3.0-or-later. */
package org.recompile.mobile;

import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/** Parses the bounded ASCII value passed by the library at player startup. */
public final class ControlProfileBindings {
    public enum Action {
        UP(-1, 0, true), DOWN(-2, 1, true), LEFT(-3, 2, true), RIGHT(-4, 3, true),
        FIRE(-5, 7, true), SOFT_LEFT(-6, 9, true), SOFT_RIGHT(-7, 8, true),
        NUM_0(48, 6, false), NUM_1(49, 10, false), NUM_2(50, 14, false),
        NUM_3(51, 11, false), NUM_4(52, 15, false), NUM_5(53, 18, false),
        NUM_6(54, 16, false), NUM_7(55, 5, false), NUM_8(56, 17, false),
        NUM_9(57, 4, false), STAR(42, 12, false), HASH(35, 13, false);

        private final int phoneCode;
        private final int mobileIndex;
        private final boolean required;

        Action(int phoneCode, int mobileIndex, boolean required) {
            this.phoneCode = phoneCode;
            this.mobileIndex = mobileIndex;
            this.required = required;
        }

        public int phoneCode() { return phoneCode; }
        public int mobileIndex() { return mobileIndex; }
        public boolean required() { return required; }
    }

    private static final int MAX_LENGTH = 1024;
    private static final AtomicBoolean WARNING_WRITTEN = new AtomicBoolean();
    private static final ControlProfileBindings DEFAULT =
            new ControlProfileBindings(Collections.<String, Action>emptyMap(), null);

    private final Map<String, Action> tokenActions;
    private final String problem;

    private ControlProfileBindings(Map<String, Action> tokenActions, String problem) {
        this.tokenActions = Collections.unmodifiableMap(new HashMap<String, Action>(tokenActions));
        this.problem = problem;
    }

    /** Missing property is the unchanged renderer-specific Default mapping. */
    public static ControlProfileBindings fromSystemProperty() {
        String value = System.getProperty("jme.controlBindings");
        ControlProfileBindings result = parse(value);
        if (result.problem != null && WARNING_WRITTEN.compareAndSet(false, true)) {
            System.err.println("Control profile ignored; using Default controls: " + result.problem);
        }
        return result;
    }

    /** Invalid input returns Default as a whole; a partially parsed map is never exposed. */
    public static ControlProfileBindings parse(String value) {
        if (value == null || value.length() == 0) return DEFAULT;
        try {
            if (value.length() > MAX_LENGTH) throw new IllegalArgumentException("wire value exceeds 1024 characters");
            for (int i = 0; i < value.length(); i++) {
                char character = value.charAt(i);
                if (character < 0x20 || character > 0x7e)
                    throw new IllegalArgumentException("wire value must contain printable ASCII only");
            }

            String[] fields = value.split("\\|", -1);
            if (fields.length != Action.values().length + 1 || !"v1".equals(fields[0]))
                throw new IllegalArgumentException("wire version or action count is invalid");

            Set<Action> seenActions = new HashSet<Action>();
            Set<String> seenTokens = new HashSet<String>();
            Map<String, Action> parsed = new HashMap<String, Action>();
            for (int i = 1; i < fields.length; i++) {
                int separator = fields[i].indexOf('=');
                if (separator <= 0 || separator != fields[i].lastIndexOf('='))
                    throw new IllegalArgumentException("binding entry is malformed");
                Action action;
                try { action = Action.valueOf(fields[i].substring(0, separator)); }
                catch (IllegalArgumentException error) { throw new IllegalArgumentException("unknown action"); }
                if (!seenActions.add(action)) throw new IllegalArgumentException("duplicate action " + action.name());
                String token = fields[i].substring(separator + 1);
                if ("NONE".equals(token)) {
                    if (action.required()) throw new IllegalArgumentException("required action is unbound: " + action.name());
                    continue;
                }
                if (!isSupportedToken(token)) throw new IllegalArgumentException("unknown physical key token");
                if (!seenTokens.add(token)) throw new IllegalArgumentException("duplicate physical key token");
                parsed.put(token, action);
            }
            if (seenActions.size() != Action.values().length)
                throw new IllegalArgumentException("wire value does not contain every action");
            return new ControlProfileBindings(parsed, null);
        } catch (IllegalArgumentException error) {
            return new ControlProfileBindings(Collections.<String, Action>emptyMap(), error.getMessage());
        }
    }

    private static boolean isSupportedToken(String token) {
        if (token.length() == 5 && token.startsWith("KEY_")) {
            char letter = token.charAt(4);
            return letter >= 'A' && letter <= 'Z';
        }
        if (token.length() == 7 && token.startsWith("DIGIT_")) {
            char digit = token.charAt(6);
            return digit >= '0' && digit <= '9';
        }
        if (token.length() == 8 && token.startsWith("NUMPAD_")) {
            char digit = token.charAt(7);
            return digit >= '0' && digit <= '9';
        }
        return "ARROW_UP".equals(token) || "ARROW_DOWN".equals(token)
                || "ARROW_LEFT".equals(token) || "ARROW_RIGHT".equals(token)
                || "ENTER".equals(token) || "NUMPAD_ENTER".equals(token)
                || "SPACE".equals(token);
    }

    public boolean isCustom() { return problem == null && !tokenActions.isEmpty(); }
    public String problem() { return problem; }
    public Map<String, Action> tokenActions() { return tokenActions; }
    public Action actionForToken(String token) { return tokenActions.get(token); }
    public int phoneCodeForToken(String token) {
        Action action = tokenActions.get(token);
        return action == null ? Integer.MIN_VALUE : action.phoneCode();
    }
    public int mobileIndexForToken(String token) {
        Action action = tokenActions.get(token);
        return action == null ? Integer.MIN_VALUE : action.mobileIndex();
    }
}
