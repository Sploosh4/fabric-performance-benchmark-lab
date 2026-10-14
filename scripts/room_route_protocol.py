"""Versioned route derived from the user's 10 October gallery/redstone screenshots."""
WORKLOAD="restworld_rooms_v1"
SCENES=(
    {"id":"mobs","points":((1.5,101.,.5),(1.5,101.,17.5),(-13.5,101.,17.5),(-13.5,101.,25.5)),
     "floors":("minecraft:smooth_quartz","minecraft:blue_concrete","minecraft:grass_block","minecraft:stripped_birch_log","minecraft:redstone_lamp"),
     "camera_target":(.5,102.,26.5),"camera_yaws":(),"camera_hold_seconds":.25},
    {"id":"paintings","points":((-47.5,101.,17.5),(-47.5,101.,25.5),(-47.5,101.,17.5)),
     "floors":("minecraft:light_gray_wool","minecraft:orange_concrete"),
     "camera_yaws":(90.,-90.),"camera_pitch":6.5,"camera_hold_seconds":1.},
    {"id":"redstone","points":((46.5,101.,-14.5),(46.5,101.,-22.5),(46.5,101.,-14.5)),
     "floors":("minecraft:yellow_concrete","minecraft:red_sandstone","minecraft:oak_planks"),
     "camera_yaws":(135.,-135.),"camera_pitch":8.5,"camera_hold_seconds":1.},
)
WEIGHTS=(1/3,1/3,1/3)
SPRINT_JUMP_DISTANCES=(3.,10.)
ROOM_POLICY={"scene_weights":list(WEIGHTS),"path_tolerance_blocks":.35,"endpoint_tolerance_blocks":.25,
             "camera_tolerance_degrees":1.,"minimum_path_samples":3,"maximum_sample_gap_blocks":4.,
             "stutter_threshold_ms":50,"minimum_measured_repeats":3,"maximum_control_drift_pct":5.,
             "warmup":"exactly-one-full-unscored-route-pass-before-each-measured-route",
             "one_percent_low_definition":"1000 / mean of slowest ceil(N*0.01) complete frame intervals (milliseconds)",
             "transition_policy":"teleport/readiness intervals and crossing frame intervals excluded; complete in-scene stalls retained"}


def walk_yaw(a,b):
    if a[1]!=b[1] or (a[0]!=b[0] and a[2]!=b[2]):raise ValueError("Expected a level cardinal leg")
    return (-90. if b[0]>a[0] else 90.) if a[0]!=b[0] else (0. if b[2]>a[2] else 180.)
