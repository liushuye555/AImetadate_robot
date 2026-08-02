#include "SettingsPage.h"
#include "../Strings.h"
#include "core/AutoStart.h"
#include <QJsonDocument>
#include <QJsonArray>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QGroupBox>
#include <QFormLayout>
#include <QLineEdit>
#include <QCheckBox>
#include <QComboBox>
#include <QPushButton>
#include <QLabel>
#include <QPlainTextEdit>
#include <QListWidget>
#include <QListWidgetItem>
#include <QDialog>
#include <QDialogButtonBox>
#include <QSpinBox>
#include <QStyle>

SettingsPage::SettingsPage(QWidget *parent) : QWidget(parent) {
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(24, 24, 24, 24);
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    m_sections = new QVBoxLayout(container);
    scroll->setWidget(container);
    outer->addWidget(scroll, 1);

    m_sections->addWidget(buildGeneralSection());

    connect(m_language, &QComboBox::currentIndexChanged, this, [this] {
        emit languageChanged(m_language->currentData().toString());
    });
    connect(m_theme, &QComboBox::currentIndexChanged, this, [this] {
        emit themeChanged(m_theme->currentData().toString());
    });
    connect(m_autoStart, &QCheckBox::toggled, this, [this](bool on) {
        if (AutoStart::setEnabled(on)) {
            m_autoStart->setChecked(AutoStart::isEnabled());
        }
        emit autoStartToggled(AutoStart::isEnabled());
    });
    connect(m_notifications, &QCheckBox::toggled, this, &SettingsPage::notificationsToggled);

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
    connect(m_save, &QPushButton::clicked, this, [this] {
        emit saveRequested(buildPatch());
    });
}

QWidget *SettingsPage::buildGeneralSection() {
    auto *general = new QGroupBox(Strings::zh("general"), this);
    auto *generalForm = new QFormLayout(general);
    m_language = new QComboBox(general);
    m_language->addItem("跟随系统", "auto");
    m_language->addItem("中文", "zh-CN");
    m_language->addItem("English", "en-US");
    m_theme = new QComboBox(general);
    m_theme->addItem("浅色", "light");
    m_theme->addItem("深色", "dark");
    m_autoStart = new QCheckBox(general);
    m_autoStart->setChecked(AutoStart::isEnabled());
    m_notifications = new QCheckBox(general);
    m_notifications->setChecked(true);
    generalForm->addRow(Strings::zh("language"), m_language);
    generalForm->addRow(Strings::zh("theme"), m_theme);
    generalForm->addRow(Strings::zh("autoStart"), m_autoStart);
    generalForm->addRow(Strings::zh("notifications"), m_notifications);
    return general;
}

