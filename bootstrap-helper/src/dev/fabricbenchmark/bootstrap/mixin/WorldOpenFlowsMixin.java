package dev.fabricbenchmark.bootstrap.mixin;

import dev.fabricbenchmark.bootstrap.BootstrapGuard;

import com.mojang.serialization.Dynamic;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.SharedConstants;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.worldselection.EditWorldScreen;
import net.minecraft.client.gui.screens.worldselection.WorldOpenFlows;
import net.minecraft.world.level.storage.LevelResource;
import net.minecraft.world.level.storage.LevelStorageSource.LevelStorageAccess;
import net.minecraft.world.level.storage.LevelSummary;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(WorldOpenFlows.class)
public abstract class WorldOpenFlowsMixin {
    @Unique private LevelStorageAccess labAccess;
    @Unique private boolean labSummarySafe;
    @Unique private String labWorldName;

    @Inject(method = "openWorldCheckVersionCompatibility", at = @At("HEAD"), require = 1)
    private void labRememberSummary(LevelStorageAccess access, LevelSummary summary, Dynamic<?> data,
                                    Runnable onCancel, CallbackInfo info) {
        labAccess = access; labWorldName = summary.getLevelName();
        labSummarySafe = SharedConstants.getCurrentVersion().name().equals("26.1.2") &&
            SharedConstants.getCurrentVersion().stable() &&
            BootstrapGuard.savedVersionAllowed(summary.levelVersion().minecraftVersionName(),
                                               summary.levelVersion().minecraftVersion().version()) &&
            summary.backupStatus() == LevelSummary.BackupStatus.NONE &&
            summary.isCompatible() && !summary.isDowngrade() && !summary.requiresManualConversion();
    }

    @Inject(method = "askForBackup", at = @At("HEAD"), cancellable = true, require = 1)
    private void labAcknowledgeExperimental(LevelStorageAccess access, boolean customized,
                                           Runnable onProceed, Runnable onCancel, CallbackInfo info) {
        // This method's false branch is exactly backupQuestion.experimental in 26.1.2.
        // Version, corruption, customized, disk-space and login screens have no bypass hook.
        if (customized || access != labAccess || !labSummarySafe) return;
        try {
            var loader = FabricLoader.getInstance();
            var jar = loader.getModContainer("fabric_benchmark_bootstrap").orElseThrow().getOrigin().getPaths().getFirst();
            String nonce = BootstrapGuard.acknowledge(loader.getGameDir(), access.getLevelPath(LevelResource.ROOT),
                                                     jar, labSummarySafe, labWorldName);
            // The same vanilla false-backup continuation used by "I know what I'm doing".
            EditWorldScreen.conditionallyMakeBackupAndShowToast(false, access)
                .thenAcceptAsync(result -> onProceed.run(), Minecraft.getInstance());
            info.cancel();
            System.out.println("[FabricBenchmarkBootstrap] acknowledged experimental prompt; nonce=" + nonce);
        } catch (Exception error) {
            System.out.println("[FabricBenchmarkBootstrap] left prompt untouched: " + error.getClass().getSimpleName());
        }
    }
}
