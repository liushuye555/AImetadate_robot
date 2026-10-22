#include "core/ManagedRuntime.h"
#include "core/ServiceControl.h"

#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QThread>
#include <QScopeGuard>

#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

class TestServiceControl final : public QObject {
    Q_OBJECT
private slots:
    void completionBeforeDeadlineDispatchIsReconciled();
    void runningCommandTimesOutAndIsCleanedUp();
    void nonzeroExitIsFailure();
    void failedToStartIsFailure();
    void breakawaySurvivesCommandAndManagerShutdown();
};

void TestServiceControl::completionBeforeDeadlineDispatchIsReconciled()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));

    ServiceControl command;
    connect(&runtime, &ManagedRuntime::startupDeadline,
            &command, &ServiceControl::reconcileFinished);
    connect(&command, &ServiceControl::commandCompleted,
            &runtime, &ManagedRuntime::startupCommandCompleted);
    connect(&command, &ServiceControl::finished, &runtime,
            [&runtime](bool ok, const QString &output) {
                if (!ok) return;
                const auto doc = QJsonDocument::fromJson(output.toUtf8());
                runtime.expectBot(doc.object().value(QStringLiteral("pid")).toInteger());
            });
    QSignalSpy finished(&command, &ServiceControl::finished);
    QSignalSpy fatal(&runtime, &ManagedRuntime::fatal);
    HANDLE nativeCommand = nullptr;
    const auto cleanup = qScopeGuard([&] {
        if (nativeCommand) CloseHandle(nativeCommand);
    });
    connect(&command, &ServiceControl::commandStarted, &runtime, [&](qint64 pid) {
        nativeCommand = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                                    FALSE, DWORD(pid));
    });

    runtime.beginTransition(30);
    command.run({QStringLiteral("-c"),
        QStringLiteral("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); print('{\"pid\":%d}'%p.pid, flush=True)")});
    QVERIFY(nativeCommand);
    // Keep Qt's event loop blocked until Python has exited natively, leaving
    // the queued QProcess completion behind the deadline check.
    QCOMPARE(WaitForSingleObject(nativeCommand, 5000), DWORD(WAIT_OBJECT_0));
    DWORD exitCode = 99;
    QVERIFY(GetExitCodeProcess(nativeCommand, &exitCode));
    QCOMPARE(exitCode, DWORD(0));
    QThread::msleep(40); // Ensure the deadline has elapsed, without Qt dispatch.
    QVERIFY(QMetaObject::invokeMethod(&runtime, "checkStartupDeadline", Qt::DirectConnection));
    QTRY_COMPARE_WITH_TIMEOUT(finished.count(), 1, 5000);
    QCOMPARE(finished.at(0).at(0).toBool(), true);
    QCOMPARE(fatal.count(), 0);
    QFile lifecycle(QDir(root.path()).filePath(QStringLiteral("logs/manager-lifecycle.jsonl")));
    QVERIFY(lifecycle.open(QIODevice::ReadOnly));
    QVERIFY(lifecycle.readAll().contains("backend_accepted"));
    const qint64 botPid = QJsonDocument::fromJson(finished.at(0).at(1).toString().toUtf8())
        .object().value("pid").toInteger();
    HANDLE bot = OpenProcess(SYNCHRONIZE, FALSE, DWORD(botPid));
    QVERIFY(bot);
    const auto closeBot = qScopeGuard([&] { CloseHandle(bot); });
    // Reusing the control channel closes its old command Job handle. A healthy
    // backend must remain alive under the manager's root Job.
    command.run({QStringLiteral("-c"), QStringLiteral("pass")});
    QTRY_COMPARE_WITH_TIMEOUT(finished.count(), 2, 5000);
    QCOMPARE(WaitForSingleObject(bot, 0), DWORD(WAIT_TIMEOUT));
    runtime.shutdown();
    QCOMPARE(WaitForSingleObject(bot, 5000), DWORD(WAIT_OBJECT_0));
#else
    QSKIP("Managed Job regression coverage requires Windows");
#endif
}

