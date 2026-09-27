# Common mobile-robot models for the showroom simulation.
# Stage angles are expressed in degrees in world files.

define showroom_lidar ranger
(
  sensor
  (
    pose [ 0 0 0 0 ]
    size [ 0.08 0.08 0.06 ]
    range [ 0.05 12.0 ]
    fov 270.0
    samples 540
    noise [ 0.01 0.002 0.05 ]
    color_rgba [ 0.10 0.45 1.00 0.18 ]
  )

  model
  (
    size [ 0.08 0.08 0.06 ]
    color "RoyalBlue"
  )
)

define showroom_diff_base position
(
  drive "diff"
  localization "odom"
  odom_error [ 0.01 0.01 0.00 0.02 ]

  obstacle_return 1
  ranger_return 0.50
  blob_return 1
  fiducial_return 1

  velocity_bounds [ -0.85 0.85 0 0 0 0 -90.0 90.0 ]
  acceleration_bounds [ -0.60 0.60 0 0 0 0 -120.0 120.0 ]

  gui_nose 1
  mass 24.0
)

define guide_robot showroom_diff_base
(
  size [ 0.62 0.48 0.38 ]
  origin [ -0.04 0 0 0 ]
  color "DodgerBlue"

  block
  (
    points 8
    point[0] [ -0.31 -0.18 ]
    point[1] [ -0.24 -0.24 ]
    point[2] [  0.22 -0.24 ]
    point[3] [  0.31 -0.15 ]
    point[4] [  0.31  0.15 ]
    point[5] [  0.22  0.24 ]
    point[6] [ -0.24  0.24 ]
    point[7] [ -0.31  0.18 ]
    z [ 0.00 0.38 ]
  )

  showroom_lidar( pose [ 0.18 0 0.38 0 ] )

  model
  (
    pose [ -0.08 0 0.43 0 ]
    size [ 0.24 0.24 0.10 ]
    color "DeepSkyBlue"
    obstacle_return 0
    ranger_return -1
  )
)

define coffee_robot showroom_diff_base
(
  size [ 0.68 0.52 0.42 ]
  origin [ -0.03 0 0 0 ]
  color "LimeGreen"
  mass 30.0

  block
  (
    points 8
    point[0] [ -0.34 -0.19 ]
    point[1] [ -0.26 -0.26 ]
    point[2] [  0.26 -0.26 ]
    point[3] [  0.34 -0.18 ]
    point[4] [  0.34  0.18 ]
    point[5] [  0.26  0.26 ]
    point[6] [ -0.26  0.26 ]
    point[7] [ -0.34  0.19 ]
    z [ 0.00 0.42 ]
  )

  showroom_lidar( pose [ 0.20 0 0.42 0 ] )

  model
  (
    pose [ -0.06 0 0.52 0 ]
    size [ 0.46 0.38 0.06 ]
    color "ForestGreen"
    obstacle_return 0
    ranger_return -1
  )
)
