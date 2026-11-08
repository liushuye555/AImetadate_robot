#pragma once
#include <QWidget>
#include <QVector>
#include <QJsonObject>
#include <QVariant>
#include "core/StatusMonitor.h"

class StatusCard;
class QPushButton;
class QLabel;
class QGridLayout;
class QResizeEvent;
class QComboBox;
class QLineEdit;
class QCheckBox;

class OverviewPage : public QWidget {
    Q_OBJECT
public:
    explicit OverviewPage(QWidget *parent = nullptr);
    void setStatus(const StatusSnapshot &s);
    void setStatNumbers(int images, int links, const QString &lastReport);
    void setHint(const QString &text);
    void setBackendFault(const QString &reason);
    void clearBackendFault();
    void setAutoRestartText(const QString &text);
    void setCollectionPaused(bool paused);
    bool collectionChecked() const;
    void setGatewaySchema(const QVariant &schema);
    void setGatewayBusy(bool busy);
    void setGatewayResult(const QString &text);
signals:
    void gatewaySwitchRequested(const QJsonObject &patch);
    void gatewayRestoreRequested();
    void snowLumaActionRequested(const QString &action);
    void actionRequested(const QString &action); // start/stop/restart/refresh/logs/reports/config/history
protected:
    void resizeEvent(QResizeEvent *event) override;
private:
    void updateResponsiveLayout();
    void updateGatewayFields();
    QWidget *m_gatewayPanel = nullptr;
    QWidget *m_gatewayDetails = nullptr;
    QWidget *m_gatewaySnowActions = nullptr;
    QPushButton *m_gatewayDetailsToggle = nullptr;
    QComboBox *m_gatewayProvider = nullptr;
    QLineEdit *m_gatewayWs = nullptr;
    QLineEdit *m_gatewayTokenEnv = nullptr;
    QLineEdit *m_gatewayWebui = nullptr;
    QCheckBox *m_gatewayManaged = nullptr;
    QCheckBox *m_gatewayInstalled = nullptr;
    QLabel *m_gatewayMessage = nullptr;
    QJsonObject m_gatewayConfig;
    bool m_gatewayLoaded = false;
    bool m_gatewayBusy = false;
    QWidget *m_body = nullptr;
    QGridLayout *m_servicesLayout = nullptr;
    QGridLayout *m_countsLayout = nullptr;
    QGridLayout *m_serviceActionsLayout = nullptr;
    QGridLayout *m_dataActionsLayout = nullptr;
    QVector<QWidget *> m_serviceCards;
    QVector<QWidget *> m_countCards;
    QVector<QWidget *> m_serviceButtons;
    QVector<QWidget *> m_dataButtons;
    int m_serviceColumns = 0;
    int m_countColumns = 0;
    int m_actionColumns = 0;
    StatusCard *m_napcat = nullptr;
    StatusCard *m_onebot = nullptr;
    StatusCard *m_bot = nullptr;
    StatusCard *m_qq = nullptr;
    QLabel *m_statImages = nullptr;
    QLabel *m_statLinks = nullptr;
    QLabel *m_statReport = nullptr;
    QLabel *m_statQueue = nullptr;
    QLabel *m_statRecall = nullptr;
    QLabel *m_statViewSync = nullptr;
    QLabel *m_statBackup = nullptr;
    QLabel *m_hint = nullptr;
    QLabel *m_autoRestart = nullptr;
    QPushButton *m_collection = nullptr;
    QString m_avatarQQ;  // 已拉取过头像的 QQ 号，避免状态刷新重复请求
    bool m_collectionPaused = false;
    QString m_backendFault;
    StatusSnapshot m_lastStatus;
};
