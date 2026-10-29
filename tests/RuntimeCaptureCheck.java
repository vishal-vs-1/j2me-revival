import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import javax.imageio.ImageIO;
import org.recompile.mobile.Enhancement;
import org.recompile.mobile.PlatformImage;
import org.recompile.mobile.RuntimeAssets;

/** Synthetic decoder check: generic RGB, encoded and resource images are captured unchanged. */
public final class RuntimeCaptureCheck {
    private static byte[] png(int width, int height, int seed) throws Exception {
        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
            image.setRGB(x, y, 0xff000000 | ((seed + x * 51) & 255) << 16 |
                    ((seed + y * 37) & 255) << 8 | ((seed + x + y) & 255));
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        if (!ImageIO.write(image, "PNG", bytes)) throw new AssertionError("PNG encoder unavailable");
        return bytes.toByteArray();
    }

    private static int[] pixels(PlatformImage image) {
        return image.getCanvas().getRGB(0, 0, image.getWidth(), image.getHeight(), null, 0, image.getWidth());
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory(Paths.get(args[0]), "runtime-capture-");
        System.setProperty("java.awt.headless", "true");
        System.setProperty("jme.pack", root.toString());
        System.setProperty("jme.scale", "1");

        byte[] resourceBytes = png(3, 2, 13);
        byte[] encodedBytes = png(4, 2, 87);
        int[] rgb = new int[] {0xff123456, 0xffabcdef, 0x00112233, 0xff987654, 0xff334455, 0xff667788};
        PlatformImage resource = new PlatformImage(new ByteArrayInputStream(resourceBytes));
        PlatformImage encoded = new PlatformImage(encodedBytes, 0, encodedBytes.length, false);
        PlatformImage rgbImage = new PlatformImage(rgb, 3, 2, true);
        int[] resourceBefore = pixels(resource);
        int[] encodedBefore = pixels(encoded);
        int[] rgbBefore = pixels(rgbImage);

        Enhancement.surface(resource);
        Enhancement.surface(encoded);
        Enhancement.surface(rgbImage);
        check(RuntimeAssets.awaitIdle(10000L), "capture writer did not drain");
        check(RuntimeAssets.lastFailure() == null, "capture writer failed: " + RuntimeAssets.lastFailure());

        Path originals = root.resolve("original-assets");
        Path events = root.resolve(".runtime").resolve("events");
        check(Files.isDirectory(originals), "original-assets was not created");
        check(Files.isDirectory(events), "capture events were not created");
        List<String> origins = new ArrayList<String>();
        int eventCount = 0;
        try (java.util.stream.Stream<Path> stream = Files.list(events)) {
            for (Path event : (Iterable<Path>) stream::iterator) {
                String json = new String(Files.readAllBytes(event), StandardCharsets.UTF_8);
                int start = json.indexOf("\"origin\":\"") + 10;
                int end = json.indexOf('"', start);
                origins.add(json.substring(start, end));
                eventCount++;
            }
        }
        check(eventCount == 3, "expected one event per decoder route, got " + eventCount);
        check(origins.contains("RESOURCE"), "resource decoding was not classified");
        check(origins.contains("ENCODED"), "encoded decoding was not classified");
        check(origins.contains("RGB"), "RGB decoding was not classified");
        check(java.util.Arrays.equals(resourceBefore, pixels(resource)), "resource pixels changed during capture");
        check(java.util.Arrays.equals(encodedBefore, pixels(encoded)), "encoded pixels changed during capture");
        check(java.util.Arrays.equals(rgbBefore, pixels(rgbImage)), "RGB pixels changed during capture");
        try (java.util.stream.Stream<Path> files = Files.list(originals)) {
            check(files.count() == 3L, "expected three content-addressed PNG source images");
        }
        RuntimeAssets.close();
        System.out.println("PASS: generic resource, encoded and RGB images were captured asynchronously without changing native pixels");
    }
}
