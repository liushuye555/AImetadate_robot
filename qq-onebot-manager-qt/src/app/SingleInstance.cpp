#include "SingleInstance.h"
#include <QLocalSocket>

SingleInstance::SingleInstance(const QString &name, QObject *parent)
    : QObject(parent), m_name(name) {
    QObject::connect(&m_server, &QLocalServer::newConnection, this, &SingleInstance::anotherInstanceRequested);
}

bool SingleInstance::tryLock() {
    QLocalSocket probe;
    probe.connectToServer(m_name);
    if (probe.waitForConnected(200)) {
        probe.disconnectFromServer();
        return false;
    }
    QLocalServer::removeServer(m_name);
    return m_server.listen(m_name);
}
