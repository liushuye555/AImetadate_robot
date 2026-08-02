#pragma once
#include <QString>

class QApplication;

class ThemeManager {
public:
    enum class Theme { Light, Dark };
    static void apply(QApplication *app, Theme theme);
    static Theme current();
    static void setCurrent(Theme theme);
    static QString themeName(Theme theme);
private:
    static Theme s_current;
};
