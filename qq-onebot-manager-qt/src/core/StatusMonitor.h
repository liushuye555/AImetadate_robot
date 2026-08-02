#pragma once
#include <QObject>
#include <QJsonObject>
#include <QDateTime>
#include <QTimer>

struct StatusSnapshot {
    bool valid = false;
    bool napcat = false;
    bool onebot = false;
    bool bot = false;
    bool qqLoggedIn = false;
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
    StatusSnapshot snapshot() const { return m_snapshot; }
public slots:
    void refresh();
signals:
    void statusChanged(const StatusSnapshot &snapshot);
private:
    QString m_statusPath;
    QTimer m_timer;
    StatusSnapshot m_snapshot;
    int m_staleSeconds = 15;
};
