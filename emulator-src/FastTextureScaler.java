/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.image.BufferedImage;
import java.nio.ByteBuffer;
import org.lwjgl.system.MemoryUtil;
import static org.lwjgl.opengl.GL11.*;
import static org.lwjgl.opengl.GL13.*;
import static org.lwjgl.opengl.GL20.*;
import static org.lwjgl.opengl.GL30.*;

/** GPU-only, deterministic Scale2x passes for native images and transient RGB blocks. */
final class FastTextureScaler {
    private static final String VERTEX =
            "#version 120\n" +
            "varying vec2 uv;\n" +
            "void main(){ gl_Position=ftransform(); uv=gl_MultiTexCoord0.st; }\n";
    private static final String FRAGMENT =
            "#version 120\n" +
            "uniform sampler2D sourceTexture;\n" +
            "uniform vec2 sourceSize;\n" +
            "uniform vec2 outputSize;\n" +
            "uniform int flipSourceY;\n" +
            "varying vec2 uv;\n" +
            "vec4 px(vec2 p){ p=clamp(p,vec2(0.0),sourceSize-vec2(1.0)); vec2 t=(p+vec2(0.5))/sourceSize; if(flipSourceY==1)t.y=1.0-t.y; return texture2D(sourceTexture,t); }\n" +
            "bool same(vec4 a,vec4 b){ return all(equal(a,b)); }\n" +
            "void main(){\n" +
            " vec2 outPixel=floor(uv*outputSize);\n" +
            " vec2 p=floor(outPixel*0.5);\n" +
            " vec2 q=mod(outPixel,2.0);\n" +
            " vec4 e=px(p), b=px(p+vec2(0.0,-1.0)), d=px(p+vec2(-1.0,0.0));\n" +
            " vec4 f=px(p+vec2(1.0,0.0)), h=px(p+vec2(0.0,1.0));\n" +
            " vec4 result=e;\n" +
            " if(!same(b,h) && !same(d,f)){\n" +
            "  if(q.x<0.5 && q.y<0.5 && same(d,b)) result=d;\n" +
            "  else if(q.x>=0.5 && q.y<0.5 && same(b,f)) result=f;\n" +
            "  else if(q.x<0.5 && q.y>=0.5 && same(d,h)) result=d;\n" +
            "  else if(q.x>=0.5 && q.y>=0.5 && same(h,f)) result=f;\n" +
            " }\n" +
            " gl_FragColor=result;\n" +
            "}\n";

    private static int program;
    private static boolean attempted;
    private static boolean unavailable;
    private static long completedPasses;
    private static long fallbackCount;
    private static volatile long lastSubmitNanos;

    private FastTextureScaler() { }

    static boolean warmup() {
        if (Boolean.getBoolean("jme.disableFastScaler") ||
                (Enhancement.SCALE != 2 && Enhancement.SCALE != 4)) return false;
        try { return program() != 0; }
        catch (RuntimeException failure) { return false; }
    }

