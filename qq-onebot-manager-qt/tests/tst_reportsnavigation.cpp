#include <QtTest>
#include <QSignalSpy>
#include <QPushButton>
#include <QFontDatabase>
#include <QFile>
#include <QScrollArea>
#include <QScrollBar>
#include <QToolBox>
#include "ui/pages/ReportsPage.h"
#include "core/Paths.h"

class TestReportsNavigation : public QObject {
    Q_OBJECT
private slots:
    void initTestCase();
    void primaryEntriesOpenExpectedPages();
    void defaultsToKnowledgeFirst();
    void followupUsesAFragmentRatherThanAFileName();
    void narrowWindowKeepsMainActionsVisibleAndScrollable();
    void maintenanceBusyStateDoesNotTriggerReportSend();
};

void TestReportsNavigation::initTestCase() {
    // The offscreen plugin does not discover Windows fallback fonts itself.
    const QString font = qEnvironmentVariable("WINDIR") + "/Fonts/msyh.ttc";
    if (QFile::exists(font)) {
        const int id = QFontDatabase::addApplicationFont(font);
        const QStringList families = QFontDatabase::applicationFontFamilies(id);
        if (!families.isEmpty()) QApplication::setFont(QFont(families.first(), 10));
    }
}

void TestReportsNavigation::primaryEntriesOpenExpectedPages() {
    ReportsPage page;
    QSignalSpy spy(&page, &ReportsPage::openRequested);
    const QList<QPair<QString, QString>> cases = {
        {QStringLiteral("群知识"), QStringLiteral("data/view/knowledge.html")},
        {QStringLiteral("待跟进"), QStringLiteral("data/view/knowledge.html#followup")},
        {QStringLiteral("术语"), QStringLiteral("data/view/glossary.html")},
        {QStringLiteral("群总结"), QStringLiteral("data/view/knowledge-summary.html")},
        {QStringLiteral("保留文件 · 精选"), QStringLiteral("data/view/knowledge-files.html")},
        {QStringLiteral("图片总览"), QStringLiteral("data/view/index.html")},
        {QStringLiteral("群文件 · 全部采集"), QStringLiteral("data/view/files.html")},
        {QStringLiteral("资源链接"), QStringLiteral("data/view/resources.html")},
    };
    for (const auto &entry : cases) {
        QPushButton *button = nullptr;
        for (auto *candidate : page.findChildren<QPushButton *>())
            if (candidate->text() == entry.first) { button = candidate; break; }
        QVERIFY2(button, qPrintable(entry.first));
        button->click();
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.takeFirst().at(0).toString(), entry.second);
    }
}

void TestReportsNavigation::defaultsToKnowledgeFirst() {
    ReportsPage page;
    const auto buttons = page.findChildren<QPushButton *>();
    QVERIFY(!buttons.isEmpty());
    QCOMPARE(buttons.first()->text(), QStringLiteral("群知识"));
}

void TestReportsNavigation::followupUsesAFragmentRatherThanAFileName() {
    const auto url = Paths::reportUrl(QStringLiteral("data/view/knowledge.html#followup"));
    QCOMPARE(url.fragment(), QStringLiteral("followup"));
    QVERIFY(url.toLocalFile().endsWith(QStringLiteral("data/view/knowledge.html")));
    const auto image = Paths::reportUrl(QStringLiteral("data/view/#42.png"));
    QVERIFY(image.fragment().isEmpty());
    QVERIFY(image.toLocalFile().endsWith(QStringLiteral("#42.png")));
}

void TestReportsNavigation::narrowWindowKeepsMainActionsVisibleAndScrollable() {
    ReportsPage page;
    page.resize(660, 560);
    page.show();
    QTRY_VERIFY(page.isVisible());
    QCoreApplication::processEvents();

    auto *scroll = page.findChild<QScrollArea *>(QStringLiteral("reportsScroll"));
    QVERIFY(scroll);
    QVERIFY(scroll->viewport()->width() > 0);
    QVERIFY(scroll->widget()->width() <= scroll->viewport()->width());
    QCOMPARE(scroll->horizontalScrollBar()->maximum(), 0);

    for (const QString &label : {QStringLiteral("群知识"), QStringLiteral("待跟进"),
                                 QStringLiteral("术语"), QStringLiteral("群总结"),
                                 QStringLiteral("保留文件 · 精选")}) {
        QPushButton *button = nullptr;
        for (auto *candidate : page.findChildren<QPushButton *>())
            if (candidate->text() == label) { button = candidate; break; }
        QVERIFY2(button, qPrintable(label));
        QVERIFY2(button->isVisible(), qPrintable(label));
    }
    QVERIFY(scroll->verticalScrollBar()->maximum() > 0);
    const QString screenshot = qEnvironmentVariable("REPORTS_SCREENSHOT");
    if (!screenshot.isEmpty()) QVERIFY(page.grab().save(screenshot));
}

void TestReportsNavigation::maintenanceBusyStateDoesNotTriggerReportSend() {
    ReportsPage page;
    QSignalSpy sendSpy(&page, &ReportsPage::sendRequested);
    page.setViewStatus(QStringLiteral("视图重建中…"));
    page.setBackupStatus(QStringLiteral("备份中…"));
    auto *tools = page.findChild<QToolBox *>(QStringLiteral("secondaryTools"));
    QVERIFY(tools);
    tools->setCurrentIndex(1);
    int disabledActions = 0;
    for (auto *button : tools->widget(1)->findChildren<QPushButton *>()) {
        if (!button->isEnabled()) ++disabledActions;
        button->click();
    }
    QCOMPARE(disabledActions, 2);
    QCOMPARE(sendSpy.count(), 0);
}

QTEST_MAIN(TestReportsNavigation)
#include "tst_reportsnavigation.moc"
