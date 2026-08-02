#include "SettingsPage.h"
#include "../Strings.h"
#include "core/AutoStart.h"
#include <QJsonDocument>
#include <QJsonArray>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QStackedWidget>
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
#include <QEvent>

SettingsPage::SettingsPage(QWidget *parent) : QWidget(parent) {
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(12, 12, 12, 12);
    auto *body = new QHBoxLayout;
    m_subnav = new QListWidget(this);
    m_subnav->setObjectName("subnav");
    m_subnav->setFixedWidth(132);
    m_stack = new QStackedWidget(this);
    body->addWidget(m_subnav);
    body->addWidget(m_stack, 1);
    outer->addLayout(body, 1);
    connect(m_subnav, &QListWidget::currentRowChanged, m_stack, &QStackedWidget::setCurrentIndex);
    m_subnav->setCurrentRow(0);

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

bool SettingsPage::eventFilter(QObject *obj, QEvent *event) {
    // 滚轮悬停在组合框/数字框/复选框上时不再改动值，避免滚动页面时误改
    if (event->type() == QEvent::Wheel
        && (qobject_cast<QComboBox *>(obj) || qobject_cast<QSpinBox *>(obj) || qobject_cast<QCheckBox *>(obj))) {
        return true;
    }
    return QWidget::eventFilter(obj, event);
}

void SettingsPage::installWheelGuard(QWidget *widget) {
    widget->installEventFilter(this);
}

QVBoxLayout *SettingsPage::sectionLayout(const QString &section) {
    if (m_tabLayouts.contains(section)) return m_tabLayouts.value(section);
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    auto *layout = new QVBoxLayout(container);
    layout->setContentsMargins(16, 16, 16, 16);
    scroll->setWidget(container);
    m_stack->addWidget(scroll);
    m_subnav->addItem(Strings::section(section));
    m_tabLayouts.insert(section, layout);
    return layout;
}

QWidget *SettingsPage::buildGeneralTab() {
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    auto *layout = new QVBoxLayout(container);
    layout->setContentsMargins(16, 16, 16, 16);
    scroll->setWidget(container);
    m_stack->addWidget(scroll);
    m_subnav->addItem(Strings::zh("general"));

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
    auto *webui = new QPushButton(Strings::zh("openNapcat"), general);
    generalForm->addRow(Strings::zh("language"), m_language);
    generalForm->addRow(Strings::zh("theme"), m_theme);
    generalForm->addRow(Strings::zh("autoStart"), m_autoStart);
    generalForm->addRow(Strings::zh("notifications"), m_notifications);
    generalForm->addRow(Strings::zh("webui"), webui);
    layout->addWidget(general);
    layout->addStretch();

    installWheelGuard(m_language);
    installWheelGuard(m_theme);
    connect(m_language, &QComboBox::currentIndexChanged, this, [this] {
        emit languageChanged(m_language->currentData().toString());
    });
    connect(m_theme, &QComboBox::currentIndexChanged, this, [this] {
        emit themeChanged(m_theme->currentData().toString());
    });
    connect(m_autoStart, &QCheckBox::toggled, this, [this](bool) {
        if (AutoStart::setEnabled(m_autoStart->isChecked()))
            m_autoStart->setChecked(AutoStart::isEnabled());
        emit autoStartToggled(AutoStart::isEnabled());
    });
    connect(m_notifications, &QCheckBox::toggled, this, &SettingsPage::notificationsToggled);
    connect(webui, &QPushButton::clicked, this, [this] { emit webuiRequested(); });
    return scroll;
}

QWidget *SettingsPage::buildProviderEditor() {
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    auto *layout = new QVBoxLayout(container);
    layout->setContentsMargins(16, 16, 16, 16);
    scroll->setWidget(container);
    m_stack->addWidget(scroll);
    m_subnav->addItem(Strings::zh("providers"));
    auto *group = new QGroupBox(Strings::zh("providers"), container);
    auto *v = new QVBoxLayout(group);
    m_providerList = new QListWidget(group);
    v->addWidget(m_providerList);
    auto *buttons = new QHBoxLayout;
    auto *add = new QPushButton(Strings::zh("addProvider"), group);
    auto *edit = new QPushButton(Strings::zh("editProvider"), group);
    auto *remove = new QPushButton(Strings::zh("removeProvider"), group);
    buttons->addWidget(add);
    buttons->addWidget(edit);
    buttons->addWidget(remove);
    buttons->addStretch();
    v->addLayout(buttons);
    layout->addWidget(group);
    layout->addStretch();
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
    return scroll;
}

QWidget *SettingsPage::buildCollectionEditor() {
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    auto *layout = new QVBoxLayout(container);
    layout->setContentsMargins(16, 16, 16, 16);
    scroll->setWidget(container);
    m_stack->addWidget(scroll);
    m_subnav->addItem(Strings::zh("collection"));
    auto *group = new QGroupBox(Strings::zh("collection"), container);
    auto *v = new QVBoxLayout(group);
    m_collectionList = new QListWidget(group);
    v->addWidget(m_collectionList);
    auto *buttons = new QHBoxLayout;
    auto *add = new QPushButton(Strings::zh("addGroup"), group);
    auto *edit = new QPushButton(Strings::zh("editGroup"), group);
    auto *remove = new QPushButton(Strings::zh("removeGroup"), group);
    auto *scan = new QPushButton(Strings::zh("scanGroups"), group);
    buttons->addWidget(add);
    buttons->addWidget(edit);
    buttons->addWidget(remove);
    buttons->addWidget(scan);
    buttons->addStretch();
    v->addLayout(buttons);
    layout->addWidget(group);
    auto *hint = new QLabel(Strings::zh("collectionHint"), container);
    hint->setObjectName("muted");
    hint->setWordWrap(true);
    layout->addWidget(hint);
    layout->addStretch();
    connect(add, &QPushButton::clicked, this, [this] { openCollectionDialog(QString()); });
    connect(edit, &QPushButton::clicked, this, [this] {
        if (m_collectionList->currentItem())
            openCollectionDialog(m_collectionList->currentItem()->data(Qt::UserRole).toString());
    });
    connect(remove, &QPushButton::clicked, this, [this] {
        QListWidgetItem *item = m_collectionList->currentItem();
        if (!item) return;
        m_collectionMap.remove(item->data(Qt::UserRole).toString());
        rebuildCollectionList();
        markDirty();
    });
    connect(scan, &QPushButton::clicked, this, [this] { emit groupsScanRequested(); });
    return scroll;
}

void SettingsPage::setGroups(const QVariantList &groups) {
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
        QListWidgetItem *item = list->item(i);
        if (item->checkState() != Qt::Checked) continue;
        const QString id = item->data(Qt::UserRole).toString();
        if (id.isEmpty() || m_collectionMap.contains(id)) continue;
        QJsonObject rule;
        rule.insert("images", true);
        rule.insert("links", true);
        rule.insert("files", true);
        rule.insert("forwards", true);
        m_collectionMap.insert(id, rule);
        added++;
    }
    if (added > 0) {
        rebuildCollectionList();
        markDirty();
    }
}

