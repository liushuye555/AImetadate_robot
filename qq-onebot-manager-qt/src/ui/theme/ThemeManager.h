#pragma once
#include <QString>

class QApplication;

class ThemeManager {
public:
    enum class Theme { Light, Dark, System };
    static void apply(QApplication *app, Theme theme);
    static Theme current();
    static void setCurrent(Theme theme);
    static QString themeName(Theme theme);
    static Theme fromName(const QString &name);
    // System 档实际套用的具体主题（读 Windows 个性化设置；非 Windows 回退深色）
    static Theme resolveSystem();
    // 上次选择的主题（QSettings 持久化；侧栏切换按钮与设置页共用）
    static Theme loadStored();
    static void store(Theme theme);
    static void toggle(QApplication *app);
private:
    static Theme s_current;
    static Theme s_resolved;
};
