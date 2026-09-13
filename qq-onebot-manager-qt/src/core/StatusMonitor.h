#pragma once
#include <QObject>
#include <QJsonObject>
#include <QDateTime>
#include <QTimer>
#include <QProcess>
#include <QStringList>

struct StatusSnapshot {
    bool valid = false;
    bool napcat = false;
    bool onebot = false;
    bool bot = false;
    bool qqLoggedIn = false;
    bool collectionPaused = false;
    bool manualStop = false;
    QString qqNumber;
    QString qqNickname;
    QDateTime updatedAt;
};

StatusSnapshot parseStatusJson(const QByteArray &json, const QDateTime &now, int staleSeconds = 15);

class StatusMonitor : public QObject {
    Q_OBJECT
public:
    explicit StatusMonitor(const QString &statusPath, int pollMs = 4000, QObject *parent = nullptr);
    void setStaleSeconds(int seconds) { m_staleSeconds = seconds; }
    void setLiveProbe(const QString &program, const QStringList &args, int intervalMs = 15000);
    StatusSnapshot snapshot() const { return m_snapshot; }
public slots:
    void refresh();
private slots:
    void liveProbeFinished(int exitCode, QProcess::ExitStatus status);
signals:
    void statusChanged(const StatusSnapshot &snapshot);
private:
    void publish(const StatusSnapshot &snapshot);
    void requestLiveProbe();

    QString m_statusPath;
    QTimer m_timer;
    QProcess m_liveProbe;
    QTimer m_liveProbeTimeout;
    QString m_liveProbeProgram;
    QStringList m_liveProbeArgs;
    QDateTime m_lastProbeAt;
    StatusSnapshot m_snapshot;
    int m_staleSeconds = 15;
    int m_liveProbeIntervalMs = 15000;
    bool m_initialized = false;
};