void SettingsPage::setSchema(const QVariant &schemaVariant) {
    while (m_stack->count() > 0) {
        QWidget *page = m_stack->widget(0);
        m_stack->removeWidget(page);
        page->deleteLater();
    }
    m_subnav->clear();
    m_tabLayouts.clear();
    m_fields.clear();
    m_providerMap.clear();
    m_collectionMap.clear();

    buildGeneralTab();
    buildProviderEditor();
    buildCollectionEditor();

    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString section = obj.value("section").toString();
        const QString key = obj.value("key").toString();
        const QString kind = obj.value("kind").toString();
        const QJsonObject label = obj.value("label").toObject();
        const QString text = label.value("zh-CN").toString(label.value("en-US").toString(key));

        if (kind == "provider-list") {
            const QJsonObject providers = obj.value("default").toObject();
            for (auto it = providers.constBegin(); it != providers.constEnd(); ++it)
                m_providerMap.insert(it.key(), it.value().toObject());
            rebuildProviderList();
            continue;
        }
        if (kind == "collection-list") {
            const QJsonObject groups = obj.value("default").toObject();
            for (auto it = groups.constBegin(); it != groups.constEnd(); ++it)
                m_collectionMap.insert(it.key(), it.value().toObject());
            rebuildCollectionList();
            continue;
        }

        QVBoxLayout *layout = sectionLayout(section);
        auto *group = new QGroupBox(Strings::section(section), this);
        auto *form = new QFormLayout(group);
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
            installWheelGuard(combo);
            field = combo;
        } else if (kind == "list") {
            auto *edit = new QPlainTextEdit(this);
            edit->setMaximumHeight(110);
            edit->setPlaceholderText(Strings::zh("listPlaceholder"));
            const QJsonArray values = obj.value("default").toArray();
            QStringList lines;
            for (const QJsonValue &v : values) lines << v.toString();
            edit->setPlainText(lines.join('\n'));
            connect(edit, &QPlainTextEdit::textChanged, this, [this] { markDirty(); });
            field = edit;
        } else {
            auto *edit = new QLineEdit(this);
            if (kind == "secret") edit->setEchoMode(QLineEdit::Password);
            if (obj.value("default").isNull())
                edit->setPlaceholderText(Strings::zh("optionalPlaceholder"));
            edit->setText(obj.value("default").toString());
            edit->setProperty("kind", kind);
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
        form->addRow(text, field);
        layout->addWidget(group);
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
        else if (auto *edit = qobject_cast<QLineEdit *>(w)) {
            // 可空数字字段留空时写 null，避免空字符串导致后端 int('') 崩溃
            if (edit->property("kind").toString() == "number" && edit->text().trimmed().isEmpty())
                patch.insert(key, QJsonValue(QJsonValue::Null));
            else
                patch.insert(key, edit->text());
        }
    }
    if (!m_collectionMap.isEmpty()) {
        QJsonObject groups;
        for (auto it = m_collectionMap.constBegin(); it != m_collectionMap.constEnd(); ++it)
            groups.insert(it.key(), it.value());
        patch.insert("collection.groups", groups);
    }
    return patch;
}

