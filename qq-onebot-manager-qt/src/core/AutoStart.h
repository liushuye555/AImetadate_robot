#pragma once
#include <QString>

class AutoStart {
public:
    static QString startupLinkPath();
    static bool isEnabled();
    static bool setEnabled(bool enabled);
};
