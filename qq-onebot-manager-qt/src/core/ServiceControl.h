#pragma once
#include <QObject>
#include <QProcess>

class ServiceControl : public QObject {
    Q_OBJECT
public:
    explicit ServiceControl(QObject *parent = nullptr);
    void run(const QStringList &args); // 如 {"-m","qq_onebot_whitelist.control","start"}
    bool isRunning() const { return m_proc.state() != QProcess::NotRunning; }
signals:
    void finished(bool ok, QString output);
private:
    QProcess m_proc;
};
