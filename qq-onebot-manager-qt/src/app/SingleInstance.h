#pragma once
#include <QObject>
#include <QLocalServer>
#include <QString>

class SingleInstance : public QObject {
    Q_OBJECT
public:
    explicit SingleInstance(const QString &name, QObject *parent = nullptr);
    bool tryLock(); // false = 已有实例在运行
signals:
    void anotherInstanceRequested();
private:
    QLocalServer m_server;
    QString m_name;
};
