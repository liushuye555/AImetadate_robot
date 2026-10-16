#include "CollectionPage.h"
#include "../Strings.h"
#include "../widgets/GroupItemRow.h"
#include "../../core/AvatarCache.h"
#include <QJsonDocument>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QGroupBox>
#include <QFormLayout>
#include <QCheckBox>
#include <QPushButton>
#include <QLabel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QBrush>
#include <QColor>
#include <QDialog>
#include <QDialogButtonBox>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QRadioButton>
#include <QStackedWidget>
#include <QFont>
#include <QTime>
#include <QTimer>
#include <QComboBox>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QRegularExpression>
#include <algorithm>

namespace {
// Defaults supply parameters only. Every opt-in is read from the group's own object.
bool explicitEnabled(const QJsonObject &object, const QString &key = QStringLiteral("enabled")) {
    return object.value(key).isBool() && object.value(key).toBool();
}

void insertPath(QJsonObject &object, const QStringList &path, const QJsonValue &value) {
    if (path.size() == 1) {
        object.insert(path.first(), value);
        return;
    }
    QJsonObject child = object.value(path.first()).toObject();
    insertPath(child, path.mid(1), value);
    object.insert(path.first(), child);
}

QJsonObject disabledKnowledgeGroup(QJsonObject group) {
    group.insert("enabled", false);
    for (const QString &feature : {QStringLiteral("summary"), QStringLiteral("extraction"),
                                  QStringLiteral("glossary"), QStringLiteral("files"),
                                  QStringLiteral("history"), QStringLiteral("notifications")}) {
        QJsonObject child = group.value(feature).toObject();
        child.insert("enabled", false);
        if (feature == "summary") {
            child.insert("daily", false);
            child.insert("weekly", false);
        } else if (feature == "files") {
            child.insert("preview_enabled", false);
        }
        group.insert(feature, child);
    }
    QJsonObject extraction = group.value("extraction").toObject();
    extraction.insert("track_topics", false);
    group.insert("extraction", extraction);
    QJsonObject glossary = group.value("glossary").toObject();
    glossary.insert("infer_context", false);
    group.insert("glossary", glossary);
    QJsonObject models = group.value("models").toObject();
    models.insert("tiered_enabled", false);
    models.insert("review_enabled", false);
    models.insert("circuit_enabled", false);
    group.insert("models", models);
    QJsonObject feedback = group.value("feedback").toObject();
    feedback.insert("enabled", false);
    feedback.insert("optimization_enabled", false);
    group.insert("feedback", feedback);
    return group;
}
}

