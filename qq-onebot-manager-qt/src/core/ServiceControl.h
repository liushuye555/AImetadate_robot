#pragma once
#include <QObject>
#include <QProcess>

class ServiceControl : public QObject {
    Q_OBJECT
public:
    explicit ServiceControl(QObject *parent = nullptr);
    void run(const QStringList &args); // 如 {"-m","qq_onebot_whitelist.control","start"}
signals:
    void finished(bool ok, QString output);
private:
    QProcess m_proc;
};
