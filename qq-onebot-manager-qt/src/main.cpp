#include <QApplication>
#include <QDesktopServices>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QFileInfo>
#include <QLabel>
#include <QMessageBox>
#include <QTimer>
#include <QUrl>
#include "app/SingleInstance.h"
#include "core/ManagedRuntime.h"
#include <functional>
#include "core/ConfigBridge.h"
#include "core/Notifier.h"
#include "core/Paths.h"
#include "core/ServiceControl.h"
#include "core/StatusMonitor.h"
#include "ui/MainWindow.h"
#include "ui/WindowActivation.h"
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
    app.setWindowIcon(QIcon(":/icons/app.png"));

    SingleInstance single("qq-onebot-manager-qt");
    const QString action = app.arguments().contains("--stop-services") ? "stop-services"
        : app.arguments().contains("--restart-services") ? "restart-services" : "show";
    ManagedRuntime runtime(Paths::repoRoot());
    if (action == "stop-services" && !runtime.markUserStopped()) return 1;
    if (!single.tryLock(action)) return 0;
    if (action == "stop-services") return 0;
    const bool recovering = app.arguments().contains("--recover-session");
    if (recovering && QFileInfo::exists(Paths::repoRoot() + "/run/manager-user-stop")) return 0;

    QString runtimeError;
    if (!runtime.initialize(&runtimeError)) {
        QMessageBox::critical(nullptr, QStringLiteral("无法启动托管服务"), runtimeError);
        return 1;
    }
    bool shuttingDown = false;
    QObject::connect(&app, &QCoreApplication::aboutToQuit, &runtime, [&] {
        shuttingDown = true;
        runtime.shutdown();
    });
    QObject::connect(&runtime, &ManagedRuntime::fatal, &app, [&](const QString &) {
        shuttingDown = true;
        app.exit(1);
    });

    ThemeManager::apply(&app, ThemeManager::loadStored());

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
    const auto stopByUser = [&] {
        if (runtime.markUserStopped()) app.quit();
        else QMessageBox::critical(&window, QStringLiteral("暂时无法停止"),
            QStringLiteral("无法保存停止状态，请检查项目目录的写入权限后重试。"));
    };
    QObject::connect(&single, &SingleInstance::anotherInstanceRequested, &window, [&window] {
        showAndActivateWindow(&window);
    });

    auto *overview = qobject_cast<OverviewPage *>(window.pageWidget("overview"));
    // 采集按钮初始状态来自暂停标记文件（不依赖滞后的状态刷新）
    overview->setCollectionPaused(QFileInfo::exists(Paths::repoRoot() + "/run/collection-paused"));
    auto *statusMonitor = new StatusMonitor(Paths::statusFile(), 4000, &window);
    // 机器人每 30 秒写一次状态；过期阈值取 90 秒。过期时由 control.py
    // 通过端口和 PID 做一次实时探测，避免冷启动沿用旧状态。
    statusMonitor->setStaleSeconds(90);
    statusMonitor->setLiveProbe(Paths::pythonExe(),
                                {"-m", "qq_onebot_whitelist.control", "live-status"});
    auto *serviceControl = new ServiceControl(&window);
    QObject::connect(serviceControl, &ServiceControl::commandStarted,
                     &runtime, &ManagedRuntime::startupCommandStarted);
    QObject::connect(&runtime, &ManagedRuntime::startupDeadline,
                     serviceControl, &ServiceControl::reconcileFinished);
    QObject::connect(serviceControl, &ServiceControl::commandCompleted,
                     &runtime, &ManagedRuntime::startupCommandCompleted);
    auto *collectionControl = new ServiceControl(&window);
    auto *statsControl = new ServiceControl(&window);
    overview->setAutoRestartText(QFileInfo::exists(Paths::repoRoot() + "/run/manager-recovery-policy.json")
        ? QStringLiteral("后台随管理器启停 · 已启用异常恢复")
        : QStringLiteral("后台随管理器启停"));
    bool pendingRestart = false;
    std::function<void(bool)> runBackend;
    runBackend = [&](bool restart) {
        if (shuttingDown) return;
        if (recovering && QFileInfo::exists(Paths::repoRoot() + "/run/manager-user-stop")) {
            app.quit();
            return;
        }
        if (serviceControl->isRunning()) {
            pendingRestart = pendingRestart || restart;
            return;
        }
        runtime.beginTransition();
        serviceControl->run({"-m", "qq_onebot_whitelist.control", restart ? "bot-restart" : "start"});
    };
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, overview, &OverviewPage::setStatus);
    QObject::connect(serviceControl, &ServiceControl::finished, overview, [&](bool ok, const QString &out) {
        if (shuttingDown) return;
        if (!ok) {
            overview->setHint("托管启动失败：" + out.trimmed());
            runtime.startupFailed();
            return;
        }
        if (pendingRestart) {
            pendingRestart = false;
            runBackend(true);
            return;
        }
        const qint64 pid = QJsonDocument::fromJson(out.toUtf8()).object().value("pid").toInteger();
        runtime.expectBot(pid);
    });
    QObject::connect(collectionControl, &ServiceControl::finished, overview, [overview](bool ok, QString out) {
        if (!ok) overview->setHint("切换采集失败：" + out.trimmed());
    });

    const auto fetchStats = [overview, statsControl]() {
        statsControl->run({"-m", "qq_onebot_whitelist.control", "stats"});
    };
    QObject::connect(statsControl, &ServiceControl::finished, overview, [overview](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (!doc.isObject()) return;
        const QJsonObject obj = doc.object();
        const QString lastReport = obj.value("lastReport").toString();
        overview->setStatNumbers(obj.value("images").toInt(),
                                 obj.value("links").toInt(),
                                 lastReport.isEmpty() ? QStringLiteral("无") : lastReport);
    });
    QObject::connect(overview, &OverviewPage::actionRequested, [&window, statusMonitor, &runBackend, &stopByUser, fetchStats, overview, collectionControl](const QString &action) {
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
            overview->setHint(QString());
            runBackend(action == "restart");
        } else if (action == "stop") {
            stopByUser();
        } else if (action == "history") {
            runBackend(false);
        } else if (action == "collection-toggle") {
            // 用独立控制通道，避免被“启动”等长任务占用而丢弃命令
            collectionControl->run({"-m", "qq_onebot_whitelist.control", "collection",
                                    overview->collectionChecked() ? "off" : "on"});
        }
    });

    auto *settings = qobject_cast<SettingsPage *>(window.pageWidget("settings"));
    // 启动时把已加载的主题同步给设置页下拉（侧栏按钮只在点击时广播）
    settings->setTheme(ThemeManager::themeName(ThemeManager::current()));
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
    QObject::connect(settings, &SettingsPage::themeChanged, [](const QString &theme) {
        ThemeManager::apply(qApp, ThemeManager::fromName(theme));
    });
    // 侧栏「切换主题」：广播给设置页同步下拉框
    QObject::connect(&window, &MainWindow::themeToggled, settings, &SettingsPage::setTheme);
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
    QObject::connect(chatPage, &ChatPage::groupsScanRequested, scanControl, [scanControl] {
        scanControl->run({"-m", "qq_onebot_whitelist.control", "groups"});
    });
    QObject::connect(scanControl, &ServiceControl::finished, chatPage, [chatPage](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isArray())
            chatPage->setGroups(doc.array().toVariantList());
    });
    // 所有重启共用控制通道，连续保存只排队一次，避免新旧后台互相终止。
    QObject::connect(configBridge, &ConfigBridge::saved, [configBridge, &runBackend](bool ok, const QString &) {
        if (!ok) return;
        configBridge->fetch();
        runBackend(true);
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
    QObject::connect(&window, &MainWindow::trayAction, [&window, &runBackend, &stopByUser, overview](const QString &action) {
        if (action == "quit") {
            stopByUser();
        } else if (action == "start" || action == "restart") {
            overview->setHint(QString());
            runBackend(action == "restart");
        } else if (action == "stop") {
            stopByUser();
        } else if (action == "logs") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
        } else if (action == "reports") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/data/view/index.html"));
        } else if (action == "napcat-webui") {
            QDesktopServices::openUrl(QUrl("http://127.0.0.1:6099/"));
        }
    });

    QObject::connect(&single, &SingleInstance::commandRequested, &window, [&](const QString &command) {
        if (command == "stop-services") stopByUser();
        else if (command == "restart-services") runBackend(true);
    });
    configBridge->fetch();

    auto *reports = qobject_cast<ReportsPage *>(window.pageWidget("reports"));
    auto *reportControl = new ServiceControl(&window);
    QObject::connect(reports, &ReportsPage::openRequested, reports, [reports](const QString &rel) {
        const QUrl target = Paths::reportUrl(rel);
        const QString fileName = QFileInfo(target.toLocalFile()).fileName();
        const bool knowledgePage = QStringList{"knowledge.html", "glossary.html", "knowledge-summary.html", "knowledge-files.html"}.contains(fileName);
        if (knowledgePage && !QFileInfo::exists(target.toLocalFile())) {
            if (reports->property("preparingReport").toBool()) return;
            reports->setProperty("preparingReport", true);
            reports->setViewStatus(QStringLiteral("正在准备资料页…"));
            auto *prepare = new ServiceControl(reports);
            QObject::connect(prepare, &ServiceControl::finished, reports, [reports, prepare, target, fileName](bool ok, const QString &out) {
                reports->setProperty("preparingReport", false);
                QUrl ready = target;
                const QString generated = QJsonDocument::fromJson(out.toUtf8()).object().value("path").toString();
                if (ok && !generated.isEmpty()) {
                    ready = QUrl::fromLocalFile(QFileInfo(generated).dir().filePath(fileName));
                    ready.setFragment(target.fragment());
                }
                if (ok && QFileInfo::exists(ready.toLocalFile())) {
                    reports->setViewStatus(QStringLiteral("资料页已准备好"));
                    QDesktopServices::openUrl(ready);
                } else {
                    reports->setViewStatus(QStringLiteral("资料页准备失败"));
                    QMessageBox::warning(reports, QStringLiteral("暂时无法打开资料"), QStringLiteral("请更新报告后重试。此操作只读取已有资料，不会调用 AI。"));
                }
                prepare->deleteLater();
            });
            prepare->run({"-m", "qq_onebot_whitelist.knowledge", "view"});
            return;
        }
        QDesktopServices::openUrl(target);
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
    // 重建视图走独立控制通道：跑完前按钮置灰、有状态提示，失败也可见
    auto *viewControl = new ServiceControl(&window);
    QObject::connect(reports, &ReportsPage::viewRequested, reports, [reports, viewControl] {
        reports->setViewStatus(QStringLiteral("视图重建中…"));
        viewControl->run({"-m", "qq_onebot_whitelist.control", "view"});
    });
    QObject::connect(viewControl, &ServiceControl::finished, reports, [reports](bool ok, QString out) {
        if (!ok) {
            reports->setViewStatus("重建失败：" + out.trimmed());
            return;
        }
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isObject() && doc.object().contains("categories"))
            reports->setCategories(doc.object().value("categories").toArray().toVariantList());
    });
    // 立即备份走独立控制通道：跑完前按钮置灰，结果（快照文件名/大小）就地展示
    auto *backupControl = new ServiceControl(&window);
    QObject::connect(reports, &ReportsPage::backupRequested, reports, [reports, backupControl] {
        reports->setBackupStatus(QStringLiteral("备份中…"));
        backupControl->run({"-m", "qq_onebot_whitelist.control", "backup"});
    });
    QObject::connect(backupControl, &ServiceControl::finished, reports, [reports](bool ok, QString out) {
        if (!ok) {
            reports->setBackupStatus("备份失败：" + out.trimmed());
            return;
        }
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isObject()) {
            const QJsonObject obj = doc.object();
            reports->setBackupStatus(QStringLiteral("已备份 ") + obj.value("file").toString()
                + QStringLiteral("（") + QString::number(obj.value("sizeMB").toDouble()) + QStringLiteral("MB）"));
        }
    });
    reportControl->run({"-m", "qq_onebot_whitelist.control", "view-list"});
    reports->setNextTime("日报发送时间可在设置页配置");

    // 启动时自动拉取已加入的群，填充群采集/群搬运页面的群列表
    scanControl->run({"-m", "qq_onebot_whitelist.control", "groups"});

    // 启动时查询一次数据概况，此后每 60s 随状态轮询低频刷新
    fetchStats();
    auto *statsTimer = new QTimer(&window);
    statsTimer->setInterval(60000);
    QObject::connect(statsTimer, &QTimer::timeout, fetchStats);
    statsTimer->start();

    showAndActivateWindow(&window);
    QTimer::singleShot(0, &window, [&] { runBackend(false); });
    return app.exec();
}
