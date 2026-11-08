#include <QtTest>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QFile>
#include "core/ConfigBridge.h"

class TestConfigBridge : public QObject {
    Q_OBJECT
private slots:
    void nestsDottedKeys();
    void keepsNestedValuesUntouched();
    void savesOfficialSecretThroughStdin();
    void migrationBlocksAllConfigurationWriters();
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

void TestConfigBridge::savesOfficialSecretThroughStdin() {
    QTemporaryDir temp;
    QVERIFY(temp.isValid());
    const QString path = temp.filePath("config.yaml");
    QFile initial(path);
    QVERIFY(initial.open(QIODevice::WriteOnly));
    initial.write("onebot:\n  provider: external\n");
    initial.close();
    ConfigBridge bridge(nullptr, path);
    QSignalSpy saved(&bridge, &ConfigBridge::saved);
    bridge.save({{"qq_official.app_id", "123"}, {"qq_official.app_secret", "qt-fixture-secret"}});
    QTRY_COMPARE_WITH_TIMEOUT(saved.size(), 1, 30000);
    QVERIFY(saved.at(0).at(0).toBool());
    QVERIFY(!saved.at(0).at(1).toString().contains("qt-fixture-secret"));
    QFile config(path);
    QVERIFY(config.open(QIODevice::ReadOnly));
    const QByteArray yaml = config.readAll();
    QVERIFY(yaml.contains("app_id"));
    QVERIFY(!yaml.contains("qt-fixture-secret"));
    QFile env(temp.filePath(".env"));
    QVERIFY(env.open(QIODevice::ReadOnly));
    QVERIFY(env.readAll().contains("QQBOT_APP_SECRET=qt-fixture-secret"));
}

void TestConfigBridge::migrationBlocksAllConfigurationWriters() {
    QTemporaryDir temp;
    QVERIFY(temp.isValid());
    const QString path = temp.filePath("config.yaml");
    ConfigBridge bridge(nullptr, path);
    QSignalSpy saved(&bridge, &ConfigBridge::saved);
    bridge.setWritesBlocked(true);
    bridge.save({{"onebot.provider", "napcat"}});
    bridge.saveEnv({{"TEST_KEY", "fixture"}});
    QCOMPARE(saved.size(), 2);
    QVERIFY(!saved.at(0).at(0).toBool());
    QVERIFY(!saved.at(1).at(0).toBool());
    QVERIFY(!QFile::exists(path));
    QVERIFY(!QFile::exists(temp.filePath(".env")));
    QVERIFY(!bridge.isBusy());
    bridge.setWritesBlocked(false);
    bridge.save({{"onebot.provider", "external"}});
    QTRY_COMPARE_WITH_TIMEOUT(saved.size(), 3, 30000);
    QVERIFY(saved.at(2).at(0).toBool());
    QVERIFY(QFile::exists(path));
}

QTEST_GUILESS_MAIN(TestConfigBridge)
#include "tst_configbridge.moc"