CollectionPage::CollectionPage(QWidget *parent) : QWidget(parent) {
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(24, 24, 24, 24);
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    auto *layout = new QVBoxLayout(container);
    layout->setContentsMargins(4, 4, 4, 4);
    layout->setSpacing(14);
    scroll->setWidget(container);
    outer->addWidget(scroll, 1);

    // 采集总开关
    auto *stateCard = new QFrame(container);
    stateCard->setObjectName("card");
    auto *stateLayout = new QHBoxLayout(stateCard);
    stateLayout->setContentsMargins(18, 12, 18, 12);
    stateLayout->setSpacing(12);
    auto *stateTitle = new QLabel(Strings::zh("collectionState"), stateCard);
    stateTitle->setObjectName("sectionTitle");
    stateLayout->addWidget(stateTitle);
    stateLayout->addStretch();
    m_collectionToggle = new QPushButton(Strings::zh("collectionOn"), stateCard);
    m_collectionToggle->setCheckable(true);
    stateLayout->addWidget(m_collectionToggle);
    layout->addWidget(stateCard);
    connect(m_collectionToggle, &QPushButton::clicked, this, [this] {
        setCollectionPaused(m_collectionToggle->isChecked());
        emit collectionToggle();
    });

    // 内置采集模板
    auto *templates = new QGroupBox(Strings::zh("builtinTemplates"), container);
    auto *templateForm = new QFormLayout(templates);
    const struct { const char *key; const char *labelKey; } rows[] = {
        {"features.image_processing", "imageProcessing"},
        {"features.link_analysis", "linkAnalysis"},
        {"features.link_metadata", "linkMetadata"},
    };
    for (const auto &row : rows) {
        auto *box = new QCheckBox(templates);
        box->setChecked(true);  // 内置模板默认开启
        box->setProperty("key", QString::fromLatin1(row.key));
        connect(box, &QCheckBox::toggled, this, [this] { markDirty(); });
        templateForm->addRow(Strings::zh(QLatin1String(row.labelKey)), box);
        m_templateBoxes.insert(QString::fromLatin1(row.key), box);
    }
    layout->addWidget(templates);

    // 群级采集
    auto *groups = new QGroupBox(Strings::zh("groupCollection"), container);
    auto *v = new QVBoxLayout(groups);
    m_expandForwards = new QCheckBox(Strings::zh("expandForwards"), groups);
    v->addWidget(m_expandForwards);
    m_collectionList = new QListWidget(groups);
    m_collectionList->setObjectName("groupList");
    m_collectionList->setMinimumHeight(180);
    v->addWidget(m_collectionList);
    auto *gButtons = new QHBoxLayout;
    gButtons->setSpacing(10);
    auto *edit = new QPushButton(Strings::zh("editGroup"), groups);
    auto *scan = new QPushButton(Strings::zh("scanGroups"), groups);
    gButtons->addWidget(edit);
    gButtons->addWidget(scan);
    gButtons->addStretch();
    v->addLayout(gButtons);
    layout->addWidget(groups);
    auto *groupsHint = new QLabel(Strings::zh("collectionGroupsHint"), groups);
    groupsHint->setObjectName("muted");
    groupsHint->setWordWrap(true);
    v->addWidget(groupsHint);
    connect(edit, &QPushButton::clicked, this, [this] {
        if (m_collectionList->currentItem())
            openCollectionDialog(m_collectionList->currentItem()->data(Qt::UserRole).toString());
    });
    connect(m_collectionList, &QListWidget::itemChanged, this, [this](QListWidgetItem *item) {
        if (m_suppressGroupChange) return;
        const QString id = item->data(Qt::UserRole).toString();
        if (id.isEmpty() || m_blockedGroups.contains(id)) return;
        QJsonObject p = m_collectionMap.value(id);
        if (item->checkState() == Qt::Checked) {
            if (p.isEmpty() || (!p.value("images").toBool() && !p.value("links").toBool()
                                && !p.value("files").toBool() && !p.value("forwards").toBool())) {
                p = QJsonObject{{"images", true}, {"links", true}, {"files", true}, {"forwards", true}};
            }
        } else {
            p = QJsonObject{{"images", false}, {"links", false}, {"files", false}, {"forwards", false}};
        }
        m_collectionMap.insert(id, p);
        rebuildCollectionList();
        markDirty();
    });
    connect(scan, &QPushButton::clicked, this, [this] {
        m_knowledgeScanPending = false;
        emit groupsScanRequested();
    });
    connect(m_expandForwards, &QCheckBox::toggled, this, [this] { markDirty(); });

    auto *knowledge = new QGroupBox(QStringLiteral("群知识"), container);
    knowledge->setObjectName("knowledgeGroupBox");
    auto *kv = new QVBoxLayout(knowledge);
    m_knowledgeEnabled = new QCheckBox(QStringLiteral("启用群知识（独立总开关）"), knowledge);
    m_knowledgeEnabled->setObjectName("knowledgeEnabled");
    kv->addWidget(m_knowledgeEnabled);
    m_knowledgeList = new QListWidget(knowledge);
    m_knowledgeList->setObjectName("knowledgeGroups");
    m_knowledgeList->setMinimumHeight(150);
    kv->addWidget(m_knowledgeList);
    auto *kb = new QHBoxLayout;
    auto *kAdd = new QPushButton(QStringLiteral("新增群"), knowledge);
    kAdd->setObjectName("knowledgeAdd");
    auto *kEdit = new QPushButton(QStringLiteral("编辑群功能"), knowledge);
    kEdit->setObjectName("knowledgeEdit");
    auto *kRemove = new QPushButton(QStringLiteral("移除群"), knowledge);
    kRemove->setObjectName("knowledgeRemove");
    auto *kScan = new QPushButton(Strings::zh("scanGroups"), knowledge);
    kScan->setObjectName("knowledgeScan");
    kb->addWidget(kAdd);
    kb->addWidget(kEdit);
    kb->addWidget(kRemove);
    kb->addWidget(kScan);
    kb->addStretch();
    kv->addLayout(kb);
    auto *kHint = new QLabel(QStringLiteral("这里只列已选群；勾选仅控制该群开关，各子功能需分别启用。扫描和新增群不会自动开启知识功能。移除群会保存关闭标记及各子功能关闭状态（配置采用合并保存，不物理删除群键）。通知外发尚不支持，结果仅在本地查看。"), knowledge);
    kHint->setWordWrap(true);
    kHint->setObjectName("muted");
    kv->addWidget(kHint);
    layout->addWidget(knowledge);
    connect(m_knowledgeEnabled, &QCheckBox::toggled, this, [this] { markDirty(); });
    connect(kAdd, &QPushButton::clicked, this, [this] { openKnowledgeDialog({}); });
    connect(kEdit, &QPushButton::clicked, this, [this] {
        if (m_knowledgeList->currentItem())
            openKnowledgeDialog(m_knowledgeList->currentItem()->data(Qt::UserRole).toString());
    });
    connect(kRemove, &QPushButton::clicked, this, &CollectionPage::removeKnowledgeGroup);
    connect(kScan, &QPushButton::clicked, this, [this] {
        m_knowledgeScanPending = true;
        emit groupsScanRequested();
    });
    connect(m_knowledgeList, &QListWidget::itemDoubleClicked, this, [this](QListWidgetItem *item) {
        openKnowledgeDialog(item->data(Qt::UserRole).toString());
    });
    connect(m_knowledgeList, &QListWidget::itemChanged, this, [this](QListWidgetItem *item) {
        if (m_suppressKnowledgeChange) return;
        const QString scope = item->data(Qt::UserRole).toString();
        QJsonObject group = m_knowledgeGroups.value(scope).toObject();
        group.insert("enabled", item->checkState() == Qt::Checked);
        m_knowledgeGroups.insert(scope, group);
        markDirty();
    });

    // 自定义采集规则
    auto *rules = new QGroupBox(Strings::zh("customRules"), container);
    auto *rv = new QVBoxLayout(rules);
    m_customRuleList = new QListWidget(rules);
    rv->addWidget(m_customRuleList);
    auto *rButtons = new QHBoxLayout;
    rButtons->setSpacing(10);
    auto *rAdd = new QPushButton(Strings::zh("addRule"), rules);
    auto *rEdit = new QPushButton(Strings::zh("editRule"), rules);
    auto *rRemove = new QPushButton(Strings::zh("removeRule"), rules);
    auto *rEnable = new QPushButton(Strings::zh("batchEnable"), rules);
    auto *rDisable = new QPushButton(Strings::zh("batchDisable"), rules);
    auto *rUp = new QPushButton(Strings::zh("moveUp"), rules);
    auto *rDown = new QPushButton(Strings::zh("moveDown"), rules);
    rButtons->addWidget(rAdd);
    rButtons->addWidget(rEdit);
    rButtons->addWidget(rRemove);
    rButtons->addWidget(rEnable);
    rButtons->addWidget(rDisable);
    rButtons->addWidget(rUp);
    rButtons->addWidget(rDown);
    rButtons->addStretch();
    rv->addLayout(rButtons);
    layout->addWidget(rules);
    auto *hint = new QLabel(Strings::zh("customRulesHint"), container);
    hint->setObjectName("muted");
    hint->setWordWrap(true);
    layout->addWidget(hint);
    layout->addStretch();
    connect(rAdd, &QPushButton::clicked, this, [this] { openCustomRuleDialog(-1); });
    connect(rEdit, &QPushButton::clicked, this, [this] {
        if (m_customRuleList->currentItem())
            openCustomRuleDialog(m_customRuleList->currentItem()->data(Qt::UserRole).toInt());
    });
    connect(rRemove, &QPushButton::clicked, this, [this] {
        QListWidgetItem *item = m_customRuleList->currentItem();
        if (!item) return;
        const int index = item->data(Qt::UserRole).toInt();
        if (index < 0 || index >= m_customRules.size()) return;
        m_customRules.removeAt(index);
        rebuildCustomRuleList();
        markDirty();
    });
    connect(rEnable, &QPushButton::clicked, this, [this] { batchSetEnabled(true); });
    connect(rDisable, &QPushButton::clicked, this, [this] { batchSetEnabled(false); });
    connect(rUp, &QPushButton::clicked, this, [this] {
        QListWidgetItem *item = m_customRuleList->currentItem();
        if (!item) return;
        const int index = item->data(Qt::UserRole).toInt();
        if (index > 0 && index < m_customRules.size()) {
            const QJsonValue value = m_customRules.at(index);
            m_customRules[index] = m_customRules.at(index - 1);
            m_customRules[index - 1] = value;
            rebuildCustomRuleList();
            markDirty();
        }
    });
    connect(rDown, &QPushButton::clicked, this, [this] {
        QListWidgetItem *item = m_customRuleList->currentItem();
        if (!item) return;
        const int index = item->data(Qt::UserRole).toInt();
        if (index >= 0 && index < m_customRules.size() - 1) {
            const QJsonValue value = m_customRules.at(index);
            m_customRules[index] = m_customRules.at(index + 1);
            m_customRules[index + 1] = value;
            rebuildCustomRuleList();
            markDirty();
        }
    });
    connect(m_customRuleList, &QListWidget::itemChanged, this, [this](QListWidgetItem *item) {
        if (m_suppressRuleChange) return;
        const int index = item->data(Qt::UserRole).toInt();
        if (index < 0 || index >= m_customRules.size()) return;
        QJsonObject rule = m_customRules.at(index).toObject();
        rule.insert("enabled", item->checkState() == Qt::Checked);
        m_customRules[index] = rule;
        markDirty();
    });

    // 底部保存
    auto *bottom = new QHBoxLayout;
    m_save = new QPushButton(Strings::zh("save"), this);
    m_save->setObjectName("primary");
    m_message = new QLabel(this);
    m_message->setObjectName("muted");
    bottom->addWidget(m_save);
    bottom->addWidget(m_message);
    bottom->addStretch();
    outer->addLayout(bottom);
    m_save->setEnabled(false);
    connect(m_save, &QPushButton::clicked, this, [this] { emit saveRequested(buildPatch()); });
}

