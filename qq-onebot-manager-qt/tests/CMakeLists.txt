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
    ../src/core/AvatarCache.cpp
    ../src/ui/pages/RelayPage.cpp
    ../src/ui/pages/ChatPage.cpp
    ../src/ui/widgets/GroupItemRow.cpp
    ../src/ui/Strings.cpp
)
target_include_directories(tst_pages PRIVATE ../src)
target_link_libraries(tst_pages PRIVATE Qt6::Test Qt6::Widgets Qt6::Network ole32 shell32)
add_test(NAME tst_pages COMMAND tst_pages)

# Keep standalone test executables runnable from Qt Creator/File Explorer.
# Qt Creator does not always add the Qt bin directory to the launched process PATH.
if (WIN32)
    function(copy_qt_runtime target)
        foreach(module Core Gui Widgets Network Svg Test)
            add_custom_command(TARGET ${target} POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "$<TARGET_FILE:Qt6::${module}>"
                    "$<TARGET_FILE_DIR:${target}>"
                VERBATIM
            )
        endforeach()
        get_filename_component(MINGW_BIN_DIR "${CMAKE_CXX_COMPILER}" DIRECTORY)
        foreach(runtime_dll libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll)
            if (EXISTS "${MINGW_BIN_DIR}/${runtime_dll}")
                add_custom_command(TARGET ${target} POST_BUILD
                    COMMAND ${CMAKE_COMMAND} -E copy_if_different
                        "${MINGW_BIN_DIR}/${runtime_dll}"
                        "$<TARGET_FILE_DIR:${target}>"
                    VERBATIM
                )
            endif()
        endforeach()
    endfunction()

    foreach(test_target tst_statusmonitor tst_configbridge tst_settingspage tst_configfetch tst_pages)
        copy_qt_runtime(${test_target})
    endforeach()
endif()
