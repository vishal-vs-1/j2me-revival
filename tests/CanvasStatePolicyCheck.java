import org.recompile.mobile.*;
import javax.microedition.lcdui.*;
import java.util.concurrent.*;

public final class CanvasStatePolicyCheck {
    public static final class TestCanvas extends Canvas {static int cT;public void paint(Graphics g){} }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Mobile.setPlatform(new MobilePlatform(176,220),()->{});Mobile.config.init("CanvasStatePolicyCheck");Mobile.updateSettings();
        Mobile.setDisplay(new Display());TestCanvas canvas=new TestCanvas();Mobile.getDisplay().setCurrent(canvas);
        CountDownLatch shown=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->shown.countDown());
        check(shown.await(3,TimeUnit.SECONDS),"Canvas did not appear");
        String name=TestCanvas.class.getName();MobileInputSink sink=new MobileInputSink(name,name+":cT:7");
        TestCanvas.cT=2;check(!sink.restoreMovementAfterRelease(),"Menu must not receive a synthetic movement press");
        TestCanvas.cT=7;check(sink.restoreMovementAfterRelease(),"Race restores the still-held direction");
        TestCanvas.cT=4;check(!sink.restoreMovementAfterRelease(),"Sound prompt must not receive movement");
        check(new MobileInputSink(name).restoreMovementAfterRelease(),"Unprofiled state keeps normal Canvas policy");
        check(!new MobileInputSink("other",name+":cT:7").restoreMovementAfterRelease(),"Other games stay isolated");
        System.out.println("PASS: held-direction restoration applies only to the profiled racing state");
        System.exit(0);
    }
}