void CollectionPage::setSchema(bool ok, const QVariant &schemaVariant) {
    if (!ok) return;
    m_loadingConfig = true;
    m_knowledgeProviderOptions.clear();
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    QJsonObject knowledge;
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString key = obj.value("key").toString();
        if (key == "ai_context.provider") {
            for (const QJsonValue &option : obj.value("options").toArray()) {
                const QString name = option.toString();
                if (!name.isEmpty() && !m_knowledgeProviderOptions.contains(name)) m_knowledgeProviderOptions << name;
            }
        } else if (key == "ai_context.providers" && obj.value("kind").toString() == "provider-list") {
            const QJsonObject providers = obj.value("default").toObject();
            for (auto it = providers.constBegin(); it != providers.constEnd(); ++it)
                if (!m_knowledgeProviderOptions.contains(it.key())) m_knowledgeProviderOptions << it.key();
        }
        if (key == "knowledge") knowledge = obj.value("default").toObject();
        else if (key.startsWith("knowledge."))
            insertPath(knowledge, key.mid(10).split('.'), obj.value("default"));
        if (m_templateBoxes.contains(key)) {
            m_templateBoxes.value(key)->setChecked(obj.value("default").toBool());
        } else if (key == "collection.expand_forwards") {
            m_expandForwards->setChecked(obj.value("default").toBool());
        } else if (key == "collection.groups") {
            m_collectionMap.clear();
            const QJsonObject groups = obj.value("default").toObject();
            for (auto it = groups.constBegin(); it != groups.constEnd(); ++it) {
                m_collectionMap.insert(it.key(), it.value().toObject());
                if (!m_groupIds.contains(it.key())) m_groupIds << it.key();
            }
            rebuildCollectionList();
        } else if (key == "listen.blocked_groups") {
            m_blockedGroups.clear();
            for (const QJsonValue &v : obj.value("default").toArray())
                m_blockedGroups.insert(v.toString());
            rebuildCollectionList();
        } else if (key == "collection.rules") {
            m_customRules = obj.value("default").toArray();
            rebuildCustomRuleList();
        }
    }
    setConfig(QJsonObject{{"knowledge", knowledge}});
    m_loadingConfig = false;
    m_schemaLoaded = true;
    m_dirty = false;
    m_save->setEnabled(false);
}

void CollectionPage::markDirty() {
    if (!m_schemaLoaded || m_loadingConfig) return;
    m_dirty = true;
    m_save->setEnabled(true);
}

QJsonObject CollectionPage::buildPatch() const {
    QJsonObject patch;
    for (auto it = m_templateBoxes.constBegin(); it != m_templateBoxes.constEnd(); ++it)
        patch.insert(it.key(), it.value()->isChecked());
    patch.insert("collection.expand_forwards", m_expandForwards->isChecked());
    QJsonObject groups;
    for (int i = 0; i < m_collectionList->count(); ++i) {
        QListWidgetItem *item = m_collectionList->item(i);
        const QString id = item->data(Qt::UserRole).toString();
        if (id.isEmpty() || m_blockedGroups.contains(id)) continue;
        QJsonObject p = m_collectionMap.value(id);
        if (item->checkState() == Qt::Checked) {
            if (p.isEmpty()) p = QJsonObject{{"images", true}, {"links", true}, {"files", true}, {"forwards", true}};
        } else {
            p = QJsonObject{{"images", false}, {"links", false}, {"files", false}, {"forwards", false}};
        }
        groups.insert(id, p);
    }
    patch.insert("collection.groups", groups);
    patch.insert("collection.rules", m_customRules);
    patch.insert("knowledge", QJsonObject{{"enabled", m_knowledgeEnabled->isChecked()},
                                          {"groups", m_knowledgeGroups}});
    return patch;
}

void CollectionPage::setCollectionPaused(bool paused) {
    m_collectionPaused = paused;
    if (!m_collectionToggle) return;
    m_collectionToggle->setChecked(paused);
    m_collectionToggle->setText(paused ? Strings::zh("collectionOff") : Strings::zh("collectionOn"));
}

void CollectionPage::setGroups(const QVariantList &groups) {
    for (const QVariant &group : groups) {
        const QJsonObject obj = group.toJsonObject();
        const QString id = obj.value("id").toString();
        const QString name = obj.value("name").toString();
        if (id.isEmpty()) continue;
        m_groupNames.insert(id, name);
        if (!m_knowledgeAvailableGroups.contains(id)) m_knowledgeAvailableGroups << id;
        if (m_knowledgeScanPending) continue;
        if (!m_groupIds.contains(id)) m_groupIds << id;
        if (!m_collectionMap.contains(id))
            m_collectionMap.insert(id, QJsonObject{{"images", true}, {"links", true}, {"files", true}, {"forwards", true}});
    }
    if (m_knowledgeScanPending) {
        m_knowledgeScanPending = false;
        rebuildKnowledgeList();
        return;
    }
    rebuildCollectionList();
    rebuildKnowledgeList();
    markDirty();
}

