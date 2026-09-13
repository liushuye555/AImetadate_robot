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
#include <algorithm>

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
    connect(scan, &QPushButton::clicked, this, [this] { emit groupsScanRequested(); });
    connect(m_expandForwards, &QCheckBox::toggled, this, [this] { markDirty(); });

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
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString key = obj.value("key").toString();
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
    m_schemaLoaded = true;
    m_dirty = false;
    m_save->setEnabled(false);
}

void CollectionPage::markDirty() {
    if (!m_schemaLoaded) return;
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
        if (!m_groupIds.contains(id)) m_groupIds << id;
        if (!m_collectionMap.contains(id))
            m_collectionMap.insert(id, QJsonObject{{"images", true}, {"links", true}, {"files", true}, {"forwards", true}});
    }
    rebuildCollectionList();
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
