import org.recompile.mobile.*;
import javax.microedition.lcdui.Image;
import javax.microedition.lcdui.Graphics;
import java.util.Arrays;

public class RenderBenchmark {
    public static void main(String[] args) throws Exception {
        PlatformFont.setScreenSize(240,320); Mobile.maskIndex=0;
        Image target=Image.createImage(240,320), front=Image.createImage(240,320);
        Graphics g=target.getGraphics(), screen=front.getGraphics();
        int[] pixels=new int[24*40];
        for(int y=0;y<40;y++)for(int x=0;x<24;x++)pixels[y*24+x]=(x>2&&x<21)?0xff20b070:0;
        Image sprite=Image.createRGBImage(pixels,24,40,true); sprite.setMutable(true);
        Enhancement.surface(sprite);
        long[] times=new long[300];
        for(int frame=-100;frame<300;frame++) {
            long start=System.nanoTime();
            g.setColor(0x224455); g.fillRect(0,0,240,320);
            for(int y=0;y<320;y+=5) { g.setColor(0x334455+y*30); g.fillRect(0,y,240,5); }
            for(int i=0;i<24;i++)g.drawRegion(sprite,0,0,24,40,i%8,(i*31+frame+100)%200,(i*17)%260,0);
            g.setColor(0xffffff); g.drawString("FRAME "+frame,4,4,0);
            screen.flushGraphics(target,0,0,240,320);
            if(GpuRenderer.ENABLED){GpuRenderer.drain();org.lwjgl.opengl.GL11.glFinish();}
            if(frame>=0)times[frame]=System.nanoTime()-start;
        }
        Arrays.sort(times);
        System.out.printf(java.util.Locale.US,"{\"scale\":%d,\"p50_ms\":%.3f,\"p95_ms\":%.3f}%n",Enhancement.SCALE,times[150]/1e6,times[285]/1e6);
    }
}
