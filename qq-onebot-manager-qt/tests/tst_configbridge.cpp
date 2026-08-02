#include <QtTest>
#include "core/ConfigBridge.h"

class TestConfigBridge : public QObject {
    Q_OBJECT
private slots:
    void nestsDottedKeys();
    void keepsNestedValuesUntouched();
};

void TestConfigBridge::nestsDottedKeys() {
    QJsonObject flat;
    flat.insert("onebot.ws_url", "ws://127.0.0.1:3001");
    flat.insert("ai_context.enabled", true);
    const QJsonObject nested = nestDottedPatch(flat);
    QCOMPARE(nested.value("onebot").toObject().value("ws_url").toString(), "ws://127.0.0.1:3001");
    QCOMPARE(nested.value("ai_context").toObject().value("enabled").toBool(), true);
}

void TestConfigBridge::keepsNestedValuesUntouched() {
    QJsonObject value;
    value.insert("name", "x");
    QJsonObject flat;
    flat.insert("provider", value);
    const QJsonObject nested = nestDottedPatch(flat);
    QCOMPARE(nested.value("provider").toObject().value("name").toString(), "x");
}

QTEST_APPLESS_MAIN(TestConfigBridge)
#include "tst_configbridge.moc"