void CollectionPage::setConfig(const QJsonObject &config) {
    const bool wasLoading = m_loadingConfig;
    m_loadingConfig = true;
    const QJsonObject knowledge = config.value("knowledge").toObject();
    m_knowledgeDefaults = knowledge.value("defaults").toObject();
    m_knowledgeGroups = knowledge.value("groups").toObject();
    m_removedKnowledgeGroups.clear();
    m_knowledgeEnabled->setChecked(explicitEnabled(knowledge));
    rebuildKnowledgeList();
    m_schemaLoaded = true;
    m_dirty = false;
    m_save->setEnabled(false);
    m_loadingConfig = wasLoading;
}

void CollectionPage::rebuildKnowledgeList() {
    m_suppressKnowledgeChange = true;
    m_knowledgeList->clear();
    for (auto it = m_knowledgeGroups.constBegin(); it != m_knowledgeGroups.constEnd(); ++it) {
        if (!it.key().startsWith("group:") || !it.value().isObject()
            || m_removedKnowledgeGroups.contains(it.key())) continue;
        const QString id = it.key().mid(6);
        const QString name = m_groupNames.value(id);
        auto *item = new QListWidgetItem(name.isEmpty() ? id : name + " · " + id, m_knowledgeList);
        item->setData(Qt::UserRole, it.key());
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(explicitEnabled(it.value().toObject()) ? Qt::Checked : Qt::Unchecked);
    }
    m_suppressKnowledgeChange = false;
}

void CollectionPage::removeKnowledgeGroup() {
    auto *item = m_knowledgeList->currentItem();
    if (!item) return;
    const QString scope = item->data(Qt::UserRole).toString();
    m_knowledgeGroups.insert(scope, disabledKnowledgeGroup(m_knowledgeGroups.value(scope).toObject()));
    m_removedKnowledgeGroups.insert(scope);
    rebuildKnowledgeList();
    markDirty();
}

