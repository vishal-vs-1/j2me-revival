import org.recompile.mobile.*;
import javax.microedition.lcdui.*;
import java.util.concurrent.*;

public class InputTargetCheck {
    static class Target extends Canvas {
        volatile int presses;
        Target(){setFullScreenMode(true);}
        public void keyPressed(int key){presses++;}
        protected void paint(Graphics g){}
    }
    public static void main(String[] args){try{run();}catch(Throwable e){e.printStackTrace();System.exit(1);}}
    static void run()throws Exception {
        Mobile.setPlatform(new MobilePlatform(176,220),()->{});Mobile.config.init("InputTargetCheck");Mobile.updateSettings();
        Mobile.setDisplay(new Display());MIDletLoader.MIDletSelected=true;Mobile.compatImmediateRepaints=true;
        Target first=new Target(),second=new Target();Mobile.getDisplay().setCurrent(first);
        CountDownLatch blocked=new CountDownLatch(1),release=new CountDownLatch(1),delivered=new CountDownLatch(1);
        Mobile.getDisplay().callSerially(()->{blocked.countDown();try{release.await(3,TimeUnit.SECONDS);}catch(Exception e){throw new RuntimeException(e);}});
        if(!blocked.await(3,TimeUnit.SECONDS))throw new AssertionError("Event blocker not entered");
        MobilePlatform.keyPressed(-2);
        Mobile.getDisplay().setCurrent(second);MobilePlatform.pointerPressed(0,0);
        Mobile.getDisplay().callSerially(()->delivered.countDown());release.countDown();
        if(!delivered.await(3,TimeUnit.SECONDS))throw new AssertionError("Event delivery stalled");
        if(first.presses!=1||second.presses!=0)throw new AssertionError("Queued key was redirected to another screen: "+first.presses+","+second.presses);
        System.out.println("PASS: later display/pointer events cannot redirect a queued keyboard event");System.exit(0);
    }
}
