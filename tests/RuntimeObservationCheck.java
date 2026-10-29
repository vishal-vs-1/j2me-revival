import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import javax.imageio.ImageIO;
import org.recompile.mobile.Enhancement;
import org.recompile.mobile.PlatformImage;
import org.recompile.mobile.RuntimeAssets;

/** Verifies stable offscreen snapshots, screen exclusion, and bounded RGB admission. */
public final class RuntimeObservationCheck {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory(Paths.get(args[0]), "runtime-observation-");
        System.setProperty("java.awt.headless", "true");
        System.setProperty("jme.pack", root.toString());
        System.setProperty("jme.scale", "1");

        PlatformImage offscreen = new PlatformImage(3, 2, 0xff102030);
        PlatformImage screen = new PlatformImage(3, 2, 0xff000000);
        RuntimeAssets.markScreen(screen);
        int[] rgb = {0x00112233, 0x00445566, 0x00778899, 0x00aabbcc};

        offscreen.setPixel(1, 0, 0xffeeddcc);
        screen.setPixel(0, 0, 0xffabcdef);
        int[] expectedOffscreen = offscreen.getCanvas().getRGB(0, 0, 3, 2, null, 0, 3);
        for (int frame = 0; frame < 4; frame++) {
            RuntimeAssets.usedAsSource(offscreen);
            RuntimeAssets.usedAsSource(screen);
            RuntimeAssets.rawRgbUsed(rgb, 2, -2, 2, 2, false);
            RuntimeAssets.endFrame();
        }
        check(RuntimeAssets.awaitIdle(10000L), "snapshot writer did not drain");
        check(RuntimeAssets.lastFailure() == null, "snapshot writer failed: " + RuntimeAssets.lastFailure());

        Path originals = root.resolve("original-assets");
        Path events = root.resolve(".runtime").resolve("events");
        int eventCount = 0;
        int mutableEvents = 0;
        int rgbEvents = 0;
        try (java.util.stream.Stream<Path> stream = Files.list(events)) {
            for (Path path : (Iterable<Path>)stream::iterator) {
                String json = new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
                eventCount++;
                if (json.contains("\"origin\":\"MUTABLE_SNAPSHOT\"")) mutableEvents++;
                if (json.contains("\"origin\":\"RGB\"")) rgbEvents++;
            }
        }
        check(eventCount == 2, "expected one stable offscreen and one RGB source, got " + eventCount);
        check(mutableEvents == 1, "mutable offscreen was not captured after stabilizing");
        check(rgbEvents == 1, "stable raw RGB block was not admitted exactly once");
        try (java.util.stream.Stream<Path> files = Files.list(originals)) {
            check(files.count() == 2L, "screen buffer or repeated RGB frame was captured");
        }
        check(java.util.Arrays.equals(expectedOffscreen,
                offscreen.getCanvas().getRGB(0, 0, 3, 2, null, 0, 3)),
                "observation changed native offscreen pixels");

        BufferedImage expectedRgb = new BufferedImage(2, 2, BufferedImage.TYPE_INT_ARGB);
        expectedRgb.setRGB(0, 0, 2, 2, new int[] {
                0xff778899, 0xffaabbcc, 0xff112233, 0xff445566
        }, 0, 2);
        String rawId = Enhancement.hash(expectedRgb);
        BufferedImage savedRgb = ImageIO.read(originals.resolve(rawId + ".png").toFile());
        check(savedRgb != null && savedRgb.getRGB(0, 0) == 0xff778899,
                "negative scan length or processAlpha=false was not normalized correctly");

        RuntimeAssets.close();
        System.out.println("PASS: stable mutable snapshots, SCREEN exclusion, bounded raw RGB admission, scan direction and opaque alpha");
    }
}
