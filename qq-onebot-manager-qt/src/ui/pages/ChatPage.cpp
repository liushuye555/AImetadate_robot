#include "ChatPage.h"
#include "../Strings.h"
#include <QCheckBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QVBoxLayout>

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
        patch.insert("chat.memory_turns", m_memoryTurns->value());
        patch.insert("chat.admin_memory_turns", m_adminMemoryTurns->value());
        patch.insert("chat.cooldown_seconds", m_cooldown->value());
        emit saveRequested(patch);
    });
}

void ChatPage::setSchema(const QVariant &schemaVariant) {
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString key = obj.value("key").toString();
        const QJsonValue def = obj.value("default");
        if (key == "chat.enabled") m_enabled->setChecked(def.toBool());
        else if (key == "chat.persona") m_persona->setPlainText(def.toString());
        else if (key == "chat.memory_turns") m_memoryTurns->setValue(def.toInt(10));
        else if (key == "chat.admin_memory_turns") m_adminMemoryTurns->setValue(def.toInt(50));
        else if (key == "chat.cooldown_seconds") m_cooldown->setValue(def.toInt(5));
    }
    m_save->setEnabled(false);
}

void ChatPage::setSavedMessage(const QString &text) {
    m_message->setText(text);
    if (!text.isEmpty()) m_save->setEnabled(false);
}

void ChatPage::markDirty() {
    if (m_save) m_save->setEnabled(true);
}
