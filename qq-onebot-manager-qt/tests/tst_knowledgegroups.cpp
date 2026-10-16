#include <QtTest>
#include <QSignalSpy>
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QLineEdit>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSpinBox>
#include <QTimer>
#include <QScopeGuard>
#include "ui/pages/CollectionPage.h"
#include "core/AvatarCache.h"

// This target exercises configuration only. Legacy collection rows must not
// start avatar downloads or create a network worker while the test exits.
AvatarCache::AvatarCache(QObject *parent) : QObject(parent) {}
AvatarCache &AvatarCache::instance() {
    static AvatarCache cache;
    return cache;
}
QPixmap AvatarCache::placeholder(const QString &, int size) {
    QPixmap pixmap(size, size);
    pixmap.fill(Qt::gray);
    return pixmap;
}
void AvatarCache::fetch(const QString &, const QString &id, std::function<void(const QPixmap &)> callback) {
    callback(placeholder(id, 32));
}
void AvatarCache::decorateGroup(QListWidget *, const QString &, const QString &) {}

class TestKnowledgeGroups : public QObject {
    Q_OBJECT
private slots:
    void defaultsCannotEnableFeatures();
    void newGroupOnlyEnablesItsOwnSwitch();
    void roundTripPreservesUnknownFields();
    void groupsRemainIndependent();
    void cancelDoesNotDirtyPage();
    void removalWritesExplicitShutdown();
    void scanDoesNotSelectOrEnableGroups();
    void schemaLoadsGroupObjects();
    void primaryProviderRoundTrip();
    void providerOptionsAndReviewProviderRoundTrip();
    void knowledgeOptInsRoundTrip();
    void lifecycleRoundTrip();
};

static QJsonObject savePatch(CollectionPage &page) {
    QSignalSpy spy(&page, &CollectionPage::saveRequested);
    page.findChild<QPushButton *>("primary")->click();
    return spy.isEmpty() ? QJsonObject{} : spy.first().first().value<QJsonObject>();
}

static QJsonObject groupsOf(const QJsonObject &patch) {
    return patch.value("knowledge").toObject().value("groups").toObject();
}

static void selectGroup(CollectionPage &page, const QString &scope) {
    auto *list = page.findChild<QListWidget *>("knowledgeGroups");
    for (int i = 0; i < list->count(); ++i)
        if (list->item(i)->data(Qt::UserRole).toString() == scope) list->setCurrentRow(i);
}

void TestKnowledgeGroups::primaryProviderRoundTrip() {
    CollectionPage page;
    const QJsonObject models{{"primary_provider", "ds_v4_flash"}, {"primary_model", "chosen-model"}, {"tiered_enabled", true}};
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"groups", QJsonObject{{"group:123", QJsonObject{{"models", models}}}}}}}});
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        QCOMPARE(dialog->findChild<QComboBox *>("knowledgeProvider")->currentText(), QStringLiteral("ds_v4_flash"));
        dialog->findChild<QComboBox *>("knowledgeProvider")->setCurrentText("default");
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    const QJsonObject saved = groupsOf(savePatch(page)).value("group:123").toObject().value("models").toObject();
    QCOMPARE(saved.value("primary_provider").toString(), QStringLiteral("default"));
    QCOMPARE(saved.value("primary_model").toString(), QStringLiteral("chosen-model"));
}

