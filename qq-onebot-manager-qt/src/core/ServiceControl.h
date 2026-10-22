#pragma once
#include <QObject>
#include <QProcess>
#include <QElapsedTimer>
#include <memory>

class ServiceControl : public QObject {
    Q_OBJECT
public:
    explicit ServiceControl(QObject *parent = nullptr);
    ~ServiceControl() override;
    void run(const QStringList &args); // 如 {"-m","qq_onebot_whitelist.control","start"}
    bool isRunning() const { return m_proc.state() != QProcess::NotRunning; }
    void reconcileFinished();
    void cancel(); // Cancel only this command and its descendants, never siblings.
signals:
    void commandStarted(qint64 pid);
    void finished(bool ok, QString output);
    void commandCompleted(int exitCode, int exitStatus, qint64 elapsedMs);
private:
    struct Native;
    std::unique_ptr<Native> m_native;
    QProcess m_proc;
    QElapsedTimer m_elapsed;
};
