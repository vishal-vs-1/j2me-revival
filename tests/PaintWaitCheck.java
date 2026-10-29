import org.recompile.mobile.*;
import javax.microedition.lcdui.*;
import java.util.concurrent.*;
public class PaintWaitCheck {
    static class TestCanvas extends Canvas {
        volatile boolean block;
        final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        protected void paint(Graphics g) {
            if(block) {entered.countDown();try{release.await(3,TimeUnit.SECONDS);}catch(Exception e){throw new RuntimeException(e);}}
        }
    }
    public static void main(String[] args)throws Exception {
        Mobile.lcdWidth=176;Mobile.lcdHeight=220;Mobile.setPlatform(new MobilePlatform(176,220),()->{});
        Mobile.config.init("PaintWaitCheck");Mobile.updateSettings();Mobile.setDisplay(new Display());
        TestCanvas canvas=new TestCanvas();Mobile.getDisplay().setCurrent(canvas);
        CountDownLatch shown=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->shown.countDown());
        if(!shown.await(3,TimeUnit.SECONDS))throw new AssertionError("Canvas not shown");
        canvas.block=true;CountDownLatch completed=new CountDownLatch(1);
        Thread game=new Thread(()->{canvas.repaint();canvas.serviceRepaints();completed.countDown();});game.start();
        if(!canvas.entered.await(3,TimeUnit.SECONDS))throw new AssertionError("Paint not entered");
        if(completed.await(100,TimeUnit.MILLISECONDS))throw new AssertionError("serviceRepaints returned before paint finished");
        canvas.release.countDown();
        if(!completed.await(3,TimeUnit.SECONDS))throw new AssertionError("serviceRepaints did not finish after paint");
        System.out.println("PASS: serviceRepaints waits for both pending and in-progress painting");System.exit(0);
    }
}
