#pragma once
#include <QWidget>
#include <QGuiApplication>
#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

inline void showAndActivateWindow(QWidget *window) {
    if (window->isMinimized()) window->showNormal();
    else window->show();
#ifdef Q_OS_WIN
    if (QGuiApplication::platformName() == QStringLiteral("windows")) {
        // A launcher can set SW_HIDE while Qt still considers this widget shown.
        // Reconcile the native state before requesting focus; show() alone is a no-op.
        ShowWindow(reinterpret_cast<HWND>(window->winId()), SW_SHOW);
    }
#endif
    window->raise();
    window->activateWindow();
}
