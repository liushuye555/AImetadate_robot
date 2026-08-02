#pragma once
#include <QObject>
#include <QDateTime>
#include "StatusMonitor.h"

class ServiceControl;

class AutoRestart : public QObject {
    Q_OBJECT
public:
    explicit AutoRestart(ServiceControl *control, QObject *parent = nullptr);
    void setEnabled(bool enabled);
    void setManualStop(bool manualStop);
    bool manualStop() const { return m_manualStop; }
public slots:
    void onStatusChanged(const StatusSnapshot &s);
signals:
    void autoRestarted();
private:
    ServiceControl *m_control = nullptr;
    bool m_enabled = true;
    bool m_manualStop = false;
    QDateTime m_lastRestart;
};