void TestKnowledgeGroups::providerOptionsAndReviewProviderRoundTrip() {
    CollectionPage page;
    const QJsonArray schema{
        QJsonObject{{"key", "ai_context.providers"}, {"kind", "provider-list"},
                    {"default", QJsonObject{{"freewb", QJsonObject{}}, {"ds_v4_flash", QJsonObject{}}, {"private-x", QJsonObject{}}}}},
        QJsonObject{{"key", "knowledge.defaults"}, {"default", QJsonObject{}}},
        QJsonObject{{"key", "knowledge.groups"}, {"default", QJsonObject{}}}
    };
    const QJsonObject models{{"primary_provider", "private-x"}, {"review_provider", "legacy-review"}};
    page.setSchema(true, schema.toVariantList());
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"groups", QJsonObject{{"group:123", QJsonObject{{"models", models}}}}}}}});
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        QVERIFY(dialog);
        auto *primary = dialog->findChild<QComboBox *>("knowledgeProvider");
        auto *review = dialog->findChild<QComboBox *>("knowledgeReviewProvider");
        QVERIFY(primary->findText("freewb") >= 0);
        QVERIFY(primary->findText("ds_v4_flash") >= 0);
        QCOMPARE(primary->currentText(), QStringLiteral("private-x"));
        QCOMPARE(review->currentData().toString(), QStringLiteral("legacy-review"));
        review->setCurrentIndex(0);
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    const QJsonObject saved = groupsOf(savePatch(page)).value("group:123").toObject().value("models").toObject();
    QCOMPARE(saved.value("primary_provider").toString(), QStringLiteral("private-x"));
    QCOMPARE(saved.value("review_provider").toString(), QString{});
}

void TestKnowledgeGroups::knowledgeOptInsRoundTrip() {
    CollectionPage page;
    const QJsonObject extraction{{"enabled", true}, {"track_topics", true}, {"unknown", "keep"}};
    const QJsonObject glossary{{"enabled", true}, {"infer_context", true}, {"unknown", "keep"}};
    const QJsonObject defaults{{"extraction", QJsonObject{{"enabled", true}, {"track_topics", true}}},
                               {"glossary", QJsonObject{{"enabled", true}, {"infer_context", true}}}};
    const QJsonObject original{{"extraction", extraction}, {"glossary", glossary}};
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"defaults", defaults},
        {"groups", QJsonObject{{"group:123", original}}}}}});
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        QVERIFY(dialog);
        const auto closeDialog = qScopeGuard([dialog] {
            if (dialog->result() != QDialog::Accepted) dialog->reject();
        });
        auto *trackTopics = dialog->findChild<QCheckBox *>("knowledgeTrackTopics");
        auto *inferContext = dialog->findChild<QCheckBox *>("knowledgeInferContext");
        QVERIFY(trackTopics);
        QVERIFY(inferContext);
        QVERIFY(trackTopics->isChecked());
        QVERIFY(inferContext->isChecked());
        trackTopics->setChecked(false);
        inferContext->setChecked(false);
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    QJsonObject saved = groupsOf(savePatch(page)).value("group:123").toObject();
    QCOMPARE(saved.value("extraction").toObject().value("track_topics"), QJsonValue(false));
    QCOMPARE(saved.value("glossary").toObject().value("infer_context"), QJsonValue(false));
    QCOMPARE(saved.value("extraction").toObject().value("unknown").toString(), QStringLiteral("keep"));
    QCOMPARE(saved.value("glossary").toObject().value("unknown").toString(), QStringLiteral("keep"));
}

void TestKnowledgeGroups::lifecycleRoundTrip() {
    CollectionPage page;
    const QJsonObject defaults{{"enabled", true}, {"brief_days", 8}, {"detailed_days", 21},
                               {"transient_days", 5}, {"resource_days", 60}};
    const QJsonObject originalLifecycle{{"enabled", true}, {"brief_days", 4}, {"resource_days", 45},
                                        {"future", QJsonObject{{"keep", true}}}};
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"defaults", QJsonObject{{"lifecycle", defaults}}},
        {"groups", QJsonObject{{"group:123", QJsonObject{{"lifecycle", originalLifecycle}}}}}}}});
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        QVERIFY(dialog);
        const auto closeDialog = qScopeGuard([dialog] {
            if (dialog->result() != QDialog::Accepted) dialog->reject();
        });
        auto *enabled = dialog->findChild<QCheckBox *>("knowledgeLifecycleEnabled");
        auto *brief = dialog->findChild<QSpinBox *>("knowledgeLifecycleBriefDays");
        auto *detailed = dialog->findChild<QSpinBox *>("knowledgeLifecycleDetailedDays");
        auto *transient = dialog->findChild<QSpinBox *>("knowledgeLifecycleTransientDays");
        auto *resource = dialog->findChild<QSpinBox *>("knowledgeLifecycleResourceDays");
        QVERIFY(enabled && brief && detailed && transient && resource);
        QVERIFY(enabled->isChecked());
        QCOMPARE(brief->value(), 4);
        QCOMPARE(detailed->value(), 21);
        QCOMPARE(transient->value(), 5);
        QCOMPARE(resource->value(), 45);
        enabled->setChecked(false);
        brief->setValue(6);
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    const QJsonObject saved = groupsOf(savePatch(page)).value("group:123").toObject().value("lifecycle").toObject();
    QCOMPARE(saved.value("enabled"), QJsonValue(false));
    QCOMPARE(saved.value("brief_days").toInt(), 6);
    QCOMPARE(saved.value("detailed_days").toInt(), 21);
    QCOMPARE(saved.value("transient_days").toInt(), 5);
    QCOMPARE(saved.value("resource_days").toInt(), 45);
    QCOMPARE(saved.value("future"), originalLifecycle.value("future"));
}

