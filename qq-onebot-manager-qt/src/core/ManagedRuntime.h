#pragma once

#include <QObject>
#include <QString>
#include <QTimer>
#include <memory>

class QProcess;

// Owns the backend lifetime without putting the manager (or browser launches)
// into the backend Job. The only Job handle belongs to this object.
class ManagedRuntime final : public QObject {
    Q_OBJECT
public:
    explicit ManagedRuntime(QString repoRoot, QObject *parent = nullptr);
    ~ManagedRuntime() override;

    bool initialize(QString *error = nullptr);
    static void bind(QProcess *process);
    void beginTransition(int timeoutMs = 45000);
    void expectBot(qint64 pid);
    void shutdown();

signals:
    void fatal(QString reason);

private:
    struct Native;
    void fail(const QString &reason);
    void clearBot();
    void removeSessionFile();

    QString m_repoRoot;
    QString m_session;
    QString m_jobName;
    QString m_created;
    QTimer m_deadline;
    QTimer m_poll;
    std::unique_ptr<Native> m_native;
    qint64 m_botPid = 0;
    bool m_initialized = false;
    bool m_stopping = false;
    bool m_failed = false;
};