void TestServiceControl::runningCommandTimesOutAndIsCleanedUp()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    ServiceControl command;
    connect(&runtime, &ManagedRuntime::startupDeadline,
            &command, &ServiceControl::reconcileFinished);
    QSignalSpy fatal(&runtime, &ManagedRuntime::fatal);
    connect(&runtime, &ManagedRuntime::backendFault, &command, &ServiceControl::cancel);
    ServiceControl sibling;
    sibling.run({QStringLiteral("-c"), QStringLiteral("import time; time.sleep(30)")});
    QTRY_VERIFY_WITH_TIMEOUT(sibling.isRunning(), 5000);
    runtime.beginTransition(700);
    QSignalSpy fault(&runtime, &ManagedRuntime::backendFault);
    QSignalSpy finished(&command, &ServiceControl::finished);
    QTemporaryDir evidence;
    const QString childFile = QDir(evidence.path()).filePath("child.pid");
    command.run({QStringLiteral("-c"), QStringLiteral(
        "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"), childFile});
    QTRY_VERIFY_WITH_TIMEOUT(command.isRunning(), 5000);
    QTRY_VERIFY_WITH_TIMEOUT(QFile::exists(childFile), 5000);
    QFile childPid(childFile);
    QVERIFY(childPid.open(QIODevice::ReadOnly));
    HANDLE child = OpenProcess(SYNCHRONIZE, FALSE, childPid.readAll().trimmed().toUInt());
    QVERIFY(child);
    const auto cleanup = qScopeGuard([&] { CloseHandle(child); });
    QTRY_COMPARE_WITH_TIMEOUT(fault.count(), 1, 5000);
    QCOMPARE(fatal.count(), 0);
    QTRY_VERIFY_WITH_TIMEOUT(!command.isRunning(), 5000);
    QCOMPARE(WaitForSingleObject(child, 5000), DWORD(WAIT_OBJECT_0));
    QVERIFY(sibling.isRunning());
    QCOMPARE(finished.count(), 1);
    runtime.beginTransition(5000);
    command.run({QStringLiteral("-c"), QStringLiteral("print('retry-ok')")});
    QTRY_COMPARE_WITH_TIMEOUT(finished.count(), 2, 5000);
    QVERIFY(finished.at(1).at(0).toBool());
    QVERIFY(finished.at(1).at(1).toString().contains("retry-ok"));
    QVERIFY(sibling.isRunning());
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!sibling.isRunning(), 5000);
#else
    QSKIP("Managed Job regression coverage requires Windows");
#endif
}

void TestServiceControl::nonzeroExitIsFailure()
{
    ServiceControl command;
    QSignalSpy finished(&command, &ServiceControl::finished);
    command.run({QStringLiteral("-c"), QStringLiteral("raise SystemExit(17)")});
    QTRY_COMPARE_WITH_TIMEOUT(finished.count(), 1, 5000);
    QCOMPARE(finished.at(0).at(0).toBool(), false);
}

void TestServiceControl::breakawaySurvivesCommandAndManagerShutdown()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    ServiceControl command;
    const QString pidFile = QDir(root.path()).filePath("escaped.pid");
    command.run({QStringLiteral("-c"), QStringLiteral(
        "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=0x01000000|0x08000000,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"), pidFile});
    QTRY_VERIFY_WITH_TIMEOUT(QFile::exists(pidFile), 5000);
    QFile file(pidFile);
    QVERIFY(file.open(QIODevice::ReadOnly));
    HANDLE escaped = OpenProcess(SYNCHRONIZE | PROCESS_TERMINATE, FALSE,
                                 file.readAll().trimmed().toUInt());
    QVERIFY(escaped);
    const auto cleanup = qScopeGuard([&] {
        TerminateProcess(escaped, 0);
        WaitForSingleObject(escaped, 5000);
        CloseHandle(escaped);
    });
    command.cancel();
    QTRY_VERIFY_WITH_TIMEOUT(!command.isRunning(), 5000);
    QCOMPARE(WaitForSingleObject(escaped, 0), DWORD(WAIT_TIMEOUT));
    runtime.shutdown();
    QCOMPARE(WaitForSingleObject(escaped, 0), DWORD(WAIT_TIMEOUT));
#else
    QSKIP("Nested Job breakaway requires Windows");
#endif
}

void TestServiceControl::failedToStartIsFailure()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    ServiceControl command; // Captures the initialized runtime's Job binding.
    runtime.shutdown();     // Its launch modifier now refuses process creation.
    QSignalSpy finished(&command, &ServiceControl::finished);
    command.run({QStringLiteral("-c"), QStringLiteral("pass")});
    QTRY_COMPARE_WITH_TIMEOUT(finished.count(), 1, 5000);
    QCOMPARE(finished.at(0).at(0).toBool(), false);
#else
    QSKIP("Managed Job regression coverage requires Windows");
#endif
}

QTEST_GUILESS_MAIN(TestServiceControl)
#include "tst_servicecontrol.moc"
