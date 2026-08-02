#include <QtTest>
#include <QSignalSpy>
#include "core/ConfigBridge.h"

class TestConfigFetch : public QObject {
    Q_OBJECT
private slots:
    void fetchSchemaFromRepo();
};

void TestConfigFetch::fetchSchemaFromRepo() {
    ConfigBridge bridge;
    QSignalSpy spy(&bridge, &ConfigBridge::schemaLoaded);
    bridge.fetch();
    QTRY_VERIFY_WITH_TIMEOUT(spy.count() >= 1, 15000);
    const bool ok = spy.at(0).at(0).toBool();
    QVERIFY2(ok, "config_bridge schema 加载失败");
    const QVariant schema = spy.at(0).at(1);
    QVERIFY(schema.toList().size() > 10);
}

QTEST_MAIN(TestConfigFetch)
#include "tst_configfetch.moc"
