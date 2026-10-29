import javax.microedition.lcdui.*;
import org.recompile.mobile.*;
import java.util.concurrent.*;
import static org.lwjgl.glfw.GLFW.*;

public class MenuNavigationCheck {
    static void delivered()throws Exception {
        CountDownLatch done=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->done.countDown());
        if(!done.await(3,TimeUnit.SECONDS))throw new AssertionError("Event dispatch stalled");
    }
    static void key(int code,int action)throws Exception{GpuPlayer.dispatchKey(code,action);delivered();}
    public static void main(String[] args){try{run();}catch(Throwable error){error.printStackTrace();System.exit(1);}}
    static void run()throws Exception {
        Mobile.setPlatform(new MobilePlatform(176,220),()->{});Mobile.config.init("MenuNavigationCheck");Mobile.updateSettings();
        Mobile.setDisplay(new Display());MIDletLoader.MIDletSelected=true;
        List menu=new List("Menu",Choice.IMPLICIT);for(int i=0;i<6;i++)menu.append("Item "+i,null);
        Mobile.getDisplay().setCurrent(menu);delivered();
        key(GLFW_KEY_DOWN,GLFW_PRESS);key(GLFW_KEY_UP,GLFW_PRESS);
        if(menu.getSelectedIndex()!=0)throw new AssertionError("Opposite menu presses should return to start");
        key(GLFW_KEY_UP,GLFW_RELEASE);
        if(menu.getSelectedIndex()!=0)throw new AssertionError("Releasing Up added an unwanted Down menu step");
        key(GLFW_KEY_DOWN,GLFW_RELEASE);
        if(menu.getSelectedIndex()!=0)throw new AssertionError("Release changed selection");
        for(int i=0;i<20;i++) {
            key(GLFW_KEY_DOWN,GLFW_PRESS);key(GLFW_KEY_DOWN,GLFW_RELEASE);
            key(GLFW_KEY_UP,GLFW_PRESS);key(GLFW_KEY_UP,GLFW_RELEASE);
            if(menu.getSelectedIndex()!=0)throw new AssertionError("Rapid taps skipped a menu item");
        }
        key(GLFW_KEY_DOWN,GLFW_PRESS);key(GLFW_KEY_DOWN,GLFW_REPEAT);
        if(menu.getSelectedIndex()!=2)throw new AssertionError("Held-key repeat must navigate once per repeat");
        GpuPlayer.releaseHeldKeys();delivered();
        key(GLFW_KEY_DOWN,GLFW_REPEAT);
        if(menu.getSelectedIndex()!=2)throw new AssertionError("Orphan repeat after focus loss navigated menu");
        System.out.println("PASS: menu up/down taps, opposite keys, repeat and focus loss without release-generated navigation");System.exit(0);
    }
}
