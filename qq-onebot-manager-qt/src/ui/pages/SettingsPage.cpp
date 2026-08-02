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

    // 通用设置
    auto *general = new QGroupBox(Strings::zh("general"), container);
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
    m_sections->addWidget(general);

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

void SettingsPage::setSchema(const QVariant &schemaVariant) {
    QLayoutItem *child;
    while ((child = m_sections->takeAt(0)) != nullptr) {
        if (QWidget *w = child->widget()) w->deleteLater();
        delete child;
    }
    m_fields.clear();
    // 通用分组在最后重建（先删掉旧的再重插，保持顺序：通用在最上）
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
        else if (auto *edit = qobject_cast<QLineEdit *>(w)) patch.insert(key, edit->text());
    }
    return patch;
}

void SettingsPage::setSavedMessage(const QString &text) {
    m_message->setText(text);
    if (!text.isEmpty()) {
        m_dirty = false;
        m_save->setEnabled(false);
    }
}
