#include <QtTest>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QSaveFile>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTimer>
#include <cstdio>

#include "core/ManagedRuntime.h"

#ifdef Q_OS_WIN
#include <qt_windows.h>

namespace {
QString creationToken(HANDLE process)
{
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(process, &created, &exited, &kernel, &user))
        return {};
    return QString::number((quint64(created.dwHighDateTime) << 32) | created.dwLowDateTime);
}

QJsonObject readObject(const QString &path)
{
    QFile file(path);
    return file.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(file.readAll()).object()
                                         : QJsonObject{};
}

bool writeObject(const QString &path, const QJsonObject &object)
{
    QSaveFile file(path);
    const QByteArray bytes = QJsonDocument(object).toJson(QJsonDocument::Compact);
    return file.open(QIODevice::WriteOnly) && file.write(bytes) == bytes.size() && file.commit();
}

// This wrapper owns an exact process HANDLE, so even assertion-failure cleanup
// cannot accidentally terminate a different process after Windows reuses a PID.
class ExactProcess {
public:
    ExactProcess() = default;
    ExactProcess(const ExactProcess &) = delete;
    ExactProcess &operator=(const ExactProcess &) = delete;
    ~ExactProcess()
    {
        if (handle) {
            if (WaitForSingleObject(handle, 0) == WAIT_TIMEOUT) {
                TerminateProcess(handle, 99);
                WaitForSingleObject(handle, 5000);
            }
            CloseHandle(handle);
        }
    }
    bool open(qint64 pid, const QString &expected = {})
    {
        if (pid <= 0 || quint64(pid) > 0xffffffffULL)
            return false;
        HANDLE candidate = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
                                       | PROCESS_TERMINATE, FALSE, DWORD(pid));
        if (!candidate)
            return false;
        if (!expected.isEmpty() && creationToken(candidate) != expected) {
            CloseHandle(candidate);
            return false;
        }
        handle = candidate;
        return true;
    }
    bool alive() const { return handle && WaitForSingleObject(handle, 0) == WAIT_TIMEOUT; }
    bool dead() const { return handle && WaitForSingleObject(handle, 0) == WAIT_OBJECT_0; }
    HANDLE handle = nullptr;
};

bool belongsToJob(HANDLE process, const QString &jobName)
{
    HANDLE job = OpenJobObjectW(JOB_OBJECT_QUERY, FALSE, jobName.toStdWString().c_str());
    if (!job)
        return false;
    BOOL member = FALSE;
    const bool result = IsProcessInJob(process, job, &member) && member;
    CloseHandle(job); // Never keep the Job alive while testing owner termination.
    return result;
}

QString jobName(const QString &root)
{
    return readObject(QDir(root).filePath("run/manager-session.json")).value("job").toString();
}

void startBound(QProcess &process, const QStringList &arguments = {"--dummy-leaf"})
{
    ManagedRuntime::bind(&process);
    process.start(QCoreApplication::applicationFilePath(), arguments);
}

// A fixture owner lives in a separate OS process. kill() below bypasses its
// destructors and proves KILL_ON_JOB_CLOSE works without graceful Qt cleanup.
class OwnerFixture {
public:
    OwnerFixture() : ready(QDir(root.path()).filePath("dummy-ready.json")) {}
    ~OwnerFixture()
    {
        if (owner.state() != QProcess::NotRunning) {
            owner.kill();
            owner.waitForFinished(5000);
        }
        // Also runs after an early QVERIFY return: the deliberately detached
        // dummy must never outlive this test, even if a later assertion fails.
        const QJsonObject record = readObject(ready);
        if (!escaped.handle && record.contains("escapedPid"))
            escaped.open(record.value("escapedPid").toInteger(), record.value("escapedCreated").toString());
    }
    bool start(bool breakaway = false)
    {
        if (!root.isValid())
            return false;
        owner.start(QCoreApplication::applicationFilePath(),
                    {"--owner-fixture", root.path(), ready, breakaway ? "breakaway" : "ordinary"});
        if (!owner.waitForStarted(5000))
            return false;
        QElapsedTimer timer;
        timer.start();
        while (timer.elapsed() < 7000) {
            const QJsonObject record = readObject(ready);
            if (record.contains("leafPid")) {
                if (!child.open(record.value("treePid").toInteger(), record.value("treeCreated").toString())
                    || !grandchild.open(record.value("leafPid").toInteger(), record.value("leafCreated").toString()))
                    return false;
                return !breakaway || escaped.open(record.value("escapedPid").toInteger(),
                                                   record.value("escapedCreated").toString());
            }
            if (owner.state() == QProcess::NotRunning)
                return false;
            QTest::qWait(10);
        }
        return false;
    }
    QTemporaryDir root;
    QString ready;
    QProcess owner;
    ExactProcess child;
    ExactProcess grandchild;
    ExactProcess escaped;
};