void TestKnowledgeGroups::defaultsCannotEnableFeatures() {
    CollectionPage page;
    QJsonObject defaults{{"enabled", true}, {"match_mode", "specialist"},
                         {"topics", QJsonArray{"研究"}},
                         {"summary", QJsonObject{{"enabled", true}, {"daily", true}, {"weekly", true}}},
                         {"files", QJsonObject{{"enabled", true}, {"preview_enabled", true}, {"max_file_mb", 99}}},
                         {"models", QJsonObject{{"tiered_enabled", true}, {"review_enabled", true}, {"circuit_enabled", true}}},
                         {"feedback", QJsonObject{{"enabled", true}, {"optimization_enabled", true}}}};
    defaults.insert("extraction", QJsonObject{{"enabled", true}, {"track_topics", true}});
    defaults.insert("glossary", QJsonObject{{"enabled", true}, {"infer_context", true}});
    defaults.insert("lifecycle", QJsonObject{{"enabled", true}, {"brief_days", 8}, {"detailed_days", 21},
                                              {"transient_days", 5}, {"resource_days", 60}});
    for (const QString &feature : {QStringLiteral("history"), QStringLiteral("notifications")})
        defaults.insert(feature, QJsonObject{{"enabled", true}});
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"defaults", defaults},
                                  {"groups", QJsonObject{{"group:123", QJsonObject{}}}}}}});
    QVERIFY(!page.findChild<QCheckBox *>("knowledgeEnabled")->isChecked());
    auto *list = page.findChild<QListWidget *>("knowledgeGroups");
    QCOMPARE(list->count(), 1);
    QCOMPARE(list->item(0)->checkState(), Qt::Unchecked);
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        QVERIFY(dialog);
        const auto closeDialog = qScopeGuard([dialog] { dialog->reject(); });
        for (auto *box : dialog->findChildren<QCheckBox *>()) QVERIFY(!box->isChecked());
        QVERIFY(dialog->findChild<QCheckBox *>("knowledgeTrackTopics"));
        QVERIFY(dialog->findChild<QCheckBox *>("knowledgeInferContext"));
        QVERIFY(!dialog->findChild<QCheckBox *>("knowledgeLifecycleEnabled")->isChecked());
        QCOMPARE(dialog->findChild<QSpinBox *>("knowledgeLifecycleBriefDays")->value(), 8);
        QCOMPARE(dialog->findChild<QSpinBox *>("knowledgeLifecycleDetailedDays")->value(), 21);
        QCOMPARE(dialog->findChild<QSpinBox *>("knowledgeLifecycleTransientDays")->value(), 5);
        QCOMPARE(dialog->findChild<QSpinBox *>("knowledgeLifecycleResourceDays")->value(), 60);
        QCOMPARE(dialog->findChild<QComboBox *>("knowledgeMatchMode")->currentText(), QStringLiteral("specialist"));
        QCOMPARE(dialog->findChild<QPlainTextEdit *>("knowledgeTopics")->toPlainText(), QStringLiteral("研究"));
        QCOMPARE(dialog->findChild<QSpinBox *>("knowledgeMaxFileMb")->value(), 99);
        QVERIFY(!dialog->findChild<QCheckBox *>("knowledgeFeature_notifications")->isEnabled());
        dialog->reject();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    QVERIFY(!page.findChild<QPushButton *>("primary")->isEnabled());
}

