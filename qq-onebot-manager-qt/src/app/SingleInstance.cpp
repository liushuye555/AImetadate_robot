#include "SingleInstance.h"
#include <QLocalSocket>
#include <QTimer>
#include <QVariant>
#include <QEventLoop>

SingleInstance::SingleInstance(const QString &name, QObject *parent)
    : QObject(parent), m_name(name) {
    QObject::connect(&m_server, &QLocalServer::newConnection, this, [this] {
        while (auto *socket = m_server.nextPendingConnection()) {
            socket->setReadBufferSize(256);
            const auto dispatch = [this, socket] {
                if (socket->property("dispatched").toBool()) return;
                if (!socket->canReadLine() && socket->state() != QLocalSocket::UnconnectedState) return;
                socket->setProperty("dispatched", true);
                const QString action = QString::fromUtf8(socket->readLine(256)).trimmed();
                if (action == "stop-services" || action == "restart-services")
                    emit commandRequested(action);
                else
                    emit anotherInstanceRequested();
                socket->write("ok\n");
                socket->disconnectFromServer();
                socket->deleteLater();
            };
            connect(socket, &QLocalSocket::readyRead, this, dispatch);
            connect(socket, &QLocalSocket::disconnected, this, dispatch);
            QTimer::singleShot(1000, socket, [socket, dispatch] {
                if (!socket->property("dispatched").toBool()) {
                    socket->abort();
                    dispatch();
                }
            });
            dispatch();
        }
    });
}

bool SingleInstance::tryLock(const QString &action) {
    QLocalSocket probe;
    probe.connectToServer(m_name);
    if (probe.waitForConnected(200)) {
        // Keep the Windows pipe open until the owner has consumed the command.
        // Closing an unaccepted pipe can discard its buffered request entirely.
        QEventLoop acknowledgement;
        QTimer timeout;
        timeout.setSingleShot(true);
        connect(&probe, &QLocalSocket::readyRead, &acknowledgement, &QEventLoop::quit);
        connect(&probe, &QLocalSocket::disconnected, &acknowledgement, &QEventLoop::quit);
        connect(&timeout, &QTimer::timeout, &acknowledgement, &QEventLoop::quit);
        probe.write(action.toUtf8() + '\n');
        probe.waitForBytesWritten(500);
        if (!probe.bytesAvailable() && probe.state() == QLocalSocket::ConnectedState) {
            timeout.start(1500);
            acknowledgement.exec();
        }
        probe.disconnectFromServer();
        return false;
    }
    QLocalServer::removeServer(m_name);
    return m_server.listen(m_name);
}
