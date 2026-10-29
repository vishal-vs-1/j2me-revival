import org.recompile.mobile.*;
import javax.microedition.lcdui.*;
import java.util.concurrent.*;
import static org.lwjgl.glfw.GLFW.*;

public class HeldInputCheck {
    static class TestCanvas extends Canvas {
        volatile int direction;
        TestCanvas(){setFullScreenMode(true);}
        public void keyPressed(int key){direction=key;}
        public void keyReleased(int key){direction=0;}
        protected void paint(Graphics g){}
    }
    static void delivered()throws Exception {
        CountDownLatch latch=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->latch.countDown());
        if(!latch.await(3,TimeUnit.SECONDS))throw new AssertionError("Input dispatch stalled");
    }
    public static void main(String[] args)throws Exception {
        System.setProperty("jme.input.restoreCanvases",TestCanvas.class.getName());
        Mobile.lcdWidth=176;Mobile.lcdHeight=220;
        Mobile.setPlatform(new MobilePlatform(176,220),()->{});Mobile.config.init("HeldInputCheck");Mobile.updateSettings();
        Mobile.setDisplay(new Display());MIDletLoader.MIDletSelected=true;
        TestCanvas canvas=new TestCanvas();Mobile.getDisplay().setCurrent(canvas);delivered();
        GpuPlayer.dispatchKey(GLFW_KEY_LEFT,GLFW_PRESS);delivered();
        if(canvas.direction!=-3)throw new AssertionError("Left press not delivered");
        GpuPlayer.dispatchKey(GLFW_KEY_RIGHT,GLFW_PRESS);delivered();
        if(canvas.direction!=-4)throw new AssertionError("Right press not delivered");
        GpuPlayer.dispatchKey(GLFW_KEY_RIGHT,GLFW_RELEASE);delivered();
        if(canvas.direction!=-3)throw new AssertionError("Still-held left direction was lost");
        GpuPlayer.releaseHeldKeys();delivered();
        if(canvas.direction!=0)throw new AssertionError("Direction stuck after focus loss");
        System.out.println("PASS: direct arrow input, opposite-key release restoration and focus-loss release");System.exit(0);
    }
}
