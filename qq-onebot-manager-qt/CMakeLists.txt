cmake_minimum_required(VERSION 3.24)
project(qq_onebot_manager_qt VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 REQUIRED COMPONENTS Widgets Network Svg Test)

add_executable(qq-onebot-manager-qt WIN32
    src/main.cpp
    src/app/SingleInstance.cpp
    src/core/ConfigBridge.cpp
    src/core/ServiceControl.cpp
    src/ui/Strings.cpp
    src/ui/MainWindow.cpp
    src/ui/theme/ThemeManager.cpp
    resources/resources.qrc
)
target_link_libraries(qq-onebot-manager-qt PRIVATE Qt6::Widgets Qt6::Network Qt6::Svg)

enable_testing()
add_subdirectory(tests)
