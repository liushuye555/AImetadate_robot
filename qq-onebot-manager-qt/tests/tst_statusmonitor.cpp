#include <QtTest>
#include "core/StatusMonitor.h"

class TestStatusMonitor : public QObject {
    Q_OBJECT
private slots:
    void parsesValidJson();
    void missingFileIsInvalid();
    void staleFileIsInvalid();
};

void TestStatusMonitor::parsesValidJson() {
    const QDateTime now = QDateTime::currentDateTime();
    const QByteArray json =
        R"({"napcat":true,"onebot":true,"bot":true,"qqLoggedIn":true,"qqNumber":"123","qqNickname":"\u67f3\u6811\u53f6","updatedAt":")"
        + now.addSecs(-5).toUTC().toString(Qt::ISODate).toUtf8() + R"("})";
    const StatusSnapshot s = parseStatusJson(json, now);
    QVERIFY(s.valid);
    QVERIFY(s.napcat);
    QVERIFY(s.onebot);
    QVERIFY(s.bot);
    QVERIFY(s.qqLoggedIn);
    QCOMPARE(s.qqNumber, "123");
    QCOMPARE(s.qqNickname, QString::fromUtf8("柳树叶"));
}

void TestStatusMonitor::missingFileIsInvalid() {
    QVERIFY(!parseStatusJson(QByteArray(), QDateTime::currentDateTime()).valid);
}

void TestStatusMonitor::staleFileIsInvalid() {
    const QDateTime now = QDateTime::currentDateTime();
    const QByteArray json =
        R"({"napcat":true,"updatedAt":")"
        + now.addSecs(-60).toUTC().toString(Qt::ISODate).toUtf8() + R"("})";
    QVERIFY(!parseStatusJson(json, now).valid);
}

QTEST_APPLESS_MAIN(TestStatusMonitor)
#include "tst_statusmonitor.moc"
