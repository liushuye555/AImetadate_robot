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

add_executable(tst_settingspage
    tst_settingspage.cpp
    ../src/ui/pages/SettingsPage.cpp
    ../src/ui/Strings.cpp
    ../src/core/AutoStart.cpp
)
target_include_directories(tst_settingspage PRIVATE ../src)
target_link_libraries(tst_settingspage PRIVATE Qt6::Test Qt6::Widgets ole32 shell32)
add_test(NAME tst_settingspage COMMAND tst_settingspage)

add_executable(tst_configfetch
    tst_configfetch.cpp
    ../src/core/ConfigBridge.cpp
)
target_include_directories(tst_configfetch PRIVATE ../src)
target_link_libraries(tst_configfetch PRIVATE Qt6::Test Qt6::Core)
add_test(NAME tst_configfetch COMMAND tst_configfetch)

add_executable(tst_pages
    tst_pages.cpp
    ../src/core/ConfigBridge.cpp
    ../src/ui/pages/RelayPage.cpp
    ../src/ui/pages/ChatPage.cpp
    ../src/ui/Strings.cpp
)
target_include_directories(tst_pages PRIVATE ../src)
target_link_libraries(tst_pages PRIVATE Qt6::Test Qt6::Widgets ole32 shell32)
add_test(NAME tst_pages COMMAND tst_pages)
