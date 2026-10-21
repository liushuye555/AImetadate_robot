#include <QtTest>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QTimer>

#include "core/HiddenCommand.h"
#include "core/Paths.h"

class TestHiddenCommand : public QObject {
    Q_OBJECT
private slots:
    void venvConsoleInterpreterGetsNoConsole_data();
    void venvConsoleInterpreterGetsNoConsole();
    void exitCodeIsPreserved();
    void missingProgramFails();
    void timeoutEndsTheCommand();
};

void TestHiddenCommand::venvConsoleInterpreterGetsNoConsole_data()
{
    QTest::addColumn<QString>("program");
    QTest::newRow("python") << Paths::pythonExe();
    QTest::newRow("pythonw-console-redirector")
        << QFileInfo(Paths::pythonExe()).dir().filePath("pythonw.exe");
}

void TestHiddenCommand::venvConsoleInterpreterGetsNoConsole()
{
#ifdef Q_OS_WIN
    QFETCH(QString, program);
    QTemporaryDir scratch;
    QVERIFY(scratch.isValid());
    const QString result = scratch.filePath("probe.json");
    const QString script = QStringLiteral(
        "import ctypes,json,pathlib,sys;"
        "k=ctypes.WinDLL('kernel32');k.GetConsoleWindow.restype=ctypes.c_void_p;"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
        "'consoleWindow':k.GetConsoleWindow() or 0,'prefix':sys.prefix}),encoding='utf-8')");
    QCOMPARE(HiddenCommand::run(program, {"-c", script, result}, Paths::repoRoot()), 0);
    QFile file(result);
    QVERIFY(file.open(QIODevice::ReadOnly));
    const auto data = QJsonDocument::fromJson(file.readAll()).object();
    QCOMPARE(data.value("consoleWindow").toInteger(-1), qint64(0));
    QCOMPARE(QDir(data.value("prefix").toString()).canonicalPath(),
             QDir(Paths::repoRoot() + "/.venv").canonicalPath());
#else
    QSKIP("Windows console suppression test");
#endif
}

void TestHiddenCommand::exitCodeIsPreserved()
{
    QCOMPARE(HiddenCommand::run(QCoreApplication::applicationFilePath(), {"--exit17"},
                               QDir::tempPath()), 17);
}

void TestHiddenCommand::missingProgramFails()
{
    QTemporaryDir scratch;
    QCOMPARE(HiddenCommand::run(scratch.filePath("not-installed.exe"), {}, scratch.path()), 1);
}

void TestHiddenCommand::timeoutEndsTheCommand()
{
    QElapsedTimer elapsed;
    elapsed.start();
    QCOMPARE(HiddenCommand::run(QCoreApplication::applicationFilePath(), {"--sleep"},
                               QDir::tempPath(), 20), 1);
    QVERIFY(elapsed.elapsed() < 5000);
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (app.arguments().contains("--exit17")) return 17;
    if (app.arguments().contains("--sleep")) {
        QTimer::singleShot(10000, &app, &QCoreApplication::quit);
        return app.exec();
    }
    TestHiddenCommand test;
    return QTest::qExec(&test, argc, argv);
}

#include "tst_hiddencommand.moc"
