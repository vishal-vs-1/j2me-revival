package org.recompile.mobile;

import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import javax.imageio.ImageIO;
import javax.microedition.lcdui.Graphics;
import javax.microedition.lcdui.Image;
import org.lwjgl.opengl.GL;
import static org.lwjgl.glfw.GLFW.*;
import static org.lwjgl.opengl.GL11.*;

/** Public drawRGB must filter immediately and later bind exact saved artwork without changing readback. */
public final class RawRgbGpuCheck {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static int[] scale2x(int[] source, int width, int height) {
        int[] result = new int[width * height * 4];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int e=source[y*width+x], b=source[Math.max(0,y-1)*width+x],
                    d=source[y*width+Math.max(0,x-1)], f=source[y*width+Math.min(width-1,x+1)],
                    h=source[Math.min(height-1,y+1)*width+x];
            int at=y*2*width*2+x*2;
            result[at]=b!=h && d!=f && d==b?d:e;
            result[at+1]=b!=h && d!=f && b==f?f:e;
            result[at+width*2]=b!=h && d!=f && d==h?d:e;
            result[at+width*2+1]=b!=h && d!=f && h==f?f:e;
        }
        return result;
    }

    private static int[] filtered(int[] pixels, int width, int height) {
        int[] result=scale2x(pixels,width,height);
        return Enhancement.SCALE==4?scale2x(result,width*2,height*2):result;
    }

    private static Image target(int width, int height) {
        Image image=Image.createImage(width,height);
        RuntimeAssets.markScreen(image);
        return image;
    }

    private static void equal(BufferedImage actual, int[] expected, String label) {
        check(Arrays.equals(expected,actual.getRGB(0,0,actual.getWidth(),actual.getHeight(),null,0,actual.getWidth())),label);
    }

    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory(Paths.get(args[0]),"raw-rgb-gpu-");
        StringBuilder key=new StringBuilder();for(int i=0;i<64;i++)key.append('a');
        String recipe=key.toString();
        System.setProperty("jme.pack",root.toString());
        System.setProperty("jme.textures",root.resolve("textures-ai").toString());
        System.setProperty("jme.recipeKey",recipe);
        long window=0;
        try {
            check(glfwInit(),"GLFW init");glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
            glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
            window=glfwCreateWindow(64,64,"Direct RGB check",0,0);check(window!=0,"GL window");
            glfwMakeContextCurrent(window);GL.createCapabilities();
            System.out.println("DEVICE: "+glGetString(GL_RENDERER)+" | "+glGetString(GL_VERSION));
            check(GpuRenderer.warmupFastScaler(),"GPU shader warmup");
            PlatformFont.setScreenSize(64,64);Mobile.maskIndex=0;
            int[] pixels={0xffffffff,0xffff0000,0xffffffff,0xffff0000,0xff000000,0xff0000ff,0xffffffff,0xff0000ff,0xffffffff};
            Image image=target(3,3);Graphics g=image.getGraphics();
            GpuRenderer.readback(image);long before=GpuRenderer.fastScalerPasses();
            g.drawRGB(pixels,0,3,0,0,3,3,true);
            equal(GpuRenderer.readback(image),filtered(pixels,3,3),"direct RGB bypassed edge-aware GPU filtering");
            check(GpuRenderer.fastScalerPasses()>before,"direct RGB submitted no GPU filter pass");
            check(Arrays.equals(pixels,image.getDataBuffer()),"GPU filter changed game-visible pixels");
            check(RawRgbPresentation.submittedDraws()>0,"public drawRGB bypassed the new adapter");

            int[] reused=pixels.clone();Image snapshot=target(3,3);
            snapshot.getGraphics().drawRGB(reused,0,3,0,0,3,3,true);
            Arrays.fill(reused,0xff00ff00);
            equal(GpuRenderer.readback(snapshot),filtered(pixels,3,3),"caller array mutation changed queued RGB drawing");

            int[] padded=new int[20];
            for(int y=0;y<3;y++)for(int x=0;x<3;x++)padded[13-y*5+x]=pixels[y*3+x];
            Image clipped=target(6,6);Graphics cg=clipped.getGraphics();
            cg.setColor(0);cg.fillRect(0,0,6,6);cg.translate(1,1);cg.setClip(1,1,2,2);
            cg.drawRGB(padded,13,-5,0,0,3,3,true);
            BufferedImage clipResult=GpuRenderer.readback(clipped);
            int s=Enhancement.SCALE;int[] edge=filtered(pixels,3,3);
            for(int y=0;y<6*s;y++)for(int x=0;x<6*s;x++) {
                int expected=x>=2*s&&x<4*s&&y>=2*s&&y<4*s?edge[(y-s)*3*s+x-s]:0xff000000;
                check(clipResult.getRGB(x,y)==expected,"clip/translation/negative scanline mismatch at "+x+","+y);
            }
            check(clipped.getCanvas().getRGB(2,2)==pixels[4],"negative-stride logical readback changed");

            Image alpha=target(2,2);Graphics ag=alpha.getGraphics();
            ag.setColor(0x0000ff);ag.fillRect(0,0,2,2);
            ag.drawRGB(new int[]{0x80ff0000,0x80ff0000,0x80ff0000,0x80ff0000},0,2,0,0,2,2,true);
            int blend=GpuRenderer.readback(alpha).getRGB(0,0);
            check((blend>>>24)==255&&((blend>>>16)&255)==128&&(blend&255)==127,"raw RGB premultiplied alpha mismatch");
            ag.drawRGB(new int[]{0x00112233},0,1,0,0,1,1,false);
            check(GpuRenderer.readback(alpha).getRGB(0,0)==0xff112233,"processAlpha=false was not opaque");

            check(RuntimeAssets.awaitIdle(3000),"early capture IO did not settle");
            String sourceId=Enhancement.hash(new PlatformImage(pixels,3,3,true).getCanvas());
            check(!Files.exists(root.resolve("original-assets").resolve(sourceId+".png")),"transient RGB was queued before repeated frame use");
            for(int frame=0;frame<3;frame++) {
                g.drawRGB(pixels,0,3,0,0,3,3,true);
                GpuRenderer.publish(image);GpuRenderer.drain();RuntimeAssets.endFrame();
            }
            check(RuntimeAssets.awaitIdle(5000),"stable RGB capture did not settle");
            check(Files.isRegularFile(root.resolve("original-assets").resolve(sourceId+".png")),"stable direct RGB was not persisted");
            BufferedImage hd=new BufferedImage(12,12,BufferedImage.TYPE_INT_ARGB);
            for(int y=0;y<12;y++)for(int x=0;x<12;x++)hd.setRGB(x,y,0xff77cc44);
            Path texture=root.resolve("textures-cache").resolve(recipe).resolve(sourceId+".png");
            Files.createDirectories(texture.getParent());ImageIO.write(hd,"PNG",texture.toFile());
            Path manifest=root.resolve(".runtime/ready").resolve(recipe+".json");Files.createDirectories(manifest.getParent());
            Files.write(manifest,("{\"schema\":1,\"generation\":1,\"recipe_key\":\""+recipe+"\",\"scale\":4,\"sources\":[\""+sourceId+"\"]}").getBytes(StandardCharsets.UTF_8));
            long until=System.nanoTime()+8_000_000_000L;
            while(RuntimeAssets.pendingTextureUpdates()==0&&System.nanoTime()<until)Thread.sleep(10L);
            check(RuntimeAssets.pendingTextureUpdates()>0,"saved HD RGB did not resolve asynchronously");
            equal(GpuRenderer.readback(image),filtered(pixels,3,3),"HD replacement changed a frame before publication");
            RuntimeAssets.endFrame();g.drawRGB(pixels,0,3,0,0,3,3,true);
            check(GpuRenderer.readback(image).getRGB(s,s)==0xff77cc44,"direct RGB ignored its live HD replacement");
            check(Arrays.equals(pixels,image.getDataBuffer()),"HD replacement changed game-visible RGB pixels");
            g.drawRGB(reused,0,3,0,0,3,3,true);
            check(GpuRenderer.readback(image).getRGB(s,s)==0xff00ff00,"changed source reused a stale HD texture");

            for(int i=0;i<300;i++)RawRgbSourceCache.acquire(new int[]{0xff000000|i},0,1,1,1,true,20L);
            check(RawRgbSourceCache.retainedSources()<=256,"RGB cache entry limit exceeded");
            for(int i=0;i<20;i++) {
                int[] block=new int[256*256];Arrays.fill(block,0xff000000|i);
                RawRgbSourceCache.acquire(block,0,256,256,256,true,20L);
            }
            check(RawRgbSourceCache.retainedBytes()<=4L*1024L*1024L,"RGB cache memory limit exceeded");
            check(glGetError()==GL_NO_ERROR,"OpenGL error");
            System.out.println("PASS: "+s+"x direct RGB GPU filtering, exact snapshots, alpha, clip, negative stride, stable capture, frame-boundary HD replacement and bounded cache");
        } finally {
            RuntimeAssets.close();GpuRenderer.shutdown();
            if(window!=0)glfwDestroyWindow(window);glfwTerminate();
        }
    }
}
