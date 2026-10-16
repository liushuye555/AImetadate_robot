#include "ManagedRuntime.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QProcess>
#include <QSaveFile>
#include <QUuid>
#include <QVariant>
#include <utility>

#ifdef Q_OS_WIN
#include <qt_windows.h>
#include <algorithm>
#include <vector>
#endif

namespace {
QPointer<ManagedRuntime> activeRuntime;

#ifdef Q_OS_WIN
QString windowsError(const QString &operation, DWORD code = GetLastError())
{
    return QStringLiteral("%1 (Windows error %2)").arg(operation).arg(code);
}

// The modifier is stored by QProcess. Keeping this holder in its capture keeps
// both STARTUPINFOEX and all referenced attribute values alive through the
// actual CreateProcess call, which occurs after the modifier returns.
struct StartupAttributes {
    STARTUPINFOEXW info{};
    std::vector<unsigned char> storage;
    std::vector<HANDLE> inheritedHandles;
    HANDLE job = nullptr;
    bool initialized = false;

    ~StartupAttributes() { reset(); }
    void reset()
    {
        if (initialized)
            DeleteProcThreadAttributeList(info.lpAttributeList);
        initialized = false;
        info = {};
        storage.clear();
        inheritedHandles.clear();
        job = nullptr;
    }

    bool prepare(const STARTUPINFOW &original, HANDLE ownedJob, QString *error)
    {
        reset();
        info.StartupInfo = original;
        info.StartupInfo.cb = sizeof(info);
        job = ownedJob;

        // Qt's own extended startup attributes may contain its pipe handle list.
        // Reconstruct that list because the opaque attribute list cannot be
        // extended safely in place. Never inherit the owner Job handle.
        if (original.dwFlags & STARTF_USESTDHANDLES) {
            const HANDLE handles[] = {original.hStdInput, original.hStdOutput,
                                      original.hStdError};
            for (HANDLE handle : handles) {
                if (!handle || handle == INVALID_HANDLE_VALUE)
                    continue;
                DWORD flags = 0;
                if (!GetHandleInformation(handle, &flags)) {
                    *error = windowsError(QStringLiteral("Cannot inspect child pipe handle"));
                    return false;
                }
                if (handle != job && (flags & HANDLE_FLAG_INHERIT)
                    && std::find(inheritedHandles.begin(), inheritedHandles.end(), handle)
                           == inheritedHandles.end())
                    inheritedHandles.push_back(handle);
            }
        }

        const DWORD count = inheritedHandles.empty() ? 1 : 2;
        SIZE_T bytes = 0;
        InitializeProcThreadAttributeList(nullptr, count, 0, &bytes);
        if (!bytes) {
            *error = windowsError(QStringLiteral("Cannot size child process attributes"));
            return false;
        }
        storage.resize(bytes);
        info.lpAttributeList = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        if (!InitializeProcThreadAttributeList(info.lpAttributeList, count, 0, &bytes)) {
            *error = windowsError(QStringLiteral("Cannot initialize child process attributes"));
            return false;
        }
        initialized = true;
        if (!UpdateProcThreadAttribute(info.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST,
                                       &job, sizeof(job), nullptr, nullptr)) {
            *error = windowsError(QStringLiteral("Cannot bind child to manager Job at creation"));
            return false;
        }
        if (!inheritedHandles.empty()
            && !UpdateProcThreadAttribute(info.lpAttributeList, 0,
                                          PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                          inheritedHandles.data(),
                                          inheritedHandles.size() * sizeof(HANDLE),
                                          nullptr, nullptr)) {
            *error = windowsError(QStringLiteral("Cannot preserve child pipe handles"));
            return false;
        }
        return true;
    }
};
#endif
}

struct ManagedRuntime::Native {
#ifdef Q_OS_WIN
    HANDLE job = nullptr;
    HANDLE bot = nullptr;
#endif
};

ManagedRuntime::ManagedRuntime(QString repoRoot, QObject *parent)
    : QObject(parent), m_repoRoot(std::move(repoRoot)), m_native(std::make_unique<Native>())
{
    m_deadline.setSingleShot(true);
    m_poll.setInterval(300);
    connect(&m_deadline, &QTimer::timeout, this, [this] {
        fail(QStringLiteral("后端未在限定时间内启动，已停止本次管理会话。"));
    });
    connect(&m_poll, &QTimer::timeout, this, [this] {
#ifdef Q_OS_WIN
        if (!m_native->bot || m_stopping)
            return;
        const DWORD state = WaitForSingleObject(m_native->bot, 0);
        if (state == WAIT_OBJECT_0)
            fail(QStringLiteral("后端进程已退出，已停止本次管理会话。"));
        else if (state == WAIT_FAILED)
            fail(windowsError(QStringLiteral("Cannot monitor backend process")));
#endif
    });
}

