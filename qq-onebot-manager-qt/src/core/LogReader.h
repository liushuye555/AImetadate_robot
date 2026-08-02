#pragma once
#include <QObject>
#include <QFile>
#include <QTimer>

class LogReader : public QObject {
    Q_OBJECT
public:
    explicit LogReader(QStringList paths, QObject *parent = nullptr);
    void setActive(int index); // 0=bot.log 1=napcat.log
signals:
    void newChunk(const QString &text);
private:
    void poll();
    QStringList m_paths;
    QFile m_file;
    qint64 m_pos = 0;
    QTimer m_timer;
    int m_active = 0;
};
