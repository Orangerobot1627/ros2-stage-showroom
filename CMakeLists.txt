cmake_minimum_required(VERSION 3.8)
project(demo_stage)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config docs launch map world
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS
    scripts/showroom_asr.py
    scripts/showroom_business_logic.py
    scripts/showroom_llm_bridge.py
    scripts/showroom_monitor.py
    scripts/showroom_navigation_gateway.py
    scripts/showroom_nav2_adapter.py
    scripts/showroom_task_manager.py
    scripts/showroom_tts.py
    scripts/waypoint_follower.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  FILES
    scripts/showroom_llm_contract.py
    scripts/showroom_llm_core.py
    scripts/showroom_llm_prompt.py
    scripts/showroom_navigation.py
    scripts/showroom_nav2_health.py
    scripts/showroom_local_planner.py
    scripts/showroom_ollama_client.py
    scripts/showroom_plan.py
    scripts/showroom_action_policy.py
    scripts/showroom_task_units.py
    scripts/showroom_voice_core.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  PROGRAMS tools/showroom_session.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME showroom_session
)

if(BUILD_TESTING)
  find_package(ament_cmake_test REQUIRED)
  find_package(ament_lint_auto REQUIRED)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)

  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()

  ament_add_test(
    showroom_asset_validation
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/validate_project.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_business_logic
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_business_logic.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_monitor_logic
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_monitor_logic.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_llm_bridge_logic
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_llm_bridge_logic.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_action_policy
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_action_policy.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_voice_core
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_voice_core.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_task_units
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_task_units.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_multi_step_plan
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_plan.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_navigation
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_navigation.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_local_planner
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_local_planner.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )

  ament_add_test(
    showroom_nav2_health
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/test_nav2_health.py
    GENERATE_RESULT_FOR_RETURN_CODE_ZERO
    TIMEOUT 30
  )
endif()

ament_package()