void CollectionPage::openKnowledgeDialog(const QString &scope) {
    const QJsonObject original = scope.isEmpty() ? QJsonObject{} : m_knowledgeGroups.value(scope).toObject();
    QDialog dialog(this);
    dialog.setObjectName("knowledgeDialog");
    dialog.setWindowTitle(scope.isEmpty() ? QStringLiteral("新增群知识配置") : QStringLiteral("编辑群知识配置"));
    dialog.resize(570, 700);
    auto *outer = new QVBoxLayout(&dialog);
    auto *scroll = new QScrollArea(&dialog);
    scroll->setWidgetResizable(true);
    auto *content = new QWidget(scroll);
    auto *form = new QFormLayout(content);
    scroll->setWidget(content);
    outer->addWidget(scroll);
    auto *groupId = new QLineEdit(scope.mid(6), content);
    groupId->setObjectName("knowledgeGroupId");
    groupId->setReadOnly(!scope.isEmpty());
    form->addRow(QStringLiteral("群号"), groupId);
    if (scope.isEmpty()) {
        auto *choices = new QComboBox(content);
        choices->setObjectName("knowledgeGroupChoices");
        choices->addItem(QStringLiteral("可手动填写群号，或选择扫描到的群"), QString{});
        for (const QString &id : m_knowledgeAvailableGroups)
            choices->addItem(m_groupNames.value(id).isEmpty() ? id : m_groupNames.value(id) + " · " + id, id);
        form->addRow(QStringLiteral("已扫描群"), choices);
        connect(choices, &QComboBox::currentIndexChanged, groupId, [choices, groupId] {
            if (!choices->currentData().toString().isEmpty()) groupId->setText(choices->currentData().toString());
        });
    }
    auto *groupEnabled = new QCheckBox(QStringLiteral("启用此群（不改变子功能开关）"), content);
    groupEnabled->setObjectName("knowledgeGroupEnabled");
    groupEnabled->setChecked(explicitEnabled(original));
    form->addRow(groupEnabled);
    auto *topics = new QPlainTextEdit(content);
    topics->setObjectName("knowledgeTopics");
    topics->setMaximumHeight(90);
    topics->setPlaceholderText(QStringLiteral("每行一个主题；空列表表示不限制主题"));
    QStringList topicNames;
    const QJsonArray topicValues = original.contains("topics") ? original.value("topics").toArray()
                                                               : m_knowledgeDefaults.value("topics").toArray();
    for (const QJsonValue &value : topicValues) topicNames.append(value.toString());
    topics->setPlainText(topicNames.join('\n'));
    form->addRow(QStringLiteral("主题"), topics);
    auto *matchMode = new QComboBox(content);
    matchMode->setObjectName("knowledgeMatchMode");
    matchMode->addItems({"specialist", "generic", "hybrid"});
    const QString match = original.value("match_mode").toString(m_knowledgeDefaults.value("match_mode").toString("hybrid"));
    matchMode->setCurrentText(match);
    form->addRow(QStringLiteral("匹配模式"), matchMode);
    const QJsonObject lifecycle = original.value("lifecycle").toObject();
    const QJsonObject defaultLifecycle = m_knowledgeDefaults.value("lifecycle").toObject();
    auto *lifecycleEnabled = new QCheckBox(QStringLiteral("自动归档过期讨论"), content);
    lifecycleEnabled->setObjectName("knowledgeLifecycleEnabled");
    lifecycleEnabled->setChecked(explicitEnabled(lifecycle));
    form->addRow(lifecycleEnabled);
    auto makeLifecycleDays = [&](const QString &key, const QString &objectName, int fallback) {
        auto *spin = new QSpinBox(content);
        spin->setObjectName(objectName);
        spin->setRange(1, 3650);
        spin->setValue(lifecycle.value(key).toInt(defaultLifecycle.value(key).toInt(fallback)));
        spin->setSuffix(QStringLiteral(" 天"));
        return spin;
    };
    auto *briefDays = makeLifecycleDays("brief_days", "knowledgeLifecycleBriefDays", 3);
    auto *detailedDays = makeLifecycleDays("detailed_days", "knowledgeLifecycleDetailedDays", 14);
    auto *transientDays = makeLifecycleDays("transient_days", "knowledgeLifecycleTransientDays", 3);
    auto *resourceDays = makeLifecycleDays("resource_days", "knowledgeLifecycleResourceDays", 30);
    form->addRow(QStringLiteral("简短求助保留天数"), briefDays);
    form->addRow(QStringLiteral("详细问题保留天数"), detailedDays);
    form->addRow(QStringLiteral("时效信息保留天数"), transientDays);
    form->addRow(QStringLiteral("资源线索保留天数"), resourceDays);
    auto *lifecycleHint = new QLabel(QStringLiteral("仅本群明确开启后生效。按原消息最后有效进展计时，重复提问不续期；原文保留，知识条目长期保留。"), content);
    lifecycleHint->setObjectName("knowledgeLifecycleHint");
    lifecycleHint->setWordWrap(true);
    form->addRow(lifecycleHint);
    QMap<QString, QCheckBox *> featureBoxes;
    const QPair<QString, QString> features[] = {
        {"summary", QStringLiteral("总结")}, {"extraction", QStringLiteral("知识提取")},
        {"glossary", QStringLiteral("术语学习")}, {"files", QStringLiteral("文件保留")},
        {"history", QStringLiteral("历史回放")}, {"notifications", QStringLiteral("通知外发（尚不支持）")}
    };
    for (const auto &feature : features) {
        auto *box = new QCheckBox(feature.second, content);
        box->setObjectName("knowledgeFeature_" + feature.first);
        box->setChecked(feature.first != "notifications" && explicitEnabled(original.value(feature.first).toObject()));
        if (feature.first == "notifications") {
            box->setEnabled(false);
            box->setToolTip(QStringLiteral("当前仅支持本地结果，不会向群或个人发送通知。"));
        }
        form->addRow(box);
        featureBoxes.insert(feature.first, box);
    }
    const QJsonObject extraction = original.value("extraction").toObject();
    auto *trackTopics = new QCheckBox(QStringLiteral("追踪话题与后续反馈"), content);
    trackTopics->setObjectName("knowledgeTrackTopics");
    trackTopics->setChecked(explicitEnabled(extraction, "track_topics"));
    form->addRow(trackTopics);
    const QJsonObject glossary = original.value("glossary").toObject();
    auto *inferContext = new QCheckBox(QStringLiteral("从上下文推断术语"), content);
    inferContext->setObjectName("knowledgeInferContext");
    inferContext->setChecked(explicitEnabled(glossary, "infer_context"));
    form->addRow(inferContext);
    const QJsonObject summary = original.value("summary").toObject();
    auto *daily = new QCheckBox(QStringLiteral("每日计划"), content);
    daily->setObjectName("knowledgeDaily");
    daily->setChecked(explicitEnabled(summary, "daily"));
    auto *weekly = new QCheckBox(QStringLiteral("每周计划"), content);
    weekly->setObjectName("knowledgeWeekly");
    weekly->setChecked(explicitEnabled(summary, "weekly"));
    form->addRow(daily);
    form->addRow(weekly);
    const QJsonObject files = original.value("files").toObject();
    const QJsonObject defaultFiles = m_knowledgeDefaults.value("files").toObject();
    auto *filesMode = new QComboBox(content);
    filesMode->setObjectName("knowledgeFilesMode");
    filesMode->addItems({"high_value", "review", "index_only"});
    filesMode->setCurrentText(files.value("mode").toString(defaultFiles.value("mode").toString("high_value")));
    form->addRow(QStringLiteral("文件模式"), filesMode);
    auto *maxFile = new QSpinBox(content);
    maxFile->setObjectName("knowledgeMaxFileMb");
    maxFile->setRange(1, 102400);
    maxFile->setValue(files.value("max_file_mb").toInt(defaultFiles.value("max_file_mb").toInt(512)));
    maxFile->setSuffix(" MB");
    form->addRow(QStringLiteral("单文件上限"), maxFile);
    auto *budget = new QDoubleSpinBox(content);
    budget->setObjectName("knowledgeBudgetGb");
    budget->setRange(0, 100000);
    budget->setDecimals(3);
    budget->setValue(files.value("budget_gb").toDouble(defaultFiles.value("budget_gb").toDouble(20)));
    budget->setSuffix(" GB");
    form->addRow(QStringLiteral("群容量预算"), budget);
    const QJsonObject models = original.value("models").toObject();
    auto *tiered = new QCheckBox(QStringLiteral("启用分层模型"), content);
    tiered->setObjectName("knowledgeTieredEnabled");
    tiered->setChecked(explicitEnabled(models, "tiered_enabled"));
    auto *review = new QCheckBox(QStringLiteral("启用模型复审"), content);
    review->setObjectName("knowledgeReviewEnabled");
    review->setChecked(explicitEnabled(models, "review_enabled"));
    auto *feedback = new QCheckBox(QStringLiteral("启用反馈优化"), content);
    feedback->setObjectName("knowledgeOptimizationEnabled");
    feedback->setChecked(explicitEnabled(original.value("feedback").toObject(), "optimization_enabled"));
    auto *feedbackEnabled = new QCheckBox(QStringLiteral("启用反馈收集"), content);
    feedbackEnabled->setObjectName("knowledgeFeedbackEnabled");
    feedbackEnabled->setChecked(explicitEnabled(original.value("feedback").toObject()));
    auto *circuit = new QCheckBox(QStringLiteral("启用模型故障自动切换"), content);
    circuit->setObjectName("knowledgeCircuitEnabled");
    circuit->setChecked(explicitEnabled(models, "circuit_enabled"));
    const QJsonObject defaultModels = m_knowledgeDefaults.value("models").toObject();
    auto *primaryModel = new QLineEdit(models.value("primary_model").toString(defaultModels.value("primary_model").toString()), content);
    primaryModel->setObjectName("knowledgePrimaryModel");
    auto *reviewModel = new QLineEdit(models.value("review_model").toString(defaultModels.value("review_model").toString()), content);
    reviewModel->setObjectName("knowledgeReviewModel");
    auto *provider = new QComboBox(content);
    provider->setObjectName("knowledgeProvider");
    QStringList providerOptions = m_knowledgeProviderOptions;
    if (providerOptions.isEmpty()) providerOptions = {QStringLiteral("default"), QStringLiteral("ds_v4_flash")};
    const QString primaryProvider = models.value("primary_provider").toString(defaultModels.value("primary_provider").toString("default"));
    if (!providerOptions.contains(primaryProvider)) providerOptions << primaryProvider;
    provider->addItems(providerOptions);
    provider->setCurrentText(primaryProvider);
    auto *reviewProvider = new QComboBox(content);
    reviewProvider->setObjectName("knowledgeReviewProvider");
    reviewProvider->addItem(QStringLiteral("（继承主供应商）"), QString{});
    for (const QString &option : providerOptions) reviewProvider->addItem(option, option);
    const QString selectedReviewProvider = models.value("review_provider").toString(defaultModels.value("review_provider").toString());
    if (!selectedReviewProvider.isEmpty() && !providerOptions.contains(selectedReviewProvider))
        reviewProvider->addItem(selectedReviewProvider, selectedReviewProvider);
    const int reviewIndex = reviewProvider->findData(selectedReviewProvider);
    reviewProvider->setCurrentIndex(reviewIndex >= 0 ? reviewIndex : 0);
    auto *preview = new QCheckBox(QStringLiteral("启用小文件正文预览"), content);
    preview->setObjectName("knowledgePreviewEnabled");
    preview->setChecked(explicitEnabled(files, "preview_enabled"));
    form->addRow(tiered);
    form->addRow(review);
    form->addRow(circuit);
    form->addRow(QStringLiteral("模型提供方"), provider);
    form->addRow(QStringLiteral("复核供应商（可空，继承主供应商）"), reviewProvider);
    form->addRow(QStringLiteral("主模型（可空）"), primaryModel);
    form->addRow(QStringLiteral("复审模型（可空）"), reviewModel);
    form->addRow(feedbackEnabled);
    form->addRow(feedback);
    form->addRow(preview);
    auto *hint = new QLabel(QStringLiteral("全局、此群及具体子功能需分别开启。默认参数只提供主题、模式和容量；开关及计划不会继承默认值。历史回放还需开启至少一项处理功能。反馈优化需同时启用反馈收集和知识提取；正文预览需启用文件保留；话题追踪需分别启用知识提取，术语推断需分别启用术语学习。依赖项不会自动开启。"), content);
    hint->setWordWrap(true);
    form->addRow(hint);
    auto *validation = new QLabel(&dialog);
    validation->setObjectName("knowledgeValidation");
    outer->addWidget(validation);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    buttons->setObjectName("knowledgeDialogButtons");
    outer->addWidget(buttons);
    auto validate = [this, groupId, validation, buttons, scope] {
        const QString id = groupId->text().trimmed();
        const bool valid = QRegularExpression(QStringLiteral("^[1-9][0-9]*$")).match(id).hasMatch();
        const bool duplicate = scope.isEmpty() && m_knowledgeGroups.contains("group:" + id)
                               && !m_removedKnowledgeGroups.contains("group:" + id);
        buttons->button(QDialogButtonBox::Ok)->setEnabled(valid && !duplicate);
        validation->setText(duplicate ? QStringLiteral("此群已选，请从列表编辑。")
                                     : valid ? QString{} : QStringLiteral("请输入有效的数字群号。"));
    };
    connect(groupId, &QLineEdit::textChanged, &dialog, validate);
    validate();
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    const QString newScope = "group:" + groupId->text().trimmed();
    QJsonObject group = scope.isEmpty() ? disabledKnowledgeGroup(m_knowledgeGroups.value(newScope).toObject()) : original;
    group.insert("enabled", groupEnabled->isChecked());
    QJsonArray topicArray;
    for (const QString &line : topics->toPlainText().split('\n')) {
        if (!line.trimmed().isEmpty()) topicArray.append(line.trimmed());
    }
    group.insert("topics", topicArray);
    group.insert("match_mode", matchMode->currentText());
    QJsonObject newLifecycle = group.value("lifecycle").toObject();
    newLifecycle.insert("enabled", lifecycleEnabled->isChecked());
    newLifecycle.insert("brief_days", briefDays->value());
    newLifecycle.insert("detailed_days", detailedDays->value());
    newLifecycle.insert("transient_days", transientDays->value());
    newLifecycle.insert("resource_days", resourceDays->value());
    group.insert("lifecycle", newLifecycle);
    for (auto it = featureBoxes.constBegin(); it != featureBoxes.constEnd(); ++it) {
        QJsonObject child = group.value(it.key()).toObject();
        child.insert("enabled", it.value()->isChecked());
        group.insert(it.key(), child);
    }
    QJsonObject newExtraction = group.value("extraction").toObject();
    newExtraction.insert("track_topics", trackTopics->isChecked());
    group.insert("extraction", newExtraction);
    QJsonObject newGlossary = group.value("glossary").toObject();
    newGlossary.insert("infer_context", inferContext->isChecked());
    group.insert("glossary", newGlossary);
    QJsonObject newSummary = group.value("summary").toObject();
    newSummary.insert("daily", daily->isChecked());
    newSummary.insert("weekly", weekly->isChecked());
    group.insert("summary", newSummary);
    QJsonObject newFiles = group.value("files").toObject();
    newFiles.insert("mode", filesMode->currentText());
    newFiles.insert("max_file_mb", maxFile->value());
    newFiles.insert("budget_gb", budget->value());
    newFiles.insert("preview_enabled", preview->isChecked());
    group.insert("files", newFiles);
    QJsonObject newModels = group.value("models").toObject();
    newModels.insert("tiered_enabled", tiered->isChecked());
    newModels.insert("review_enabled", review->isChecked());
    newModels.insert("circuit_enabled", circuit->isChecked());
    newModels.insert("primary_provider", provider->currentText());
    newModels.insert("review_provider", reviewProvider->currentData().toString());
    newModels.insert("primary_model", primaryModel->text().trimmed());
    newModels.insert("review_model", reviewModel->text().trimmed());
    group.insert("models", newModels);
    QJsonObject newFeedback = group.value("feedback").toObject();
    newFeedback.insert("enabled", feedbackEnabled->isChecked());
    newFeedback.insert("optimization_enabled", feedback->isChecked());
    group.insert("feedback", newFeedback);
    if (group == original && newScope == scope) return;
    m_knowledgeGroups.insert(newScope, group);
    m_removedKnowledgeGroups.remove(newScope);
    rebuildKnowledgeList();
    markDirty();
}