    static boolean scale(BufferedImage image, int targetFramebuffer, int logicalWidth,
                         int logicalHeight, int scale) {
        if (Boolean.getBoolean("jme.disableFastScaler") || (scale != 2 && scale != 4) ||
                image.getWidth() != logicalWidth || image.getHeight() != logicalHeight) return false;
        long started = System.nanoTime();
        try {
            int shader = program();
            if (shader == 0) return false;
            int sourceTexture = glGenTextures();
            int intermediateTexture = 0, intermediateFramebuffer = 0;
            try {
                bindTexture(sourceTexture, image.getWidth(), image.getHeight());
                upload(image.getRGB(0, 0, image.getWidth(), image.getHeight(), null, 0, image.getWidth()),
                        image.getWidth(), image.getHeight());
                int inputTexture = sourceTexture, inputWidth = image.getWidth(), inputHeight = image.getHeight();
                if (scale == 4) {
                    int middleWidth = logicalWidth * 2, middleHeight = logicalHeight * 2;
                    intermediateTexture = glGenTextures();
                    bindTexture(intermediateTexture, middleWidth, middleHeight);
                    intermediateFramebuffer = glGenFramebuffers();
                    glBindFramebuffer(GL_FRAMEBUFFER, intermediateFramebuffer);
                    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                            intermediateTexture, 0);
                    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
                        throw new IllegalStateException("Scale2x intermediate framebuffer is incomplete");
                    pass(shader, inputTexture, inputWidth, inputHeight, middleWidth, middleHeight,
                            intermediateFramebuffer, false);
                    inputTexture = intermediateTexture;
                    inputWidth = middleWidth;
                    inputHeight = middleHeight;
                }
                GpuRenderer.bindScalerTarget(targetFramebuffer, logicalWidth * scale, logicalHeight * scale);
                pass(shader, inputTexture, inputWidth, inputHeight,
                        logicalWidth * scale, logicalHeight * scale, targetFramebuffer, scale == 4);
                completedPasses += scale == 4 ? 2 : 1;
                return true;
            } finally {
                glUseProgram(0);
                glDeleteTextures(sourceTexture);
                if (intermediateTexture != 0) glDeleteTextures(intermediateTexture);
                if (intermediateFramebuffer != 0) glDeleteFramebuffers(intermediateFramebuffer);
                GpuRenderer.invalidateScalerBinding();
            }
        } catch (RuntimeException failure) {
            unavailable = true;
            fallbackCount++;
            System.err.println("Fast GPU scaler unavailable; using compatibility scaling: " + failure);
            return false;
        } finally {
            lastSubmitNanos = System.nanoTime() - started;
        }
    }

    private static int program() {
        if (unavailable) return 0;
        if (program != 0) return program;
        if (attempted) return 0;
        attempted = true;
        int vertex = glCreateShader(GL_VERTEX_SHADER);
        int fragment = glCreateShader(GL_FRAGMENT_SHADER);
        int linked = 0;
        try {
            glShaderSource(vertex, VERTEX); glCompileShader(vertex);
            if (glGetShaderi(vertex, GL_COMPILE_STATUS) == GL_FALSE)
                throw new IllegalStateException("Vertex shader: " + glGetShaderInfoLog(vertex));
            glShaderSource(fragment, FRAGMENT); glCompileShader(fragment);
            if (glGetShaderi(fragment, GL_COMPILE_STATUS) == GL_FALSE)
                throw new IllegalStateException("Scale2x shader: " + glGetShaderInfoLog(fragment));
            linked = glCreateProgram();
            glAttachShader(linked, vertex); glAttachShader(linked, fragment); glLinkProgram(linked);
            if (glGetProgrami(linked, GL_LINK_STATUS) == GL_FALSE)
                throw new IllegalStateException("Scale2x program: " + glGetProgramInfoLog(linked));
            program = linked;
            return program;
        } catch (RuntimeException failure) {
            unavailable = true;
            if (linked != 0) glDeleteProgram(linked);
            throw failure;
        } finally {
            glDeleteShader(vertex); glDeleteShader(fragment);
        }
    }

    private static void pass(int shader, int texture, int sourceWidth, int sourceHeight,
                             int outputWidth, int outputHeight, int targetFramebuffer, boolean flipSourceY) {
        glBindFramebuffer(GL_FRAMEBUFFER, targetFramebuffer);
        glViewport(0, 0, outputWidth, outputHeight);
        glMatrixMode(GL_PROJECTION); glLoadIdentity(); glOrtho(0, outputWidth, outputHeight, 0, -1, 1);
        glMatrixMode(GL_MODELVIEW); glLoadIdentity();
        glDisable(GL_BLEND); glDisable(GL_SCISSOR_TEST); glEnable(GL_TEXTURE_2D);
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, texture);
        glUseProgram(shader);
        glUniform1i(glGetUniformLocation(shader, "sourceTexture"), 0);
        glUniform2f(glGetUniformLocation(shader, "sourceSize"), sourceWidth, sourceHeight);
        glUniform2f(glGetUniformLocation(shader, "outputSize"), outputWidth, outputHeight);
        glUniform1i(glGetUniformLocation(shader, "flipSourceY"), flipSourceY ? 1 : 0);
        glColor4f(1, 1, 1, 1);
        glBegin(GL_QUADS);
        glTexCoord2f(0,0); glVertex2f(0,0);
        glTexCoord2f(1,0); glVertex2f(outputWidth,0);
        glTexCoord2f(1,1); glVertex2f(outputWidth,outputHeight);
        glTexCoord2f(0,1); glVertex2f(0,outputHeight);
        glEnd();
        glUseProgram(0);
    }

    private static void bindTexture(int texture, int width, int height) {
        glBindTexture(GL_TEXTURE_2D, texture);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, (ByteBuffer) null);
    }

    private static void upload(int[] pixels, int width, int height) {
        ByteBuffer buffer = MemoryUtil.memAlloc(width * height * 4);
        try {
            for (int pixel : pixels) {
                int alpha = pixel >>> 24;
                buffer.put((byte) ((((pixel >>> 16) & 255) * alpha + 127) / 255));
                buffer.put((byte) ((((pixel >>> 8) & 255) * alpha + 127) / 255));
                buffer.put((byte) (((pixel & 255) * alpha + 127) / 255));
                buffer.put((byte) alpha);
            }
            buffer.flip();
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, buffer);
        } finally { MemoryUtil.memFree(buffer); }
    }

    static long completedPasses() { return completedPasses; }
    static long fallbackCount() { return fallbackCount; }
    static long lastSubmitNanos() { return lastSubmitNanos; }
}
