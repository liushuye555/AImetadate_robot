#include "RelayPage.h"
#include "../Strings.h"
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QListWidgetItem>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QVBoxLayout>

RelayPage::RelayPage(QWidget *parent) : QWidget(parent) {
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

    m_enabled = new QCheckBox(Strings::zh("relayEnabled"), container);
    layout->addWidget(m_enabled);

    auto *modeForm = new QGroupBox(Strings::zh("relayMode"), container);
    auto *form = new QFormLayout(modeForm);
    m_mode = new QComboBox(modeForm);
    m_mode->addItem(Strings::zh("relayWhitelist"), QString("whitelist"));
    m_mode->addItem(Strings::zh("relayBlacklist"), QString("blacklist"));
    form->addRow(Strings::zh("relayMode"), m_mode);
    layout->addWidget(modeForm);

    layout->addWidget(buildGroupBox(Strings::zh("relayGroups"), m_groups, true));
    layout->addWidget(buildGroupBox(Strings::zh("relayInputGroups"), m_inputGroups, false));
    layout->addWidget(buildGroupBox(Strings::zh("relayOutputGroups"), m_outputGroups, false));

    auto *hint = new QLabel(Strings::zh("relayGroupsHint"), container);
    hint->setObjectName("muted");
    hint->setWordWrap(true);
    layout->addWidget(hint);

    m_ordinary = new QCheckBox(Strings::zh("relayOrdinary"), container);
    m_ordinary->setChecked(true);
    layout->addWidget(m_ordinary);

    auto *textBox = new QGroupBox(Strings::zh("relayText"), container);
    auto *textForm = new QFormLayout(textBox);
    m_keywords = new QPlainTextEdit(textBox);
    m_keywords->setPlaceholderText(Strings::zh("listPlaceholder"));
    m_keywords->setMaximumHeight(90);
    textForm->addRow(Strings::zh("relayKeywords"), m_keywords);
    m_regex = new QLineEdit(textBox);
    m_regex->setPlaceholderText(Strings::zh("optionalPlaceholder"));
    textForm->addRow(Strings::zh("relayRegex"), m_regex);
    layout->addWidget(textBox);

    m_aiFilter = new QCheckBox(Strings::zh("relayAiFilter"), container);
    layout->addWidget(m_aiFilter);

    auto *extra = new QFormLayout;
    m_dedupeHours = new QSpinBox(container);
    m_dedupeHours->setRange(1, 168);
    m_dedupeHours->setValue(24);
    extra->addRow(Strings::zh("relayDedupeHours"), m_dedupeHours);
    layout->addLayout(extra);

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
    connect(m_mode, &QComboBox::currentIndexChanged, this, [this] { markDirty(); });
    connect(m_ordinary, &QCheckBox::toggled, this, [this] { markDirty(); });
    connect(m_keywords, &QPlainTextEdit::textChanged, this, [this] { markDirty(); });
    connect(m_regex, &QLineEdit::textChanged, this, [this] { markDirty(); });
    connect(m_aiFilter, &QCheckBox::toggled, this, [this] { markDirty(); });
    connect(m_dedupeHours, &QSpinBox::valueChanged, this, [this] { markDirty(); });
    connect(m_save, &QPushButton::clicked, this, [this] {
        QJsonObject patch;
        patch.insert("relay.enabled", m_enabled->isChecked());
        patch.insert("relay.mode", m_mode->currentData().toString());
        patch.insert("relay.groups", QJsonArray::fromStringList(groupIds(m_groups)));
        patch.insert("relay.input_groups", QJsonArray::fromStringList(groupIds(m_inputGroups)));
        patch.insert("relay.output_groups", QJsonArray::fromStringList(groupIds(m_outputGroups)));
        patch.insert("relay.ordinary", m_ordinary->isChecked());
        QStringList keywords;
        for (const QString &line : m_keywords->toPlainText().split('\n'))
            if (!line.trimmed().isEmpty())
                keywords << line.trimmed();
        patch.insert("relay.text_keywords", QJsonArray::fromStringList(keywords));
        patch.insert("relay.text_regex", m_regex->text().trimmed());
        patch.insert("relay.ai_filter", m_aiFilter->isChecked());
        patch.insert("relay.dedupe_hours", m_dedupeHours->value());
        emit saveRequested(patch);
    });
}

QWidget *RelayPage::buildGroupBox(const QString &title, QListWidget *&list, bool withScan) {
    auto *box = new QGroupBox(title, this);
    auto *v = new QVBoxLayout(box);
    list = new QListWidget(box);
    v->addWidget(list);
    auto *buttons = new QHBoxLayout;
    auto *add = new QPushButton(Strings::zh("addGroup"), box);
    auto *edit = new QPushButton(Strings::zh("editGroup"), box);
    auto *remove = new QPushButton(Strings::zh("removeGroup"), box);
    buttons->addWidget(add);
    buttons->addWidget(edit);
    buttons->addWidget(remove);
    if (withScan) {
        auto *scan = new QPushButton(Strings::zh("scanGroups"), box);
        buttons->addWidget(scan);
        connect(scan, &QPushButton::clicked, this, [this] { emit groupsScanRequested(); });
    }
    buttons->addStretch();
    v->addLayout(buttons);
    connect(add, &QPushButton::clicked, this, [this, list] { openGroupDialog(list, QString()); });
    connect(edit, &QPushButton::clicked, this, [this, list] {
        if (list->currentItem())
            openGroupDialog(list, list->currentItem()->data(Qt::UserRole).toString());
    });
    connect(remove, &QPushButton::clicked, this, [this, list] {
        if (!list->currentItem()) return;
        delete list->takeItem(list->row(list->currentItem()));
        markDirty();
    });
    connect(list, &QListWidget::itemChanged, this, [this] { markDirty(); });
    return box;
}

