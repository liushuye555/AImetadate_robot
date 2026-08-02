#include <QtTest>
#include <QJsonDocument>
#include <QGroupBox>
#include <QCheckBox>
#include <QLineEdit>
#include <QComboBox>
#include "ui/pages/SettingsPage.h"

class TestSettingsPage : public QObject {
    Q_OBJECT
private slots:
    void schemaRendersSections();
    void emptySchemaKeepsGeneralSection();
};

static QByteArray sampleSchema() {
    return R"([
      {"key":"onebot.ws_url","kind":"text","default":"ws://127.0.0.1:3001","label":{"zh-CN":"OneBot WebSocket"},"section":"runtime"},
      {"key":"ai_context.enabled","kind":"bool","default":true,"label":{"zh-CN":"启用 AI 上下文"},"section":"ai"},
      {"key":"ai_context.scopes","kind":"select","default":"all_groups","options":["all_groups","whitelist_groups"],"label":{"zh-CN":"AI 分析范围"},"section":"ai"}
    ])";
}

void TestSettingsPage::schemaRendersSections() {
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson(sampleSchema()).toVariant());
    QVERIFY(page.findChildren<QGroupBox *>().size() >= 3);   // 通用 + runtime + ai
    QVERIFY(!page.findChildren<QCheckBox *>().isEmpty());
    QVERIFY(!page.findChildren<QLineEdit *>().isEmpty());
    QVERIFY(!page.findChildren<QComboBox *>().isEmpty());
}

void TestSettingsPage::emptySchemaKeepsGeneralSection() {
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson("[]").toVariant());
    QVERIFY(!page.findChildren<QGroupBox *>().isEmpty());     // 通用分组不能被清空
}

QTEST_MAIN(TestSettingsPage)
#include "tst_settingspage.moc"