ManagedRuntime::~ManagedRuntime()
{
    shutdown();
}

bool ManagedRuntime::initialize(QString *error)
{
    if (m_initialized)
        return true;
    if (m_stopping || m_failed) {
        if (error) *error = QStringLiteral("Manager runtime has already stopped");
        return false;
    }
    if (activeRuntime && activeRuntime != this) {
        if (error) *error = QStringLiteral("Another manager runtime already owns this process");
        return false;
    }
#ifdef Q_OS_WIN
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) {
        if (error) *error = windowsError(QStringLiteral("Cannot identify manager process"));
        return false;
    }
    const quint64 creationToken = (quint64(created.dwHighDateTime) << 32) | created.dwLowDateTime;
    m_created = QString::number(creationToken);
    m_session = QUuid::createUuid().toString(QUuid::WithoutBraces);
    m_jobName = QStringLiteral("Local\\QQOneBotManager-%1").arg(m_session);
    const std::wstring jobName = m_jobName.toStdWString();
    m_native->job = CreateJobObjectW(nullptr, jobName.c_str());
    const DWORD creationError = GetLastError();
    if (!m_native->job) {
        if (error) *error = windowsError(QStringLiteral("Cannot create manager Job"), creationError);
        return false;
    }
    if (creationError == ERROR_ALREADY_EXISTS) {
        CloseHandle(m_native->job);
        m_native->job = nullptr;
        if (error) *error = QStringLiteral("Manager Job name is already in use");
        return false;
    }
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                                            | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
    if (!SetHandleInformation(m_native->job, HANDLE_FLAG_INHERIT, 0)
        || !SetInformationJobObject(m_native->job, JobObjectExtendedLimitInformation,
                                    &limits, sizeof(limits))) {
        const QString reason = windowsError(QStringLiteral("Cannot configure manager Job"));
        CloseHandle(m_native->job);
        m_native->job = nullptr;
        if (error) *error = reason;
        return false;
    }

    if (!QDir(m_repoRoot).mkpath(QStringLiteral("run"))) {
        if (error) *error = QStringLiteral("Cannot create manager session directory");
        CloseHandle(m_native->job);
        m_native->job = nullptr;
        return false;
    }
    const QString pid = QString::number(GetCurrentProcessId());
    QJsonObject session{{QStringLiteral("pid"), qint64(GetCurrentProcessId())},
                        {QStringLiteral("created"), m_created},
                        {QStringLiteral("session"), m_session},
                        {QStringLiteral("job"), m_jobName}};
    QSaveFile file(QDir(m_repoRoot).filePath(QStringLiteral("run/manager-session.json")));
    const QByteArray document = QJsonDocument(session).toJson(QJsonDocument::Compact);
    if (!file.open(QIODevice::WriteOnly) || file.write(document) != document.size()
        || !file.commit()) {
        if (error) *error = QStringLiteral("Cannot publish manager session: %1").arg(file.errorString());
        CloseHandle(m_native->job);
        m_native->job = nullptr;
        return false;
    }
    qputenv("QQ_ONEBOT_MANAGER_PID", pid.toUtf8());
    qputenv("QQ_ONEBOT_MANAGER_CREATED", m_created.toUtf8());
    qputenv("QQ_ONEBOT_MANAGER_SESSION", m_session.toUtf8());
    qputenv("QQ_ONEBOT_MANAGER_JOB", m_jobName.toUtf8());
    m_initialized = true;
    activeRuntime = this;
    return true;
#else
    if (error) *error = QStringLiteral("Managed backend runtime requires Windows");
    return false;
#endif
}