bool CollectionPage::collectionChecked() const {
    return m_collectionToggle ? m_collectionToggle->isChecked() : m_collectionPaused;
}

void CollectionPage::setSavedMessage(const QString &text) {
    if (text.isEmpty()) {
        m_message->clear();
        return;
    }
    m_message->setText(text + "  " + QTime::currentTime().toString("HH:mm:ss"));
    m_dirty = false;
    m_save->setEnabled(false);
    QTimer::singleShot(6000, m_message, [msg = m_message] { msg->clear(); });
}

void CollectionPage::rebuildCollectionList() {
    if (!m_collectionList) return;
    m_suppressGroupChange = true;
    m_collectionList->clear();
    for (const QString &id : m_groupIds) {
        const QJsonObject p = m_collectionMap.value(id);
        const bool blocked = m_blockedGroups.contains(id);
        const QString name = m_groupNames.value(id);
        const QString displayName = name.isEmpty() ? id : name;
        // 原版 QQ 风两行条目：第一行群名，第二行群号与采集内容摘要
        QString summary = id;
        for (const char *tag : {"图片", "链接", "文件", "转发"}) {
            if (p.value(tag).toBool()) summary += QStringLiteral(" · ") + QString::fromUtf8(tag);
        }
        auto *item = new QListWidgetItem(m_collectionList);
        item->setData(Qt::UserRole, id);
        if (blocked) {
            item->setFlags(item->flags() & ~Qt::ItemIsUserCheckable);
            item->setForeground(QBrush(QColor("#8b96a8")));
            GroupItemRow::bind(m_collectionList, item, id, displayName, QStringLiteral("已屏蔽 · ") + summary, true);
        } else {
            item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
            const bool any = p.isEmpty() || p.value("images").toBool() || p.value("links").toBool()
                             || p.value("files").toBool() || p.value("forwards").toBool();
            item->setCheckState(any ? Qt::Checked : Qt::Unchecked);
            GroupItemRow::bind(m_collectionList, item, id, displayName, summary);
        }
        m_collectionList->addItem(item);
    }
    if (m_collectionList->count() == 0)
        m_collectionList->addItem(Strings::zh("collectionEmpty"));
    m_suppressGroupChange = false;
}

