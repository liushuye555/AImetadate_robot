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
    const QJsonArray arr = QJsonDocument::fromVariant(schema).array();
    bool expEnabled = false, expOrdinary = false, expStreak = false, expAi = false;
    int expGroups = 0, expInput = 0, expOutput = 0;
    for (const QJsonValue &v : arr) {
        const QJsonObject o = v.toObject();
        const QString key = o.value("key").toString();
        if (key == "relay.enabled") expEnabled = o.value("default").toBool();
        else if (key == "relay.ordinary") expOrdinary = o.value("default").toBool();
        else if (key == "relay.image_streak") expStreak = o.value("default").toBool();
        else if (key == "relay.ai_filter") expAi = o.value("default").toBool();
        else if (key == "relay.groups") expGroups = o.value("default").toArray().size();
        else if (key == "relay.input_groups") expInput = o.value("default").toArray().size();
        else if (key == "relay.output_groups") expOutput = o.value("default").toArray().size();
    }
    QVERIFY(boxes.at(0)->isChecked() == expEnabled);
    QVERIFY(boxes.at(1)->isChecked() == expOrdinary);
    QVERIFY(boxes.at(2)->isChecked() == expStreak);
    QVERIFY(boxes.at(3)->isChecked() == expAi);
    const auto lists = page.findChildren<QListWidget *>();
    dbg("relay: lists=" + QString::number(lists.size()));
    QVERIFY(lists.size() >= 3);  // 参与/输入/输出
    const int expList[] = {expGroups, expInput, expOutput};
    for (int li = 0; li < 3 && li < lists.size(); ++li) {
        QListWidget *list = lists.at(li);
        int checked = 0;
        for (int i = 0; i < list->count(); ++i)
            if (list->item(i)->checkState() == Qt::Checked) checked++;
        QVERIFY(checked == expList[li]);
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
    bool expEnabled = false;
    int expGroups = 0;
    for (const QJsonValue &v : QJsonDocument::fromVariant(schema).array()) {
        const QJsonObject o = v.toObject();
        const QString key = o.value("key").toString();
        if (key == "chat.enabled") expEnabled = o.value("default").toBool();
        else if (key == "chat.groups") expGroups = o.value("default").toArray().size();
    }
    QVERIFY(boxes.first()->isChecked() == expEnabled);
    const auto lists = page.findChildren<QListWidget *>();
    QVERIFY(!lists.isEmpty());
    int checked = 0;
    for (int i = 0; i < lists.first()->count(); ++i)
        if (lists.first()->item(i)->checkState() == Qt::Checked) checked++;
    QVERIFY(checked == expGroups);
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
    QVERIFY(!boxes.isEmpty());
    // 与真实配置对齐：断言信号路径写入的值等于 schema 里 relay.enabled 的默认值，
    // 而不是硬编码 true（config.yaml 里 relay.enabled 可能为 false）。
    bool expEnabled = false;
    const QJsonArray arr = QJsonDocument::fromVariant(spy.at(0).at(1)).array();
    for (const QJsonValue &v : arr) {
        const QJsonObject o = v.toObject();
        if (o.value("key").toString() == "relay.enabled")
            expEnabled = o.value("default").toBool();
    }
    QCOMPARE(boxes.at(0)->isChecked(), expEnabled);
    dbg("signal: done");
}

QTEST_MAIN(TestPages)
#include "tst_pages.moc"
