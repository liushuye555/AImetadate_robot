#include "ServiceControl.h"
#include "Paths.h"
#include "ManagedRuntime.h"
#include <QProcessEnvironment>

ServiceControl::ServiceControl(QObject *parent) : QObject(parent) {
    ManagedRuntime::bind(&m_proc);
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

void ServiceControl::reconcileFinished() {
    if (m_proc.state() != QProcess::NotRunning)
        m_proc.waitForFinished(0); // Drain native completion without extending the deadline.
}

void ServiceControl::run(const QStringList &args) {
    if (m_proc.state() != QProcess::NotRunning) return;
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONUTF8", "1");
    m_proc.setProcessEnvironment(env);
    m_elapsed.start();
    m_proc.start();
}