void TestKnowledgeGroups::newGroupOnlyEnablesItsOwnSwitch() {
    CollectionPage page;
    page.setConfig({});
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        QVERIFY(dialog);
        dialog->findChild<QLineEdit *>("knowledgeGroupId")->setText("123");
        dialog->findChild<QCheckBox *>("knowledgeGroupEnabled")->setChecked(true);
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeAdd")->click();
    const QJsonObject patch = savePatch(page);
    const QJsonObject group = groupsOf(patch).value("group:123").toObject();
    QVERIFY(group.value("enabled").toBool());
    QVERIFY(!patch.value("knowledge").toObject().value("enabled").toBool());
    for (const QString &feature : {QStringLiteral("summary"), QStringLiteral("extraction"),
                                  QStringLiteral("glossary"), QStringLiteral("files"),
                                  QStringLiteral("history"), QStringLiteral("notifications"), QStringLiteral("feedback")}) {
        const QJsonValue flag = group.value(feature).toObject().value("enabled");
        QVERIFY(flag.isBool());
        QVERIFY(!flag.toBool());
    }
    QVERIFY(!group.value("summary").toObject().value("daily").toBool());
    QVERIFY(!group.value("summary").toObject().value("weekly").toBool());
    QVERIFY(!group.value("files").toObject().value("preview_enabled").toBool());
    QVERIFY(!group.value("feedback").toObject().value("optimization_enabled").toBool());
    QVERIFY(group.value("extraction").toObject().value("track_topics").isBool());
    QVERIFY(!group.value("extraction").toObject().value("track_topics").toBool());
    QVERIFY(group.value("glossary").toObject().value("infer_context").isBool());
    QVERIFY(!group.value("glossary").toObject().value("infer_context").toBool());
    for (const QString &flag : {QStringLiteral("tiered_enabled"), QStringLiteral("review_enabled"), QStringLiteral("circuit_enabled")})
        QVERIFY(!group.value("models").toObject().value(flag).toBool());
    auto *list = page.findChild<QListWidget *>("knowledgeGroups");
    list->item(0)->setCheckState(Qt::Unchecked);
    list->item(0)->setCheckState(Qt::Checked);
    QCOMPARE(groupsOf(savePatch(page)), groupsOf(patch));
    QVERIFY(patch.contains("collection.groups"));
    QVERIFY(patch.contains("collection.rules"));
    QVERIFY(patch.contains("features.image_processing"));
}

void TestKnowledgeGroups::roundTripPreservesUnknownFields() {
    CollectionPage page;
    const QJsonObject groups{{"group:123", QJsonObject{{"custom", QJsonObject{{"list", QJsonArray{1, "x"}}}},
                                  {"summary", QJsonObject{{"enabled", true}, {"hour", 17}, {"unknown", "keep"}}}}},
                             {"group:456", QJsonObject{{"future_feature", QJsonObject{{"enabled", true}}}}},
                             {"future-key", QJsonArray{1, 2}}};
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"groups", groups}, {"defaults", QJsonObject{{"topics", QJsonArray{"a"}}}}}}});
    page.findChild<QCheckBox *>("knowledgeEnabled")->setChecked(true);
    QCOMPARE(groupsOf(savePatch(page)), groups);
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        dialog->findChild<QPlainTextEdit *>("knowledgeTopics")->setPlainText("one\ntwo");
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    const QJsonObject result = groupsOf(savePatch(page));
    QCOMPARE(result.value("group:456"), groups.value("group:456"));
    QCOMPARE(result.value("future-key"), groups.value("future-key"));
    QCOMPARE(result.value("group:123").toObject().value("custom"), groups.value("group:123").toObject().value("custom"));
    const QJsonObject summary = result.value("group:123").toObject().value("summary").toObject();
    QCOMPARE(summary.value("hour").toInt(), 17);
    QCOMPARE(summary.value("unknown").toString(), QStringLiteral("keep"));
}

