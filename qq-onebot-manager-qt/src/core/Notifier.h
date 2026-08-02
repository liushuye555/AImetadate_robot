#pragma once
#include <QObject>
#include <QDateTime>
#include <QHash>
#include "StatusMonitor.h"

class QSystemTrayIcon;

class Notifier : public QObject {
    Q_OBJECT
public:
    explicit Notifier(QSystemTrayIcon *tray, QObject *parent = nullptr);
    void setEnabled(bool enabled);
public slots:
    void onStatusChanged(const StatusSnapshot &snapshot);
private:
    void notify(const QString &title, const QString &body, const QString &dedupeKey);
    QSystemTrayIcon *m_tray = nullptr;
    bool m_enabled = true;
    StatusSnapshot m_last;
    bool m_hasLast = false;
    QHash<QString, QDateTime> m_lastNotified;
};
