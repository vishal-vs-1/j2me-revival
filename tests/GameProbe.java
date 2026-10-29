import org.recompile.mobile.*;
import javax.imageio.ImageIO;
import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Exercise an imported MIDlet in isolation without touching the user's player. */
public class GameProbe {
    static void snapshot(MobilePlatform p, File out, int stage) throws Exception {
        synchronized(p.getLcdFrontbuffer()) {
            ImageIO.write(p.getLcdFrontbuffer().getCanvas(),"PNG",new File(out,"logical-"+stage+".png"));
            ImageIO.write(Enhancement.surface(p.getLcdFrontbuffer()),"PNG",new File(out,"enhanced-"+stage+".png"));
        }
        CountDownLatch alive=new CountDownLatch(1);
        Mobile.getDisplay().callSerially(() -> alive.countDown());
        if(!alive.await(3,TimeUnit.SECONDS))throw new AssertionError("Event thread stopped at stage "+stage);
        System.out.println("STAGE "+stage+" responsive: "+Mobile.getDisplay().getCurrent().getClass().getName());
    }
    public static void main(String[] args) throws Exception {
        try {
            int width=Integer.getInteger("jme.width",240),height=Integer.getInteger("jme.height",320);
            Mobile.lcdWidth=width; Mobile.lcdHeight=height;
            MobilePlatform p=new MobilePlatform(width,height);
            Mobile.setPlatform(p,() -> {});
            File jar=new File(args[0]), out=new File(args[1]); out.mkdirs();
            MobilePlatform.fileName=jar.toURI().toString();
            if(!p.load(MobilePlatform.fileName))throw new AssertionError("Load failed");
            Mobile.config.settings.put("scrwidth",""+width);Mobile.config.settings.put("scrheight",""+height);
            Mobile.updateSettings();
            p.loader.start();
            Thread.sleep(1500);
            snapshot(p,out,0);
            for(int stage=1;stage<args.length-1;stage++) {
                int key=Integer.parseInt(args[stage+1]);
                MobilePlatform.keyPressed(key);
                CountDownLatch delivered=new CountDownLatch(1);
                Mobile.getDisplay().callSerially(() -> delivered.countDown());
                if(!delivered.await(3,TimeUnit.SECONDS))throw new AssertionError("Input was not delivered");
                Thread.sleep(250); MobilePlatform.keyReleased(key);
                Thread.sleep(1500);
                snapshot(p,out,stage);
            }
            System.out.println("PASS: game start/input stages remained responsive");
            System.exit(0);
        } catch(Throwable error) { error.printStackTrace(); System.exit(1); }
    }
}
