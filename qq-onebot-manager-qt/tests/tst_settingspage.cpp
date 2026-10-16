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
#include <QTimer>
#include <QDialog>
#include <QDialogButtonBox>
#include <QRegularExpression>
#include <QLabel>
#include "ui/pages/SettingsPage.h"

class TestSettingsPage : public QObject {
    Q_OBJECT
private slots:
    void schemaRendersSections();
    void emptySchemaKeepsGeneralSection();
    void listFieldsRenderLines();
    void providerListRendersEditor();
    void providerSecretGetsStableEnvironmentName();
    void providerWithoutKeyLocationCannotBeSaved();
    void providerEditPreservesSettingsAndExistingKeyReference();
    void numericFieldsValidateOpenBoundsAndDecimals();
    void settingsCannotOverwriteCollectionKnowledgeSwitch_data();
    void settingsCannotOverwriteCollectionKnowledgeSwitch();
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

void TestSettingsPage::providerSecretGetsStableEnvironmentName() {
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson(sampleSchema()).toVariant());
    QSignalSpy changed(&page, &SettingsPage::providersChanged);
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>();
        QVERIFY(dialog);
        auto closeOnFailure = qScopeGuard([dialog] { dialog->reject(); });
        dialog->findChild<QLineEdit *>("providerId")->setText(QStringLiteral("绘图-provider"));
        dialog->findChild<QLineEdit *>("providerUrl")->setText(QStringLiteral("https://example.invalid"));
        dialog->findChild<QLineEdit *>("providerModel")->setText(QStringLiteral("model-x"));
        dialog->findChild<QLineEdit *>("providerSecret")->setText(QStringLiteral("secret-value"));
        dialog->findChild<QDialogButtonBox *>()->button(QDialogButtonBox::Ok)->click();
        closeOnFailure.dismiss();
    });
    page.findChild<QPushButton *>("addProvider")->click();
    QCOMPARE(changed.count(), 1);
    const QList<QVariant> args = changed.takeFirst();
    const QString envName = args.at(1).toString();
    QVERIFY(envName.startsWith(QStringLiteral("AI_PROVIDER_")));
    QVERIFY(envName.endsWith(QStringLiteral("_API_KEY")));
    QVERIFY(!envName.contains(QRegularExpression(QStringLiteral("[^A-Z0-9_]"))));
    QCOMPARE(args.at(2).toString(), QStringLiteral("secret-value"));
    const QJsonObject providers = args.at(0).toJsonObject();
    QCOMPARE(providers.value(QStringLiteral("绘图-provider")).toObject().value("api_key_env").toString(), envName);
}

void TestSettingsPage::providerWithoutKeyLocationCannotBeSaved() {
    SettingsPage page;
    page.setSchema(QJsonDocument::fromJson(sampleSchema()).toVariant());
    QSignalSpy changed(&page, &SettingsPage::providersChanged);
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>();
        auto *name = dialog->findChild<QLineEdit *>();
        name->setText(QStringLiteral("empty-key-provider"));
        auto *buttons = dialog->findChild<QDialogButtonBox *>();
        QVERIFY(!buttons->button(QDialogButtonBox::Ok)->isEnabled());
        QVERIFY(dialog->findChild<QLabel *>("providerValidation")->text().contains(QStringLiteral("API Key")));
        dialog->reject();
    });
    page.findChild<QPushButton *>("addProvider")->click();
    QCOMPARE(changed.count(), 0);
}

void TestSettingsPage::providerEditPreservesSettingsAndExistingKeyReference() {
    SettingsPage page;
    const QJsonObject original{{"base_url", "https://example.invalid/v1"}, {"model", "kept"},
        {"api_key_env", "EXISTING_KEY"}, {"timeout_seconds", 91}, {"extra_setting", "preserved"},
        {"_credential_status", "configured"}};
    const QJsonArray schema{QJsonObject{{"key", "ai_context.providers"}, {"kind", "provider-list"},
        {"default", QJsonObject{{"freewb", original}}}}};
    page.setSchema(schema.toVariantList());
    page.findChild<QListWidget *>("providerList")->setCurrentRow(0);
    QVERIFY(page.findChild<QListWidget *>("providerList")->item(0)->text().contains(QStringLiteral("接口未验证")));
    QSignalSpy changed(&page, &SettingsPage::providersChanged);
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>();
        QVERIFY(dialog);
        auto closeOnFailure = qScopeGuard([dialog] { dialog->reject(); });
        QVERIFY(dialog->findChild<QLineEdit *>("providerId")->isReadOnly());
        dialog->findChild<QLineEdit *>("providerModel")->setText(QStringLiteral("updated"));
        auto *ok = dialog->findChild<QDialogButtonBox *>()->button(QDialogButtonBox::Ok);
        QVERIFY(ok->isEnabled());
        ok->click();
        closeOnFailure.dismiss();
    });
    page.findChild<QPushButton *>("editProvider")->click();
    QCOMPARE(changed.count(), 1);
    const auto args = changed.takeFirst();
    const auto saved = args.at(0).toJsonObject().value("freewb").toObject();
    QCOMPARE(saved.value("extra_setting").toString(), QStringLiteral("preserved"));
    QCOMPARE(saved.value("api_key_env").toString(), QStringLiteral("EXISTING_KEY"));
    QCOMPARE(saved.value("timeout_seconds").toInt(), 91);
    QVERIFY(!saved.contains("_credential_status"));
    QCOMPARE(args.at(2).toString(), QString{});
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

void TestSettingsPage::settingsCannotOverwriteCollectionKnowledgeSwitch_data() {
    QTest::addColumn<bool>("cachedEnabled");
    QTest::newRow("collection-has-enabled") << false;
    QTest::newRow("collection-has-disabled") << true;
}

void TestSettingsPage::settingsCannotOverwriteCollectionKnowledgeSwitch() {
    QFETCH(bool, cachedEnabled);
    // A settings save can already be queued when the collection save finishes,
    // before the asynchronous schema refresh reaches this page.
    const QJsonArray schema{
        QJsonObject{{"key", "knowledge.enabled"}, {"kind", "bool"},
            {"default", cachedEnabled}, {"section", "knowledge"}},
        QJsonObject{{"key", "knowledge.defaults.interval_minutes"}, {"kind", "number"},
            {"default", 15}, {"min", 1}, {"max", 1440}, {"section", "knowledge"}},
        QJsonObject{{"key", "onebot.ws_url"}, {"kind", "text"},
            {"default", "ws://before"}, {"section", "runtime"}}
    };
    SettingsPage page;
    page.setSchema(schema.toVariantList());
    bool edited = false;
    for (auto *field : page.findChildren<QLineEdit *>()) {
        if (field->text() == "ws://before") {
            field->setText("ws://after");
            edited = true;
        }
    }
    QVERIFY(edited);
    QSignalSpy saved(&page, &SettingsPage::saveRequested);
    page.findChild<QPushButton *>("primary")->click();
    QCOMPARE(saved.count(), 1);
    const auto patch = saved.takeFirst().at(0).toJsonObject();
    QCOMPARE(patch.value("onebot.ws_url").toString(), QStringLiteral("ws://after"));
    QVERIFY(patch.contains("knowledge.defaults.interval_minutes"));
    QVERIFY2(!patch.contains("knowledge.enabled"),
             "Saving settings must not write the separately owned collection knowledge switch");
}
QTEST_MAIN(TestSettingsPage)
#include "tst_settingspage.moc"
