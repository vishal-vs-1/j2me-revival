import org.recompile.mobile.*;
import org.lwjgl.opengl.GL;
import javax.imageio.ImageIO;
import java.io.File;
import java.lang.reflect.Field;
import java.util.*;
import static org.lwjgl.glfw.GLFW.*;
import static org.lwjgl.opengl.GL11.*;

/** Isolated, real-game GPU/input probe. Uses only normal game input; never changes game fields. */
public class GpuGameProbe {
    static int read(Class<?> type,String name)throws Exception {Field f=type.getDeclaredField(name);f.setAccessible(true);return f.getInt(null);}
    public static void main(String[] args) {
        try {
            if(!glfwInit())throw new IllegalStateException("GLFW");glfwWindowHint(GLFW_VISIBLE,Boolean.getBoolean("probe.visible")?GLFW_TRUE:GLFW_FALSE);
            glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
            long window=glfwCreateWindow(640,800,"Isolated Mr Bean GPU probe",0,0);glfwMakeContextCurrent(window);GL.createCapabilities();glfwSwapInterval(1);
            if(Boolean.getBoolean("probe.visible"))glfwFocusWindow(window);
            FramePresentationPolicy presentation=new FramePresentationPolicy();
            glfwSetWindowRefreshCallback(window,handle->presentation.requestRedraw());
            System.out.println("DEVICE: "+glGetString(GL_RENDERER));
            Enhancement.preload();
            new Thread(()->{
                try {
                    Mobile.lcdWidth=176;Mobile.lcdHeight=220;Mobile.setPlatform(new MobilePlatform(176,220),()->{});
                    MobilePlatform.fileName=new File(args[0]).toURI().toString();
                    if(!Mobile.getPlatform().load(MobilePlatform.fileName))throw new IllegalStateException("Load failed");
                    Mobile.config.settings.put("scrwidth","176");Mobile.config.settings.put("scrheight","220");Mobile.updateSettings();
                    Mobile.getPlatform().loader.start();
                }catch(Exception e){e.printStackTrace();}
            },"isolated-game").start();
            long start=System.nanoTime(),lastAction=0,releaseAt=0,raceAt=0,raceFrame=0,pressedAt=0;
            int held=0,previousState=-999,control=0,before=0,right=0,left=0;
            int pressedPosition=0;double rightResponse=-1,leftResponse=-1;
            boolean success=false,firstDisplay=true;
            while(System.nanoTime()-start<50000000000L) {
                glfwPollEvents();int pumped=GpuRenderer.pump(4000000L);
                long complete=GpuRenderer.submittedFrames;
                if(presentation.shouldPresent(complete,640,800)){
                    presentation.presenting(complete,640,800);GpuRenderer.present(640,800);glfwSwapBuffers(window);
                }else if(pumped==0)glfwWaitEventsTimeout(.004);
                long now=System.nanoTime();
                if(held!=0&&now>releaseAt){GpuPlayer.dispatchKey(held,GLFW_RELEASE);held=0;}
                if(Mobile.getDisplay()!=null&&Mobile.getDisplay().getCurrent()!=null) {
                    Object display=Mobile.getDisplay().getCurrent();String type=display.getClass().getName();int key=0;
                    if(firstDisplay){System.out.println("STARTUP first display="+type);firstDisplay=false;}
                    if(Boolean.getBoolean("probe.directStartup")&&!type.equals("p"))
                        throw new AssertionError("Cleaned startup entered a wrapper display: "+type);
                    if(type.equals("p")) {
                        Class<?> game=display.getClass();int state=read(game,"cT"),menu=read(game,"eC");
                        if(state!=previousState){System.out.println("GAME STATE "+state+" menu "+menu);previousState=state;}
                        if(state==7) {
                            if(raceAt==0){raceAt=now;raceFrame=GpuRenderer.submittedFrames;before=read(game,"di");System.out.println("RACE START x="+before);}
                            if(held!=0&&read(game,"di")!=pressedPosition) {
                                if(control==1&&rightResponse<0)rightResponse=(now-pressedAt)/1e6;
                                if(control==2&&leftResponse<0)leftResponse=(now-pressedAt)/1e6;
                            }
                            if(control==0&&now-raceAt>1000000000L) {
                                pressedAt=now;pressedPosition=read(game,"di");
                                GpuPlayer.dispatchKey(GLFW_KEY_RIGHT,GLFW_PRESS);held=GLFW_KEY_RIGHT;releaseAt=now+300000000L;control=1;
                            }else if(control==1&&held==0) {
                                right=read(game,"di");System.out.println("RIGHT x="+right+" input="+read(game,"bo"));
                                pressedAt=now;pressedPosition=right;
                                GpuPlayer.dispatchKey(GLFW_KEY_LEFT,GLFW_PRESS);held=GLFW_KEY_LEFT;releaseAt=now+300000000L;control=2;
                            }else if(control==2&&held==0) {
                                left=read(game,"di");System.out.println("LEFT x="+left+" input="+read(game,"bo"));control=3;
                            }else if(control==3&&now-raceAt>4000000000L) {
                                GpuRenderer.drain();
                                ImageIO.write(GpuRenderer.readback(Mobile.getPlatform().getLcdFrontbuffer()),"PNG",new File(args[1]));
                                double fps=(GpuRenderer.submittedFrames-raceFrame)*1e9/(now-raceAt);
                                System.out.printf(Locale.US,"RACE FPS %.2f; x before=%d right=%d left=%d%n",fps,before,right,left);
                                System.out.printf(Locale.US,"Steering first game-state response: right %.1f ms, left %.1f ms (not physical display latency)%n",rightResponse,leftResponse);
                                if(right==left)throw new AssertionError("No steering movement was observed");
                                if(rightResponse<0||leftResponse<0||rightResponse>150||leftResponse>150)throw new AssertionError("Steering response exceeded three game updates");
                                success=true;break;
                            }
                        }else if(now-lastAction>1000000000L&&held==0) {
                            if(state==4)key=read(game,"bZ")==11?GLFW_KEY_W:GLFW_KEY_ENTER;
                            else if(state==1||state==2||state==13||state==14)key=GLFW_KEY_ENTER;
                        }
                    }else if(now-lastAction>1000000000L&&held==0) {
                        if(type.equals("d"))key=GLFW_KEY_Q;
                        else key=GLFW_KEY_ENTER;
                    }
                    if(key!=0){GpuPlayer.dispatchKey(key,GLFW_PRESS);held=key;releaseAt=now+250000000L;lastAction=now;}
                }
            }
            if(!success) {
                if(Mobile.getPlatform()!=null){GpuRenderer.drain();ImageIO.write(GpuRenderer.readback(Mobile.getPlatform().getLcdFrontbuffer()),"PNG",new File(args[1]));}
                throw new AssertionError("Probe did not complete a race/steering sample");
            }
            PlayerLifecycle.stop(Mobile.midlet,500);
            System.out.println("PASS: actual Mr Bean race, held steering response, GPU composition and bounded shutdown");System.exit(0);
        }catch(Throwable e){e.printStackTrace();System.exit(1);}
    }
}
