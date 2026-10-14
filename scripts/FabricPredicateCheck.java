import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import net.fabricmc.loader.api.Version;
import net.fabricmc.loader.api.metadata.version.VersionPredicate;

/** Uses the pinned Loader's rules; does not launch Minecraft or initialize mods. */
public final class FabricPredicateCheck {
    public static void main(String[] args) throws Exception {
        var decoder = Base64.getDecoder();
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            for (String line; (line = input.readLine()) != null;) {
                String[] fields = line.split("\t", -1);
                if (fields.length == 3 && fields[0].equals("compare")) {
                    String left = new String(decoder.decode(fields[1]), StandardCharsets.UTF_8);
                    String right = new String(decoder.decode(fields[2]), StandardCharsets.UTF_8);
                    System.out.println(Integer.signum(Version.parse(left).compareTo(Version.parse(right))));
                    continue;
                }
                if (fields.length != 2) throw new IllegalArgumentException("Expected version and predicate");
                String version = new String(decoder.decode(fields[0]), StandardCharsets.UTF_8);
                String predicate = new String(decoder.decode(fields[1]), StandardCharsets.UTF_8);
                System.out.println(VersionPredicate.parse(predicate).test(Version.parse(version)));
            }
        }
    }
}
