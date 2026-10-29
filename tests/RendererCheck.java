import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;
import javax.microedition.lcdui.Image;
import javax.microedition.lcdui.Graphics;
import org.recompile.mobile.Enhancement;
import org.recompile.mobile.PlatformImage;

public class RendererCheck {
    static void check(boolean condition, String label) {
        if(!condition) throw new AssertionError(label);
    }
    static void equal(BufferedImage a, BufferedImage b, String label) {
        check(a.getWidth()==b.getWidth() && a.getHeight()==b.getHeight(), label+" dimensions");
        for(int y=0;y<a.getHeight();y++) for(int x=0;x<a.getWidth();x++)
            check(a.getRGB(x,y)==b.getRGB(x,y),label+" pixel "+x+","+y);
    }
    public static void main(String[] args) throws Exception {
        org.recompile.mobile.PlatformFont.setScreenSize(240,320);
        org.recompile.mobile.Mobile.maskIndex=0;
        javax.microedition.lcdui.StringItem item=new javax.microedition.lcdui.StringItem(null,"layout");
        item.setLayout(0x4001);
        check(item.getLayout()==0x4001,"Mr Bean MIDP LAYOUT_2 accepted");
        try { item.setLayout(0x8000); throw new AssertionError("Invalid layout accepted"); }
        catch (IllegalArgumentException expected) {}
        int[] colours={0xff112233,0xffee4455,0xff55ee44,0xff3344cc,0xffcc8844,0xff777777};
        Image source=Image.createRGBImage(colours,2,3,true);
        System.out.println("HASH="+Enhancement.hash(source.getCanvas()));
        // Distinct high-resolution subpixels prove that the renderer uses replacements.
        BufferedImage replacement=new BufferedImage(8,12,BufferedImage.TYPE_INT_ARGB);
        for(int y=0;y<12;y++) for(int x=0;x<8;x++) replacement.setRGB(x,y,0xff000000|((x*25)<<16)|((y*17)<<8)|((x+y)*9));
        source.hdCanvas=replacement;
        for(int transform=0;transform<8;transform++) {
            boolean rotate=transform>=4;
            int w=rotate?3:2,h=rotate?2:3;
            Image target=Image.createImage(w,h);
            Graphics g=target.getGraphics();
            g.drawRegion(source,0,0,2,3,transform,0,0,0);
            equal(Enhancement.surface(target),PlatformImage.transformImage(replacement,transform),"transform "+transform);
            int[] logical=new int[w*h]; target.getRGB(logical,0,w,0,0,w,h);
            BufferedImage expected=PlatformImage.transformImage(source.getCanvas(),transform);
            for(int y=0;y<h;y++) for(int x=0;x<w;x++) check(logical[y*w+x]==expected.getRGB(x,y),"logical readback unchanged");
        }
        Image target=Image.createImage(12,12); Graphics g=target.getGraphics();
        g.setColor(0); g.fillRect(0,0,12,12);
        g.translate(2,1); g.setClip(1,1,1,2); g.drawImage(source,0,0,0);
        BufferedImage hd=Enhancement.surface(target);
        check(hd.getRGB(12,8)==replacement.getRGB(4,4),"translated clipped replacement");
        check(hd.getRGB(8,4)==0xff000000,"clip outside untouched");
        g.translate(-2,-1); g.setClip(0,0,12,12);
        g.setColor(0); g.fillRect(0,0,12,12);
        check(hd.getRGB(12,8)==0xff000000,"same-colour clear removes replacement detail");
        g.drawImage(source,0,0,0); g.copyArea(0,0,2,3,4,4,0);
        check(hd.getRGB(17,17)==replacement.getRGB(1,1),"copyArea preserves detail");
        Image front=Image.createImage(12,12);
        front.getGraphics().flushGraphics(target,0,0,12,12);
        equal(Enhancement.surface(front),hd,"framebuffer transfer");
        int original=source.getARGB(0,0);
        check(original==colours[0],"source unchanged");
        Image textTarget=Image.createImage(80,32);
        Graphics textGraphics=textTarget.getGraphics();
        textGraphics.setColor(0xffffff); textGraphics.fillRect(0,0,80,32);
        textGraphics.setColor(0); textGraphics.drawString("Opaque text",0,0,0);
        BufferedImage textHd=Enhancement.surface(textTarget);
        for(int yy=0;yy<textHd.getHeight();yy++)for(int xx=0;xx<textHd.getWidth();xx++)
            check((textHd.getRGB(xx,yy)>>>24)==255,"opaque RGB glyphs must not turn transparent");
        File file=new File(args[0]); ImageIO.write(hd,"PNG",file);
        System.out.println("PASS: replacement detail, 8 transforms, logical readback, clip, translation, clear, copy and flush");
        javax.microedition.lcdui.Display display=new javax.microedition.lcdui.Display();
        java.util.concurrent.CountDownLatch recovered=new java.util.concurrent.CountDownLatch(1);
        display.postInputEvent(() -> { throw new IllegalArgumentException("intentional failed input fixture"); });
        display.postInputEvent(() -> recovered.countDown());
        check(recovered.await(3,java.util.concurrent.TimeUnit.SECONDS),"event thread survived failed callback");
        System.out.println("PASS: MIDP LAYOUT_2 accepted; event queue continues after callback exception");
        System.exit(0);
    }
}
