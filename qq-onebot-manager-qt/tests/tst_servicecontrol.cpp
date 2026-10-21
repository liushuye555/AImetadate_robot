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
    runtime.shutdown();
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
    runtime.beginTransition(30);
    command.run({QStringLiteral("-c"), QStringLiteral("import time; time.sleep(30)")});
    QTRY_VERIFY_WITH_TIMEOUT(command.isRunning(), 5000);
    QTRY_COMPARE_WITH_TIMEOUT(fatal.count(), 1, 5000);
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!command.isRunning(), 5000);
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
