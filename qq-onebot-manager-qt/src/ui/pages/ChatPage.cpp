#include "ChatPage.h"
#include "../Strings.h"
#include <QCheckBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QVBoxLayout>
#include <QTime>
#include <QTimer>

ChatPage::ChatPage(QWidget *parent) : QWidget(parent) {
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

    m_enabled = new QCheckBox(Strings::zh("chatEnabled"), container);
    layout->addWidget(m_enabled);

    auto *groupsBox = new QGroupBox(Strings::zh("chatGroups"), container);
    auto *gv = new QVBoxLayout(groupsBox);
    m_groups = new QListWidget(groupsBox);
    gv->addWidget(m_groups);
    auto *gButtons = new QHBoxLayout;
    auto *scan = new QPushButton(Strings::zh("scanGroups"), groupsBox);
    gButtons->addWidget(scan);
    gButtons->addStretch();
    gv->addLayout(gButtons);
    layout->addWidget(groupsBox);
    connect(scan, &QPushButton::clicked, this, [this] { emit groupsScanRequested(); });
    connect(m_groups, &QListWidget::itemChanged, this, [this] { markDirty(); });
    auto *groupsHint = new QLabel(Strings::zh("chatGroupsHint"), container);
    groupsHint->setObjectName("muted");
    groupsHint->setWordWrap(true);
    layout->addWidget(groupsHint);

    auto *personaBox = new QFormLayout;
    m_persona = new QPlainTextEdit(container);
    m_persona->setMaximumHeight(110);
    m_persona->setPlaceholderText(Strings::zh("chatPersonaPlaceholder"));
    personaBox->addRow(Strings::zh("chatPersona"), m_persona);
    layout->addLayout(personaBox);

    auto *memoryForm = new QFormLayout;
    m_memoryTurns = new QSpinBox(container);
    m_memoryTurns->setRange(1, 100);
    m_memoryTurns->setValue(10);
    memoryForm->addRow(Strings::zh("chatMemoryTurns"), m_memoryTurns);
    m_adminMemoryTurns = new QSpinBox(container);
    m_adminMemoryTurns->setRange(1, 500);
    m_adminMemoryTurns->setValue(50);
    memoryForm->addRow(Strings::zh("chatAdminMemoryTurns"), m_adminMemoryTurns);
    m_cooldown = new QSpinBox(container);
    m_cooldown->setRange(1, 3600);
    m_cooldown->setValue(5);
    memoryForm->addRow(Strings::zh("chatCooldownSeconds"), m_cooldown);
    layout->addLayout(memoryForm);

    auto *hint = new QLabel(Strings::zh("chatHint"), container);
    hint->setObjectName("muted");
    hint->setWordWrap(true);
    layout->addWidget(hint);
    layout->addStretch();

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

    connect(m_enabled, &QCheckBox::toggled, this, [this] { markDirty(); });
    connect(m_persona, &QPlainTextEdit::textChanged, this, [this] { markDirty(); });
    connect(m_memoryTurns, &QSpinBox::valueChanged, this, [this] { markDirty(); });
    connect(m_adminMemoryTurns, &QSpinBox::valueChanged, this, [this] { markDirty(); });
    connect(m_cooldown, &QSpinBox::valueChanged, this, [this] { markDirty(); });
    connect(m_save, &QPushButton::clicked, this, [this] {
        QJsonObject patch;
        patch.insert("chat.enabled", m_enabled->isChecked());
        patch.insert("chat.persona", m_persona->toPlainText().trimmed());
        patch.insert("chat.groups", QJsonArray::fromStringList(groupIds(m_groups)));
        patch.insert("chat.memory_turns", m_memoryTurns->value());
        patch.insert("chat.admin_memory_turns", m_adminMemoryTurns->value());
        patch.insert("chat.cooldown_seconds", m_cooldown->value());
        emit saveRequested(patch);
    });
}

void ChatPage::setSchema(bool ok, const QVariant &schemaVariant) {
    if (!ok) return;
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString key = obj.value("key").toString();
        const QJsonValue def = obj.value("default");
        if (key == "chat.enabled") m_enabled->setChecked(def.toBool());
        else if (key == "chat.persona") m_persona->setPlainText(def.toString());
        else if (key == "chat.groups") fillGroupList(m_groups, def.toArray());
        else if (key == "chat.memory_turns") m_memoryTurns->setValue(def.toInt(10));
        else if (key == "chat.admin_memory_turns") m_adminMemoryTurns->setValue(def.toInt(50));
        else if (key == "chat.cooldown_seconds") m_cooldown->setValue(def.toInt(5));
    }
    m_schemaLoaded = true;
    m_save->setEnabled(false);
}

void ChatPage::setSavedMessage(const QString &text) {
    if (text.isEmpty()) {
        m_message->clear();
        return;
    }
    m_message->setText(text + "  " + QTime::currentTime().toString("HH:mm:ss"));
    m_save->setEnabled(false);
    QTimer::singleShot(6000, m_message, [msg = m_message] { msg->clear(); });
}

QStringList ChatPage::groupIds(QListWidget *list) const {
    QStringList ids;
    if (!list) return ids;
    for (int i = 0; i < list->count(); ++i) {
        QListWidgetItem *item = list->item(i);
        if (item->checkState() == Qt::Checked)
            ids << item->data(Qt::UserRole).toString();
    }
    return ids;
}

void ChatPage::fillGroupList(QListWidget *list, const QJsonArray &ids) {
    if (!list) return;
    list->clear();
    for (const QJsonValue &value : ids) {
        const QString id = value.toString();
        if (id.isEmpty()) continue;
        auto *item = new QListWidgetItem(id, list);
        item->setData(Qt::UserRole, id);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(Qt::Checked);
        list->addItem(item);
    }
}

void ChatPage::setGroups(const QVariantList &groups) {
    if (!m_groups) return;
    int added = 0;
    for (const QVariant &group : groups) {
        const QJsonObject obj = group.toJsonObject();
        const QString id = obj.value("id").toString();
        const QString name = obj.value("name").toString();
        if (id.isEmpty()) continue;
        m_groupNames.insert(id, name);
        bool exists = false;
        for (int j = 0; j < m_groups->count(); ++j)
            if (m_groups->item(j)->data(Qt::UserRole).toString() == id) { exists = true; break; }
        if (exists) continue;
        auto *item = new QListWidgetItem(name.isEmpty() ? id : name + " (" + id + ")", m_groups);
        item->setData(Qt::UserRole, id);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(Qt::Unchecked);
        m_groups->addItem(item);
        added++;
    }
    if (added > 0) markDirty();
}

void ChatPage::markDirty() {
    if (m_schemaLoaded && m_save) m_save->setEnabled(true);
}
