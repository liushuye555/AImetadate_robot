#include "ThemeManager.h"
#include <QApplication>
#include <QFile>

ThemeManager::Theme ThemeManager::s_current = ThemeManager::Theme::Light;

void ThemeManager::apply(QApplication *app, Theme theme) {
    s_current = theme;
    const QString path = theme == Theme::Dark ? ":/themes/dark.qss" : ":/themes/light.qss";
    QFile file(path);
    if (file.open(QIODevice::ReadOnly | QIODevice::Text))
        app->setStyleSheet(QString::fromUtf8(file.readAll()));
}

ThemeManager::Theme ThemeManager::current() { return s_current; }
void ThemeManager::setCurrent(Theme theme) { s_current = theme; }
QString ThemeManager::themeName(Theme theme) { return theme == Theme::Dark ? "dark" : "light"; }
