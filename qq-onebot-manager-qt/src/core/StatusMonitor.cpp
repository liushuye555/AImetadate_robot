#include "StatusMonitor.h"
#include <QFile>

StatusSnapshot parseStatusJson(const QByteArray &json, const QDateTime &now, int staleSeconds) {
    StatusSnapshot s;
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) return s;
    const QJsonObject obj = doc.object();
    s.updatedAt = QDateTime::fromString(obj.value("updatedAt").toString(), Qt::ISODate);
    if (!s.updatedAt.isValid()) return s;
    if (s.updatedAt.secsTo(now) > staleSeconds) return s;
    s.napcat = obj.value("napcat").toBool(false);
    s.onebot = obj.value("onebot").toBool(false);
    s.bot = obj.value("bot").toBool(false);
    s.qqLoggedIn = obj.value("qqLoggedIn").toBool(false);
    s.collectionPaused = obj.value("collectionPaused").toBool(false);
    s.qqNumber = obj.value("qqNumber").toString();
    s.qqNickname = obj.value("qqNickname").toString();
    s.valid = true;
    return s;
}

StatusMonitor::StatusMonitor(const QString &statusPath, int pollMs, QObject *parent)
    : QObject(parent), m_statusPath(statusPath) {
    m_timer.setInterval(pollMs);
    connect(&m_timer, &QTimer::timeout, this, &StatusMonitor::refresh);
    m_timer.start();
}

void StatusMonitor::refresh() {
    QFile file(m_statusPath);
    const QByteArray data = file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray();
    const StatusSnapshot next = parseStatusJson(data, QDateTime::currentDateTime(), m_staleSeconds);
    if (next.valid != m_snapshot.valid || next.qqLoggedIn != m_snapshot.qqLoggedIn ||
        next.napcat != m_snapshot.napcat || next.onebot != m_snapshot.onebot ||
        next.bot != m_snapshot.bot || next.qqNumber != m_snapshot.qqNumber ||
        next.qqNickname != m_snapshot.qqNickname) {
        m_snapshot = next;
        emit statusChanged(m_snapshot);
    }
}
