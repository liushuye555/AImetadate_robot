#include "AutoRestart.h"
#include "ServiceControl.h"

AutoRestart::AutoRestart(ServiceControl *control, QObject *parent)
    : QObject(parent), m_control(control) {}

void AutoRestart::setEnabled(bool enabled) { m_enabled = enabled; }
void AutoRestart::setManualStop(bool manualStop) { m_manualStop = manualStop; }

void AutoRestart::onStatusChanged(const StatusSnapshot &s) {
    if (!m_enabled || m_manualStop || !s.valid) return;
    if (s.napcat && s.onebot && s.bot) return;
    if (m_lastRestart.isValid() && m_lastRestart.secsTo(QDateTime::currentDateTime()) < 30) return;
    m_lastRestart = QDateTime::currentDateTime();
    m_control->run({"-m", "qq_onebot_whitelist.control", "start"});
    emit autoRestarted();
}
