#pragma once
#include <QObject>
#include <QLocalServer>
#include <QString>

class SingleInstance : public QObject {
    Q_OBJECT
public:
    explicit SingleInstance(const QString &name, QObject *parent = nullptr);
    bool tryLock(const QString &action = QStringLiteral("show"));
signals:
    void anotherInstanceRequested();
    void commandRequested(const QString &action);
private:
    QLocalServer m_server;
    QString m_name;
};
