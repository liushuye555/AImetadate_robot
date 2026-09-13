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
    // 上次选择的主题（QSettings 持久化；侧栏切换按钮与设置页共用）
    static Theme loadStored();
    static void store(Theme theme);
    static void toggle(QApplication *app);
private:
    static Theme s_current;
};
