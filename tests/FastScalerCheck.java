import java.awt.image.BufferedImage;
import javax.microedition.lcdui.Image;
import org.recompile.mobile.GpuRenderer;
import org.recompile.mobile.Mobile;
import org.recompile.mobile.PlatformFont;
import org.recompile.mobile.PlatformImage;
import org.recompile.mobile.Enhancement;

/** Confirms the native Scale2x shader preserves its edge-aware quadrant rule. */
public final class FastScalerCheck {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static int[] scale2x(int[] source, int width, int height) {
        int[] result = new int[width * height * 4];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int e=source[y*width+x], b=source[Math.max(0,y-1)*width+x],
                    d=source[y*width+Math.max(0,x-1)], f=source[y*width+Math.min(width-1,x+1)],
                    h=source[Math.min(height-1,y+1)*width+x];
            int p0=e,p1=e,p2=e,p3=e;
            if(b!=h && d!=f) {
                if(d==b)p0=d;
                if(b==f)p1=f;
                if(d==h)p2=d;
                if(h==f)p3=f;
            }
            int outWidth=width*2, at=(y*2)*outWidth+x*2;
            result[at]=p0;result[at+1]=p1;result[at+outWidth]=p2;result[at+outWidth+1]=p3;
        }
        return result;
    }

    public static void main(String[] args) {
        long window = 0;
        try {
            check(org.lwjgl.glfw.GLFW.glfwInit(), "GLFW init");
            org.lwjgl.glfw.GLFW.glfwWindowHint(org.lwjgl.glfw.GLFW.GLFW_VISIBLE, org.lwjgl.glfw.GLFW.GLFW_FALSE);
            org.lwjgl.glfw.GLFW.glfwWindowHint(org.lwjgl.glfw.GLFW.GLFW_CONTEXT_VERSION_MAJOR, 3);
            org.lwjgl.glfw.GLFW.glfwWindowHint(org.lwjgl.glfw.GLFW.GLFW_CONTEXT_VERSION_MINOR, 0);
            window = org.lwjgl.glfw.GLFW.glfwCreateWindow(64, 64, "Scale2x check", 0, 0);
            check(window != 0, "GL window");
            org.lwjgl.glfw.GLFW.glfwMakeContextCurrent(window);
            org.lwjgl.opengl.GL.createCapabilities();
            check(GpuRenderer.warmupFastScaler(), "GPU scaler shader warmup");
            PlatformFont.setScreenSize(64, 64);
            Mobile.maskIndex = 0;

            int red = 0xffff0000, blue = 0xff0000ff, black = 0xff000000, white = 0xffffffff;
            int[] pixels = {white, red, white, red, black, blue, white, blue, white};
            Image image = Image.createRGBImage(pixels, 3, 3, true);
            GpuRenderer.observe((PlatformImage) image);
            BufferedImage result = GpuRenderer.readback((PlatformImage) image);
            int[] expected=scale2x(pixels,3,3);
            if(Enhancement.SCALE==4)expected=scale2x(expected,6,6);
            check(result.getWidth() == 3*Enhancement.SCALE && result.getHeight() == 3*Enhancement.SCALE,
                    "scaled dimensions");
            for(int y=0;y<result.getHeight();y++)for(int x=0;x<result.getWidth();x++)
                check(result.getRGB(x,y)==expected[y*result.getWidth()+x],
                        "Scale2x output mismatch at "+x+","+y+" scale="+Enhancement.SCALE+
                        " got="+Integer.toHexString(result.getRGB(x,y))+" expected="+
                        Integer.toHexString(expected[y*result.getWidth()+x]));
            check(GpuRenderer.fastScalerPasses() == (Enhancement.SCALE==4?2:1),
                    "native image bypassed one of its GPU scale passes");
            check(((PlatformImage) image).getCanvas().getRGB(1, 1) == black, "the native logical image was modified");
            System.out.println("PASS: native pixels use "+Enhancement.SCALE+"x deterministic GPU Scale2x; logical image is unchanged; last CPU submission "+
                    String.format(java.util.Locale.ROOT,"%.3f ms",GpuRenderer.fastScalerSubmitNanos()/1e6));
        } finally {
            GpuRenderer.shutdown();
            if (window != 0) org.lwjgl.glfw.GLFW.glfwDestroyWindow(window);
            org.lwjgl.glfw.GLFW.glfwTerminate();
        }
    }
}
