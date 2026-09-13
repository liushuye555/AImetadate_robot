#pragma once
#include <QWidget>
#include "core/StatusMonitor.h"

class StatusCard;
class QPushButton;
class QLabel;

class OverviewPage : public QWidget {
    Q_OBJECT
public:
    explicit OverviewPage(QWidget *parent = nullptr);
    void setStatus(const StatusSnapshot &s);
    void setStatNumbers(int images, int links, const QString &lastReport);
    void setHint(const QString &text);
    void setAutoRestartText(const QString &text);
    void setCollectionPaused(bool paused);
    bool collectionChecked() const;
signals:
    void actionRequested(const QString &action); // start/stop/restart/refresh/logs/reports/config/history
private:
    StatusCard *m_napcat = nullptr;
    StatusCard *m_onebot = nullptr;
    StatusCard *m_bot = nullptr;
    StatusCard *m_qq = nullptr;
    QLabel *m_statImages = nullptr;
    QLabel *m_statLinks = nullptr;
    QLabel *m_statReport = nullptr;
    QLabel *m_hint = nullptr;
    QLabel *m_autoRestart = nullptr;
    QPushButton *m_collection = nullptr;
    QString m_avatarQQ;  // 已拉取过头像的 QQ 号，避免状态刷新重复请求
    bool m_collectionPaused = false;
};