void SettingsPage::setSchema(const QVariant &schemaVariant) {
    QLayoutItem *child;
    while ((child = m_sections->takeAt(0)) != nullptr) {
        if (QWidget *w = child->widget()) w->deleteLater();
        delete child;
    }
    m_fields.clear();
    // 通用分组必须先重建，否则页面被清空后只剩空白
    m_sections->addWidget(buildGeneralSection());
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    QMap<QString, QFormLayout *> sections;
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString section = obj.value("section").toString();
        if (!sections.contains(section)) {
            auto *group = new QGroupBox(section, this);
            auto *form = new QFormLayout(group);
            sections.insert(section, form);
            m_sections->addWidget(group);
        }
        const QString key = obj.value("key").toString();
        const QString kind = obj.value("kind").toString();
        const QJsonObject label = obj.value("label").toObject();
        const QString text = label.value("zh-CN").toString(label.value("en-US").toString(key));
        QWidget *field = nullptr;
        if (kind == "bool") {
            auto *box = new QCheckBox(this);
            box->setChecked(obj.value("default").toBool());
            connect(box, &QCheckBox::toggled, this, [this] { markDirty(); });
            field = box;
        } else if (kind == "select") {
            auto *combo = new QComboBox(this);
            for (const QJsonValue &opt : obj.value("options").toArray()) combo->addItem(opt.toString());
            combo->setCurrentText(obj.value("default").toString());
            connect(combo, &QComboBox::currentTextChanged, this, [this] { markDirty(); });
            field = combo;
        } else if (kind == "list") {
            auto *edit = new QPlainTextEdit(this);
            edit->setMaximumHeight(110);
            const QJsonArray values = obj.value("default").toArray();
            QStringList lines;
            for (const QJsonValue &v : values) lines << v.toString();
            edit->setPlainText(lines.join('\n'));
            edit->setProperty("key", key);
            connect(edit, &QPlainTextEdit::textChanged, this, [this] { markDirty(); });
            field = edit;
        } else if (kind == "provider-list") {
            // 供应商单独用编辑器管理，不放进普通字段
            m_providerMap.clear();
            const QJsonObject providers = obj.value("default").toObject();
            for (auto it = providers.constBegin(); it != providers.constEnd(); ++it)
                m_providerMap.insert(it.key(), it.value().toObject());
            m_sections->addWidget(buildProviderSection());
            rebuildProviderList();
            continue;
        } else {
            auto *edit = new QLineEdit(this);
            if (kind == "secret") edit->setEchoMode(QLineEdit::Password);
            edit->setText(obj.value("default").toString());
            edit->setProperty("key", key);
            edit->setProperty("min", obj.value("min").toInt());
            edit->setProperty("max", obj.value("max").toInt());
            connect(edit, &QLineEdit::textChanged, this, [this, edit] {
                markDirty();
                bool ok = true;
                const int v = edit->text().toInt(&ok);
                const int min = edit->property("min").toInt();
                const int max = edit->property("max").toInt();
                const bool valid = !ok || (min == 0 && max == 0) || (v >= min && v <= max);
                edit->setProperty("class", valid ? "" : "invalid");
                edit->style()->unpolish(edit);
                edit->style()->polish(edit);
            });
            field = edit;
        }
        sections[section]->addRow(text, field);
        m_fields.insert(key, field);
    }
    if (items.isEmpty())
        m_message->setText(Strings::zh("error") + ": schema 为空");
    m_dirty = false;
    m_save->setEnabled(false);
}

void SettingsPage::markDirty() {
    m_dirty = true;
    m_save->setEnabled(true);
}

QJsonObject SettingsPage::buildPatch() const {
    QJsonObject patch;
    for (auto it = m_fields.constBegin(); it != m_fields.constEnd(); ++it) {
        const QString key = it.key();
        QWidget *w = it.value();
        if (auto *box = qobject_cast<QCheckBox *>(w)) patch.insert(key, box->isChecked());
        else if (auto *combo = qobject_cast<QComboBox *>(w)) patch.insert(key, combo->currentText());
        else if (auto *list = qobject_cast<QPlainTextEdit *>(w)) {
            QJsonArray values;
            const QStringList lines = list->toPlainText().split('\n');
            for (const QString &line : lines) {
                const QString trimmed = line.trimmed();
                if (!trimmed.isEmpty()) values.append(trimmed);
            }
            patch.insert(key, values);
        }
        else if (auto *edit = qobject_cast<QLineEdit *>(w)) patch.insert(key, edit->text());
    }
    return patch;
}

QJsonObject SettingsPage::buildProvidersObject() const {
    QJsonObject providers;
    for (auto it = m_providerMap.constBegin(); it != m_providerMap.constEnd(); ++it)
        providers.insert(it.key(), it.value());
    return providers;
}

void SettingsPage::rebuildProviderList() {
    if (!m_providerList) return;
    m_providerList->clear();
    for (auto it = m_providerMap.constBegin(); it != m_providerMap.constEnd(); ++it) {
        const QJsonObject p = it.value();
        const QString summary = it.key() + "  ·  " + p.value("base_url").toString()
            + "  ·  " + p.value("model").toString();
        auto *item = new QListWidgetItem(summary, m_providerList);
        item->setData(Qt::UserRole, it.key());
        m_providerList->addItem(item);
    }
}

