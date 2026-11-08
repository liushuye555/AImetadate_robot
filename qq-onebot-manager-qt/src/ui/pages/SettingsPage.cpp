#include "SettingsPage.h"
#include "../Strings.h"
#include "core/AutoStart.h"
#include <QJsonDocument>
#include <QJsonArray>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGridLayout>
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
#include <QCryptographicHash>
#include <QRegularExpression>
#include <QUrl>

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
    connect(m_save, &QPushButton::clicked, this, [this] {
        const QString error = validationError();
        if (!error.isEmpty()) {
            m_message->setText(Strings::zh("error") + ": " + error);
            return;
        }
        if (hasGatewayDraftChanges()) {
            if (!hasUnsavedNonGatewayChanges()) {
                emit gatewaySwitchRequested(gatewayDraftPatch());
                return;
            }
            m_pendingGatewayPatch = gatewayDraftPatch();
            emit saveRequested(buildBusinessPatch());
            return;
        }
        emit saveRequested(buildBusinessPatch());
    });
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
    m_theme->addItem("跟随系统", "system");
    m_theme->addItem("浅色", "light");
    m_theme->addItem("深色", "dark");
    if (!m_pendingTheme.isEmpty())
        setTheme(m_pendingTheme);  // 应用启动早期暂存的主题同步
    m_autoStart = new QCheckBox(general);
    m_autoStart->setChecked(AutoStart::isEnabled());
    m_notifications = new QCheckBox(general);
    m_notifications->setChecked(true);
    auto *webui = new QPushButton(Strings::zh("openNapcat"), general);
    auto *officialBind = new QPushButton("连接 QQ 官方机器人（扫码）", general);
    officialBind->setObjectName("officialBind");
    generalForm->addRow(Strings::zh("language"), m_language);
    generalForm->addRow(Strings::zh("theme"), m_theme);
    generalForm->addRow(Strings::zh("autoStart"), m_autoStart);
    generalForm->addRow(Strings::zh("notifications"), m_notifications);
    generalForm->addRow(Strings::zh("webui"), webui);
    generalForm->addRow("QQ 官方接入", officialBind);
    layout->addWidget(general);

    auto *gatewayGroup = new QGroupBox("接入框架", container);
    auto *gatewayLayout = new QVBoxLayout(gatewayGroup);
    auto *gatewayHelp = new QLabel(
        "选择运行配置中的接入方式后，可在这里检查连接并切换。操作只更新接入框架设置，其他未保存设置不会带入。",
        gatewayGroup);
    gatewayHelp->setWordWrap(true);
    gatewayLayout->addWidget(gatewayHelp);
    auto *gatewayButtons = new QHBoxLayout;
    auto *switchGateway = new QPushButton("检查并切换框架", gatewayGroup);
    auto *restoreGateway = new QPushButton("恢复上次框架", gatewayGroup);
    switchGateway->setObjectName("gatewaySwitch");
    restoreGateway->setObjectName("gatewayRestore");
    m_gatewaySwitchButtons = {switchGateway, restoreGateway};
    for (QPushButton *button : m_gatewaySwitchButtons) {
        button->setEnabled(!m_gatewaySwitchBusy);
        gatewayButtons->addWidget(button);
    }
    gatewayButtons->addStretch();
    gatewayLayout->addLayout(gatewayButtons);
    m_gatewaySwitchMessage = new QLabel(gatewayGroup);
    m_gatewaySwitchMessage->setObjectName("gatewaySwitchMessage");
    m_gatewaySwitchMessage->setWordWrap(true);
    m_gatewaySwitchMessage->setText(m_gatewaySwitchResultText);
    m_gatewaySwitchMessage->setProperty("class", m_gatewaySwitchResultOk ? "success" : "error");
    gatewayLayout->addWidget(m_gatewaySwitchMessage);
    layout->addWidget(gatewayGroup);
    connect(switchGateway, &QPushButton::clicked, this, [this] {
        if (!validationError().isEmpty()) {
            setGatewaySwitchResult(QStringLiteral("请先修正设置中的无效数值。"), false);
            return;
        }
        if (hasUnsavedNonGatewayChanges()) {
            setGatewaySwitchResult(QStringLiteral("请先保存接入框架以外的设置，再进行切换。"), false);
            return;
        }
        const QJsonObject patch = gatewayDraftPatch();
        if (patch.isEmpty()) {
            setGatewaySwitchResult(QStringLiteral("当前没有可用的接入框架设置，请先加载运行配置。"), false);
            return;
        }
        emit gatewaySwitchRequested(patch);
    });
    connect(restoreGateway, &QPushButton::clicked, this, [this] {
        if (hasUnsavedNonGatewayChanges()) {
            setGatewaySwitchResult(QStringLiteral("请先保存接入框架以外的设置，再恢复上次框架。"), false);
            return;
        }
        emit gatewayRestoreRequested();
    });

    auto *snowLuma = new QGroupBox("SnowLuma", container);
    auto *snowLayout = new QVBoxLayout(snowLuma);
    auto *snowHelp = new QLabel(
        "安装会下载并准备 SnowLuma 运行环境。安装后请打开管理页，按页面提示完成服务条款确认和 QQ 登录。\n"
        "切换会先停止机器人，验证连接并保存原配置备份。完成后请在概览页启动机器人；管理器会保持打开。",
        snowLuma);
    snowHelp->setWordWrap(true);
    snowLayout->addWidget(snowHelp);
    auto *snowButtons = new QGridLayout;
    const QList<QPair<QString, QString>> actions = {
        {"安装 SnowLuma", "install"}, {"启动 SnowLuma", "start"},
        {"停止 SnowLuma", "stop"}, {"切换到 SnowLuma", "switch"},
        {"恢复上次接入", "restore"},
        {"打开管理页", "webui"}, {"查看运行日志", "logs"}
    };
    int actionIndex = 0;
    for (const auto &action : actions) {
        auto *button = new QPushButton(action.first, snowLuma);
        button->setObjectName("snowLuma_" + action.second);
        snowButtons->addWidget(button, actionIndex / 4, actionIndex % 4);
        ++actionIndex;
        if (action.second != "webui") {
            m_snowLumaButtons.append(button);
            button->setEnabled(!m_snowLumaBusy && !m_gatewaySwitchBusy);
        }
        connect(button, &QPushButton::clicked, this, [this, key = action.second] {
            emit snowLumaActionRequested(key);
        });
    }
    snowLayout->addLayout(snowButtons);
    m_snowLumaMessage = new QLabel(snowLuma);
    m_snowLumaMessage->setObjectName("snowLumaMessage");
    m_snowLumaMessage->setWordWrap(true);
    m_snowLumaMessage->setText(m_snowLumaResultText);
    m_snowLumaMessage->setProperty("class", m_snowLumaResultOk ? "success" : "error");
    snowLayout->addWidget(m_snowLumaMessage);
    layout->addWidget(snowLuma);
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
    connect(officialBind, &QPushButton::clicked, this, &SettingsPage::officialBindRequested);
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
    m_providerList->setObjectName("providerList");
    v->addWidget(m_providerList);
    auto *buttons = new QHBoxLayout;
    auto *add = new QPushButton(Strings::zh("addProvider"), group);
    auto *edit = new QPushButton(Strings::zh("editProvider"), group);
    auto *remove = new QPushButton(Strings::zh("removeProvider"), group);
    add->setObjectName("addProvider");
    edit->setObjectName("editProvider");
    remove->setObjectName("removeProvider");
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
    m_snowLumaButtons.clear();
    m_snowLumaMessage = nullptr;
    m_gatewaySwitchButtons.clear();
    m_gatewaySwitchMessage = nullptr;

    buildGeneralTab();
    buildProviderEditor();

    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString section = obj.value("section").toString();
        const QString key = obj.value("key").toString();
        const QString kind = obj.value("kind").toString();
        const QJsonObject label = obj.value("label").toObject();
        const QString text = label.value("zh-CN").toString(label.value("en-US").toString(key));

        // 以下功能开关已拆分到“采集”一级页面
        if (key == "features.image_processing" || key == "features.link_analysis"
            || key == "features.link_metadata" || key == "knowledge.enabled") {
            continue;
        }
        // 群采集/群搬运/聊天已有独立一级页面，设置页不再重复展示
        if (section == "collection" || section == "relay" || section == "chat") {
            continue;
        }

        if (kind == "provider-list") {
            const QJsonObject providers = obj.value("default").toObject();
            for (auto it = providers.constBegin(); it != providers.constEnd(); ++it)
                m_providerMap.insert(it.key(), it.value().toObject());
            rebuildProviderList();
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
            for (const QJsonValue &opt : obj.value("options").toArray()) {
                const QString value = opt.toString();
                if (key == "onebot.provider") {
                    const QMap<QString, QString> names = {{"external", "通用 OneBot v11"}, {"napcat", "NapCat"},
                        {"llbot", "LLBot"}, {"snowluma", "SnowLuma"}, {"lagrange", "Lagrange.OneBot（旧版）"},
                        {"qqofficial", "QQ 官方机器人"}};
                    combo->addItem(names.value(value, value), value);
                } else combo->addItem(value);
            }
            if (key == "onebot.provider") combo->setCurrentIndex(combo->findData(obj.value("default").toString()));
            else combo->setCurrentText(obj.value("default").toString());
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
            const QJsonValue defaultValue = obj.value("default");
            if (kind == "secret") edit->setEchoMode(QLineEdit::Password);
            if (defaultValue.isNull())
                edit->setPlaceholderText(Strings::zh("optionalPlaceholder"));
            else if (defaultValue.toVariant().toString().trimmed().isEmpty())
                edit->setPlaceholderText(Strings::zh("notSet"));
            edit->setProperty("nullable", defaultValue.isNull());
            edit->setText(defaultValue.isNull() ? QString() : defaultValue.toVariant().toString());
            edit->setProperty("kind", kind);
            edit->setProperty("hasMin", obj.contains("min"));
            edit->setProperty("hasMax", obj.contains("max"));
            edit->setProperty("min", obj.value("min").toDouble());
            edit->setProperty("max", obj.value("max").toDouble());
            connect(edit, &QLineEdit::textChanged, this, [this, edit] {
                markDirty();
                if (edit->property("kind").toString() != "number") return;
                const QString text = edit->text().trimmed();
                const bool empty = text.isEmpty();
                bool ok = false;
                const double value = text.toDouble(&ok);
                const double min = edit->property("min").toDouble();
                const double max = edit->property("max").toDouble();
                const bool valid = (edit->property("nullable").toBool() && empty)
                    || (ok
                        && (!edit->property("hasMin").toBool() || value >= min)
                        && (!edit->property("hasMax").toBool() || value <= max));
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
    m_baselinePatch = buildPatch();
    if (!m_pendingGatewayPatch.isEmpty()) {
        for (auto it = m_pendingGatewayPatch.constBegin(); it != m_pendingGatewayPatch.constEnd(); ++it) {
            QWidget *field = m_fields.value(it.key(), nullptr);
            if (!field) continue;
            const QJsonValue value = it.value();
            if (auto *box = qobject_cast<QCheckBox *>(field)) {
                box->setChecked(value.toBool());
            } else if (auto *combo = qobject_cast<QComboBox *>(field)) {
                int index = combo->findData(value.toVariant());
                if (index < 0) index = combo->findText(value.toVariant().toString());
                if (index >= 0) combo->setCurrentIndex(index);
            } else if (auto *edit = qobject_cast<QLineEdit *>(field)) {
                edit->setText(value.isNull() ? QString() : value.toVariant().toString());
            } else if (auto *list = qobject_cast<QPlainTextEdit *>(field)) {
                QStringList lines;
                for (const QJsonValue &entry : value.toArray()) lines << entry.toString();
                list->setPlainText(lines.join('\n'));
            }
        }
        m_pendingGatewayPatch = {};
        if (hasGatewayDraftChanges()) {
            m_dirty = true;
            m_save->setEnabled(!m_snowLumaBusy && !m_gatewaySwitchBusy);
            setGatewaySwitchResult(QStringLiteral("其他设置已保存，接入参数请点击检查并切换框架。"), true);
        }
    }
}

void SettingsPage::markDirty() {
    m_dirty = true;
    m_save->setEnabled(!m_snowLumaBusy && !m_gatewaySwitchBusy);
}

QString SettingsPage::validationError() const {
    for (auto it = m_fields.constBegin(); it != m_fields.constEnd(); ++it) {
        const QWidget *w = it.value();
        const auto *edit = qobject_cast<const QLineEdit *>(w);
        if (!edit) continue;
        if (edit->property("kind").toString() != "number") continue;
        if (edit->property("nullable").toBool() && edit->text().trimmed().isEmpty()) continue;
        bool ok = false;
        const double value = edit->text().trimmed().toDouble(&ok);
        const double min = edit->property("min").toDouble();
        const double max = edit->property("max").toDouble();
        const bool rangeOk = (!edit->property("hasMin").toBool() || value >= min)
            && (!edit->property("hasMax").toBool() || value <= max);
        if (!ok || !rangeOk)
            return it.key();
    }
    return QString();
}

QJsonObject SettingsPage::buildPatch() const {
    QJsonObject patch;
    for (auto it = m_fields.constBegin(); it != m_fields.constEnd(); ++it) {
        const QString key = it.key();
        QWidget *w = it.value();
        if (auto *box = qobject_cast<QCheckBox *>(w)) patch.insert(key, box->isChecked());
        else if (auto *combo = qobject_cast<QComboBox *>(w)) patch.insert(key, combo->currentData().isValid() ? combo->currentData().toString() : combo->currentText());
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
    return patch;
}

QJsonObject SettingsPage::buildBusinessPatch() const {
    QJsonObject patch;
    const QJsonObject all = buildPatch();
    for (auto it = all.constBegin(); it != all.constEnd(); ++it)
        if (!it.key().startsWith(QStringLiteral("onebot."))) patch.insert(it.key(), it.value());
    return patch;
}

bool SettingsPage::hasGatewayDraftChanges() const {
    const QJsonObject current = gatewayDraftPatch();
    for (auto it = current.constBegin(); it != current.constEnd(); ++it)
        if (m_baselinePatch.value(it.key()) != it.value()) return true;
    for (auto it = m_baselinePatch.constBegin(); it != m_baselinePatch.constEnd(); ++it) {
        if (it.key().startsWith(QStringLiteral("onebot.")) && current.value(it.key()) != it.value())
            return true;
    }
    return false;
}

bool SettingsPage::hasUnsavedNonGatewayChanges() const {
    const QJsonObject current = buildPatch();
    for (auto it = current.constBegin(); it != current.constEnd(); ++it) {
        if (it.key().startsWith(QStringLiteral("onebot."))) continue;
        if (m_baselinePatch.value(it.key()) != it.value()) return true;
    }
    for (auto it = m_baselinePatch.constBegin(); it != m_baselinePatch.constEnd(); ++it) {
        if (it.key().startsWith(QStringLiteral("onebot."))) continue;
        if (current.value(it.key()) != it.value()) return true;
    }
    return false;
}

QJsonObject SettingsPage::gatewayDraftPatch() const {
    QJsonObject patch;
    const QJsonObject current = buildPatch();
    for (auto it = current.constBegin(); it != current.constEnd(); ++it)
        if (it.key().startsWith(QStringLiteral("onebot."))) patch.insert(it.key(), it.value());
    return patch;
}

QJsonObject SettingsPage::buildProvidersObject() const {
    QJsonObject providers;
    for (auto it = m_providerMap.constBegin(); it != m_providerMap.constEnd(); ++it) {
        QJsonObject provider = it.value();
        provider.remove("_credential_status");
        providers.insert(it.key(), provider);
    }
    return providers;
}


void SettingsPage::rebuildProviderList() {
    if (!m_providerList) return;
    m_providerList->clear();
    for (auto it = m_providerMap.constBegin(); it != m_providerMap.constEnd(); ++it) {
        const QJsonObject p = it.value();
        const QString state = p.value("_credential_status").toString();
        const QString credential = state == "configured" ? QStringLiteral("密钥已配置，接口未验证")
            : state == "missing_key" ? QStringLiteral("密钥变量未找到")
            : state == "missing_reference" ? QStringLiteral("尚未保存密钥") : QStringLiteral("密钥状态待检查");
        const QString summary = it.key() + "  ·  " + p.value("base_url").toString()
            + "  ·  " + p.value("model").toString() + "  ·  " + credential;
        auto *item = new QListWidgetItem(summary, m_providerList);
        item->setData(Qt::UserRole, it.key());
        m_providerList->addItem(item);
    }
    if (m_providerList->count() == 0)
        m_providerList->addItem(Strings::zh("providerEmpty"));
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
    nameEdit->setObjectName("providerId");
    urlEdit->setObjectName("providerUrl");
    modelEdit->setObjectName("providerModel");
    keyEnvEdit->setObjectName("providerKeyEnv");
    secretEdit->setObjectName("providerSecret");
    secretEdit->setEchoMode(QLineEdit::Password);
    secretEdit->setPlaceholderText(Strings::zh("secretPlaceholder"));
    form->addRow("供应商 ID", nameEdit);
    form->addRow("Base URL", urlEdit);
    form->addRow("模型", modelEdit);
    form->addRow("Key 环境变量", keyEnvEdit);
    form->addRow(Strings::zh("providerTimeout"), timeoutSpin);
    form->addRow("API Key", secretEdit);
    auto *validation = new QLabel(&dialog);
    validation->setObjectName("providerValidation");
    form->addRow(validation);
    const bool editingExisting = !editName.isEmpty() && m_providerMap.contains(editName);
    if (editingExisting) {
        const QJsonObject p = m_providerMap.value(editName);
        nameEdit->setText(editName);
        urlEdit->setText(p.value("base_url").toString());
        modelEdit->setText(p.value("model").toString());
        keyEnvEdit->setText(p.value("api_key_env").toString());
        timeoutSpin->setValue(p.value("timeout_seconds").toInt(60));
        nameEdit->setReadOnly(true);
    }
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    auto validateName = [this, nameEdit, urlEdit, modelEdit, keyEnvEdit, secretEdit, validation, buttons, editingExisting] {
        const QString name = nameEdit->text().trimmed();
        bool duplicate = false;
        if (!editingExisting)
            for (auto it = m_providerMap.constBegin(); it != m_providerMap.constEnd(); ++it)
                duplicate |= it.key().compare(name, Qt::CaseInsensitive) == 0;
        const bool hasKeyLocation = !keyEnvEdit->text().trimmed().isEmpty() || !secretEdit->text().isEmpty();
        const QString envName = keyEnvEdit->text().trimmed();
        const bool validEnv = envName.isEmpty() || QRegularExpression(QStringLiteral("^[A-Za-z_][A-Za-z0-9_]*$")).match(envName).hasMatch();
        const QUrl url(urlEdit->text().trimmed());
        const bool validConnection = url.isValid() && !url.host().isEmpty()
            && (url.scheme() == "http" || url.scheme() == "https") && !modelEdit->text().trimmed().isEmpty();
        const bool nameValid = !name.isEmpty() && !duplicate;
        buttons->button(QDialogButtonBox::Ok)->setEnabled(nameValid && hasKeyLocation && validEnv && validConnection);
        validation->setText(duplicate ? QStringLiteral("该供应商 ID 已存在。")
                             : !nameValid ? QStringLiteral("请输入唯一的供应商 ID。")
                             : !hasKeyLocation ? QStringLiteral("请填写 Key 环境变量名，或输入 API Key 以自动生成。")
                             : !validEnv ? QStringLiteral("Key 环境变量名仅可使用字母、数字和下划线，且不能以数字开头。")
                             : !validConnection ? QStringLiteral("请填写有效的 HTTP/HTTPS 接口地址和模型名称。")
                             : QString{});
    };
    connect(nameEdit, &QLineEdit::textChanged, &dialog, validateName);
    connect(urlEdit, &QLineEdit::textChanged, &dialog, validateName);
    connect(modelEdit, &QLineEdit::textChanged, &dialog, validateName);
    connect(keyEnvEdit, &QLineEdit::textChanged, &dialog, validateName);
    connect(secretEdit, &QLineEdit::textChanged, &dialog, validateName);
    validateName();
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted) return;
    const QString name = nameEdit->text().trimmed();
    if (name.isEmpty() || (!editingExisting && m_providerMap.contains(name))) return;
    QJsonObject p = editingExisting ? m_providerMap.value(editName) : QJsonObject{};
    QString keyEnv = keyEnvEdit->text().trimmed();
    const QString secret = secretEdit->text();
    if (keyEnv.isEmpty() && !secret.isEmpty()) {
        QString safe = name.toUpper();
        safe.replace(QRegularExpression(QStringLiteral("[^A-Z0-9]+")), QStringLiteral("_"));
        safe.remove(QRegularExpression(QStringLiteral("^_+|_+$")));
        if (safe.isEmpty()) safe = QStringLiteral("PROVIDER");
        // Add a stable suffix whenever normalization changed the ID, preventing
        // collisions such as "my-provider" and "my_provider".
        if (safe != name) {
            const QByteArray hash = QCryptographicHash::hash(name.toUtf8(), QCryptographicHash::Sha256).toHex().left(10).toUpper();
            safe += QStringLiteral("_") + QString::fromLatin1(hash);
        }
        keyEnv = QStringLiteral("AI_PROVIDER_") + safe + QStringLiteral("_API_KEY");
    }
    p.insert("base_url", urlEdit->text().trimmed());
    p.insert("model", modelEdit->text().trimmed());
    p.insert("api_key_env", keyEnv);
    p.insert("timeout_seconds", timeoutSpin->value());
    m_providerMap.insert(name, p);
    rebuildProviderList();
    emit providersChanged(buildProvidersObject(), keyEnv, secret);
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

void SettingsPage::setSnowLumaBusy(bool busy) {
    m_snowLumaBusy = busy;
    const bool frozen = busy || m_gatewaySwitchBusy;
    m_save->setEnabled(!frozen && m_dirty);
    // Freeze configuration editors while a deployment command owns the config.
    // The general tab keeps its WebUI link available during lengthy downloads.
    for (int i = 1; i < m_stack->count(); ++i) m_stack->widget(i)->setEnabled(!frozen);
    if (auto *binding = findChild<QPushButton *>("officialBind")) binding->setEnabled(!frozen);
    for (QPushButton *button : m_snowLumaButtons)
        if (button) button->setEnabled(!frozen);
    for (QPushButton *button : m_gatewaySwitchButtons)
        if (button) button->setEnabled(!busy && !m_gatewaySwitchBusy);
    if (m_snowLumaMessage)
        m_snowLumaMessage->setText(busy ? QStringLiteral("正在处理，请稍候…") : m_snowLumaMessage->text());
}

void SettingsPage::setSnowLumaResult(const QString &text, bool ok) {
    m_snowLumaResultText = text;
    m_snowLumaResultOk = ok;
    if (!m_snowLumaMessage) return;
    m_snowLumaMessage->setText(text);
    m_snowLumaMessage->setProperty("class", ok ? "success" : "error");
    m_snowLumaMessage->style()->unpolish(m_snowLumaMessage);
    m_snowLumaMessage->style()->polish(m_snowLumaMessage);
}

void SettingsPage::setGatewaySwitchBusy(bool busy) {
    m_gatewaySwitchBusy = busy;
    const bool frozen = busy || m_snowLumaBusy;
    m_save->setEnabled(!frozen && m_dirty);
    for (int i = 1; i < m_stack->count(); ++i) m_stack->widget(i)->setEnabled(!frozen);
    if (auto *binding = findChild<QPushButton *>("officialBind")) binding->setEnabled(!frozen);
    for (QPushButton *button : m_gatewaySwitchButtons)
        if (button) button->setEnabled(!frozen);
    for (QPushButton *button : m_snowLumaButtons)
        if (button) button->setEnabled(!busy && !m_snowLumaBusy);
    if (m_gatewaySwitchMessage && busy)
        m_gatewaySwitchMessage->setText(QStringLiteral("正在检查并切换接入框架，请稍候…"));
}

void SettingsPage::setGatewaySwitchResult(const QString &text, bool ok) {
    m_gatewaySwitchResultText = text;
    m_gatewaySwitchResultOk = ok;
    if (!m_gatewaySwitchMessage) return;
    m_gatewaySwitchMessage->setText(text);
    m_gatewaySwitchMessage->setProperty("class", ok ? "success" : "error");
    m_gatewaySwitchMessage->style()->unpolish(m_gatewaySwitchMessage);
    m_gatewaySwitchMessage->style()->polish(m_gatewaySwitchMessage);
}

void SettingsPage::setTheme(const QString &theme) {
    if (!m_theme) {
        m_pendingTheme = theme;  // 通用页尚未构建（config 未拉取），先暂存
        return;
    }
    const int index = m_theme->findData(theme);
    if (index >= 0 && index != m_theme->currentIndex()) {
        QSignalBlocker blocker(m_theme);  // 只同步显示，不回发 themeChanged
        m_theme->setCurrentIndex(index);
    }
}