void CollectionPage::rebuildCustomRuleList() {
    if (!m_customRuleList) return;
    m_suppressRuleChange = true;
    m_customRuleList->clear();
    QMap<QString, QList<QPair<int, QJsonObject>>> byCategory;
    for (int i = 0; i < m_customRules.size(); ++i) {
        const QJsonObject rule = m_customRules.at(i).toObject();
        const QString category = rule.value("category").toString().trimmed().isEmpty()
            ? Strings::zh("uncategorized") : rule.value("category").toString();
        byCategory[category].append(qMakePair(i, rule));
    }
    for (auto it = byCategory.constBegin(); it != byCategory.constEnd(); ++it) {
        auto *header = new QListWidgetItem(it.key(), m_customRuleList);
        header->setFlags(Qt::NoItemFlags);
        QFont headerFont = header->font();
        headerFont.setBold(true);
        header->setFont(headerFont);
        m_customRuleList->addItem(header);
        for (const auto &pair : it.value()) {
            const int index = pair.first;
            const QJsonObject &rule = pair.second;
            const QString name = rule.value("name").toString();
            const QString keywords = rule.value("keywords").toArray().isEmpty()
                ? rule.value("regex").toString()
                : rule.value("keywords").toArray().first().toString();
            const QString summary = (rule.value("enabled").toBool(true) ? "" : "[停] ")
                + (name.isEmpty() ? Strings::zh("unnamed") : name)
                + (rule.value("ai_match").toBool(false) ? " [AI]" : rule.value("regex").toString().trimmed().isEmpty() ? "" : " [正则]")
                + (keywords.isEmpty() ? "" : "  ·  " + keywords);
            auto *item = new QListWidgetItem(summary, m_customRuleList);
            item->setData(Qt::UserRole, index);
            item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
            item->setCheckState(rule.value("enabled").toBool(true) ? Qt::Checked : Qt::Unchecked);
            m_customRuleList->addItem(item);
        }
    }
    if (m_customRules.isEmpty())
        m_customRuleList->addItem(Strings::zh("customRulesEmpty"));
    m_suppressRuleChange = false;
}

void CollectionPage::batchSetEnabled(bool enabled) {
    bool changed = false;
    for (int i = 0; i < m_customRules.size(); ++i) {
        QJsonObject rule = m_customRules.at(i).toObject();
        if (rule.value("enabled").toBool(true) == enabled) continue;
        rule.insert("enabled", enabled);
        m_customRules[i] = rule;
        changed = true;
    }
    if (changed) {
        rebuildCustomRuleList();
        markDirty();
    }
}

void CollectionPage::batchRemove() {
    QList<int> toRemove;
    for (int i = 0; i < m_customRuleList->count(); ++i) {
        QListWidgetItem *item = m_customRuleList->item(i);
        if (!item || !(item->flags() & Qt::ItemIsUserCheckable)) continue;
        if (item->checkState() == Qt::Checked)
            toRemove.append(item->data(Qt::UserRole).toInt());
    }
    if (!toRemove.isEmpty()) {
        std::sort(toRemove.begin(), toRemove.end(), std::greater<int>());
        for (int index : toRemove) {
            if (index >= 0 && index < m_customRules.size())
                m_customRules.removeAt(index);
        }
        rebuildCustomRuleList();
        markDirty();
    }
}

void CollectionPage::openCollectionDialog(const QString &editGroup) {
    QDialog dialog(this);
    dialog.setWindowTitle(editGroup.isEmpty() ? Strings::zh("addGroup") : Strings::zh("editGroup"));
    auto *form = new QFormLayout(&dialog);
    auto *groupEdit = new QLineEdit(&dialog);
    auto *images = new QCheckBox(Strings::zh("collectImages"), &dialog);
    auto *links = new QCheckBox(Strings::zh("collectLinks"), &dialog);
    auto *files = new QCheckBox(Strings::zh("collectFiles"), &dialog);
    auto *forwards = new QCheckBox(Strings::zh("collectForwards"), &dialog);
    images->setChecked(true);
    links->setChecked(true);
    files->setChecked(true);
    forwards->setChecked(true);
    form->addRow("群号", groupEdit);
    form->addRow(images);
    form->addRow(links);
    form->addRow(files);
    form->addRow(forwards);
    if (!editGroup.isEmpty() && m_collectionMap.contains(editGroup)) {
        const QJsonObject p = m_collectionMap.value(editGroup);
        groupEdit->setText(editGroup);
        images->setChecked(p.value("images").toBool(true));
        links->setChecked(p.value("links").toBool(true));
        files->setChecked(p.value("files").toBool(true));
        forwards->setChecked(p.value("forwards").toBool(true));
    }
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    const QString group = groupEdit->text().trimmed();
    if (group.isEmpty()) return;
    QJsonObject p;
    p.insert("images", images->isChecked());
    p.insert("links", links->isChecked());
    p.insert("files", files->isChecked());
    p.insert("forwards", forwards->isChecked());
    m_collectionMap.insert(group, p);
    rebuildCollectionList();
    markDirty();
}

