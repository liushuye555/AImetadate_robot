#include <QApplication>
#include <QDesktopServices>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
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
        {"settings", "settings", makeSettings},
        {"logs", "logs", makeLogs},
        {"reports", "reports", makeReports},
    };
    MainWindow window(pages);

    auto *overview = qobject_cast<OverviewPage *>(window.pageWidget("overview"));
    auto *statusMonitor = new StatusMonitor(Paths::statusFile(), 4000, &window);
    // 机器人每 30 秒写一次状态；过期阈值取 90 秒，避免两次写入之间误显示“未知”
    statusMonitor->setStaleSeconds(90);
    auto *serviceControl = new ServiceControl(&window);
    auto *statsControl = new ServiceControl(&window);
    auto *autoRestart = new AutoRestart(serviceControl, &window);
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, overview, &OverviewPage::setStatus);

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
    QObject::connect(overview, &OverviewPage::actionRequested, [&window, statusMonitor, runControl, fetchStats, autoRestart, overview](const QString &action) {
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
            const bool paused = statusMonitor->snapshot().collectionPaused;
            overview->setCollectionPaused(!paused);
            runControl({"-m", "qq_onebot_whitelist.control", "collection", paused ? "on" : "off"});
            statusMonitor->refresh();
        }
    });

    auto *settings = qobject_cast<SettingsPage *>(window.pageWidget("settings"));
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
    auto *scanControl = new ServiceControl(&window);
    QObject::connect(settings, &SettingsPage::groupsScanRequested, scanControl, [scanControl] {
        scanControl->run({"-m", "qq_onebot_whitelist.control", "groups"});
    });
    QObject::connect(scanControl, &ServiceControl::finished, settings, [settings](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isArray())
            settings->setGroups(doc.array().toVariantList());
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
    reports->setNextTime("日报发送时间可在设置页配置");

    // 启动时查询一次数据概况
    fetchStats();

    window.show();
    return app.exec();
}
