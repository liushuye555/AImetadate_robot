#include <QtTest>
#include <QComboBox>
#include <QCheckBox>
#include <QDir>
#include <QJsonDocument>
#include <QJsonArray>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QPushButton>
#include <QSettings>
#include <QTemporaryDir>
#include <QUuid>
#include <QScrollArea>
#include <QScrollBar>
#include "app/SingleInstance.h"
#include "ui/MainWindow.h"
#include "ui/pages/OverviewPage.h"
#include "ui/pages/SettingsPage.h"
#include "ui/theme/ThemeManager.h"
#include "ui/widgets/StatusCard.h"

namespace {
QWidget *overview(QWidget *parent) { return new OverviewPage(parent); }
QWidget *settings(QWidget *parent) { return new SettingsPage(parent); }
QWidget *placeholder(QWidget *parent) { return new QLabel(parent); }
const QVector<PageDef> pages = {
    {"overview", "overview", overview}, {"collection", "collection", placeholder},
    {"relay", "relay", placeholder}, {"chat", "chat", placeholder},
    {"settings", "settings", settings}, {"logs", "logs", placeholder},
    {"reports", "reports", placeholder}
};
QVector<QImage> illustrations(MainWindow &window) {
    QVector<QImage> result;
    auto *nav = window.findChild<QListWidget *>("nav");
    for (int i = 0; i < nav->count(); ++i)
        result.append(nav->item(i)->icon().pixmap(32, 32).toImage());
    for (const auto *label : window.findChildren<QLabel *>()) {
        if (label->objectName() == "mascot" || label->objectName() == "brandLogo"
            || label->objectName() == "cardIcon") result.append(label->pixmap().toImage());
    }
    for (const QString &name : {"themeButton", "quitButton"})
        result.append(window.findChild<QPushButton *>(name)->icon().pixmap(28, 28).toImage());
    result.append(window.windowIcon().pixmap(32, 32).toImage());
    result.append(qApp->windowIcon().pixmap(32, 32).toImage());
    result.append(window.trayIcon()->icon().pixmap(32, 32).toImage());
    return result;
}
void preview(MainWindow &window, const QString &name) {
    const QString dir = qEnvironmentVariable("QQ_THEME_PREVIEW_DIR");
    if (dir.isEmpty()) return;
    QDir().mkpath(dir);
    window.grab().save(dir + "/" + name + ".png");
}
}

