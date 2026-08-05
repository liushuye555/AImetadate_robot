#include <QtTest>
#include <QSignalSpy>
#include <QCheckBox>
#include <QListWidget>
#include <QListWidgetItem>
#include "core/ConfigBridge.h"
#include "ui/pages/RelayPage.h"
#include "ui/pages/ChatPage.h"
#include <QFile>
#include <QTextStream>

static void dbg(const QString &line) {
    QFile f("C:/Users/eryis/workspace/qq-onebot-whitelist/tst_pages_dbg.txt");
    if (f.open(QIODevice::Append | QIODevice::Text)) {
        QTextStream out(&f);
        out << line << "\n";
    }
}

class TestPages : public QObject {
    Q_OBJECT
private slots:
    void relayPageReflectsRealSchema();
    void chatPageReflectsRealSchema();
    void relayPageViaSignalConnection();
};

static bool fetchSchema(QVariant &out) {
    ConfigBridge bridge;
    QSignalSpy spy(&bridge, &ConfigBridge::schemaLoaded);
    qDebug() << "fetch start";
    bridge.fetch();
    for (int i = 0; i < 150 && spy.count() == 0; ++i)
        QTest::qWait(100);
    qDebug() << "fetch done, spy count" << spy.count();
    if (spy.count() == 0 || !spy.at(0).at(0).toBool())
        return false;
    out = spy.at(0).at(1);
    qDebug() << "schema variant size" << out.toList().size();
    return true;
}

void TestPages::relayPageReflectsRealSchema() {
    dbg("relay: start");
    QVariant schema;
    QVERIFY(fetchSchema(schema));
    dbg("relay: schema ok, size=" + QString::number(schema.toList().size()));
    RelayPage page;
    dbg("relay: page constructed");
    page.setSchema(true, schema);
    dbg("relay: setSchema done");
    const auto boxes = page.findChildren<QCheckBox *>();
    dbg("relay: checkboxes=" + QString::number(boxes.size()));
    QVERIFY(boxes.size() >= 3);  // enabled / ordinary / image_streak
    QVERIFY(boxes.at(0)->isChecked());   // 启用群搬运
    QVERIFY(boxes.at(1)->isChecked());   // 普通消息搬运
    QVERIFY(boxes.at(2)->isChecked());   // 连续多图
    QVERIFY(!boxes.at(3)->isChecked());  // AI 过滤默认关
    const auto lists = page.findChildren<QListWidget *>();
    dbg("relay: lists=" + QString::number(lists.size()));
    QVERIFY(lists.size() >= 3);  // 参与/输入/输出
    for (QListWidget *list : lists) {
        int checked = 0;
        for (int i = 0; i < list->count(); ++i)
            if (list->item(i)->checkState() == Qt::Checked) checked++;
        dbg(QString("relay: list count=%1 checked=%2").arg(list->count()).arg(checked));
    }
    dbg("relay: done");
}

void TestPages::chatPageReflectsRealSchema() {
    dbg("chat: start");
    QVariant schema;
    QVERIFY(fetchSchema(schema));
    ChatPage page;
    page.setSchema(true, schema);
    const auto boxes = page.findChildren<QCheckBox *>();
    dbg("chat: checkboxes=" + QString::number(boxes.size()));
    QVERIFY(!boxes.isEmpty());
    QVERIFY(boxes.first()->isChecked());  // 聊天启用
    const auto lists = page.findChildren<QListWidget *>();
    QVERIFY(!lists.isEmpty());
    int checked = 0;
    for (int i = 0; i < lists.first()->count(); ++i)
        if (lists.first()->item(i)->checkState() == Qt::Checked) checked++;
    QVERIFY2(checked >= 4, qPrintable(QString("chat groups checked=%1").arg(checked)));
    dbg(QString("chat: groups count=%1 checked=%2").arg(lists.first()->count()).arg(checked));
    dbg("chat: done");
}

void TestPages::relayPageViaSignalConnection() {
    dbg("signal: start");
    ConfigBridge bridge;
    RelayPage page;
    QObject::connect(&bridge, &ConfigBridge::schemaLoaded, &page, &RelayPage::setSchema);
    QSignalSpy spy(&bridge, &ConfigBridge::schemaLoaded);
    bridge.fetch();
    for (int i = 0; i < 150 && spy.count() == 0; ++i)
        QTest::qWait(100);
    dbg("signal: emitted=" + QString::number(spy.count())
        + " variantList=" + QString::number(spy.at(0).at(1).toList().size()));
    const auto boxes = page.findChildren<QCheckBox *>();
    if (!boxes.isEmpty())
        dbg("signal: relay enabled checked=" + QString::number(boxes.at(0)->isChecked()));
    QVERIFY(!boxes.isEmpty());
    QVERIFY(boxes.at(0)->isChecked());
    dbg("signal: done");
}

QTEST_MAIN(TestPages)
#include "tst_pages.moc"