void TestKnowledgeGroups::groupsRemainIndependent() {
    CollectionPage page;
    const QJsonObject other{{"enabled", true}, {"summary", QJsonObject{{"enabled", true}}}, {"topics", QJsonArray{"other"}}};
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"groups", QJsonObject{{"group:123", QJsonObject{}}, {"group:456", other}}}}}});
    selectGroup(page, "group:123");
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        dialog->findChild<QCheckBox *>("knowledgeFeature_extraction")->setChecked(true);
        dialog->findChild<QCheckBox *>("knowledgeOptimizationEnabled")->setChecked(true);
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeEdit")->click();
    const QJsonObject result = groupsOf(savePatch(page));
    QCOMPARE(result.value("group:456").toObject(), other);
    const QJsonObject first = result.value("group:123").toObject();
    QVERIFY(first.value("extraction").toObject().value("enabled").toBool());
    QVERIFY(first.value("feedback").toObject().value("optimization_enabled").toBool());
    QVERIFY(!first.value("feedback").toObject().value("enabled").toBool());
    QVERIFY(!first.value("summary").toObject().value("enabled").toBool());
    QVERIFY(!first.value("enabled").toBool());
}

void TestKnowledgeGroups::cancelDoesNotDirtyPage() {
    CollectionPage page;
    page.setConfig({});
    QSignalSpy spy(&page, &CollectionPage::saveRequested);
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        dialog->findChild<QLineEdit *>("knowledgeGroupId")->setText("123");
        dialog->findChild<QCheckBox *>("knowledgeFeature_extraction")->setChecked(true);
        dialog->reject();
    });
    page.findChild<QPushButton *>("knowledgeAdd")->click();
    QVERIFY(!page.findChild<QPushButton *>("primary")->isEnabled());
    QCOMPARE(page.findChild<QListWidget *>("knowledgeGroups")->count(), 0);
    QCOMPARE(spy.count(), 0);
}

void TestKnowledgeGroups::removalWritesExplicitShutdown() {
    CollectionPage page;
    const QJsonObject original{{"enabled", true}, {"opaque", "keep"},
                               {"summary", QJsonObject{{"enabled", true}, {"daily", true}, {"weekly", true}, {"hour", 12}}},
                               {"models", QJsonObject{{"tiered_enabled", true}, {"review_enabled", true}, {"circuit_enabled", true}, {"primary_model", "keep"}}},
                               {"feedback", QJsonObject{{"enabled", true}, {"optimization_enabled", true}}},
                               {"files", QJsonObject{{"enabled", true}, {"preview_enabled", true}, {"max_file_mb", 42}}}};
    page.setConfig(QJsonObject{{"knowledge", QJsonObject{{"groups", QJsonObject{{"group:123", original}}}}}});
    selectGroup(page, "group:123");
    page.findChild<QPushButton *>("knowledgeRemove")->click();
    QCOMPARE(page.findChild<QListWidget *>("knowledgeGroups")->count(), 0);
    const QJsonObject group = groupsOf(savePatch(page)).value("group:123").toObject();
    QVERIFY(!group.value("enabled").toBool());
    for (const QString &feature : {QStringLiteral("summary"), QStringLiteral("extraction"),
                                  QStringLiteral("glossary"), QStringLiteral("files"),
                                  QStringLiteral("history"), QStringLiteral("notifications"), QStringLiteral("feedback")})
        QCOMPARE(group.value(feature).toObject().value("enabled"), QJsonValue(false));
    QCOMPARE(group.value("summary").toObject().value("daily"), QJsonValue(false));
    QCOMPARE(group.value("summary").toObject().value("weekly"), QJsonValue(false));
    QCOMPARE(group.value("files").toObject().value("preview_enabled"), QJsonValue(false));
    QCOMPARE(group.value("models").toObject().value("circuit_enabled"), QJsonValue(false));
    QCOMPARE(group.value("feedback").toObject().value("optimization_enabled"), QJsonValue(false));
    QCOMPARE(group.value("opaque").toString(), QStringLiteral("keep"));
    QCOMPARE(group.value("files").toObject().value("max_file_mb").toInt(), 42);
}

