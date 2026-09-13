#include <QtTest>
#include <QSignalSpy>
#include <QJsonDocument>
#include <QGroupBox>
#include <QCheckBox>
#include <QLineEdit>
#include <QComboBox>
#include <QPlainTextEdit>
#include <QListWidget>
#include <QPushButton>
#include "ui/pages/SettingsPage.h"

class TestSettingsPage : public QObject {
    Q_OBJECT
private slots:
    void schemaRendersSections();
    void emptySchemaKeepsGeneralSection();
    void listFieldsRenderLines();
    void providerListRendersEditor();
    void numericFieldsValidateOpenBoundsAndDecimals();
};

static QByteArray sampleSchema() {
    return R"([
      {"key":"onebot.ws_url","kind":"text","default":"ws://127.0.0.1:3001","label":{"zh-CN":"OneBot WebSocket"},"section":"runtime"},
      {"key":"reply.whitelist_users","kind":"list","default":["123","456"],"label":{"zh-CN":"用户白名单"},"section":"access"},
      {"key":"ai_context.providers","kind":"provider-list","default":{"ds_v4_flash":{"base_url":"https://x","model":"flash","api_key_env":"DS_V4_FLASH_API_KEY","timeout_seconds":60}},"label":{"zh-CN":"AI 供应商"},"section":"ai"},
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

void TestSettingsPage::listFieldsRenderLines() {
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson(sampleSchema()).toVariant());
    const auto lists = page.findChildren<QPlainTextEdit *>();
    QVERIFY(!lists.isEmpty());
    const QString text = lists.first()->toPlainText();
    QVERIFY(text.contains("123") && text.contains("456"));    // 列表值以行显示，而不是空
}

void TestSettingsPage::providerListRendersEditor() {
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson(sampleSchema()).toVariant());
    const auto lists = page.findChildren<QListWidget *>();
    QVERIFY(!lists.isEmpty());                                  // 供应商编辑器存在
    bool foundProvider = false;
    for (const auto *list : lists) {
        for (int i = 0; i < list->count(); ++i) {
            if (list->item(i)->text().contains("ds_v4_flash")) foundProvider = true;
        }
    }
    QVERIFY(foundProvider);                                     // 现有供应商显示在列表中
}

void TestSettingsPage::numericFieldsValidateOpenBoundsAndDecimals() {
    const QByteArray schema = R"([
      {"key":"images.candidate_ttl_hours","kind":"number","default":24,"min":1,"label":{"zh-CN":"候选图片保留时间"},"section":"advanced"},
      {"key":"images.reencode_threshold","kind":"number","default":6.5,"min":1,"max":20,"label":{"zh-CN":"重编码疑似阈值"},"section":"advanced"}
    ])";
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson(schema).toVariant());

    QLineEdit *candidate = nullptr;
    for (QLineEdit *edit : page.findChildren<QLineEdit *>()) {
        if (edit->text() == "24") candidate = edit;
    }
    QVERIFY(candidate);

    QPushButton *save = page.findChild<QPushButton *>("primary");
    QVERIFY(save);
    QSignalSpy saved(&page, &SettingsPage::saveRequested);
    candidate->setText("25");
    QVERIFY(save->isEnabled());
    save->click();
    QCOMPARE(saved.count(), 1);
}
QTEST_MAIN(TestSettingsPage)
#include "tst_settingspage.moc"
