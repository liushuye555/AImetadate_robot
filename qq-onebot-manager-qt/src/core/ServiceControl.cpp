#include "ServiceControl.h"
#include "Paths.h"
#include <QProcessEnvironment>

ServiceControl::ServiceControl(QObject *parent) : QObject(parent) {
    connect(&m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        emit finished(code == 0, QString::fromUtf8(m_proc.readAllStandardOutput()));
    });
    connect(&m_proc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            emit finished(false, QStringLiteral("无法启动本地服务，请检查运行环境后重试。"));
    });
}

void ServiceControl::run(const QStringList &args) {
    if (m_proc.state() != QProcess::NotRunning) return;
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONUTF8", "1");
    m_proc.setProcessEnvironment(env);
    m_proc.start();
}
