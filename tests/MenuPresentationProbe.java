import org.recompile.mobile.*;
import javax.microedition.lcdui.*;
import java.lang.reflect.*;
import java.nio.*;
import java.util.concurrent.*;
import static org.lwjgl.glfw.GLFW.*;
import static org.lwjgl.opengl.GL11.*;
import static org.lwjgl.opengl.GL30.*;

/** Measure the committed GPU picture, after the real menu has been running. */
public final class MenuPresentationProbe {
    static long picture() throws Exception {
        Field field=GpuRenderer.class.getDeclaredField("presented");field.setAccessible(true);
        Object frame=field.get(null);if(frame==null)throw new AssertionError("No presented frame");
        Field fbo=frame.getClass().getDeclaredField("framebuffer"),w=frame.getClass().getDeclaredField("w"),h=frame.getClass().getDeclaredField("h");
        fbo.setAccessible(true);w.setAccessible(true);h.setAccessible(true);
        int width=w.getInt(frame)*Enhancement.SCALE,height=h.getInt(frame)*Enhancement.SCALE;
        int previous=glGetInteger(GL_READ_FRAMEBUFFER_BINDING);
        ByteBuffer pixels=org.lwjgl.BufferUtils.createByteBuffer(width*height*4);
        glBindFramebuffer(GL_READ_FRAMEBUFFER,fbo.getInt(frame));glReadPixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
        glBindFramebuffer(GL_READ_FRAMEBUFFER,previous);
        long hash=1;while(pixels.hasRemaining())hash=31*hash+(pixels.get()&255);return hash;
    }
    static <T> T gpu(Callable<T> action)throws Exception {
        Field field=GpuRenderer.class.getDeclaredField("QUEUE");field.setAccessible(true);
        BlockingQueue<Runnable> queue=(BlockingQueue<Runnable>)field.get(null);
        FutureTask<T> task=new FutureTask<T>(action);
        if(!queue.offer(task,2,TimeUnit.SECONDS))throw new AssertionError("GPU command queue stayed full");
        return task.get(3,TimeUnit.SECONDS);
    }
    static void delivered()throws Exception {
        CountDownLatch done=new CountDownLatch(1);Mobile.getDisplay().callSerially(()->done.countDown());
        if(!done.await(3,TimeUnit.SECONDS))throw new AssertionError("Menu event delivery stalled behind drawing");
    }
    static void tap(int key)throws Exception {
        GpuPlayer.dispatchKey(key,GLFW_PRESS);Thread.sleep(60);GpuPlayer.dispatchKey(key,GLFW_RELEASE);delivered();
    }
    static Object waitDisplay(String type)throws Exception {
        long until=System.nanoTime()+8000000000L;
        while(System.nanoTime()<until) {
            Object current=Mobile.getDisplay()==null?null:Mobile.getDisplay().getCurrent();
            if(current!=null&&current.getClass().getName().equals(type))return current;
            Thread.sleep(20);
        }
        throw new AssertionError("Did not reach "+type);
    }
    public static void main(String[] args) {
        Thread probe=new Thread(()->{try {
            List menu=(List)waitDisplay("javax.microedition.lcdui.List");
            // Earlier tests only checked startup CPU pixels. Let the repeating menu build pressure.
            Thread.sleep(10000);
            long before=gpu(()->picture());
            for(int key:new int[]{GLFW_KEY_DOWN,GLFW_KEY_UP}) {
                int expected=key==GLFW_KEY_DOWN?1:0;long start=System.nanoTime();
                tap(key);
                long deliveredAt=System.nanoTime();
                long after=gpu(()->picture());double elapsed=(System.nanoTime()-start)/1e6;
                System.out.printf(java.util.Locale.US,"DETAIL event %.1f ms, GPU %.1f ms, frames %d%n",(deliveredAt-start)/1e6,(System.nanoTime()-deliveredAt)/1e6,GpuRenderer.submittedFrames);
                if(menu.getSelectedIndex()!=expected)throw new AssertionError("Wrong list selection");
                if(after==before)throw new AssertionError("Menu selection changed but committed GPU picture stayed stale");
                if(Boolean.getBoolean("probe.strictLatency")&&elapsed>250)
                    throw new AssertionError("Visible menu response took "+elapsed+" ms");
                System.out.printf(java.util.Locale.US,"MENU GPU %s %.1f ms%n",key==GLFW_KEY_DOWN?"Down":"Up",elapsed);
                before=after;
            }
            tap(GLFW_KEY_ENTER);waitDisplay("h");
            Thread.sleep(400);gpu(()->picture());
            tap(GLFW_KEY_ENTER);waitDisplay("d");
            Thread.sleep(1000);long form=gpu(()->picture());
            // A progress Form has soft-key commands rather than a selectable arrow-key list.
            tap(GLFW_KEY_Q);waitDisplay("p");
            gpu(()->picture());
            System.out.println("PASS: original wrapper List arrows visibly redraw, Enter opens h/d, Q starts the game");
            System.exit(0);
        }catch(Throwable error){System.out.println("PRESENTATION PROBE FAILED");error.printStackTrace();System.exit(1);}},"presentation-probe");
        probe.setDaemon(true);probe.start();GpuPlayer.main(args);
    }
}
