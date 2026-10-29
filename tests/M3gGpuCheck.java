package org.recompile.mobile;
import javax.microedition.lcdui.*;
import javax.microedition.m3g.*;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;
import org.lwjgl.opengl.GL;
import static org.lwjgl.glfw.GLFW.*;

public final class M3gGpuCheck {
 static void check(boolean ok,String msg){if(!ok)throw new AssertionError(msg);}
 public static void main(String[] args)throws Exception {
  check(glfwInit(),"GLFW");glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
  glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
  long win=glfwCreateWindow(64,64,"M3G diagnostic",0,0);
  try {
   glfwMakeContextCurrent(win);GL.createCapabilities();PlatformFont.setScreenSize(32,32);
   Image image=Image.createImage(32,32);RuntimeAssets.markScreen(image);
   Graphics g=image.getGraphics();g.setColor(0x123456);g.fillRect(0,0,32,32);
   GpuRenderer.readback(image);
   if(args.length==1) {
    BufferedImage hd=new BufferedImage(32*Enhancement.SCALE,32*Enhancement.SCALE,BufferedImage.TYPE_INT_ARGB);
    java.awt.Graphics2D paint=hd.createGraphics();paint.setColor(new java.awt.Color(0x123456));paint.fillRect(0,0,hd.getWidth(),hd.getHeight());paint.dispose();
    hd.setRGB(0,0,0xff00ffff);GpuRenderer.stageReplacement(image,hd);GpuRenderer.readback(image);
   }
   Graphics3D renderer=Graphics3D.getInstance();renderer.bindTarget(g);
   renderer.setViewport(4,4,24,24);
   Camera camera=new Camera();camera.setPerspective(60,1,0.1f,10);
   renderer.setCamera(camera,new Transform());
   VertexArray positions=new VertexArray(3,3,2);
   positions.set(0,3,new short[]{-1,-1,-3,1,-1,-3,0,1,-3});
   VertexBuffer vertices=new VertexBuffer();vertices.setPositions(positions,1,null);vertices.setDefaultColor(0xffff0000);
   Appearance appearance=new Appearance();PolygonMode polygon=new PolygonMode();polygon.setCulling(PolygonMode.CULL_NONE);appearance.setPolygonMode(polygon);
   renderer.render(vertices,new TriangleStripArray(new int[]{0,1,2},new int[]{3}),appearance,new Transform());
   renderer.releaseTarget();
   BufferedImage logical=image.getCanvas(),gpu=GpuRenderer.readback(image);
   int s=Enhancement.SCALE;
   ImageIO.write(logical,"PNG",new File(args[0]+"-logical.png"));ImageIO.write(gpu,"PNG",new File(args[0]+"-gpu.png"));
   int original=logical.getRGB(16,16),shown=gpu.getRGB(16*s,16*s);
   System.out.println("logical="+Integer.toHexString(original)+" GPU="+Integer.toHexString(shown));
   check((original&0xffffff)==0xff0000,"software M3G triangle did not draw");
   if(args.length>1)check(original!=shown,"baseline unexpectedly contains 3D upload");
   else {
    check(original==shown,"M3G software pixels missing from GPU");
    check(gpu.getRGB(0,0)==0xff00ffff,"outside viewport HD detail damaged");
    g.setColor(0x00ff00);g.fillRect(15,15,2,2);
    check(GpuRenderer.readback(image).getRGB(16*s,16*s)==0xff00ff00,"later 2D draw order broken");
    Image clipped=Image.createImage(32,32);RuntimeAssets.markScreen(clipped);
    Graphics cg=clipped.getGraphics();cg.setColor(0x123456);cg.fillRect(0,0,32,32);GpuRenderer.readback(clipped);
    cg.translate(3,2);cg.setClip(1,2,8,9);renderer.bindTarget(cg);
    cg.setClip(0,0,32,32); // M3G must use the clip/origin captured at bind time.
    Background bg=new Background();bg.setColor(0xffff0000);renderer.clear(bg);renderer.releaseTarget();
    BufferedImage shownClip=GpuRenderer.readback(clipped);
    for(int y=0;y<32;y++)for(int x=0;x<32;x++) {
     int expected=x>=4&&x<12&&y>=4&&y<13?0xffff0000:0xff123456;
     check(clipped.getCanvas().getRGB(x,y)==expected,"M3G logical clip mismatch");
     check(shownClip.getRGB(x*s,y*s)==expected,"M3G presentation clip mismatch");
    }
    Image2D plain=new Image2D(Image2D.RGBA,8,8);renderer.bindTarget(plain);renderer.clear(bg);renderer.releaseTarget();
    renderer.releaseTarget(); // Unbound release stays harmless.
   }
   System.out.println("PASS M3G software/GPU comparison scale="+s);
  } finally {GpuRenderer.shutdown();glfwDestroyWindow(win);glfwTerminate();}
  System.exit(0);
 }
}
