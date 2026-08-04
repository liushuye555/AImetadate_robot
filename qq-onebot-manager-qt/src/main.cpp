#include <QApplication>
#include <QDesktopServices>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QFileInfo>
#include <QLabel>
#include <QMessageBox>
#include <QUrl>
#include "app/SingleInstance.h"
#include "core/AutoRestart.h"
#include "core/ConfigBridge.h"
#include "core/Notifier.h"
#include "core/Paths.h"
#include "core/ServiceControl.h"
#include "core/StatusMonitor.h"
#include "ui/MainWindow.h"
#include "ui/Strings.h"
#include "ui/pages/CollectionPage.h"
#include "ui/pages/RelayPage.h"
#include "ui/pages/ChatPage.h"
#include "ui/pages/LogsPage.h"
#include "ui/pages/OverviewPage.h"
#include "ui/pages/ReportsPage.h"
#include "ui/pages/SettingsPage.h"
#include "ui/theme/ThemeManager.h"

static QWidget *makePlaceholder(const char *key, QWidget *parent) {
    auto *label = new QLabel(Strings::zh(QString::fromLatin1(key)), parent);
    label->setAlignment(Qt::AlignCenter);
    return label;
}

static QWidget *makeOverview(QWidget *parent) { return new OverviewPage(parent); }
static QWidget *makeCollection(QWidget *parent) { return new CollectionPage(parent); }
static QWidget *makeRelay(QWidget *parent) { return new RelayPage(parent); }
static QWidget *makeChat(QWidget *parent) { return new ChatPage(parent); }
static QWidget *makeSettings(QWidget *parent) { return new SettingsPage(parent); }
static QWidget *makeLogs(QWidget *parent) { return new LogsPage(parent); }
static QWidget *makeReports(QWidget *parent) { return new ReportsPage(parent); }

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    app.setApplicationName("QQ OneBot 管理器");
    app.setWindowIcon(QIcon(":/icons/app.svg"));

    SingleInstance single("qq-onebot-manager-qt");
    if (!single.tryLock()) {
        QMessageBox::information(nullptr, "QQ OneBot 管理器", "管理器已在运行。");
        return 0;
    }

    ThemeManager::apply(&app, ThemeManager::Theme::Light);

    const QVector<PageDef> pages = {
        {"overview", "overview", makeOverview},
        {"collection", "collection", makeCollection},
        {"relay", "relay", makeRelay},
        {"chat", "chat", makeChat},
        {"settings", "settings", makeSettings},
        {"logs", "logs", makeLogs},
        {"reports", "reports", makeReports},
    };
    MainWindow window(pages);

    auto *overview = qobject_cast<OverviewPage *>(window.pageWidget("overview"));
    // 采集按钮初始状态来自暂停标记文件（不依赖滞后的状态刷新）
    overview->setCollectionPaused(QFileInfo::exists(Paths::repoRoot() + "/run/collection-paused"));
    auto *statusMonitor = new StatusMonitor(Paths::statusFile(), 4000, &window);
    // 机器人每 30 秒写一次状态；过期阈值取 90 秒，避免两次写入之间误显示“未知”
    statusMonitor->setStaleSeconds(90);
    auto *serviceControl = new ServiceControl(&window);
    auto *collectionControl = new ServiceControl(&window);
    auto *statsControl = new ServiceControl(&window);
    auto *autoRestart = new AutoRestart(serviceControl, &window);
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, overview, &OverviewPage::setStatus);
    QObject::connect(serviceControl, &ServiceControl::finished, overview, [overview](bool ok, QString out) {
        if (!ok) overview->setHint("操作失败：" + out.trimmed());
    });
    QObject::connect(collectionControl, &ServiceControl::finished, overview, [overview](bool ok, QString out) {
        if (!ok) overview->setHint("切换采集失败：" + out.trimmed());
    });

    const auto runControl = [serviceControl](const QStringList &args) {
        serviceControl->run(args);
    };
    const auto fetchStats = [overview, statsControl]() {
        statsControl->run({"-m", "qq_onebot_whitelist.control", "stats"});
    };
    QObject::connect(statsControl, &ServiceControl::finished, overview, [overview](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (!doc.isObject()) return;
        const QJsonObject obj = doc.object();
        const QString lastReport = obj.value("lastReport").toString();
        overview->setStats(QString("图片 %1 · 链接 %2 · 最近报告 %3")
                               .arg(obj.value("images").toInt())
                               .arg(obj.value("links").toInt())
                               .arg(lastReport.isEmpty() ? "无" : lastReport));
    });
    QObject::connect(overview, &OverviewPage::actionRequested, [&window, statusMonitor, runControl, fetchStats, autoRestart, overview, collectionControl](const QString &action) {
        if (action == "logs") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
        } else if (action == "reports") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/data/view/index.html"));
        } else if (action == "config") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot()));
        } else if (action == "napcat-webui") {
            QDesktopServices::openUrl(QUrl("http://127.0.0.1:6099/"));
        } else if (action == "refresh") {
            statusMonitor->refresh();
            fetchStats();
        } else if (action == "start" || action == "restart") {
            autoRestart->setManualStop(false);
            overview->setHint(QString());
            runControl({"-m", "qq_onebot_whitelist.control", "start"});
        } else if (action == "stop") {
            autoRestart->setManualStop(true);
            overview->setHint(Strings::zh("manualStop"));
            runControl({"-m", "qq_onebot_whitelist.control", "stop"});
        } else if (action == "history") {
            runControl({"-m", "qq_onebot_whitelist.control", "start"});
        } else if (action == "collection-toggle") {
            // 用独立控制通道，避免被“启动”等长任务占用而丢弃命令
            collectionControl->run({"-m", "qq_onebot_whitelist.control", "collection",
                                    overview->collectionChecked() ? "off" : "on"});
        }
    });

    auto *settings = qobject_cast<SettingsPage *>(window.pageWidget("settings"));
    auto *collectionPage = qobject_cast<CollectionPage *>(window.pageWidget("collection"));
    auto *configBridge = new ConfigBridge(&window);
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, settings, [settings](bool ok, const QVariant &schema) {
        if (ok) settings->setSchema(schema);
        else settings->showError("配置加载失败");
    });
    QObject::connect(settings, &SettingsPage::saveRequested, configBridge, &ConfigBridge::save);
    QObject::connect(settings, &SettingsPage::providersChanged, configBridge, [configBridge](const QJsonObject &providers, const QString &keyEnv, const QString &secret) {
        QJsonObject patch;
        patch.insert("ai_context.providers", providers);
        configBridge->save(patch);
        if (!keyEnv.isEmpty() && !secret.isEmpty()) {
            QJsonObject env;
            env.insert(keyEnv, secret);
            configBridge->saveEnv(env);
        }
    });
    QObject::connect(configBridge, &ConfigBridge::saved, settings, [settings](bool ok, const QString &msg) {
        settings->setSavedMessage(ok ? Strings::zh("saved") : (msg.isEmpty() ? Strings::zh("error") : msg));
    });
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, [autoRestart, overview](bool ok, const QVariant &schema) {
        if (!ok) return;
        const QJsonArray items = QJsonDocument::fromVariant(schema).array();
        for (const QJsonValue &value : items) {
            if (value.toObject().value("key").toString() == "features.auto_restart") {
                const bool enabled = value.toObject().value("default").toBool(true);
                autoRestart->setEnabled(enabled);
                overview->setAutoRestartText(enabled ? Strings::zh("autoRestartOn") : Strings::zh("autoRestartOff"));
                break;
            }
        }
    });
    QObject::connect(settings, &SettingsPage::themeChanged, [](const QString &theme) {
        ThemeManager::apply(qApp, theme == "dark" ? ThemeManager::Theme::Dark : ThemeManager::Theme::Light);
    });
    QObject::connect(settings, &SettingsPage::languageChanged, &window, &MainWindow::setLanguage);
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, collectionPage, &CollectionPage::setSchema);
    QObject::connect(collectionPage, &CollectionPage::saveRequested, configBridge, &ConfigBridge::save);
    QObject::connect(configBridge, &ConfigBridge::saved, collectionPage, [collectionPage](bool ok, const QString &msg) {
        collectionPage->setSavedMessage(ok ? Strings::zh("saved") : (msg.isEmpty() ? Strings::zh("error") : msg));
    });
    auto *scanControl = new ServiceControl(&window);
    QObject::connect(collectionPage, &CollectionPage::groupsScanRequested, scanControl, [scanControl] {
        scanControl->run({"-m", "qq_onebot_whitelist.control", "groups"});
    });
    QObject::connect(scanControl, &ServiceControl::finished, collectionPage, [collectionPage](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isArray())
            collectionPage->setGroups(doc.array().toVariantList());
    });
    auto *relayPage = qobject_cast<RelayPage *>(window.pageWidget("relay"));
    auto *chatPage = qobject_cast<ChatPage *>(window.pageWidget("chat"));
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, relayPage, &RelayPage::setSchema);
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, chatPage, &ChatPage::setSchema);
    QObject::connect(relayPage, &RelayPage::saveRequested, configBridge, &ConfigBridge::save);
    QObject::connect(chatPage, &ChatPage::saveRequested, configBridge, &ConfigBridge::save);
    QObject::connect(configBridge, &ConfigBridge::saved, relayPage, [relayPage](bool ok, const QString &msg) {
        relayPage->setSavedMessage(ok ? Strings::zh("saved") : (msg.isEmpty() ? Strings::zh("error") : msg));
    });
    QObject::connect(configBridge, &ConfigBridge::saved, chatPage, [chatPage](bool ok, const QString &msg) {
        chatPage->setSavedMessage(ok ? Strings::zh("saved") : (msg.isEmpty() ? Strings::zh("error") : msg));
    });
    QObject::connect(relayPage, &RelayPage::groupsScanRequested, scanControl, [scanControl] {
        scanControl->run({"-m", "qq_onebot_whitelist.control", "groups"});
    });
    QObject::connect(scanControl, &ServiceControl::finished, relayPage, [relayPage](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isArray())
            relayPage->setGroups(doc.array().toVariantList());
    });
    // 配置保存后只重启 bot（不动 NapCat，避免重新扫码），让新配置立即生效；
    // 使用独立控制通道，避免被其他按钮任务占用而静默丢弃
    auto *restartControl = new ServiceControl(&window);
    QObject::connect(configBridge, &ConfigBridge::saved, [restartControl](bool ok, const QString &) {
        if (ok) restartControl->run({"-m", "qq_onebot_whitelist.control", "bot-restart"});
    });
    QObject::connect(collectionPage, &CollectionPage::collectionToggle, collectionPage, [collectionControl, collectionPage] {
        collectionControl->run({"-m", "qq_onebot_whitelist.control", "collection",
                                collectionPage->collectionChecked() ? "off" : "on"});
    });
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, collectionPage, [collectionPage](const StatusSnapshot &s) {
        collectionPage->setCollectionPaused(s.collectionPaused);
    });
    QObject::connect(settings, &SettingsPage::webuiRequested, [] {
        QDesktopServices::openUrl(QUrl("http://127.0.0.1:6099/"));
    });

    auto *notifier = new Notifier(window.trayIcon(), &window);
    QObject::connect(settings, &SettingsPage::notificationsToggled, notifier, &Notifier::setEnabled);
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, notifier, &Notifier::onStatusChanged);
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, autoRestart, &AutoRestart::onStatusChanged);
    QObject::connect(autoRestart, &AutoRestart::autoRestarted, [statusMonitor] {
        statusMonitor->refresh();
    });
    QObject::connect(&window, &MainWindow::trayAction, [&window, statusMonitor, runControl, autoRestart, overview](const QString &action) {
        if (action == "quit") {
            QApplication::quit();
        } else if (action == "start" || action == "restart") {
            autoRestart->setManualStop(false);
            overview->setHint(QString());
            runControl({"-m", "qq_onebot_whitelist.control", "start"});
        } else if (action == "stop") {
            autoRestart->setManualStop(true);
            overview->setHint(Strings::zh("manualStop"));
            runControl({"-m", "qq_onebot_whitelist.control", "stop"});
        } else if (action == "logs") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
        } else if (action == "reports") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/data/view/index.html"));
        } else if (action == "napcat-webui") {
            QDesktopServices::openUrl(QUrl("http://127.0.0.1:6099/"));
        }
    });

    configBridge->fetch();

    auto *reports = qobject_cast<ReportsPage *>(window.pageWidget("reports"));
    auto *reportControl = new ServiceControl(&window);
    QObject::connect(reports, &ReportsPage::openRequested, [](const QString &rel) {
        QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/" + rel));
    });
    QObject::connect(reports, &ReportsPage::previewRequested, reportControl, [reportControl] {
        reportControl->run({"-m", "qq_onebot_whitelist.control", "report-preview"});
    });
    QObject::connect(reportControl, &ServiceControl::finished, reports, [reports](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isObject())
            reports->setPreview(doc.object().value("content").toString());
    });
    QObject::connect(reports, &ReportsPage::sendRequested, reportControl, [reportControl] {
        reportControl->run({"-m", "qq_onebot_whitelist.control", "report-send"});
    });
    QObject::connect(reports, &ReportsPage::viewRequested, reportControl, [reportControl] {
        reportControl->run({"-m", "qq_onebot_whitelist.control", "view"});
    });
    QObject::connect(reportControl, &ServiceControl::finished, reports, [reports](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isObject() && doc.object().contains("categories"))
            reports->setCategories(doc.object().value("categories").toArray().toVariantList());
    });
    reportControl->run({"-m", "qq_onebot_whitelist.control", "view-list"});
    reports->setNextTime("日报发送时间可在设置页配置");

    // 启动时自动拉取已加入的群，填充群采集/群搬运页面的群列表
    scanControl->run({"-m", "qq_onebot_whitelist.control", "groups"});

    // 启动时查询一次数据概况
    fetchStats();

    window.show();
    return app.exec();
}
