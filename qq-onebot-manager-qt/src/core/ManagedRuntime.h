#pragma once

#include <QObject>
#include <QJsonObject>
#include <QString>
#include <QTimer>
#include <memory>
#include <functional>

class QProcess;

// Owns the backend lifetime without putting the manager (or browser launches)
// into the backend Job. The only Job handle belongs to this object.
class ManagedRuntime final : public QObject {
    Q_OBJECT
public:
    explicit ManagedRuntime(QString repoRoot, QObject *parent = nullptr);
    ~ManagedRuntime() override;

    bool initialize(QString *error = nullptr);
    static void bind(QProcess *process, std::function<quintptr()> commandJob = {});
    void beginTransition(int timeoutMs = 45000);
    void expectBot(qint64 pid);
    void startupCommandStarted(qint64 pid);
    void startupCommandCompleted(int exitCode, int exitStatus, qint64 elapsedMs);
    void startupFailed();
    bool markUserStopped();
    void shutdown();

signals:
    void fatal(QString reason);
    void backendFault(QString reason);
    void backendReady();
    // Reconcile an already-finished launch command before declaring a timeout.
    void startupDeadline();

private slots:
    void checkStartupDeadline();

private:
    struct Native;
    void fail(const QString &reason);
    void reportBackendFault(const QString &reason);
    void clearBot();
    void removeSessionFile();
    void record(const QString &event, QJsonObject fields = {});

    QString m_repoRoot;
    QString m_session;
    QString m_jobName;
    QString m_created;
    QTimer m_deadline;
    QTimer m_poll;
    std::unique_ptr<Native> m_native;
    qint64 m_botPid = 0;
    quint64 m_transition = 0;
    bool m_initialized = false;
    bool m_stopping = false;
    bool m_failed = false;
};