QJsonObject SettingsPage::buildProvidersObject() const {
    QJsonObject providers;
    for (auto it = m_providerMap.constBegin(); it != m_providerMap.constEnd(); ++it)
        providers.insert(it.key(), it.value());
    return providers;
}

QJsonObject SettingsPage::buildCollectionObject() const {
    QJsonObject groups;
    for (auto it = m_collectionMap.constBegin(); it != m_collectionMap.constEnd(); ++it)
        groups.insert(it.key(), it.value());
    return groups;
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
    if (m_providerList->count() == 0)
        m_providerList->addItem(Strings::zh("providerEmpty"));
}

void SettingsPage::rebuildCollectionList() {
    if (!m_collectionList) return;
    m_collectionList->clear();
    for (auto it = m_collectionMap.constBegin(); it != m_collectionMap.constEnd(); ++it) {
        const QJsonObject p = it.value();
        const QString summary = it.key()
            + (p.value("images").toBool() ? " · 图片" : "")
            + (p.value("links").toBool() ? " · 链接" : "")
            + (p.value("files").toBool() ? " · 文件" : "")
            + (p.value("forwards").toBool() ? " · 转发" : "");
        auto *item = new QListWidgetItem(summary, m_collectionList);
        item->setData(Qt::UserRole, it.key());
        m_collectionList->addItem(item);
    }
    if (m_collectionList->count() == 0)
        m_collectionList->addItem(Strings::zh("collectionEmpty"));
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

void SettingsPage::openCollectionDialog(const QString &editGroup) {
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