int dummyLeaf(QCoreApplication &app)
{
    std::fputs("dummy-stdout\n", stdout);
    std::fflush(stdout);
    std::fputs("dummy-stderr\n", stderr);
    std::fflush(stderr);
    QTimer::singleShot(30000, &app, &QCoreApplication::quit); // Emergency lifetime bound.
    return app.exec();
}

int dummyTree(QCoreApplication &app, const QStringList &args)
{
    if (args.size() != 4)
        return 20;
    QProcess leaf;
    leaf.start(QCoreApplication::applicationFilePath(), {"--dummy-leaf"});
    if (!leaf.waitForStarted(5000))
        return 21;
    ExactProcess leafIdentity;
    if (!leafIdentity.open(leaf.processId()))
        return 22;
    QJsonObject record{{"treePid", qint64(GetCurrentProcessId())},
                       {"treeCreated", creationToken(GetCurrentProcess())},
                       {"leafPid", leaf.processId()},
                       {"leafCreated", creationToken(leafIdentity.handle)}};
    PROCESS_INFORMATION escaped{};
    if (args.at(3) == "breakaway") {
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        std::wstring command = QString("\"%1\" --dummy-leaf")
                                   .arg(QCoreApplication::applicationFilePath()).toStdWString();
        if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE,
                            CREATE_BREAKAWAY_FROM_JOB | CREATE_SUSPENDED | CREATE_NO_WINDOW,
                            nullptr, nullptr, &startup, &escaped)) {
            std::fprintf(stderr, "Breakaway dummy creation failed: %lu\n", GetLastError());
            return 23;
        }
        record.insert("escapedPid", qint64(escaped.dwProcessId));
        record.insert("escapedCreated", creationToken(escaped.hProcess));
    }
    const bool written = writeObject(args.at(2), record);
    if (escaped.hProcess) {
        if (written)
            ResumeThread(escaped.hThread);
        else {
            TerminateProcess(escaped.hProcess, 24);
            WaitForSingleObject(escaped.hProcess, 5000);
        }
        CloseHandle(escaped.hThread);
        CloseHandle(escaped.hProcess);
    }
    if (!written)
        return 24;
    return dummyLeaf(app);
}

int ownerFixture(QCoreApplication &app, const QStringList &args)
{
    if (args.size() != 5)
        return 30;
    ManagedRuntime runtime(args.at(2));
    QString error;
    if (!runtime.initialize(&error)) {
        std::fprintf(stderr, "%s\n", qPrintable(error));
        return 31;
    }
    QProcess tree;
    tree.setProcessChannelMode(QProcess::ForwardedChannels);
    QObject::connect(&tree, &QProcess::finished, &app, [&app](int code, QProcess::ExitStatus) {
        app.exit(code ? code : 33);
    });
    startBound(tree, {"--dummy-tree", args.at(3), args.at(4)});
    if (!tree.waitForStarted(5000))
        return 32;
    QTimer::singleShot(30000, &app, &QCoreApplication::quit);
    return app.exec();
}
}
#endif

