#include <QApplication>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QTemporaryDir>
#include <QTimer>
#include <QtTest>
#include "ui/WindowActivation.h"
#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

class TestWindowActivation : public QObject {
    Q_OBJECT
private slots:
    void hiddenAndMinimizedWindowRestores() {
        QWidget window;
        window.show();
        window.hide();
        showAndActivateWindow(&window);
        QVERIFY(window.isVisible());
        window.showMinimized();
        showAndActivateWindow(&window);
        QVERIFY(window.isVisible());
        QVERIFY(!window.isMinimized());
    }
    void nativeHiddenWindowRestoresDespiteQtVisibility() {
#ifdef Q_OS_WIN
        if (QGuiApplication::platformName() != "windows") QSKIP("Requires the Windows platform plugin");
        QWidget window;
        window.show();
        const HWND handle = reinterpret_cast<HWND>(window.winId());
        ShowWindow(handle, SW_HIDE);
        QVERIFY(window.isVisible());
        QVERIFY(!IsWindowVisible(handle));
        showAndActivateWindow(&window);
        QVERIFY(IsWindowVisible(handle));
#else
        QSKIP("Windows native visibility regression");
#endif
    }
    void hiddenStartupShowsNativeWindow() {
#ifdef Q_OS_WIN
        QTemporaryDir dir;
        QVERIFY(dir.isValid());
        const QString resultPath = dir.filePath("result.json");
        QProcess child;
        child.setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *args) {
            args->startupInfo->dwFlags |= STARTF_USESHOWWINDOW;
            args->startupInfo->wShowWindow = SW_HIDE;
            args->flags |= CREATE_NO_WINDOW;
        });
        child.start(QCoreApplication::applicationFilePath(), {"-platform", "windows", "--hidden-startup-fixture", resultPath});
        QVERIFY(child.waitForStarted(5000));
        QVERIFY(child.waitForFinished(10000));
        QCOMPARE(child.exitCode(), 0);
        QFile result(resultPath);
        QVERIFY(result.open(QIODevice::ReadOnly));
        const auto state = QJsonDocument::fromJson(result.readAll()).object();
        QVERIFY(state.value("qtVisible").toBool());
        QVERIFY(state.value("nativeVisible").toBool());
#else
        QSKIP("Windows startup regression");
#endif
    }
};

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    const auto args = app.arguments();
    const int fixture = args.indexOf("--hidden-startup-fixture");
    if (fixture >= 0 && fixture + 1 < args.size()) {
        QWidget window;
        window.resize(320, 180);
        showAndActivateWindow(&window);
        QTimer::singleShot(100, &app, [&] {
            bool nativeVisible = window.isVisible();
#ifdef Q_OS_WIN
            nativeVisible = IsWindowVisible(reinterpret_cast<HWND>(window.winId()));
#endif
            QFile file(args.at(fixture + 1));
            if (!file.open(QIODevice::WriteOnly)) { app.exit(2); return; }
            file.write(QJsonDocument(QJsonObject{{"qtVisible",window.isVisible()},{"nativeVisible",nativeVisible}}).toJson());
            file.close();
            app.quit();
        });
        return app.exec();
    }
    TestWindowActivation test;
    return QTest::qExec(&test, argc, argv);
}
#include "tst_windowactivation.moc"
