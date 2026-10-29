import org.recompile.mobile.*;
import javax.microedition.lcdui.*;
import java.util.concurrent.*;

public class InitialPaintCheck {
    static class Menu extends Canvas {
        final CountDownLatch painted=new CountDownLatch(1);
        protected void paint(Graphics g){g.setColor(0xff00ff);g.fillRect(0,0,getWidth(),getHeight());painted.countDown();}
    }
    public static void main(String[] args){try{run();}catch(Throwable e){e.printStackTrace();System.exit(1);}}
    static void run()throws Exception {
        Mobile.setPlatform(new MobilePlatform(176,220),()->{});Mobile.config.init("InitialPaintCheck");
        Mobile.config.settings.put("compatrepaintonsetcurrent","off");System.clearProperty("jme.compat.repaintOnShow");Mobile.updateSettings();
        if(Mobile.compatRepaintOnSetCurrent)throw new AssertionError("Default game policy changed");
        System.setProperty("jme.compat.repaintOnShow","on");Mobile.updateSettings();
        if(!Mobile.compatRepaintOnSetCurrent)throw new AssertionError("Explicit profile not applied");
        if(!"off".equals(Mobile.config.settings.get("compatrepaintonsetcurrent")))throw new AssertionError("Runtime override changed saved configuration");
        Mobile.setDisplay(new Display());Menu menu=new Menu();Mobile.getDisplay().setCurrent(menu);
        if(!menu.painted.await(3,TimeUnit.SECONDS))throw new AssertionError("Initial menu was not painted");
        CountDownLatch complete=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->complete.countDown());complete.await(3,TimeUnit.SECONDS);
        if(Mobile.getPlatform().getLcdFrontbuffer().getCanvas().getRGB(20,20)!=0xffff00ff)throw new AssertionError("New menu did not reach framebuffer");
        System.out.println("PASS: scoped initial redraw paints the new screen without changing other game defaults");System.exit(0);
    }
}
