#include "Notifier.h"
#include "../ui/Strings.h"
#include <QSystemTrayIcon>

Notifier::Notifier(QSystemTrayIcon *tray, QObject *parent)
    : QObject(parent), m_tray(tray) {}

void Notifier::setEnabled(bool enabled) { m_enabled = enabled; }

void Notifier::notify(const QString &title, const QString &body, const QString &dedupeKey) {
    if (!m_enabled || !m_tray) return;
    const QDateTime now = QDateTime::currentDateTime();
    if (m_lastNotified.value(dedupeKey).secsTo(now) < 600) return;
    m_lastNotified.insert(dedupeKey, now);
    m_tray->showMessage(title, body, QSystemTrayIcon::Information, 5000);
}

void Notifier::onStatusChanged(const StatusSnapshot &s) {
    if (!m_hasLast) {
        m_last = s;
        m_hasLast = true;
        return;
    }
    if (!s.valid || !m_last.valid) {
        m_last = s;
        return;
    }
    if (!m_last.qqLoggedIn && s.qqLoggedIn)
        notify(Strings::zh("qqLogin"), s.qqNickname + " (" + s.qqNumber + ")", "login");
    if (m_last.qqLoggedIn && !s.qqLoggedIn)
        notify(Strings::zh("qqLogout"), s.qqNickname, "logout");
    if (m_last.napcat && !s.napcat)
        notify(Strings::zh("error"), "NapCat", "napcat-down");
    if (m_last.onebot && !s.onebot)
        notify(Strings::zh("error"), "OneBot", "onebot-down");
    if (m_last.bot && !s.bot)
        notify(Strings::zh("error"), "Bot", "bot-down");
    m_last = s;
}
