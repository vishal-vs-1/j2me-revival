import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;
import javax.microedition.lcdui.Image;
import javax.microedition.lcdui.Graphics;
import org.recompile.mobile.*;
import org.lwjgl.opengl.GL;
import static org.lwjgl.glfw.GLFW.*;
import static org.lwjgl.opengl.GL11.*;
import org.lwjgl.BufferUtils;
import java.nio.ByteBuffer;

public class GpuCheck {
    static void check(boolean b,String label){if(!b)throw new AssertionError(label);}
    static void equal(BufferedImage a,BufferedImage b,String label) {
        check(a.getWidth()==b.getWidth()&&a.getHeight()==b.getHeight(),label+" size");
        for(int y=0;y<a.getHeight();y++)for(int x=0;x<a.getWidth();x++)
            if(a.getRGB(x,y)!=b.getRGB(x,y))throw new AssertionError(label+" at "+x+","+y+": "+Integer.toHexString(a.getRGB(x,y))+" != "+Integer.toHexString(b.getRGB(x,y)));
    }
    public static void main(String[] args) {
        long window=0;
        try {
            check(glfwInit(),"GLFW init");glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
            glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
            window=glfwCreateWindow(128,128,"GPU renderer check",0,0);check(window!=0,"GL window");
            glfwMakeContextCurrent(window);GL.createCapabilities();
            System.out.println("DEVICE: "+glGetString(GL_RENDERER)+" | "+glGetString(GL_VERSION));
            PlatformFont.setScreenSize(240,320);Mobile.maskIndex=0;
            int[] colours={0xff112233,0xffee4455,0xff55ee44,0xff3344cc,0xffcc8844,0xff777777};
            Image source=Image.createRGBImage(colours,2,3,true);
            BufferedImage art=new BufferedImage(8,12,BufferedImage.TYPE_INT_ARGB);
            for(int y=0;y<12;y++)for(int x=0;x<8;x++)art.setRGB(x,y,0xff000000|((x*25)<<16)|((y*17)<<8)|((x+y)*9));
            source.hdCanvas=art;
            for(int t=0;t<8;t++) {
                boolean rotated=t>=4;Image target=Image.createImage(rotated?3:2,rotated?2:3);
                target.getGraphics().drawRegion(source,0,0,2,3,t,0,0,0);
                equal(GpuRenderer.readback(target),PlatformImage.transformImage(art,t),"GPU transform "+t);
                Image derived=Image.createImage(source,0,0,2,3,t);
                equal(GpuRenderer.readback(derived),PlatformImage.transformImage(art,t),"Derived HD region "+t);
            }
            Image target=Image.createImage(12,12);Graphics g=target.getGraphics();
            g.setColor(0);g.fillRect(0,0,12,12);g.translate(2,1);g.setClip(1,1,1,2);g.drawImage(source,0,0,0);
            BufferedImage hd=GpuRenderer.readback(target);
            check(hd.getRGB(12,8)==art.getRGB(4,4),"GPU clipping/translation");
            check(hd.getRGB(8,4)==0xff000000,"GPU clip outside");
            g.translate(-2,-1);g.setClip(0,0,12,12);g.setColor(0);g.fillRect(0,0,12,12);
            check(GpuRenderer.readback(target).getRGB(12,8)==0xff000000,"GPU clear");
            g.drawImage(source,0,0,0);g.copyArea(0,0,2,3,4,4,0);
            check(GpuRenderer.readback(target).getRGB(17,17)==art.getRGB(1,1),"GPU overlapping copy");
            Image front=Image.createImage(12,12);front.getGraphics().flushGraphics(target,0,0,12,12);
            equal(GpuRenderer.readback(front),GpuRenderer.readback(target),"GPU framebuffer transfer");
            check(source.getARGB(0,0)==colours[0],"logical original unchanged");
            Image sparse=Image.createImage(3,2);Graphics sg=sparse.getGraphics();sg.drawImage(source,0,0,0);
            BufferedImage sparseBefore=GpuRenderer.readback(sparse);
            sg.setColor(0xabcdef);sg.drawLine(0,0,0,0);sg.drawLine(2,0,2,0);
            BufferedImage sparseAfter=GpuRenderer.readback(sparse);
            check(sparseAfter.getRGB(5,1)==sparseBefore.getRGB(5,1),"sparse dirty upload preserves untouched HD detail");
            check(sparseAfter.getRGB(0,0)==0xffabcdef&&sparseAfter.getRGB(8,0)==0xffabcdef,"sparse dirty upload applies both writes");
            g.setColor(0xabcdef);g.drawLine(0,10,10,10);
            check(GpuRenderer.readback(target).getRGB(4,40)==0xffabcdef,"dirty pixel fallback");
            Image translucent=Image.createRGBImage(new int[]{0x80ff0000},1,1,true);
            Image composite=Image.createImage(64,32);Graphics cg=composite.getGraphics();
            cg.setColor(0x0000ff);cg.fillRect(0,0,64,32);cg.drawImage(translucent,2,2,0);
            int blend=GpuRenderer.readback(composite).getRGB(8,8);
            check(((blend>>>16)&255)==128&&(blend&255)==127&&(blend>>>24)==255,"premultiplied alpha blend");
            cg.setColor(0xffffff);cg.drawString("Smooth",0,0,Graphics.TOP|Graphics.LEFT);
            BufferedImage text=GpuRenderer.readback(composite);boolean foundText=false;
            for(int y=0;y<text.getHeight();y++)for(int x=0;x<text.getWidth();x++)if(text.getRGB(x,y)==0xffffffff)foundText=true;
            check(foundText,"opaque RGB text patch");
            boolean antialiased=false;
            for(int y=0;y<text.getHeight();y++)for(int x=0;x<text.getWidth();x++) {
                int p=text.getRGB(x,y);if((p&255)==255&&((p>>>16)&255)>0&&((p>>>16)&255)<255)antialiased=true;
            }
            check(antialiased,"text rendered with HD antialiasing");
            Image atomic=Image.createImage(12,12);Graphics ag=atomic.getGraphics();
            ag.setColor(0xff0000);ag.fillRect(0,0,12,12);GpuRenderer.publish(atomic);GpuRenderer.drain();GpuRenderer.present(128,128);
            ByteBuffer pixel=BufferUtils.createByteBuffer(4);glReadPixels(64,64,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
            check((pixel.get(0)&255)==255&&(pixel.get(1)&255)==0,"completed red frame presented");
            ag.setColor(0x00ff00);ag.fillRect(0,0,12,12);GpuRenderer.drain();GpuRenderer.present(128,128);
            glReadPixels(64,64,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
            check((pixel.get(0)&255)==255&&(pixel.get(1)&255)==0,"uncommitted writes stay hidden");
            GpuRenderer.publish(atomic);GpuRenderer.drain();GpuRenderer.present(128,128);
            glReadPixels(64,64,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
            check((pixel.get(0)&255)==0&&(pixel.get(1)&255)==255,"next complete frame swaps atomically");
            check(glGetError()==GL_NO_ERROR,"GL error state");
            ImageIO.write(GpuRenderer.readback(target),"PNG",new File(args[0]));
            System.out.println("PASS: GPU detail, derived HD copies, 8 transforms, clip, alpha, HD text, fallback writes and complete-frame-only presentation");
            GpuRenderer.shutdown();glfwDestroyWindow(window);glfwTerminate();System.exit(0);
        }catch(Throwable e){e.printStackTrace();if(window!=0)glfwDestroyWindow(window);glfwTerminate();System.exit(1);}
    }
}