void ManagedRuntime::bind(QProcess *process)
{
    if (!process || !activeRuntime || !activeRuntime->m_initialized)
        return;
#ifdef Q_OS_WIN
    const QPointer<ManagedRuntime> owner = activeRuntime;
    if (process->property("qqOnebotManagedRuntimeSession").toString() == owner->m_session)
        return;
    process->setProperty("qqOnebotManagedRuntimeSession", owner->m_session);
    const auto priorModifier = process->createProcessArgumentsModifier();
    auto attributes = std::make_shared<StartupAttributes>();
    process->setCreateProcessArgumentsModifier(
        [owner, priorModifier, attributes](QProcess::CreateProcessArguments *args) {
            if (priorModifier)
                priorModifier(args);
            QString reason;
            bool prepared = owner && owner->m_initialized && !owner->m_stopping
                            && owner->m_native->job && args->startupInfo;
            if (prepared)
                prepared = attributes->prepare(*args->startupInfo, owner->m_native->job, &reason);
            if (!prepared) {
                if (reason.isEmpty())
                    reason = QStringLiteral("Manager runtime is unavailable; backend launch refused");
                // Windows has no QProcess failChildProcessModifier equivalent.
                // An explicitly empty application name guarantees CreateProcess
                // fails, preventing any unmanaged fallback or suspended orphan.
                args->applicationName = L"";
                args->arguments = nullptr;
                if (owner) {
                    QMetaObject::invokeMethod(owner, [owner, reason] {
                        if (owner) owner->fail(reason);
                    }, Qt::QueuedConnection);
                }
                return;
            }
            args->flags |= EXTENDED_STARTUPINFO_PRESENT;
            args->inheritHandles = !attributes->inheritedHandles.empty();
            args->startupInfo = &attributes->info.StartupInfo;
        });
#endif
}

void ManagedRuntime::beginTransition(int timeoutMs)
{
    if (!m_initialized || m_stopping || m_failed)
        return;
    clearBot();
    m_deadline.start(qMax(1, timeoutMs));
}

void ManagedRuntime::expectBot(qint64 pid)
{
    if (!m_initialized || m_stopping || m_failed)
        return;
    if (pid <= 0 || quint64(pid) > 0xffffffffULL) {
        fail(QStringLiteral("后端进程标识无效，已停止本次管理会话。"));
        return;
    }
    if (m_botPid == pid)
        return;
#ifdef Q_OS_WIN
    HANDLE bot = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                             FALSE, DWORD(pid));
    if (!bot) {
        fail(windowsError(QStringLiteral("Cannot open backend process")));
        return;
    }
    BOOL inJob = FALSE;
    if (!IsProcessInJob(bot, m_native->job, &inJob) || !inJob) {
        const QString reason = QStringLiteral("Backend process is not owned by this manager session");
        CloseHandle(bot);
        fail(reason);
        return;
    }
    clearBot();
    m_native->bot = bot;
    m_botPid = pid;
    m_deadline.stop();
    if (WaitForSingleObject(bot, 0) != WAIT_TIMEOUT) {
        fail(QStringLiteral("后端进程已退出，已停止本次管理会话。"));
        return;
    }
    m_poll.start();
#endif
}

void ManagedRuntime::clearBot()
{
    m_poll.stop();
    m_botPid = 0;
#ifdef Q_OS_WIN
    if (m_native->bot) {
        CloseHandle(m_native->bot);
        m_native->bot = nullptr;
    }
#endif
}

void ManagedRuntime::removeSessionFile()
{
    if (m_session.isEmpty())
        return;
    QFile file(QDir(m_repoRoot).filePath(QStringLiteral("run/manager-session.json")));
    if (file.open(QIODevice::ReadOnly)) {
        const QJsonObject current = QJsonDocument::fromJson(file.readAll()).object();
        file.close();
        if (current.value(QStringLiteral("session")).toString() == m_session)
            file.remove();
    }
}

void ManagedRuntime::shutdown()
{
    if (m_stopping)
        return;
    m_stopping = true;
    m_deadline.stop();
    clearBot();
    m_initialized = false;
    if (activeRuntime == this)
        activeRuntime.clear();
#ifdef Q_OS_WIN
    if (m_native->job) {
        // Terminate explicitly as well as closing the sole owner handle. This
        // also covers a privileged diagnostic tool temporarily opening the Job.
        TerminateJobObject(m_native->job, 1);
        CloseHandle(m_native->job);
        m_native->job = nullptr;
    }
#endif
    removeSessionFile();
    if (!m_session.isEmpty() && qgetenv("QQ_ONEBOT_MANAGER_SESSION") == m_session.toUtf8()) {
        qunsetenv("QQ_ONEBOT_MANAGER_PID");
        qunsetenv("QQ_ONEBOT_MANAGER_CREATED");
        qunsetenv("QQ_ONEBOT_MANAGER_SESSION");
        qunsetenv("QQ_ONEBOT_MANAGER_JOB");
    }
}

void ManagedRuntime::fail(const QString &reason)
{
    if (m_failed || m_stopping)
        return;
    m_failed = true;
    QDir(m_repoRoot).mkpath(QStringLiteral("logs"));
    QFile log(QDir(m_repoRoot).filePath(QStringLiteral("logs/manager-runtime.log")));
    if (log.open(QIODevice::WriteOnly | QIODevice::Append)) {
        log.write((QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)
                   + QStringLiteral(" ") + reason + QLatin1Char('\n')).toUtf8());
    }
    shutdown();
    emit fatal(reason);
}
