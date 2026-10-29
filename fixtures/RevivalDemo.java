import javax.microedition.midlet.MIDlet;
import javax.microedition.lcdui.Display;
import javax.microedition.lcdui.Graphics;
import javax.microedition.lcdui.Image;
import javax.microedition.lcdui.game.GameCanvas;
import javax.microedition.lcdui.game.Sprite;
import javax.microedition.rms.RecordStore;

public class RevivalDemo extends MIDlet {
    private Track track;
    public void startApp() {
        if (track == null) { track = new Track(); Display.getDisplay(this).setCurrent(track); new Thread(track).start(); }
    }
    public void pauseApp() {}
    public void destroyApp(boolean unconditional) { if (track != null) track.running = false; }

    private static class Track extends GameCanvas implements Runnable {
        volatile boolean running = true;
        Image car, background;
        int x = 110, distance = 0, best = 0;
        Track() {
            super(false); setFullScreenMode(true);
            try { car = Image.createImage("/car.png"); background = Image.createImage("/track.png"); }
            catch (Exception e) { throw new RuntimeException(e.toString()); }
            try {
                RecordStore rs = RecordStore.openRecordStore("revival-demo", true);
                if (rs.getNumRecords() > 0) { byte[] b=rs.getRecord(1); best=((b[0]&255)<<8)|(b[1]&255); }
                rs.closeRecordStore();
            } catch (Exception ignored) {}
        }
        public void run() {
            Graphics g = getGraphics();
            while (running) {
                int keys = getKeyStates();
                if ((keys & LEFT_PRESSED) != 0) x -= 4;
                if ((keys & RIGHT_PRESSED) != 0) x += 4;
                x = Math.max(40, Math.min(getWidth()-64, x));
                int w = getWidth(), h = getHeight();
                g.setColor(0x101b2b); g.fillRect(0,0,w,h);
                // Repeated source images exercise high-resolution offscreen drawing and clipping.
                for(int yy=0; yy<h; yy+=80) for(int xx=32; xx<w-32; xx+=80) g.drawImage(background,xx,yy,0);
                g.setColor(0xe0d699);
                for(int yy=distance%40-40; yy<h; yy+=40) g.fillRect(w/2-2,yy,4,20);
                g.drawImage(car,x,h-90,0);
                g.drawRegion(car,0,0,24,40,Sprite.TRANS_ROT180,w/2-12,(distance*2)%(h+80)-60,0);
                g.setColor(0x122235); g.fillRect(0,0,w,50);
                g.setColor(0x8de6cf); g.drawString("JAR REVIVAL",w/2,5,Graphics.HCENTER|Graphics.TOP);
                g.setColor(0xffffff); g.drawString("Arrows: steer  |  " + distance,8,27,Graphics.LEFT|Graphics.TOP);
                if(distance%150==0) {
                    try {
                        RecordStore rs=RecordStore.openRecordStore("revival-demo",true);
                        byte[] data={(byte)(distance>>8),(byte)distance};
                        if(rs.getNumRecords()==0) rs.addRecord(data,0,2); else rs.setRecord(1,data,0,2);
                        rs.closeRecordStore();
                    } catch(Exception ignored) {}
                }
                distance++; flushGraphics();
                try { Thread.sleep(33); } catch(InterruptedException ignored) {}
            }
        }
    }
}