class TestManagedRuntime : public QObject {
    Q_OBJECT
private slots:
    void boundPipesAndSpecificJob();
    void shutdownTerminatesTree();
    void forcedOwnerExitTerminatesTree();
    void explicitBreakawaySurvivesOwnerExit();
    void unexpectedBotExitIsFatal();
    void controlledTransitionAllowsReplacement();
    void transitionTimeoutFailsClosed();
};

void TestManagedRuntime::boundPipesAndSpecificJob()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    QProcess process;
    startBound(process);
    QVERIFY2(process.waitForStarted(5000), qPrintable(process.errorString()));
    ExactProcess child;
    QVERIFY(child.open(process.processId()));
    const QString name = jobName(root.path());
    QVERIFY(!name.isEmpty());
    QVERIFY(belongsToJob(child.handle, name));
    QVERIFY(!belongsToJob(GetCurrentProcess(), name));
    QByteArray out, err;
    QTRY_VERIFY_WITH_TIMEOUT(([&] {
        out += process.readAllStandardOutput();
        err += process.readAllStandardError();
        return out.contains("dummy-stdout") && err.contains("dummy-stderr");
    })(), 5000);
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(child.dead(), 5000);
    QVERIFY(process.waitForFinished(5000) || process.state() == QProcess::NotRunning);
    QVERIFY(!QFile::exists(QDir(root.path()).filePath("run/manager-session.json")));
#else
    QSKIP("Windows Job test");
#endif
}

void TestManagedRuntime::shutdownTerminatesTree()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    const QString ready = QDir(root.path()).filePath("tree-ready.json");
    QProcess tree;
    startBound(tree, {"--dummy-tree", ready, "ordinary"});
    QVERIFY2(tree.waitForStarted(5000), qPrintable(tree.errorString()));
    QTRY_VERIFY_WITH_TIMEOUT(readObject(ready).contains("leafPid"), 5000);
    const QJsonObject record = readObject(ready);
    ExactProcess child, grandchild;
    QVERIFY(child.open(tree.processId(), record.value("treeCreated").toString()));
    QVERIFY(grandchild.open(record.value("leafPid").toInteger(), record.value("leafCreated").toString()));
    QVERIFY(belongsToJob(grandchild.handle, jobName(root.path())));
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(child.dead() && grandchild.dead(), 5000);
    QVERIFY(tree.waitForFinished(5000) || tree.state() == QProcess::NotRunning);
#else
    QSKIP("Windows Job test");
#endif
}

void TestManagedRuntime::forcedOwnerExitTerminatesTree()
{
#ifdef Q_OS_WIN
    OwnerFixture fixture;
    QVERIFY2(fixture.start(), fixture.owner.readAllStandardError().constData());
    QVERIFY(fixture.child.alive() && fixture.grandchild.alive());
    fixture.owner.kill();
    QVERIFY(fixture.owner.waitForFinished(5000));
    QTRY_VERIFY_WITH_TIMEOUT(fixture.child.dead() && fixture.grandchild.dead(), 5000);
#else
    QSKIP("Windows Job test");
#endif
}

void TestManagedRuntime::explicitBreakawaySurvivesOwnerExit()
{
#ifdef Q_OS_WIN
    OwnerFixture fixture;
    QVERIFY2(fixture.start(true), fixture.owner.readAllStandardError().constData());
    const QString name = jobName(fixture.root.path());
    QVERIFY(belongsToJob(fixture.child.handle, name));
    QVERIFY(!belongsToJob(fixture.escaped.handle, name));
    QVERIFY(fixture.escaped.alive());
    fixture.owner.kill();
    QVERIFY(fixture.owner.waitForFinished(5000));
    QTRY_VERIFY_WITH_TIMEOUT(fixture.child.dead() && fixture.grandchild.dead(), 5000);
    QVERIFY(fixture.escaped.alive());
    // ExactProcess closes this deliberately detached dummy by its original
    // process HANDLE on every exit path, including failed assertions.
#else
    QSKIP("Windows Job test");
#endif
}

