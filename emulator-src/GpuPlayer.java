/* Native desktop-height player. GPL-3.0-or-later. */
package org.recompile.mobile;

import java.io.File;
import java.nio.IntBuffer;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import javax.imageio.ImageIO;
import org.lwjgl.BufferUtils;
import org.lwjgl.glfw.*;
import org.lwjgl.opengl.GL;
import static org.lwjgl.glfw.GLFW.*;
import static org.lwjgl.opengl.GL11.*;

public final class GpuPlayer {
    private static String json(String value){return value.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r");}
    private static String gpuName(String value){return value.toLowerCase(Locale.ROOT).replace("(tm)","").replace("(r)","").replaceAll("[^a-z0-9]","");}
    private static final KeyInputController INPUT=new KeyInputController(DesktopKeyMap::toPhone,new MobileInputSink());
    private static volatile Throwable gameFailure;
    public static void releaseHeldKeys() {
        INPUT.releaseAll();
    }
    public static void dispatchKey(int key,int action) {
        INPUT.handle(key,action);
    }
    public static void main(String[] args) {
        long window=0;
        try {
            GLFWErrorCallback.createPrint(System.err).set();
            if(!glfwInit())throw new IllegalStateException("GLFW could not initialize");
            boolean hidden=Boolean.getBoolean("jme.hidden");
            glfwDefaultWindowHints();glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
            glfwWindowHint(GLFW_VISIBLE,hidden?GLFW_FALSE:GLFW_TRUE);glfwWindowHint(GLFW_MAXIMIZED,hidden?GLFW_FALSE:GLFW_TRUE);
            window=glfwCreateWindow(hidden?640:1000,hidden?640:800,"JAR Revival · GPU player",0,0);
            if(window==0)throw new IllegalStateException("An OpenGL 3.0 window could not be created");
            glfwMakeContextCurrent(window);GL.createCapabilities();
            if(!GL.getCapabilities().OpenGL30)throw new IllegalStateException("OpenGL 3.0 framebuffer support is required");
            glfwSwapInterval(1);
            GpuRenderer.device=glGetString(GL_RENDERER);
            System.out.println("GPU compositor: "+GpuRenderer.device+" | "+glGetString(GL_VERSION));
            System.out.println(GpuRenderer.warmupFastScaler()
                    ? "GPU Scale2x shader ready before game startup"
                    : "GPU Scale2x unavailable; using compatibility scaling");
            String expectedGpu=System.getProperty("jme.expectedGpu","");
            boolean gpuMatched=expectedGpu.isEmpty()||gpuName(GpuRenderer.device).contains(gpuName(expectedGpu));
            if(!gpuMatched)System.err.println("GPU preference mismatch: requested "+expectedGpu+"; Windows/driver selected "+GpuRenderer.device);
            final long nativeWindow=window;
            final int logicalWidth=Integer.parseInt(args[1]),logicalHeight=Integer.parseInt(args[2]);
            final String name=args.length>3?args[3]:"Java ME game";
            glfwSetWindowTitle(window,name+" · "+GpuRenderer.device+" · Arrows / Enter / Q W · F11 fullscreen · Esc close");
            if(!hidden)glfwFocusWindow(window);
            glfwSetKeyCallback(window,(handle,key,scan,action,mods)->{
                if(Boolean.getBoolean("jme.inputTrace"))System.out.println("NATIVE KEY key="+key+" scan="+scan+" action="+action+" mapped="+DesktopKeyMap.toPhone(key));
                if(key==GLFW_KEY_ESCAPE&&action==GLFW_PRESS){glfwSetWindowShouldClose(handle,true);return;}
                if(key==GLFW_KEY_F11&&action==GLFW_PRESS) {
                    long monitor=glfwGetPrimaryMonitor();GLFWVidMode mode=glfwGetVideoMode(monitor);
                    if(glfwGetWindowMonitor(handle)==0)glfwSetWindowMonitor(handle,monitor,0,0,mode.width(),mode.height(),mode.refreshRate());
                    else {glfwSetWindowMonitor(handle,0,60,40,1000,800,GLFW_DONT_CARE);glfwMaximizeWindow(handle);}
                    return;
                }
                dispatchKey(key,action);
                if(Boolean.getBoolean("jme.inputTrace")&&Mobile.getDisplay()!=null)Mobile.getDisplay().callSerially(()->{
                    javax.microedition.lcdui.Displayable current=Mobile.getDisplay().getCurrent();
                    System.out.println("KEY DELIVERY mapped="+DesktopKeyMap.toPhone(key)+" canvasAction="+Mobile.getCanvasAction(DesktopKeyMap.toPhone(key))+" display="+(current==null?"null":current.getClass().getName())+" index="+(current instanceof javax.microedition.lcdui.List?((javax.microedition.lcdui.List)current).getSelectedIndex():-1));
                });
            });
            glfwSetWindowFocusCallback(window,(handle,focused)->{if(!focused)releaseHeldKeys();});
            FramePresentationPolicy presentation=new FramePresentationPolicy();
            glfwSetWindowRefreshCallback(window,handle->presentation.requestRedraw());
            Thread game=new Thread(()->{
                try {
                    Enhancement.preload();
                    Mobile.lcdWidth=logicalWidth;Mobile.lcdHeight=logicalHeight;
                    MobilePlatform platform=new MobilePlatform(logicalWidth,logicalHeight);
                    Mobile.setPlatform(platform,()->{});
                    MobilePlatform.fileName=new File(args[0]).toURI().toString();
                    if(!platform.load(MobilePlatform.fileName))throw new IllegalStateException("Game could not be loaded");
                    Mobile.config.settings.put("scrwidth",""+logicalWidth);Mobile.config.settings.put("scrheight",""+logicalHeight);
                    Mobile.updateSettings();platform.setPainter(()->{});platform.runJar();
                }catch(Throwable error){gameFailure=error;error.printStackTrace();glfwSetWindowShouldClose(nativeWindow,true);}
            },"game-runtime");
            game.setDaemon(true);game.start();
            IntBuffer w=BufferUtils.createIntBuffer(1),h=BufferUtils.createIntBuffer(1);
            long start=System.nanoTime(),cleaned=start;int oldW=0,oldH=0;boolean proof=false;
            int stopSeconds=Integer.getInteger("jme.stopSeconds",0);
            while(!glfwWindowShouldClose(window)) {
                glfwPollEvents();
                int pumped=GpuRenderer.pump(4000000L);
                glfwGetFramebufferSize(window,w,h);
                long completedFrame=GpuRenderer.submittedFrames;
                if(presentation.shouldPresent(completedFrame,w.get(0),h.get(0))) {
                    presentation.presenting(completedFrame,w.get(0),h.get(0));
                    GpuRenderer.present(w.get(0),h.get(0));glfwSwapBuffers(window);
                }else if(pumped==0) {
                    glfwWaitEventsTimeout(.004);
                }
                if(w.get(0)!=oldW||h.get(0)!=oldH) {
                    oldW=w.get(0);oldH=h.get(0);
                    String report=System.getProperty("jme.stats");
                    if(report!=null) {
                        String device=json(GpuRenderer.device);
                        float fit=Math.min((float)oldW/logicalWidth,(float)oldH/logicalHeight);
                        String json="{\"renderer\":\"OpenGL GPU\",\"device\":\""+device+"\",\"preference\":\""+json(System.getProperty("jme.gpuPreference","system"))+"\",\"expected\":\""+json(expectedGpu)+"\",\"matched\":"+gpuMatched+",\"window_width\":"+oldW+",\"window_height\":"+oldH+",\"game_width\":"+Math.round(logicalWidth*fit)+",\"game_height\":"+Math.round(logicalHeight*fit)+"}";
                        Files.write(Paths.get(report+".gpu.json"),json.getBytes(StandardCharsets.UTF_8));
                    }
                }
                if(System.nanoTime()-cleaned>2000000000L){GpuRenderer.cleanup();cleaned=System.nanoTime();}
                if(!proof&&GpuRenderer.submittedFrames>=120&&System.getProperty("jme.proof")!=null) {
                    GpuRenderer.drain();
                    ImageIO.write(GpuRenderer.readback(Mobile.getPlatform().getLcdFrontbuffer()),"PNG",new File(System.getProperty("jme.proof")));
                    System.out.println("PROOF: 120 GPU frames rendered");proof=true;
                }
                if(stopSeconds>0&&System.nanoTime()-start>stopSeconds*1000000000L)break;
            }
            releaseHeldKeys();
            GpuRenderer.closing=true;
            PlayerLifecycle.stop(Mobile.midlet,500);
            GpuRenderer.shutdown();GLFW.glfwSetWindowShouldClose(window,true);
            org.lwjgl.glfw.Callbacks.glfwFreeCallbacks(window);glfwDestroyWindow(window);glfwTerminate();System.exit(gameFailure==null?0:72);
        }catch(Throwable error) {
            System.err.println("GPU player failed: "+error);error.printStackTrace();
            if(window!=0)glfwDestroyWindow(window);glfwTerminate();System.exit(71);
        }
    }
}
