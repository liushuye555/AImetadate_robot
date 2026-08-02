#include <QApplication>
#include <QDesktopServices>
#include <QIcon>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QMessageBox>
#include <QUrl>
#include "app/SingleInstance.h"
#include "core/ConfigBridge.h"
#include "core/Paths.h"
#include "core/ServiceControl.h"
#include "core/StatusMonitor.h"
#include "ui/MainWindow.h"
#include "ui/Strings.h"
#include "ui/pages/OverviewPage.h"
#include "ui/pages/SettingsPage.h"
#include "ui/theme/ThemeManager.h"

static QWidget *makePlaceholder(const char *key, QWidget *parent) {
    auto *label = new QLabel(Strings::zh(QString::fromLatin1(key)), parent);
    label->setAlignment(Qt::AlignCenter);
    return label;
}

static QWidget *makeOverview(QWidget *parent) { return new OverviewPage(parent); }
static QWidget *makeSettings(QWidget *parent) { return new SettingsPage(parent); }
static QWidget *makeLogs(QWidget *parent) { return makePlaceholder("logs", parent); }
static QWidget *makeReports(QWidget *parent) { return makePlaceholder("reports", parent); }

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
    auto *serviceControl = new ServiceControl(&window);
    auto *statsControl = new ServiceControl(&window);
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
    QObject::connect(overview, &OverviewPage::actionRequested, [&window, statusMonitor, runControl, fetchStats](const QString &action) {
        if (action == "logs") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
        } else if (action == "reports") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/data/view/index.html"));
        } else if (action == "config") {
            QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot()));
        } else if (action == "refresh") {
            statusMonitor->refresh();
            fetchStats();
        } else if (action == "start" || action == "restart") {
            runControl({"-m", "qq_onebot_whitelist.control", "start"});
        } else if (action == "stop") {
            runControl({"-m", "qq_onebot_whitelist.control", "stop"});
        } else if (action == "history") {
            runControl({"-m", "qq_onebot_whitelist.control", "start"});
        }
    });

    auto *settings = qobject_cast<SettingsPage *>(window.pageWidget("settings"));
    auto *configBridge = new ConfigBridge(&window);
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, settings, &SettingsPage::setSchema);
    QObject::connect(settings, &SettingsPage::saveRequested, configBridge, &ConfigBridge::save);
    QObject::connect(configBridge, &ConfigBridge::saved, settings, [settings](bool ok, const QString &msg) {
        settings->setSavedMessage(ok ? Strings::zh("saved") : (msg.isEmpty() ? Strings::zh("error") : msg));
    });
    QObject::connect(settings, &SettingsPage::themeChanged, [](const QString &theme) {
        ThemeManager::apply(qApp, theme == "dark" ? ThemeManager::Theme::Dark : ThemeManager::Theme::Light);
    });
    QObject::connect(settings, &SettingsPage::languageChanged, &window, &MainWindow::setLanguage);
    configBridge->fetch();

    // 启动时查询一次数据概况
    fetchStats();

    window.show();
    return app.exec();
}
