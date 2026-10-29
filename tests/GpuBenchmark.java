import static org.lwjgl.glfw.GLFW.*;
import org.lwjgl.opengl.GL;
import org.recompile.mobile.GpuRenderer;
public class GpuBenchmark {
    public static void main(String[] args) throws Exception {
        if(!glfwInit())throw new IllegalStateException("GLFW init");
        glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
        long window=glfwCreateWindow(128,128,"GPU benchmark",0,0);glfwMakeContextCurrent(window);GL.createCapabilities();
        RenderBenchmark.main(args);GpuRenderer.shutdown();glfwDestroyWindow(window);glfwTerminate();
    }
}