QWidget *SettingsPage::buildProviderSection() {
    auto *group = new QGroupBox(Strings::zh("providers"), this);
    auto *layout = new QVBoxLayout(group);
    m_providerList = new QListWidget(group);
    layout->addWidget(m_providerList);
    auto *buttons = new QHBoxLayout;
    auto *add = new QPushButton(Strings::zh("addProvider"), group);
    auto *edit = new QPushButton(Strings::zh("editProvider"), group);
    auto *remove = new QPushButton(Strings::zh("removeProvider"), group);
    buttons->addWidget(add);
    buttons->addWidget(edit);
    buttons->addWidget(remove);
    buttons->addStretch();
    layout->addLayout(buttons);
    connect(add, &QPushButton::clicked, this, [this] { openProviderDialog(QString()); });
    connect(edit, &QPushButton::clicked, this, [this] {
        if (m_providerList->currentItem())
            openProviderDialog(m_providerList->currentItem()->data(Qt::UserRole).toString());
    });
    connect(remove, &QPushButton::clicked, this, [this] {
        QListWidgetItem *item = m_providerList->currentItem();
        if (!item) return;
        m_providerMap.remove(item->data(Qt::UserRole).toString());
        rebuildProviderList();
        emit providersChanged(buildProvidersObject(), QString(), QString());
    });
    return group;
}

void SettingsPage::openProviderDialog(const QString &editName) {
    QDialog dialog(this);
    dialog.setWindowTitle(editName.isEmpty() ? Strings::zh("addProvider") : Strings::zh("editProvider"));
    auto *form = new QFormLayout(&dialog);
    auto *nameEdit = new QLineEdit(&dialog);
    auto *urlEdit = new QLineEdit(&dialog);
    auto *modelEdit = new QLineEdit(&dialog);
    auto *keyEnvEdit = new QLineEdit(&dialog);
    auto *timeoutSpin = new QSpinBox(&dialog);
    timeoutSpin->setRange(1, 3600);
    timeoutSpin->setValue(60);
    auto *secretEdit = new QLineEdit(&dialog);
    secretEdit->setEchoMode(QLineEdit::Password);
    secretEdit->setPlaceholderText(Strings::zh("secretPlaceholder"));
    form->addRow("供应商 ID", nameEdit);
    form->addRow("Base URL", urlEdit);
    form->addRow("模型", modelEdit);
    form->addRow("Key 环境变量", keyEnvEdit);
    form->addRow(Strings::zh("providerTimeout"), timeoutSpin);
    form->addRow("API Key", secretEdit);
    if (!editName.isEmpty() && m_providerMap.contains(editName)) {
        const QJsonObject p = m_providerMap.value(editName);
        nameEdit->setText(editName);
        urlEdit->setText(p.value("base_url").toString());
        modelEdit->setText(p.value("model").toString());
        keyEnvEdit->setText(p.value("api_key_env").toString());
        timeoutSpin->setValue(p.value("timeout_seconds").toInt(60));
    }
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    const QString name = nameEdit->text().trimmed();
    if (name.isEmpty()) return;
    QJsonObject p;
    p.insert("base_url", urlEdit->text().trimmed());
    p.insert("model", modelEdit->text().trimmed());
    p.insert("api_key_env", keyEnvEdit->text().trimmed());
    p.insert("timeout_seconds", timeoutSpin->value());
    m_providerMap.insert(name, p);
    rebuildProviderList();
    emit providersChanged(buildProvidersObject(), keyEnvEdit->text().trimmed(), secretEdit->text());
}

void SettingsPage::setSavedMessage(const QString &text) {
    m_message->setText(text);
    if (!text.isEmpty()) {
        m_dirty = false;
        m_save->setEnabled(false);
    }
}

void SettingsPage::showError(const QString &text) {
    m_message->setText(Strings::zh("error") + ": " + text);
}
