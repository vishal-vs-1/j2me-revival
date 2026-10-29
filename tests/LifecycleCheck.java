import org.recompile.mobile.PlayerLifecycle;
import javax.microedition.midlet.MIDlet;

public class LifecycleCheck {
    static class Broken extends MIDlet {
        final boolean hang;Broken(boolean hang){this.hang=hang;}
        protected void startApp(){} protected void pauseApp(){}
        protected void destroyApp(boolean unconditional) {
            if(!hang)throw new StackOverflowError("broken wrapper");
            for(;;)try{Thread.sleep(1000);}catch(Exception ignored){}
        }
    }
    public static void main(String[] args) {
        long start=System.nanoTime();
        PlayerLifecycle.stop(new Broken(false),200);
        PlayerLifecycle.stop(new Broken(true),100);
        if(System.nanoTime()-start>1500000000L)throw new AssertionError("Close was not bounded");
        System.out.println("PASS: recursive/error and hanging shutdown callbacks cannot crash or block window close");
        System.exit(0);
    }
}
