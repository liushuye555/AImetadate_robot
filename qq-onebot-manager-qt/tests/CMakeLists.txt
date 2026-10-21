find_package(Qt6 REQUIRED COMPONENTS Test)
add_executable(tst_statusmonitor
    tst_statusmonitor.cpp
    ../src/core/StatusMonitor.cpp
)
target_include_directories(tst_statusmonitor PRIVATE ../src)
target_link_libraries(tst_statusmonitor PRIVATE manager_runtime Qt6::Test Qt6::Core)
add_test(NAME tst_statusmonitor COMMAND tst_statusmonitor)

add_executable(tst_configbridge
    tst_configbridge.cpp
    ../src/core/ConfigBridge.cpp
)
target_include_directories(tst_configbridge PRIVATE ../src)
target_link_libraries(tst_configbridge PRIVATE manager_runtime Qt6::Test Qt6::Core)
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
target_link_libraries(tst_configfetch PRIVATE manager_runtime Qt6::Test Qt6::Core)
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
target_link_libraries(tst_pages PRIVATE manager_runtime Qt6::Test Qt6::Widgets Qt6::Network ole32 shell32)
add_test(NAME tst_pages COMMAND tst_pages)

add_executable(tst_themeappearance
    tst_themeappearance.cpp
    ../src/app/SingleInstance.cpp
    ../src/ui/MainWindow.cpp
    ../src/ui/theme/ThemeManager.cpp
    ../src/ui/widgets/StatusCard.cpp
    ../src/ui/pages/OverviewPage.cpp
    ../src/ui/pages/SettingsPage.cpp
    ../src/core/AvatarCache.cpp
    ../src/core/AutoStart.cpp
    ../src/ui/Strings.cpp
    ../resources/resources.qrc
)
target_include_directories(tst_themeappearance PRIVATE ../src)
target_link_libraries(tst_themeappearance PRIVATE Qt6::Test Qt6::Widgets Qt6::Network Qt6::Svg ole32 shell32)
add_test(NAME tst_themeappearance COMMAND tst_themeappearance)
if(WIN32)
    # Fresh build directories also need the ICO plugin and real Windows fonts
    # when these appearance checks run with the offscreen platform.
    set_tests_properties(tst_themeappearance PROPERTIES
        ENVIRONMENT "QT_PLUGIN_PATH=$<TARGET_FILE_DIR:Qt6::Core>/../plugins;QT_QPA_FONTDIR=$ENV{SystemRoot}/Fonts"
        TIMEOUT 90)
endif()

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

    foreach(test_target tst_statusmonitor tst_configbridge tst_settingspage tst_configfetch tst_pages tst_themeappearance)
        copy_qt_runtime(${test_target})
    endforeach()
endif()

add_executable(tst_reportsnavigation
    tst_reportsnavigation.cpp
    ../src/ui/pages/ReportsPage.cpp
    ../src/ui/Strings.cpp
)
target_include_directories(tst_reportsnavigation PRIVATE ../src)
target_link_libraries(tst_reportsnavigation PRIVATE Qt6::Test Qt6::Widgets)
add_test(NAME tst_reportsnavigation COMMAND tst_reportsnavigation -platform offscreen)
set_tests_properties(tst_reportsnavigation PROPERTIES
    ENVIRONMENT "QT_QPA_PLATFORM_PLUGIN_PATH=$<TARGET_FILE_DIR:Qt6::Core>/../plugins/platforms"
    TIMEOUT 30
)
if (WIN32)
    copy_qt_runtime(tst_reportsnavigation)
endif()

add_executable(tst_knowledgegroups
    tst_knowledgegroups.cpp
    ../src/ui/pages/CollectionPage.cpp
    ../src/ui/widgets/GroupItemRow.cpp
    ../src/core/AvatarCache.h
    ../src/ui/Strings.cpp
)
target_include_directories(tst_knowledgegroups PRIVATE ../src)
target_link_libraries(tst_knowledgegroups PRIVATE Qt6::Test Qt6::Widgets Qt6::Network)
add_test(NAME tst_knowledgegroups COMMAND tst_knowledgegroups -platform offscreen)
set_tests_properties(tst_knowledgegroups PROPERTIES
    ENVIRONMENT "QT_QPA_PLATFORM_PLUGIN_PATH=$<TARGET_FILE_DIR:Qt6::Core>/../plugins/platforms"
    TIMEOUT 30
)
if (WIN32)
    foreach(module Core Gui Widgets Network Test)
        add_custom_command(TARGET tst_knowledgegroups POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "$<TARGET_FILE:Qt6::${module}>" "$<TARGET_FILE_DIR:tst_knowledgegroups>"
            VERBATIM)
    endforeach()
    get_filename_component(KNOWLEDGE_MINGW_BIN "${CMAKE_CXX_COMPILER}" DIRECTORY)
    foreach(runtime_dll libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll)
        if (EXISTS "${KNOWLEDGE_MINGW_BIN}/${runtime_dll}")
            add_custom_command(TARGET tst_knowledgegroups POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                    "${KNOWLEDGE_MINGW_BIN}/${runtime_dll}" "$<TARGET_FILE_DIR:tst_knowledgegroups>"
                VERBATIM)
        endif()
    endforeach()
endif()

add_executable(tst_managedruntime tst_managedruntime.cpp)
target_link_libraries(tst_managedruntime PRIVATE manager_runtime Qt6::Test)
add_test(NAME tst_managedruntime COMMAND tst_managedruntime)
set_tests_properties(tst_managedruntime PROPERTIES TIMEOUT 90)
if(WIN32)
    copy_qt_runtime(tst_managedruntime)
endif()

add_executable(tst_singleinstance tst_singleinstance.cpp ../src/app/SingleInstance.cpp)
target_include_directories(tst_singleinstance PRIVATE ../src)
target_link_libraries(tst_singleinstance PRIVATE Qt6::Test Qt6::Network)
add_test(NAME tst_singleinstance COMMAND tst_singleinstance)
set_tests_properties(tst_singleinstance PROPERTIES TIMEOUT 30)
if(WIN32)
    copy_qt_runtime(tst_singleinstance)
endif()

add_executable(tst_windowactivation tst_windowactivation.cpp)
target_include_directories(tst_windowactivation PRIVATE ../src)
target_link_libraries(tst_windowactivation PRIVATE Qt6::Test Qt6::Widgets)
add_test(NAME tst_windowactivation COMMAND tst_windowactivation -platform offscreen)
set_tests_properties(tst_windowactivation PROPERTIES TIMEOUT 30)
if(WIN32)
    copy_qt_runtime(tst_windowactivation)
endif()

add_executable(tst_servicecontrol
    tst_servicecontrol.cpp
    ../src/core/ServiceControl.cpp
)
target_include_directories(tst_servicecontrol PRIVATE ../src)
target_link_libraries(tst_servicecontrol PRIVATE manager_runtime Qt6::Test Qt6::Core)
add_test(NAME tst_servicecontrol COMMAND tst_servicecontrol)
set_tests_properties(tst_servicecontrol PROPERTIES TIMEOUT 60)
if(WIN32)
    copy_qt_runtime(tst_servicecontrol)
endif()

add_executable(tst_hiddencommand tst_hiddencommand.cpp)
target_link_libraries(tst_hiddencommand PRIVATE manager_runtime Qt6::Test)
add_test(NAME tst_hiddencommand COMMAND tst_hiddencommand)
set_tests_properties(tst_hiddencommand PROPERTIES TIMEOUT 30)
if(WIN32)
    copy_qt_runtime(tst_hiddencommand)
endif()
