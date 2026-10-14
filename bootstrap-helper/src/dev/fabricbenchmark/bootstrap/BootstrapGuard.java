package dev.fabricbenchmark.bootstrap;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.DosFileAttributes;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;

/** One-use, instance/world-bound acknowledgement. Never changes world or registry data. */
public final class BootstrapGuard {
    private static final Gson JSON = new Gson();
    private BootstrapGuard() {}

    public static boolean savedVersionAllowed(String name, int dataVersion) {
        return (name.equals("26.1") && dataVersion == 4786) ||
               (name.equals("26.1.2") && dataVersion == 4790);
    }

    public static String sha(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[1048576];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    public static void plain(Path path) throws Exception {
        for (Path part = path.toAbsolutePath().normalize(); part != null; part = part.getParent()) {
            if (!Files.exists(part, LinkOption.NOFOLLOW_LINKS)) continue;
            if (Files.isSymbolicLink(part)) throw new IllegalStateException("Linked path rejected");
            if (System.getProperty("os.name").startsWith("Windows")) {
                // Windows reparse attributes are returned by the DOS provider.
                int attributes = (Integer) Files.getAttribute(part, "dos:attributes", LinkOption.NOFOLLOW_LINKS);
                if ((attributes & 1024) != 0) throw new IllegalStateException("Reparse path rejected");
            }
        }
    }

    public static String acknowledge(Path profile, Path world, Path helperJar,
                                     boolean summarySafe, String worldName) throws Exception {
        if (!summarySafe) throw new IllegalStateException("Version/conversion summary not safe");
        plain(profile); plain(world);
        profile = profile.toRealPath(); world = world.toRealPath();
        Path directory = profile.resolve("minescript/lab-results");
        Path ticket = directory.resolve("bootstrap-launch-authorization.json");
        plain(ticket);
        JsonObject grant = JSON.fromJson(Files.readString(ticket), JsonObject.class);
        if (!grant.get("schema").getAsString().equals("fabric-lab-launch-authorization-v1") ||
            !grant.get("status").getAsString().equals("armed") ||
            !grant.get("minecraft").getAsString().equals("26.1.2"))
            throw new IllegalStateException("Unknown launch authorization");
        String nonce = grant.get("nonce").getAsString();
        if (!nonce.matches("[a-f0-9]{32}")) throw new IllegalStateException("Invalid nonce");
        long now = Instant.now().toEpochMilli();
        long created = grant.get("created_unix_ms").getAsLong();
        long expires = grant.get("expires_unix_ms").getAsLong();
        if (expires - created != 300000 || now < created || now >= expires)
            throw new IllegalStateException("Launch authorization expired");
        if (!profile.equals(Path.of(grant.get("profile").getAsString()).toRealPath()) ||
            !world.equals(profile.resolve("saves").resolve(grant.get("world_folder").getAsString()).toRealPath()) ||
            !world.getParent().equals(profile.resolve("saves").toRealPath()) ||
            !world.getFileName().toString().startsWith("Lab_"))
            throw new IllegalStateException("Instance/world identity differs");
        boolean named = false;
        for (var name : grant.getAsJsonArray("world_names")) named |= name.getAsString().equals(worldName);
        if (!named) throw new IllegalStateException("World display name differs");
        Path master = Path.of(grant.get("master_archive").getAsString()); plain(master); plain(helperJar);
        if (master.toRealPath().startsWith(world)) throw new IllegalStateException("Master is inside active world");
        if (!sha(master).equals(grant.get("master_sha256").getAsString()) ||
            !sha(helperJar).equals(grant.get("helper_sha256").getAsString()) ||
            !sha(world.resolve("level.dat")).equals(grant.get("level_dat_sha256").getAsString()) ||
            !sha(profile.resolve("minescript/lab-conditions.json")).equals(grant.get("conditions_sha256").getAsString()))
            throw new IllegalStateException("Pinned launch files changed");
        JsonObject actual = new JsonObject();
        Path packs = world.resolve("datapacks"); plain(packs);
        try (var paths = Files.walk(packs)) {
            for (Path path : paths.toList()) {
                plain(path);
                if (Files.isRegularFile(path)) actual.addProperty(packs.relativize(path).toString().replace('\\','/'), sha(path));
            }
        }
        if (!actual.equals(grant.getAsJsonObject("datapack_files")))
            throw new IllegalStateException("Datapack inventory changed");
        // CREATE_NEW consumes this nonce without changing the armed ticket/world.
        JsonObject receipt = new JsonObject();
        receipt.addProperty("schema", "fabric-lab-warning-acknowledgement-v1");
        receipt.addProperty("nonce", nonce); receipt.addProperty("game_pid", ProcessHandle.current().pid());
        receipt.addProperty("world_folder", world.getFileName().toString());
        receipt.addProperty("accepted_unix_ms", now); receipt.addProperty("backup_created", false);
        receipt.addProperty("prompt", "selectWorld.backupQuestion.experimental");
        Files.writeString(directory.resolve("bootstrap-" + nonce + "-accepted.json"), JSON.toJson(receipt),
                          StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        return nonce;
    }
}