void TestKnowledgeGroups::scanDoesNotSelectOrEnableGroups() {
    CollectionPage page;
    page.setConfig({});
    QSignalSpy scanSpy(&page, &CollectionPage::groupsScanRequested);
    page.findChild<QPushButton *>("knowledgeScan")->click();
    QCOMPARE(scanSpy.count(), 1);
    page.setGroups(QVariantList{QJsonObject{{"id", "123"}, {"name", "群 A"}}.toVariantMap()});
    QCOMPARE(page.findChild<QListWidget *>("knowledgeGroups")->count(), 0);
    QVERIFY(!page.findChild<QPushButton *>("primary")->isEnabled());
    QVERIFY(!page.findChild<QCheckBox *>("knowledgeEnabled")->isChecked());
    QTimer::singleShot(0, &page, [&page] {
        auto *dialog = page.findChild<QDialog *>("knowledgeDialog");
        auto *choices = dialog->findChild<QComboBox *>("knowledgeGroupChoices");
        const auto closeDialog = qScopeGuard([dialog] {
            if (dialog->result() != QDialog::Accepted) dialog->reject();
        });
        choices->setCurrentIndex(1);
        QCOMPARE(dialog->findChild<QLineEdit *>("knowledgeGroupId")->text(), QStringLiteral("123"));
        QVERIFY(!dialog->findChild<QCheckBox *>("knowledgeGroupEnabled")->isChecked());
        dialog->findChild<QDialogButtonBox *>("knowledgeDialogButtons")->button(QDialogButtonBox::Ok)->click();
    });
    page.findChild<QPushButton *>("knowledgeAdd")->click();
    const QJsonObject selected = groupsOf(savePatch(page)).value("group:123").toObject();
    QCOMPARE(selected.value("enabled"), QJsonValue(false));
    QCOMPARE(selected.value("extraction").toObject().value("enabled"), QJsonValue(false));
    page.findChild<QCheckBox *>("knowledgeEnabled")->setChecked(true);
    const QJsonObject patch = savePatch(page);
    QCOMPARE(groupsOf(patch).size(), 1);
    QCOMPARE(groupsOf(patch).value("group:123").toObject(), selected);
    QVERIFY(patch.value("collection.groups").toObject().isEmpty());
}

void TestKnowledgeGroups::schemaLoadsGroupObjects() {
    CollectionPage page;
    const QJsonObject group{{"enabled", true}, {"extraction", QJsonObject{{"enabled", true}}}, {"unknown", "retained"}};
    const QJsonObject groups{{"group:123", group}};
    const QJsonArray schema{
        QJsonObject{{"key", "knowledge.enabled"}, {"default", false}},
        QJsonObject{{"key", "knowledge.defaults"}, {"default", QJsonObject{{"match_mode", "generic"}}}},
        QJsonObject{{"key", "knowledge.groups"}, {"default", groups}},
        QJsonObject{{"key", "collection.groups"}, {"default", QJsonObject{{"789", QJsonObject{{"images", false}, {"files", true}}}}}}
    };
    page.setSchema(true, schema.toVariantList());
    QCOMPARE(page.findChild<QListWidget *>("knowledgeGroups")->count(), 1);
    QCOMPARE(page.findChild<QListWidget *>("knowledgeGroups")->item(0)->checkState(), Qt::Checked);
    page.findChild<QCheckBox *>("knowledgeEnabled")->setChecked(true);
    const QJsonObject patch = savePatch(page);
    QCOMPARE(groupsOf(patch), groups);
    QVERIFY(patch.value("collection.groups").toObject().value("789").toObject().value("files").toBool());
}

QTEST_MAIN(TestKnowledgeGroups)
#include "tst_knowledgegroups.moc"
