import java.util.HashMap;
import java.util.Map;
import java.util.prefs.AbstractPreferences;
import java.util.prefs.BackingStoreException;
import java.util.prefs.Preferences;
import java.util.prefs.PreferencesFactory;

/** Isolated in-memory preferences for emulator smoke tests without registry writes. */
public final class RuntimePreferencesFactory implements PreferencesFactory {
    private static final Preferences USER = new MemoryNode(null, "");
    private static final Preferences SYSTEM = new MemoryNode(null, "");

    public Preferences userRoot() { return USER; }
    public Preferences systemRoot() { return SYSTEM; }

    private static final class MemoryNode extends AbstractPreferences {
        private final Map<String, String> values = new HashMap<String, String>();
        private final Map<String, MemoryNode> children = new HashMap<String, MemoryNode>();

        MemoryNode(AbstractPreferences parent, String name) { super(parent, name); }

        protected void putSpi(String key, String value) { values.put(key, value); }
        protected String getSpi(String key) { return values.get(key); }
        protected void removeSpi(String key) { values.remove(key); }
        protected void removeNodeSpi() { values.clear(); children.clear(); }
        protected String[] keysSpi() { return values.keySet().toArray(new String[values.size()]); }
        protected String[] childrenNamesSpi() { return children.keySet().toArray(new String[children.size()]); }
        protected AbstractPreferences childSpi(String name) {
            MemoryNode child = children.get(name);
            if (child == null) {
                child = new MemoryNode(this, name);
                children.put(name, child);
            }
            return child;
        }
        protected void syncSpi() throws BackingStoreException { }
        protected void flushSpi() throws BackingStoreException { }
    }
}
