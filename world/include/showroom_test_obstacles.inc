# Movable objects for repeatable obstacle-stop and recovery experiments.
# The orange box starts beside the guide robot's first aisle. Select it in the
# Stage GUI and drag it onto x=0, y=-12.5 before starting a manual tour.

define showroom_test_obstacle model
(
  size [ 0.80 0.80 1.00 ]
  color "OrangeRed"

  # Keep explicit geometry across the laser plane. A short centered model can
  # collide in 2-D while sitting below the laser mounted at z=0.38 m.
  block
  (
    points 4
    point[0] [ -0.40 -0.40 ]
    point[1] [  0.40 -0.40 ]
    point[2] [  0.40  0.40 ]
    point[3] [ -0.40  0.40 ]
    z [ 0.00 1.00 ]
  )

  # Make the object visible to collision checks and the robots' laser rangers.
  obstacle_return 1
  ranger_return 1

  # Top-level models can be repositioned interactively in the Stage GUI.
  gui_move 1
  gui_nose 0
  gui_grid 0
  gui_outline 1
)

showroom_test_obstacle
(
  name "test_obstacle"
  pose [ -2.0 -12.5 0 0 ]
)
