import javax.microedition.lcdui.Display;
import javax.microedition.midlet.MIDlet;

/** Startup adapter for the exact, verified MrBeanRacer2 archive.
 * The added wrappers moved construction of the original game Canvas out of a.
 * Keep the two exit signatures that the modified game still calls.
 */
public final class WRAPPER extends a {
    public WRAPPER() {
        super();
        gm = new p(this, Display.getDisplay(this));
    }

    public void startApp() { super.startApp(); }
    public void pauseApp() { super.pauseApp(); }
    public void destroyApp(boolean unconditional) { super.destroyApp(unconditional); }
    public void destroyApp2(boolean unconditional) { super.destroyApp(unconditional); }
    public static void a(MIDlet game) { game.notifyDestroyed(); }
}
