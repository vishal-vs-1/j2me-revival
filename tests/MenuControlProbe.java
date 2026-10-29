/* Diagnostic only: launch the real native player and inspect menu input delivery. */
import org.recompile.mobile.*;
import javax.microedition.lcdui.List;
import static org.lwjgl.glfw.GLFW.*;
import java.util.concurrent.*;

public class MenuControlProbe {
    static int picture() {
        PlatformImage front=Mobile.getPlatform().getLcdFrontbuffer();
        synchronized(front){return java.util.Arrays.hashCode(front.getCanvas().getRGB(0,0,front.getWidth(),front.getHeight(),null,0,front.getWidth()));}
    }
    static void delivered()throws Exception {
        CountDownLatch done=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->done.countDown());
        if(!done.await(3,TimeUnit.SECONDS))throw new AssertionError("Event queue stalled");
    }
    static void key(int code)throws Exception {
        GpuPlayer.dispatchKey(code,GLFW_PRESS);delivered();Thread.sleep(120);
        GpuPlayer.dispatchKey(code,GLFW_RELEASE);delivered();Thread.sleep(250);
    }
    public static void main(String[] args) {
        Thread inspect=new Thread(()->{
            try {
                long until=System.nanoTime()+(Boolean.getBoolean("probe.observe")?120000000000L:12000000000L);
                while(System.nanoTime()<until) {
                    if(Mobile.getDisplay()!=null&&Mobile.getDisplay().getCurrent()!=null) {
                        Object current=Mobile.getDisplay().getCurrent();
                        java.lang.reflect.Field queueField=GpuRenderer.class.getDeclaredField("QUEUE");queueField.setAccessible(true);
                        int queued=((java.util.concurrent.BlockingQueue<?>)queueField.get(null)).size();
                        System.out.println("MENU DISPLAY "+current.getClass().getName()+" midletSelected="+MIDletLoader.MIDletSelected+" gpuFrames="+GpuRenderer.submittedFrames+" gpuCommands="+queued+" time="+System.currentTimeMillis());
                        if(current instanceof List) {
                            List list=(List)current;int start=list.getSelectedIndex();
                            System.out.println("INITIAL index="+start+" title="+list.getTitle()+" count="+list.size());
                            for(int i=0;i<list.size();i++)System.out.println("ITEM "+i+" "+list.getString(i));
                            if(!Boolean.getBoolean("probe.observe")) {
                                int initialPicture=picture();
                                key(GLFW_KEY_DOWN);System.out.println("AFTER DOWN index="+list.getSelectedIndex());
                                if(list.getSelectedIndex()==start)throw new AssertionError("Down did not change menu selection");
                                int downPicture=picture();
                                if(Boolean.getBoolean("probe.assertInitialPaint")&&initialPicture==downPicture)throw new AssertionError("Down changed selection but not its visible image");
                                key(GLFW_KEY_UP);System.out.println("AFTER UP index="+list.getSelectedIndex());
                                if(Boolean.getBoolean("probe.assertInitialPaint")&&picture()==downPicture)throw new AssertionError("Up did not repaint selection");
                                int before=picture();System.out.println("BEFORE ENTER image="+before);
                                key(GLFW_KEY_ENTER);Thread.sleep(500);
                                System.out.println("AFTER ENTER display="+Mobile.getDisplay().getCurrent().getClass().getName());
                                int after=picture();System.out.println("AFTER ENTER image="+after+" unchanged="+(before==after));
                                if(Boolean.getBoolean("probe.assertInitialPaint")&&after==before)throw new AssertionError("Enter switched menu without painting");
                                if(Mobile.getDisplay().getCurrent() instanceof javax.microedition.lcdui.Canvas) {
                                    javax.microedition.lcdui.Canvas canvas=(javax.microedition.lcdui.Canvas)Mobile.getDisplay().getCurrent();
                                    canvas.repaint();canvas.serviceRepaints();delivered();Thread.sleep(250);
                                    int repainted=picture();System.out.println("AFTER EXPLICIT REPAINT image="+repainted+" changed="+(after!=repainted));
                                }
                                if(Mobile.getDisplay().getCurrent()==list)throw new AssertionError("Enter did not leave initial menu");
                                System.out.println("PASS: actual player startup/menu dispatch");
                                return;
                            }
                        }
                    }
                    Thread.sleep(500);
                }
            }catch(Throwable error){System.out.println("MENU PROBE FAILED");error.printStackTrace();}
        },"menu-control-diagnostic");
        inspect.setDaemon(true);inspect.start();GpuPlayer.main(args);
    }
}
