#pragma once
#include <QObject>
#include <QProcess>
#include <QElapsedTimer>

class ServiceControl : public QObject {
    Q_OBJECT
public:
    explicit ServiceControl(QObject *parent = nullptr);
    void run(const QStringList &args); // 如 {"-m","qq_onebot_whitelist.control","start"}
    bool isRunning() const { return m_proc.state() != QProcess::NotRunning; }
    void reconcileFinished();
signals:
    void commandStarted(qint64 pid);
    void finished(bool ok, QString output);
    void commandCompleted(int exitCode, int exitStatus, qint64 elapsedMs);
private:
    QProcess m_proc;
    QElapsedTimer m_elapsed;
};
