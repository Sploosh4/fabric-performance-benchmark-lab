import com.google.gson.JsonObject;
import dev.fabricbenchmark.bootstrap.BootstrapGuard;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.UUID;

/** Tiny owned fixtures only: no Minecraft process or real world. */
public class BootstrapGuardFixtures {
    public static void main(String[] args) throws Exception {
        Path temp = Files.createTempDirectory("lab-bootstrap-fixture-");
        try {
            Path profile = temp.resolve("profile"), world = profile.resolve("saves/Lab_fixture");
            Path result = profile.resolve("minescript/lab-results");
            Files.createDirectories(result); Files.createDirectories(world.resolve("datapacks"));
            Path conditions = profile.resolve("minescript/lab-conditions.json"); Files.writeString(conditions,"fixture");
            Files.writeString(world.resolve("level.dat"),"fixture-world");
            Files.writeString(world.resolve("datapacks/pack.zip"),"fixture-pack");
            Path master = temp.resolve("master.zip"), jar = temp.resolve("helper.jar");
            Files.writeString(master,"immutable-master"); Files.writeString(jar,"fixture-helper");
            JsonObject grant = new JsonObject();
            grant.addProperty("schema","fabric-lab-launch-authorization-v1");grant.addProperty("status","armed");
            grant.addProperty("minecraft","26.1.2");grant.addProperty("profile",profile.toString());
            grant.addProperty("world_folder","Lab_fixture");
            var names=new com.google.gson.JsonArray();names.add("RestWorld_26.1");grant.add("world_names",names);
            grant.addProperty("master_archive",master.toString());grant.addProperty("master_sha256",BootstrapGuard.sha(master));
            grant.addProperty("helper_sha256",BootstrapGuard.sha(jar));grant.addProperty("level_dat_sha256",BootstrapGuard.sha(world.resolve("level.dat")));
            grant.addProperty("conditions_sha256",BootstrapGuard.sha(conditions));
            JsonObject packs=new JsonObject();packs.addProperty("pack.zip",BootstrapGuard.sha(world.resolve("datapacks/pack.zip")));grant.add("datapack_files",packs);
            Path ticket=result.resolve("bootstrap-launch-authorization.json");
            if (!BootstrapGuard.savedVersionAllowed("26.1",4786) || !BootstrapGuard.savedVersionAllowed("26.1.2",4790) ||
                BootstrapGuard.savedVersionAllowed("26.1",4790) || BootstrapGuard.savedVersionAllowed("26.1.2",4786) ||
                BootstrapGuard.savedVersionAllowed("26.2",4800))throw new AssertionError("Restored-master version allowlist differs");
            int checks=5;
            for (String scenario : new String[]{"valid","replay","summary","name","expired","status","version","master","helper","level","conditions","pack"}) {
                JsonObject test=grant.deepCopy();long now=Instant.now().toEpochMilli();
                test.addProperty("created_unix_ms",now);test.addProperty("expires_unix_ms",now+300000);
                test.addProperty("nonce",UUID.randomUUID().toString().replace("-",""));
                if(scenario.equals("expired")){test.addProperty("created_unix_ms",now-400000);test.addProperty("expires_unix_ms",now-100000);}
                if(scenario.equals("status"))test.addProperty("status","unknown");
                if(scenario.equals("version"))test.addProperty("minecraft","26.2");
                String key=switch(scenario){case "master"->"master_sha256";case "helper"->"helper_sha256";case "level"->"level_dat_sha256";case "conditions"->"conditions_sha256";default->null;};
                if(key!=null)test.addProperty(key,"a".repeat(64));
                if(scenario.equals("pack"))test.getAsJsonObject("datapack_files").addProperty("pack.zip","a".repeat(64));
                Files.writeString(ticket,test.toString());
                boolean safe=!scenario.equals("summary");String name=scenario.equals("name")?"Unrelated world":"RestWorld_26.1";
                if(scenario.equals("replay"))BootstrapGuard.acknowledge(profile,world,jar,true,name);
                boolean accepted=false;
                try { BootstrapGuard.acknowledge(profile,world,jar,safe,name);accepted=true; }
                catch(Exception denied) { if(scenario.equals("valid"))throw denied; }
                if(accepted!=scenario.equals("valid"))throw new AssertionError("Unexpected acceptance: "+scenario);
                checks++;
            }
            if(!Files.readString(master).equals("immutable-master") || !Files.readString(world.resolve("datapacks/pack.zip")).equals("fixture-pack"))throw new AssertionError("Protected content changed");
            System.out.println("PASS: "+checks+" bootstrap authorization/failure fixtures; master/datapack unchanged");
        } finally {
            if(!temp.getFileName().toString().startsWith("lab-bootstrap-fixture-"))throw new AssertionError("Fixture cleanup boundary");
            try(var files=Files.walk(temp)){for(Path path:files.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}
        }
    }
}