void TestManagedRuntime::unexpectedBotExitIsFatal()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    QSignalSpy fatal(&runtime, &ManagedRuntime::fatal);
    QProcess bot, sibling;
    startBound(bot);
    startBound(sibling);
    QVERIFY(bot.waitForStarted(5000));
    QVERIFY(sibling.waitForStarted(5000));
    ExactProcess siblingIdentity;
    QVERIFY(siblingIdentity.open(sibling.processId()));
    runtime.expectBot(bot.processId());
    QCOMPARE(fatal.count(), 0);
    bot.kill();
    QVERIFY(bot.waitForFinished(5000));
    QTRY_COMPARE_WITH_TIMEOUT(fatal.count(), 1, 5000);
    QTRY_VERIFY_WITH_TIMEOUT(siblingIdentity.dead(), 5000);
    QVERIFY(!QFile::exists(QDir(root.path()).filePath("run/manager-session.json")));
    QVERIFY(sibling.waitForFinished(5000) || sibling.state() == QProcess::NotRunning);
#else
    QSKIP("Windows Job test");
#endif
}

void TestManagedRuntime::controlledTransitionAllowsReplacement()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    QSignalSpy fatal(&runtime, &ManagedRuntime::fatal);
    QProcess oldBot, replacement;
    startBound(oldBot);
    QVERIFY(oldBot.waitForStarted(5000));
    runtime.expectBot(oldBot.processId());
    runtime.beginTransition(10000);
    oldBot.kill();
    QVERIFY(oldBot.waitForFinished(5000));
    QTest::qWait(650); // More than two native bot-monitor polling intervals.
    QCOMPARE(fatal.count(), 0);
    startBound(replacement);
    QVERIFY(replacement.waitForStarted(5000));
    ExactProcess replacementIdentity;
    QVERIFY(replacementIdentity.open(replacement.processId()));
    runtime.expectBot(replacement.processId());
    QTest::qWait(650);
    QCOMPARE(fatal.count(), 0);
    QVERIFY(replacementIdentity.alive());
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(replacementIdentity.dead(), 5000);
    QVERIFY(replacement.waitForFinished(5000) || replacement.state() == QProcess::NotRunning);
#else
    QSKIP("Windows Job test");
#endif
}

void TestManagedRuntime::transitionTimeoutFailsClosed()
{
#ifdef Q_OS_WIN
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ManagedRuntime runtime(root.path());
    QString error;
    QVERIFY2(runtime.initialize(&error), qPrintable(error));
    QSignalSpy fatal(&runtime, &ManagedRuntime::fatal);
    QProcess child, queuedLaunch;
    startBound(child);
    ManagedRuntime::bind(&queuedLaunch); // Modifier must refuse use after timeout.
    QVERIFY(child.waitForStarted(5000));
    ExactProcess childIdentity;
    QVERIFY(childIdentity.open(child.processId()));
    runtime.beginTransition(30);
    QTRY_COMPARE_WITH_TIMEOUT(fatal.count(), 1, 5000);
    QTRY_VERIFY_WITH_TIMEOUT(childIdentity.dead(), 5000);
    QVERIFY(child.waitForFinished(5000) || child.state() == QProcess::NotRunning);
    queuedLaunch.start(QCoreApplication::applicationFilePath(), {"--dummy-leaf"});
    QVERIFY(!queuedLaunch.waitForStarted(3000));
    QCOMPARE(queuedLaunch.state(), QProcess::NotRunning);
    QVERIFY(!runtime.initialize(&error));
    QVERIFY(!QFile::exists(QDir(root.path()).filePath("run/manager-session.json")));
    QCOMPARE(fatal.count(), 1);
#else
    QSKIP("Windows Job test");
#endif
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
#ifdef Q_OS_WIN
    const QStringList args = app.arguments();
    if (args.size() >= 2 && args.at(1) == "--dummy-leaf")
        return dummyLeaf(app);
    if (args.size() >= 2 && args.at(1) == "--dummy-tree")
        return dummyTree(app, args);
    if (args.size() >= 2 && args.at(1) == "--owner-fixture")
        return ownerFixture(app, args);
#endif
    TestManagedRuntime test;
    return QTest::qExec(&test, argc, argv);
}

#include "tst_managedruntime.moc"
