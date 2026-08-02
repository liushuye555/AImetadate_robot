find_package(Qt6 REQUIRED COMPONENTS Test)
add_executable(tst_statusmonitor
    tst_statusmonitor.cpp
    ../src/core/StatusMonitor.cpp
)
target_include_directories(tst_statusmonitor PRIVATE ../src)
target_link_libraries(tst_statusmonitor PRIVATE Qt6::Test Qt6::Core)
add_test(NAME tst_statusmonitor COMMAND tst_statusmonitor)

add_executable(tst_configbridge
    tst_configbridge.cpp
    ../src/core/ConfigBridge.cpp
)
target_include_directories(tst_configbridge PRIVATE ../src)
target_link_libraries(tst_configbridge PRIVATE Qt6::Test Qt6::Core)
add_test(NAME tst_configbridge COMMAND tst_configbridge)