class TestThemeAppearance : public QObject {
    Q_OBJECT
private slots:
    void cachedAccountDoesNotImplyOnline() {
        OverviewPage page;
        StatusSnapshot status;
        status.valid = true;
        status.gatewayProvider = "external";
        status.gatewayName = "通用 OneBot v11";
        status.qqNumber = "1234567890";
        status.qqNickname = "缓存昵称";
        status.qqStatusKnown = false;
        page.setStatus(status);
        auto hasText = [&](const QString &text) {
            for (auto *label : page.findChildren<QLabel *>())
                if (label->text().contains(text)) return true;
            return false;
        };
        QVERIFY(hasText("登录状态未确认"));
        QVERIFY(hasText("缓存昵称"));
        status.qqStatusKnown = true;
        page.setStatus(status);
        QVERIFY(hasText("未登录"));
        status.qqLoggedIn = true;
        page.setStatus(status);
        QVERIFY(!hasText("未登录"));
        QVERIFY(!hasText("登录状态未确认"));
    }
    void overviewGatewaySwitchControlsAndSignals() {
        OverviewPage page;
        auto *provider = page.findChild<QComboBox *>("homeGatewayProvider");
        auto *ws = page.findChild<QLineEdit *>("homeGatewayWs");
        auto *token = page.findChild<QLineEdit *>("homeGatewayTokenEnv");
        auto *webui = page.findChild<QLineEdit *>("homeGatewayWebui");
        QCheckBox *managed = nullptr;
        QCheckBox *installed = nullptr;
        for (auto *check : page.findChildren<QCheckBox *>()) {
            if (check->text().contains("内置 NapCat")) managed = check;
            if (check->text().contains("已安装的 SnowLuma")) installed = check;
        }
        auto *switchButton = page.findChild<QPushButton *>("homeGatewaySwitch");
        auto *restoreButton = page.findChild<QPushButton *>("homeGatewayRestore");
        QVERIFY(provider && ws && token && webui && managed && installed && switchButton && restoreButton);
        const QJsonArray schema = QJsonArray{
            QJsonObject{{"key", "unrelated.setting"}, {"default", "ignore-me"}},
            QJsonObject{{"key", "onebot.provider"}, {"default", "external"}},
            QJsonObject{{"key", "onebot.protocol"}, {"default", "onebot11"}},
            QJsonObject{{"key", "onebot.ws_url"}, {"default", "ws://existing:3001"}},
            QJsonObject{{"key", "onebot.access_token_env"}, {"default", "EXISTING_TOKEN"}},
            QJsonObject{{"key", "onebot.webui_url"}, {"default", "http://existing/"}},
            QJsonObject{{"key", "onebot.manage_process"}, {"default", true}},
            QJsonObject{{"key", "onebot.start_installed_runtime"}, {"default", false}},
            QJsonObject{{"key", "onebot.disabled_actions"}, {"default", QJsonArray{"get_group_files"}}},
            QJsonObject{{"key", "onebot.max_message_mb"}, {"default", 12}}
        };
        page.setGatewaySchema(schema.toVariantList());
        QCOMPARE(provider->currentData().toString(), QString("external"));
        QCOMPARE(ws->text(), QString("ws://existing:3001"));
        QCOMPARE(token->text(), QString("EXISTING_TOKEN"));
        QCOMPARE(webui->text(), QString("http://existing/"));

        QSignalSpy switchSpy(&page, &OverviewPage::gatewaySwitchRequested);
        QSignalSpy restoreSpy(&page, &OverviewPage::gatewayRestoreRequested);
        QSignalSpy snowSpy(&page, &OverviewPage::snowLumaActionRequested);
        provider->setCurrentIndex(provider->findData("snowluma"));
        QCOMPARE(ws->text(), QString("ws://127.0.0.1:3001"));
        QCOMPARE(token->text(), QString("SNOWLUMA_ONEBOT_TOKEN"));
        QCOMPARE(webui->text(), QString("http://127.0.0.1:5099/"));
        QVERIFY(!installed->isHidden());
        installed->setChecked(true);
        ws->setText(" ws://snow:3001 ");
        switchButton->click();
        QCOMPARE(switchSpy.size(), 1);
        const QJsonObject patch = qvariant_cast<QJsonObject>(switchSpy.takeFirst().at(0));
        QCOMPARE(patch.value("onebot.provider").toString(), QString("snowluma"));
        QCOMPARE(patch.value("onebot.protocol").toString(), QString("onebot11"));
        QCOMPARE(patch.value("onebot.ws_url").toString(), QString("ws://snow:3001"));
        QCOMPARE(patch.value("onebot.access_token_env").toString(), QString("SNOWLUMA_ONEBOT_TOKEN"));
        QCOMPARE(patch.value("onebot.start_installed_runtime").toBool(), true);
        QCOMPARE(patch.value("onebot.manage_process").toBool(), false);
        QCOMPARE(patch.value("onebot.disabled_actions").toArray(), QJsonArray{"get_group_files"});
        QCOMPARE(patch.value("onebot.max_message_mb").toInt(), 12);
        QVERIFY(!patch.contains("unrelated.setting"));

        provider->setCurrentIndex(provider->findData("qqofficial"));
        QVERIFY(!ws->isEnabled());
        QVERIFY(!token->isEnabled());
        QVERIFY(!webui->isEnabled());
        switchButton->click();
        const QJsonObject officialPatch = qvariant_cast<QJsonObject>(switchSpy.takeFirst().at(0));
        QCOMPARE(officialPatch.value("onebot.provider").toString(), QString("qqofficial"));
        QCOMPARE(officialPatch.value("onebot.protocol").toString(), QString("qqofficial"));
        QCOMPARE(officialPatch.value("onebot.ws_url").toString(), QString("ws://existing:3001"));
        QCOMPARE(officialPatch.value("onebot.access_token_env").toString(), QString("EXISTING_TOKEN"));
        QCOMPARE(officialPatch.value("onebot.webui_url").toString(), QString("http://existing/"));
        QCOMPARE(officialPatch.value("onebot.disabled_actions").toArray(), QJsonArray{"get_group_files"});
        QCOMPARE(officialPatch.value("onebot.max_message_mb").toInt(), 12);
        QVERIFY(!officialPatch.contains("unrelated.setting"));

        auto *snowStart = page.findChild<QPushButton *>("homeSnowLuma_start");
        QVERIFY(snowStart);
        snowStart->click();
        QCOMPARE(snowSpy.size(), 1);
        QCOMPARE(snowSpy.takeFirst().at(0).toString(), QString("start"));
        restoreButton->click();
        QCOMPARE(restoreSpy.size(), 1);
        page.setGatewayBusy(true);
        QVERIFY(!switchButton->isEnabled());
        QVERIFY(!restoreButton->isEnabled());
        const int switchesBefore = switchSpy.size();
        switchButton->click();
        QCOMPARE(switchSpy.size(), switchesBefore);
        page.setGatewayBusy(false);
        QVERIFY(switchButton->isEnabled());
        page.setGatewayResult("配置已更新");
        QCOMPARE(page.findChild<QLabel *>("homeGatewayMessage")->text(), QString("配置已更新"));
    }
    void initTestCase() {
        QVERIFY(m_settingsDir.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, m_settingsDir.path());
    }
    void liveSwitchUpdatesAllIllustrations() {
        ThemeManager::apply(qApp, ThemeManager::Theme::Light);
        MainWindow window(pages);
        window.resize(1060, 700);
        window.show();
        QCoreApplication::processEvents();
        const auto light = illustrations(window);
        QCOMPARE(light.size(), 18);
        for (const auto &image : light) QVERIFY(!image.isNull());
        preview(window, "theme-light");

        auto *page = qobject_cast<SettingsPage *>(window.pageWidget("settings"));
        QVERIFY(page);
        page->setTheme("light");
        page->setSchema(QJsonDocument::fromJson("[]").toVariant());
        connect(page, &SettingsPage::themeChanged, &window, [](const QString &name) {
            const auto selected = ThemeManager::fromName(name);
            ThemeManager::apply(qApp, selected);
            ThemeManager::store(selected);
        });
        connect(&window, &MainWindow::themeToggled, page, &SettingsPage::setTheme);
        QComboBox *theme = nullptr;
        for (auto *combo : page->findChildren<QComboBox *>())
            if (combo->findData("dark") >= 0) theme = combo;
        QVERIFY(theme);
        theme->setCurrentIndex(theme->findData("dark"));
        QCoreApplication::processEvents();
        QCOMPARE(ThemeManager::loadStored(), ThemeManager::Theme::Dark);
        const auto dark = illustrations(window);
        QCOMPARE(dark.size(), light.size());
        for (int i = 0; i < dark.size(); ++i) {
            QVERIFY(!dark[i].isNull());
            QVERIFY2(dark[i] != light[i], qPrintable(QString("Unchanged illustration %1").arg(i)));
        }
        auto *nav = window.findChild<QListWidget *>("nav");
        for (int i = 0; i < nav->count(); ++i)
            QCOMPARE(nav->item(i)->icon().pixmap(32, 32, QIcon::Selected).toImage(),
                     nav->item(i)->icon().pixmap(32, 32, QIcon::Normal).toImage());
        for (int size : {16, 20, 24, 32, 48, 64})
            QVERIFY(!window.trayIcon()->icon().pixmap(size, size).isNull());
        preview(window, "theme-dark");
        window.findChild<QPushButton *>("themeButton")->click();
        QCoreApplication::processEvents();
        QCOMPARE(theme->currentData().toString(), QString("light"));
        QCOMPARE(ThemeManager::loadStored(), ThemeManager::Theme::Light);
        QCOMPARE(illustrations(window), light);

        ThemeManager::apply(qApp, ThemeManager::Theme::Dark);
        window.resize(900, 600);
        QCoreApplication::processEvents();
        QVERIFY(nav->visualItemRect(nav->item(nav->count() - 1)).bottom() < nav->viewport()->height());
        preview(window, "theme-dark-minimum");
    }
    void startupAndSystemUseResolvedAppearance() {
        ThemeManager::store(ThemeManager::Theme::Dark);
        ThemeManager::apply(qApp, ThemeManager::loadStored());
        MainWindow darkWindow(pages);
        auto *darkNav = darkWindow.findChild<QListWidget *>("nav");
        const QImage darkIcon = darkNav->item(0)->icon().pixmap(32, 32).toImage();
        ThemeManager::apply(qApp, ThemeManager::Theme::Light);
        QVERIFY(darkNav->item(0)->icon().pixmap(32, 32).toImage() != darkIcon);
        ThemeManager::apply(qApp, ThemeManager::Theme::System);
        const QString prefix = ThemeManager::resolveSystem() == ThemeManager::Theme::Dark
            ? ":/icons/dark/" : ":/icons/";
        QCOMPARE(darkNav->item(0)->icon().pixmap(32, 32).toImage(),
                 QIcon(prefix + "nav-overview.png").pixmap(32, 32).toImage());
        QCOMPARE(ThemeManager::current(), ThemeManager::Theme::System);
    }
    void realAvatarSurvivesThemeChanges() {
        ThemeManager::apply(qApp, ThemeManager::Theme::Light);
        StatusCard card("QQ", ":/icons/card-qq.png");
        QPixmap avatar(40, 40);
        avatar.fill(QColor("#de831c"));
        card.setIconPixmap(avatar);
        const QImage before = card.findChild<QLabel *>("cardIcon")->pixmap().toImage();
        ThemeManager::apply(qApp, ThemeManager::Theme::Dark);
        QCOMPARE(card.findChild<QLabel *>("cardIcon")->pixmap().toImage(), before);
    }
    void backendFailureSurvivesStaleStatusRefresh() {
        OverviewPage page;
        StatusSnapshot cached;
        cached.valid = true;
        cached.bot = true;
        page.setStatus(cached);
        auto cards = page.findChildren<StatusCard *>();
        QCOMPARE(cards.size(), 4);
        auto *botValue = cards.at(2)->findChild<QLabel *>("cardValue");
        QVERIFY(botValue);
        const QString healthy = botValue->text();
        const QString failure = QStringLiteral("采集后端已退出；管理器继续运行，可重启。");
        page.setBackendFault(failure);
        QVERIFY(botValue->text() != healthy);
        page.setStatus(cached); // Old heartbeat must not resurrect the failed backend.
        QVERIFY(botValue->text() != healthy);
        bool found = false;
        for (auto *label : page.findChildren<QLabel *>())
            if (label->text() == failure) found = true;
        QVERIFY(found);
        page.clearBackendFault();
        QCOMPARE(botValue->text(), healthy);
    }
    void repeatedLaunchRestoresHiddenAndMinimizedWindow() {
        const QString endpoint = "qq-manager-test-" + QUuid::createUuid().toString(QUuid::Id128);
        SingleInstance primary(endpoint);
        QVERIFY(primary.tryLock());
        MainWindow window(pages);
        connect(&primary, &SingleInstance::anotherInstanceRequested,
                &window, &MainWindow::showAndActivate);
        QSignalSpy requested(&primary, &SingleInstance::anotherInstanceRequested);
        // Repeated launches must continue to work beyond the local server queue size.
        for (int i = 0; i < 40; ++i) {
            if (i % 2 == 0) window.hide();
            else window.showMinimized();
            SingleInstance secondary(endpoint);
            QVERIFY(!secondary.tryLock());
            QTRY_COMPARE(requested.size(), i + 1);
            QVERIFY(window.isVisible());
            QVERIFY(!window.isMinimized());
        }
    }
    void overviewAdaptsAndKeepsTimestampsReadable() {
        for (const auto appearance : {ThemeManager::Theme::Light, ThemeManager::Theme::Dark}) {
            ThemeManager::apply(qApp, appearance);
            MainWindow window(pages);
            auto *page = qobject_cast<OverviewPage *>(window.pageWidget("overview"));
            QVERIFY(page);
            page->setGatewaySchema(QJsonArray{
                QJsonObject{{"key", "onebot.provider"}, {"default", "external"}},
                QJsonObject{{"key", "onebot.ws_url"}, {"default", "ws://127.0.0.1:3001"}},
                QJsonObject{{"key", "onebot.access_token_env"}, {"default", "ONEBOT_ACCESS_TOKEN"}}
            }.toVariantList());
            StatusSnapshot status;
            status.valid = true;
            status.napcat = status.onebot = status.bot = true;
            status.qqLoggedIn = true;
            status.imageQueue = 0;
            status.recallCount = 60;
            status.lastViewSync = "2026-10-04 22:34:56";
            status.lastBackup = "2026-10-04 11:01";
            status.backupOk = true;
            page->setStatus(status);
            page->setStatNumbers(24649, 1466, "2026-10-03");
            page->setCollectionPaused(false);
            page->setAutoRestartText("自动重启：已开启");
            auto *qqCard = page->findChildren<StatusCard *>().last();
            qqCard->setValue("示例账号", true, "QQ 1234567890");
            auto metric = [page](const QString &key) -> QLabel * {
                for (auto *label : page->findChildren<QLabel *>())
                    if (label->property("metric").toString() == key) return label;
                return nullptr;
            };
            QVERIFY(metric("sync"));
            QCOMPARE(metric("sync")->text(), QString("2026-10-04\n22:34"));
            QCOMPARE(metric("sync")->toolTip(), status.lastViewSync);
            QCOMPARE(metric("backup")->text(), QString("2026-10-04\n11:01"));
            for (const QSize size : {QSize(1060, 700), QSize(900, 600), QSize(1440, 900)}) {
                window.resize(size);
                window.show();
                QCoreApplication::processEvents();
                auto *scroll = page->findChild<QScrollArea *>("overviewScroll");
                QVERIFY(scroll);
                QVERIFY(scroll->widget()->width() <= scroll->viewport()->width());
                for (const auto &key : {"images", "links", "queue", "recall", "sync", "backup"}) {
                    auto *label = metric(key);
                    QVERIFY(label && label->isVisible());
                    for (const QString &line : label->text().split('\n'))
                        QVERIFY2(label->fontMetrics().horizontalAdvance(line) <= label->contentsRect().width(),
                                 qPrintable(QString("Clipped %1 at %2").arg(key).arg(size.width())));
                }
                for (auto *button : page->findChildren<QPushButton *>())
                    if (button->isVisible()) QVERIFY(button->width() >= button->minimumSizeHint().width());
                auto *actionCard = page->findChild<QPushButton *>("primary")->parentWidget();
                QTRY_COMPARE(actionCard->height(), actionCard->sizeHint().height());
                preview(window, QString("overview-%1-%2").arg(ThemeManager::themeName(appearance)).arg(size.width()));
            }
            status.backupOk = false;
            page->setStatus(status);
            QVERIFY(metric("backup")->text().contains("备份失败"));
            QCOMPARE(metric("backup")->property("state").toString(), QString("bad"));
            status.lastBackup.clear();
            status.lastViewSync.clear();
            page->setStatus(status);
            QCOMPARE(metric("backup")->text(), QString("暂无备份"));
            QCOMPARE(metric("backup")->property("state").toString(), QString("normal"));
            QCOMPARE(metric("sync")->text(), QString("尚未同步"));
            page->setStatNumbers(12345678, 87654321, QString(80, QChar(u'长')));
            qqCard->setValue(QString(30, QChar(u'名')), true, "QQ 1234567890");
            window.resize(900, 600);
            QCoreApplication::processEvents();
            auto *scroll = page->findChild<QScrollArea *>("overviewScroll");
            QVERIFY(scroll->widget()->width() <= scroll->viewport()->width());
            QCOMPARE(metric("report")->toolTip(), QString(80, QChar(u'长')));
            QVERIFY(metric("report")->height() >= metric("report")->heightForWidth(metric("report")->width()));
            auto *nickname = qqCard->findChild<QLabel *>("cardValue");
            QVERIFY(nickname->height() >= nickname->heightForWidth(nickname->width()));
            page->setStatNumbers(2147483647, 2147483647, "暂无日报");
            window.resize(1060, 700);
            QCoreApplication::processEvents();
            QVERIFY(metric("images")->fontMetrics().horizontalAdvance(metric("images")->text())
                    <= metric("images")->contentsRect().width());
            const auto controls = page->findChildren<QPushButton *>();
            QSignalSpy actions(page, &OverviewPage::actionRequested);
            for (auto *button : controls) button->click();
            QCOMPARE(actions.size(), 10);
        }
    }
private:
    QTemporaryDir m_settingsDir;
};
QTEST_MAIN(TestThemeAppearance)
#include "tst_themeappearance.moc"