void RelayPage::openGroupDialog(QListWidget *list, const QString &editId) {
    QDialog dialog(this);
    dialog.setWindowTitle(editId.isEmpty() ? Strings::zh("addGroup") : Strings::zh("editGroup"));
    auto *layout = new QVBoxLayout(&dialog);
    auto *edit = new QLineEdit(editId, &dialog);
    edit->setPlaceholderText(Strings::zh("groupIdPlaceholder"));
    layout->addWidget(edit);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    const QString id = edit->text().trimmed();
    if (id.isEmpty()) return;
    if (editId.isEmpty()) {
        auto *item = new QListWidgetItem(id, list);
        item->setData(Qt::UserRole, id);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(Qt::Checked);
        list->addItem(item);
    } else {
        for (int i = 0; i < list->count(); ++i) {
            if (list->item(i)->data(Qt::UserRole).toString() == editId) {
                list->item(i)->setText(id);
                list->item(i)->setData(Qt::UserRole, id);
                break;
            }
        }
    }
    markDirty();
}

QStringList RelayPage::groupIds(QListWidget *list) const {
    QStringList ids;
    if (!list) return ids;
    for (int i = 0; i < list->count(); ++i) {
        QListWidgetItem *item = list->item(i);
        if (item->checkState() == Qt::Checked)
            ids << item->data(Qt::UserRole).toString();
    }
    return ids;
}

void RelayPage::setSchema(const QVariant &schemaVariant) {
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString key = obj.value("key").toString();
        const QJsonValue def = obj.value("default");
        if (key == "relay.enabled") m_enabled->setChecked(def.toBool());
        else if (key == "relay.mode") {
            const QString mode = def.toString();
            const int idx = m_mode->findData(mode);
            if (idx >= 0) m_mode->setCurrentIndex(idx);
        } else if (key == "relay.groups") fillGroupList(m_groups, def.toArray());
        else if (key == "relay.input_groups") fillGroupList(m_inputGroups, def.toArray());
        else if (key == "relay.output_groups") fillGroupList(m_outputGroups, def.toArray());
        else if (key == "relay.ordinary") m_ordinary->setChecked(def.toBool());
        else if (key == "relay.text_keywords") {
            QStringList lines;
            for (const QJsonValue &v : def.toArray())
                lines << v.toString();
            m_keywords->setPlainText(lines.join('\n'));
        } else if (key == "relay.text_regex") m_regex->setText(def.toString());
        else if (key == "relay.ai_filter") m_aiFilter->setChecked(def.toBool());
        else if (key == "relay.dedupe_hours") m_dedupeHours->setValue(def.toInt(24));
    }
    m_save->setEnabled(false);
}

void RelayPage::setGroups(const QVariantList &groups) {
    QDialog dialog(this);
    dialog.setWindowTitle(Strings::zh("scanGroups"));
    auto *layout = new QVBoxLayout(&dialog);
    auto *list = new QListWidget(&dialog);
    for (const QVariant &group : groups) {
        const QJsonObject obj = group.toJsonObject();
        const QString id = obj.value("id").toString();
        const QString name = obj.value("name").toString();
        auto *item = new QListWidgetItem(name.isEmpty() ? id : name + " (" + id + ")", list);
        item->setData(Qt::UserRole, id);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(Qt::Unchecked);
        list->addItem(item);
    }
    layout->addWidget(list);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    int added = 0;
    for (int i = 0; i < list->count(); ++i) {
        const QString id = list->item(i)->data(Qt::UserRole).toString();
        if (id.isEmpty()) continue;
        bool exists = false;
        for (int j = 0; j < m_groups->count(); ++j)
            if (m_groups->item(j)->data(Qt::UserRole).toString() == id) { exists = true; break; }
        if (exists) continue;
        auto *newItem = new QListWidgetItem(id, m_groups);
        newItem->setData(Qt::UserRole, id);
        newItem->setFlags(newItem->flags() | Qt::ItemIsUserCheckable);
        newItem->setCheckState(list->item(i)->checkState());
        m_groups->addItem(newItem);
        added++;
    }
    if (added > 0) markDirty();
}

void RelayPage::fillGroupList(QListWidget *list, const QJsonArray &ids) {
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

void RelayPage::setSavedMessage(const QString &text) {
    m_message->setText(text);
    if (!text.isEmpty()) m_save->setEnabled(false);
}

void RelayPage::markDirty() {
    if (m_save) m_save->setEnabled(true);
}