void CollectionPage::openCustomRuleDialog(int editIndex) {
    QDialog dialog(this);
    dialog.setWindowTitle(editIndex < 0 ? Strings::zh("addRule") : Strings::zh("editRule"));
    dialog.resize(520, 470);
    auto *form = new QFormLayout(&dialog);
    auto *nameEdit = new QLineEdit(&dialog);
    auto *categoryEdit = new QLineEdit(&dialog);
    auto *enabled = new QCheckBox(Strings::zh("ruleEnabled"), &dialog);
    enabled->setChecked(true);
    auto *modeKeywords = new QRadioButton(Strings::zh("modeKeywords"), &dialog);
    auto *modeRegex = new QRadioButton(Strings::zh("modeRegex"), &dialog);
    auto *modeAi = new QRadioButton(Strings::zh("modeAi"), &dialog);
    modeKeywords->setChecked(true);
    auto *modeRow = new QHBoxLayout;
    modeRow->addWidget(modeKeywords);
    modeRow->addWidget(modeRegex);
    modeRow->addWidget(modeAi);
    modeRow->addStretch();
    auto *groupsEdit = new QPlainTextEdit(&dialog);
    groupsEdit->setMaximumHeight(90);
    groupsEdit->setPlaceholderText(Strings::zh("listPlaceholder"));
    auto *keywordsEdit = new QPlainTextEdit(&dialog);
    keywordsEdit->setMaximumHeight(90);
    keywordsEdit->setPlaceholderText(Strings::zh("keywordsPlaceholder"));
    auto *regexEdit = new QLineEdit(&dialog);
    auto *aiPrompt = new QPlainTextEdit(&dialog);
    aiPrompt->setMaximumHeight(80);
    aiPrompt->setPlaceholderText(Strings::zh("aiPromptPlaceholder"));
    auto *stack = new QStackedWidget(&dialog);
    stack->addWidget(keywordsEdit);
    stack->addWidget(regexEdit);
    stack->addWidget(aiPrompt);
    connect(modeKeywords, &QRadioButton::toggled, this, [stack](bool on) { if (on) stack->setCurrentIndex(0); });
    connect(modeRegex, &QRadioButton::toggled, this, [stack](bool on) { if (on) stack->setCurrentIndex(1); });
    connect(modeAi, &QRadioButton::toggled, this, [stack](bool on) { if (on) stack->setCurrentIndex(2); });
    auto *images = new QCheckBox(Strings::zh("collectImages"), &dialog);
    auto *links = new QCheckBox(Strings::zh("collectLinks"), &dialog);
    auto *files = new QCheckBox(Strings::zh("collectFiles"), &dialog);
    images->setChecked(true);
    links->setChecked(true);
    files->setChecked(true);
    form->addRow(Strings::zh("ruleName"), nameEdit);
    form->addRow(Strings::zh("ruleCategory"), categoryEdit);
    form->addRow(enabled);
    form->addRow(Strings::zh("matchMode"), modeRow);
    form->addRow(stack);
    form->addRow(Strings::zh("ruleGroups"), groupsEdit);
    form->addRow(images);
    form->addRow(links);
    form->addRow(files);
    if (editIndex >= 0 && editIndex < m_customRules.size()) {
        const QJsonObject rule = m_customRules.at(editIndex).toObject();
        nameEdit->setText(rule.value("name").toString());
        categoryEdit->setText(rule.value("category").toString());
        enabled->setChecked(rule.value("enabled").toBool(true));
        const bool useAi = rule.value("ai_match").toBool(false);
        const bool useRegex = !useAi && !rule.value("regex").toString().trimmed().isEmpty();
        if (useAi) modeAi->setChecked(true);
        else if (useRegex) modeRegex->setChecked(true);
        else modeKeywords->setChecked(true);
        QStringList groups;
        for (const QJsonValue &g : rule.value("groups").toArray()) groups << g.toString();
        groupsEdit->setPlainText(groups.join('\n'));
        QStringList keywords;
        for (const QJsonValue &k : rule.value("keywords").toArray()) keywords << k.toString();
        keywordsEdit->setPlainText(keywords.join('\n'));
        regexEdit->setText(rule.value("regex").toString());
        aiPrompt->setPlainText(rule.value("ai_prompt").toString());
        images->setChecked(rule.value("collect_images").toBool(true));
        links->setChecked(rule.value("collect_links").toBool(true));
        files->setChecked(rule.value("collect_files").toBool(true));
    }
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    if (nameEdit->text().trimmed().isEmpty()) return;
    QJsonArray groups;
    for (const QString &line : groupsEdit->toPlainText().split('\n')) {
        const QString trimmed = line.trimmed();
        if (!trimmed.isEmpty()) groups.append(trimmed);
    }
    QJsonArray keywords;
    if (modeKeywords->isChecked()) {
        for (const QString &line : keywordsEdit->toPlainText().split('\n')) {
            const QString trimmed = line.trimmed();
            if (!trimmed.isEmpty()) keywords.append(trimmed);
        }
    }
    QJsonObject rule;
    rule.insert("name", nameEdit->text().trimmed());
    rule.insert("category", categoryEdit->text().trimmed());
    rule.insert("enabled", enabled->isChecked());
    rule.insert("groups", groups);
    rule.insert("keywords", keywords);
    rule.insert("regex", modeRegex->isChecked() ? regexEdit->text().trimmed() : "");
    rule.insert("collect_images", images->isChecked());
    rule.insert("collect_links", links->isChecked());
    rule.insert("collect_files", files->isChecked());
    rule.insert("ai_match", modeAi->isChecked());
    rule.insert("ai_prompt", modeAi->isChecked() ? aiPrompt->toPlainText().trimmed() : "");
    if (editIndex >= 0 && editIndex < m_customRules.size())
        m_customRules[editIndex] = rule;
    else
        m_customRules.append(rule);
    rebuildCustomRuleList();
    markDirty();
}
