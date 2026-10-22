#include "ServiceControl.h"
#include "Paths.h"
#include "ManagedRuntime.h"
#include <QProcessEnvironment>
#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

struct ServiceControl::Native {
#ifdef Q_OS_WIN
    HANDLE job = nullptr;
    ~Native() { if (job) CloseHandle(job); }
#endif
};

ServiceControl::ServiceControl(QObject *parent) : QObject(parent), m_native(std::make_unique<Native>()) {
    ManagedRuntime::bind(&m_proc, [this]() -> quintptr {
#ifdef Q_OS_WIN
        return reinterpret_cast<quintptr>(m_native->job);
#else
        return 0;
#endif
    });
    connect(&m_proc, &QProcess::started, this, [this] {
        emit commandStarted(m_proc.processId());
    });
    connect(&m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status) {
        emit commandCompleted(code, int(status), m_elapsed.elapsed());
        emit finished(code == 0 && status == QProcess::NormalExit,
                      QString::fromUtf8(m_proc.readAllStandardOutput()));
    });
    connect(&m_proc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            emit commandCompleted(-1, int(QProcess::CrashExit), m_elapsed.elapsed());
            emit finished(false, QStringLiteral("无法启动本地服务，请检查运行环境后重试。"));
        }
    });
}

ServiceControl::~ServiceControl() = default;

void ServiceControl::cancel() {
    if (!isRunning()) return;
#ifdef Q_OS_WIN
    if (m_native->job) {
        // All interpreter launcher layers and children were assigned at creation.
        // The root manager Job and sibling commands remain untouched.
        if (!TerminateJobObject(m_native->job, 1)) return;
    } else
#endif
        m_proc.kill();
}

void ServiceControl::reconcileFinished() {
    if (m_proc.state() != QProcess::NotRunning)
        m_proc.waitForFinished(0); // Drain native completion without extending the deadline.
}

void ServiceControl::run(const QStringList &args) {
    if (m_proc.state() != QProcess::NotRunning) return;
#ifdef Q_OS_WIN
    if (m_native->job) CloseHandle(m_native->job);
    m_native->job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    // Closing this per-command handle after normal completion must not kill a
    // successfully started backend. The manager's root Job still owns it.
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_BREAKAWAY_OK;
    if (!m_native->job || !SetHandleInformation(m_native->job, HANDLE_FLAG_INHERIT, 0)
        || !SetInformationJobObject(m_native->job, JobObjectExtendedLimitInformation,
                                    &limits, sizeof(limits))) {
        emit commandCompleted(-1, int(QProcess::CrashExit), 0);
        emit finished(false, QStringLiteral("无法建立服务命令隔离，请重试。"));
        return;
    }
#endif
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONUTF8", "1");
    m_proc.setProcessEnvironment(env);
    m_elapsed.start();
    m_proc.start();
}
