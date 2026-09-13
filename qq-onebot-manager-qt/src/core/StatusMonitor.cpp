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
    s.manualStop = obj.value("manualStop").toBool(false);
    s.qqNumber = obj.value("qqNumber").toString();
    s.qqNickname = obj.value("qqNickname").toString();
    s.valid = true;
    return s;
}

StatusMonitor::StatusMonitor(const QString &statusPath, int pollMs, QObject *parent)
    : QObject(parent), m_statusPath(statusPath) {
    m_timer.setInterval(pollMs);
    connect(&m_timer, &QTimer::timeout, this, &StatusMonitor::refresh);
    connect(&m_liveProbe, &QProcess::finished, this, &StatusMonitor::liveProbeFinished);
    connect(&m_liveProbe, &QProcess::errorOccurred, this, [this](QProcess::ProcessError) {
        m_liveProbeTimeout.stop();
        publish(StatusSnapshot{});
    });
    m_liveProbeTimeout.setSingleShot(true);
    connect(&m_liveProbeTimeout, &QTimer::timeout, this, [this] {
        if (m_liveProbe.state() == QProcess::NotRunning) return;
        m_liveProbe.kill();
        publish(StatusSnapshot{});
    });
    m_timer.start();
    QTimer::singleShot(0, this, &StatusMonitor::refresh);
}

void StatusMonitor::setLiveProbe(const QString &program, const QStringList &args, int intervalMs) {
    m_liveProbeProgram = program;
    m_liveProbeArgs = args;
    m_liveProbeIntervalMs = qMax(1000, intervalMs);
}

void StatusMonitor::publish(const StatusSnapshot &next) {
    const bool changed = !m_initialized ||
        next.valid != m_snapshot.valid ||
        next.qqLoggedIn != m_snapshot.qqLoggedIn ||
        next.napcat != m_snapshot.napcat ||
        next.onebot != m_snapshot.onebot ||
        next.bot != m_snapshot.bot ||
        next.collectionPaused != m_snapshot.collectionPaused ||
        next.manualStop != m_snapshot.manualStop ||
        next.qqNumber != m_snapshot.qqNumber ||
        next.qqNickname != m_snapshot.qqNickname;
    m_snapshot = next;
    m_initialized = true;
    if (changed)
        emit statusChanged(m_snapshot);
}

void StatusMonitor::requestLiveProbe() {
    if (m_liveProbeProgram.isEmpty() || m_liveProbe.state() != QProcess::NotRunning)
        return;
    const QDateTime now = QDateTime::currentDateTime();
    if (m_lastProbeAt.isValid() && m_lastProbeAt.msecsTo(now) < m_liveProbeIntervalMs)
        return;
    m_lastProbeAt = now;
    m_liveProbe.start(m_liveProbeProgram, m_liveProbeArgs);
    m_liveProbeTimeout.start(5000);
}

void StatusMonitor::refresh() {
    QFile file(m_statusPath);
    const QByteArray data = file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray();
    const StatusSnapshot next = parseStatusJson(data, QDateTime::currentDateTime(), m_staleSeconds);
    if (next.valid) {
        publish(next);
        return;
    }

    // Do not trust an old heartbeat. Keep the last live result while a probe is
    // running, then replace it with an invalid snapshot if the probe fails.
    if (m_liveProbeProgram.isEmpty()) {
        publish(next);
        return;
    }
    if (!m_initialized)
        publish(next);
    requestLiveProbe();
}

void StatusMonitor::liveProbeFinished(int exitCode, QProcess::ExitStatus status) {
    m_liveProbeTimeout.stop();
    const QByteArray output = m_liveProbe.readAllStandardOutput();
    if (exitCode != 0 || status != QProcess::NormalExit) {
        publish(StatusSnapshot{});
        return;
    }
    const StatusSnapshot next = parseStatusJson(output, QDateTime::currentDateTime(), m_staleSeconds);
    publish(next);
}
