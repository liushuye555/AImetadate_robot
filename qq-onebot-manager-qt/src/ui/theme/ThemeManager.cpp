#include "ThemeManager.h"
#include <QApplication>
#include <QFile>
#include <QSettings>

ThemeManager::Theme ThemeManager::s_current = ThemeManager::Theme::System;
ThemeManager::Theme ThemeManager::s_resolved = ThemeManager::Theme::Dark;

ThemeManager::Theme ThemeManager::resolveSystem() {
#ifdef Q_OS_WIN
    // Windows 深浅色个性化设置（与 HTML 报告页的 prefers-color-scheme 对齐）
    QSettings personalize(
        "HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        QSettings::NativeFormat);
    return personalize.value("AppsUseLightTheme", 1).toInt() == 1 ? Theme::Light : Theme::Dark;
#else
    return Theme::Dark;
#endif
}

void ThemeManager::apply(QApplication *app, Theme theme) {
    s_current = theme;
    const Theme effective = theme == Theme::System ? resolveSystem() : theme;
    s_resolved = effective;
    const QString path = effective == Theme::Dark ? ":/themes/dark.qss" : ":/themes/light.qss";
    QFile file(path);
    if (file.open(QIODevice::ReadOnly | QIODevice::Text))
        app->setStyleSheet(QString::fromUtf8(file.readAll()));
}

ThemeManager::Theme ThemeManager::current() { return s_current; }
void ThemeManager::setCurrent(Theme theme) { s_current = theme; }
QString ThemeManager::themeName(Theme theme) {
    switch (theme) {
    case Theme::System: return "system";
    case Theme::Dark: return "dark";
    case Theme::Light: return "light";
    }
    return "light";
}

ThemeManager::Theme ThemeManager::fromName(const QString &name) {
    if (name == "dark") return Theme::Dark;
    if (name == "system") return Theme::System;
    return Theme::Light;
}

ThemeManager::Theme ThemeManager::loadStored() { return fromName(
    QSettings("qq-onebot-manager", "panel").value("ui/theme").toString()); }

void ThemeManager::store(Theme theme) {
    QSettings("qq-onebot-manager", "panel").setValue("ui/theme", themeName(theme));
}

void ThemeManager::toggle(QApplication *app) {
    // 侧栏切换按钮：在两套具体主题间翻转（当前跟随系统时以解析结果为基准）
    const Theme next = s_resolved == Theme::Dark ? Theme::Light : Theme::Dark;
    apply(app, next);
    store(next);
}
