#include "OverviewPage.h"
#include "../widgets/StatusCard.h"
#include "../Strings.h"
#include "../../core/AvatarCache.h"
#include <QGridLayout>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QStyle>
#include <QScrollArea>
#include <QResizeEvent>
#include <QRegularExpression>
#include <QDate>
#include <QTime>
#include <QComboBox>
#include <QLineEdit>
#include <QCheckBox>
#include <QFormLayout>
#include <QJsonDocument>
#include <QJsonArray>
#include <QSignalBlocker>

namespace {
// Count and activity cards use separate type sizes so timestamps stay readable.
QFrame *makeStatCard(QLabel **valueLabel, const QString &caption, QWidget *parent,
                     bool activity = false) {
    auto *card = new QFrame(parent);
    card->setObjectName("card");
    card->setMinimumHeight(88);
    card->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    auto *layout = new QVBoxLayout(card);
    layout->setContentsMargins(16, 12, 16, 12);
    layout->setSpacing(6);
    auto *value = new QLabel("—", card);
    value->setObjectName(activity ? "statDetail" : "statValue");
    value->setTextFormat(Qt::PlainText);
    value->setAlignment(Qt::AlignLeft | Qt::AlignVCenter);
    value->setWordWrap(activity);
    value->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    auto *captionLabel = new QLabel(caption, card);
    captionLabel->setObjectName("statCaption");
    captionLabel->setAlignment(Qt::AlignLeft);
    layout->addWidget(captionLabel);
    layout->addWidget(value, 1);
    *valueLabel = value;
    return card;
}

void setActivity(QLabel *label, const QString &raw, const QString &emptyText,
                 bool failed = false) {
    QString display = raw.trimmed();
    if (display.isEmpty() || display == "无" || display == "—") display = emptyText;
    else {
        static const QRegularExpression timestamp(
            R"(^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$)");
        const auto match = timestamp.match(display);
        if (match.hasMatch() && QDate::fromString(match.captured(1), "yyyy-MM-dd").isValid()
            && QTime::fromString(match.captured(2), "HH:mm").isValid())
            display = match.captured(1) + "\n" + match.captured(2);
    }
    if (failed) display += "\n备份失败";
    label->setText(display);
    label->setToolTip(failed ? "备份失败：" + raw : raw);
    label->setProperty("state", failed ? "bad" : "normal");
    label->style()->unpolish(label);
    label->style()->polish(label);
}

void reflow(QGridLayout *grid, const QVector<QWidget *> &widgets, int columns) {
    for (auto *widget : widgets) grid->removeWidget(widget);
    for (int col = 0; col < 5; ++col) grid->setColumnStretch(col, 0);
    for (int i = 0; i < widgets.size(); ++i)
        grid->addWidget(widgets[i], i / columns, i % columns);
    for (int col = 0; col < columns; ++col) grid->setColumnStretch(col, 1);
}
}  // namespace

OverviewPage::OverviewPage(QWidget *parent) : QWidget(parent) {
    auto *rootLayout = new QVBoxLayout(this);
    rootLayout->setContentsMargins(0, 0, 0, 0);
    auto *scroll = new QScrollArea(this);
    scroll->setObjectName("overviewScroll");
    scroll->setWidgetResizable(true);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_body = new QWidget(scroll);
    m_body->setObjectName("overviewBody");
    auto *layout = new QVBoxLayout(m_body);
    layout->setContentsMargins(20, 16, 20, 20);
    layout->setSpacing(12);
    scroll->setWidget(m_body);
    rootLayout->addWidget(scroll);

    // 服务状态卡行
    auto *cards = new QGridLayout;
    m_servicesLayout = cards;
    cards->setHorizontalSpacing(12);
    cards->setVerticalSpacing(12);
    m_napcat = new StatusCard("接入框架", ":/icons/card-napcat.png", this);
    m_onebot = new StatusCard("OneBot", ":/icons/card-onebot.png", this);
    m_bot = new StatusCard("Bot", ":/icons/card-bot.png", this);
    m_qq = new StatusCard("QQ", ":/icons/card-qq.png", this);
    cards->addWidget(m_napcat, 0, 0);
    cards->addWidget(m_onebot, 0, 1);
    cards->addWidget(m_bot, 0, 2);
    cards->addWidget(m_qq, 0, 3);
    m_serviceCards = {m_napcat, m_onebot, m_bot, m_qq};
    layout->addLayout(cards);

    auto *gatewayCard = new QFrame(m_body);
    gatewayCard->setObjectName("card");
    m_gatewayPanel = gatewayCard;
    auto *gatewayLayout = new QVBoxLayout(gatewayCard);
    gatewayLayout->setContentsMargins(18, 14, 18, 14);
    auto *gatewayTitle = new QLabel(QStringLiteral("框架切换"), gatewayCard);
    gatewayTitle->setObjectName("sectionTitle");
    gatewayLayout->addWidget(gatewayTitle);
    auto *gatewayCurrent = new QLabel(gatewayCard);
    gatewayCurrent->setObjectName("homeGatewayCurrent");
    gatewayCurrent->setTextFormat(Qt::PlainText);
    gatewayLayout->addWidget(gatewayCurrent);
    auto *gatewayForm = new QFormLayout;
    gatewayForm->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    gatewayForm->setRowWrapPolicy(QFormLayout::WrapLongRows);
    m_gatewayProvider = new QComboBox(gatewayCard);
    m_gatewayProvider->setObjectName("homeGatewayProvider");
    const QList<QPair<QString, QString>> providers = {
        {"通用 OneBot v11", "external"}, {"NapCat", "napcat"},
        {"LuckyLilliaBot", "llbot"}, {"SnowLuma", "snowluma"},
        {"Lagrange.OneBot", "lagrange"}, {"QQ 官方机器人", "qqofficial"}
    };
    for (const auto &provider : providers) m_gatewayProvider->addItem(provider.first, provider.second);
    m_gatewayWs = new QLineEdit(gatewayCard);
    m_gatewayWs->setObjectName("homeGatewayWs");
    m_gatewayTokenEnv = new QLineEdit(gatewayCard);
    m_gatewayTokenEnv->setObjectName("homeGatewayTokenEnv");
    m_gatewayTokenEnv->setToolTip(QStringLiteral("填写保存 Token 的环境变量名，密钥本身保存在项目 .env 中。"));
    m_gatewayWebui = new QLineEdit(gatewayCard);
    m_gatewayWebui->setObjectName("homeGatewayWebui");
    m_gatewayManaged = new QCheckBox(QStringLiteral("随管理器启动内置 NapCat"), gatewayCard);
    m_gatewayInstalled = new QCheckBox(QStringLiteral("随管理器启动已安装的 SnowLuma"), gatewayCard);
    gatewayForm->addRow(QStringLiteral("目标框架"), m_gatewayProvider);
    gatewayLayout->addLayout(gatewayForm);
    m_gatewayDetails = new QWidget(gatewayCard);
    m_gatewayDetails->setObjectName("homeGatewayDetails");
    gatewayForm = new QFormLayout;
    gatewayForm->setContentsMargins(0, 0, 0, 0);
    gatewayForm->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    gatewayForm->setRowWrapPolicy(QFormLayout::WrapLongRows);
    gatewayForm->addRow(QStringLiteral("连接地址"), m_gatewayWs);
    gatewayForm->addRow(QStringLiteral("Token 变量名"), m_gatewayTokenEnv);
    gatewayForm->addRow(QStringLiteral("管理页地址"), m_gatewayWebui);
    gatewayForm->addRow(m_gatewayManaged);
    gatewayForm->addRow(m_gatewayInstalled);
    m_gatewayDetails->setLayout(gatewayForm);
    gatewayLayout->addWidget(m_gatewayDetails);
    m_gatewayDetails->hide();
    auto *gatewayButtons = new QHBoxLayout;
    auto *gatewaySwitch = new QPushButton(QStringLiteral("检查并切换"), gatewayCard);
    gatewaySwitch->setObjectName("homeGatewaySwitch");
    auto *gatewayRestore = new QPushButton(QStringLiteral("恢复上次框架"), gatewayCard);
    gatewayRestore->setObjectName("homeGatewayRestore");
    gatewayButtons->addWidget(gatewaySwitch);
    gatewayButtons->addWidget(gatewayRestore);
    m_gatewayDetailsToggle = new QPushButton(QStringLiteral("连接参数"), gatewayCard);
    m_gatewayDetailsToggle->setObjectName("homeGatewayDetailsToggle");
    gatewayButtons->addWidget(m_gatewayDetailsToggle);
    connect(m_gatewayDetailsToggle, &QPushButton::clicked, this, [this] {
        const bool expanded = m_gatewayDetails->isHidden();
        m_gatewayDetails->setVisible(expanded);
        m_gatewayDetailsToggle->setText(expanded ? QStringLiteral("收起参数") : QStringLiteral("连接参数"));
    });
    gatewayButtons->addStretch();
    gatewayLayout->addLayout(gatewayButtons);
    m_gatewaySnowActions = new QWidget(gatewayCard);
    auto *snowButtons = new QGridLayout(m_gatewaySnowActions);
    snowButtons->setContentsMargins(0, 0, 0, 0);
    const QList<QPair<QString, QString>> snowActions = {
        {"安装 SnowLuma", "install"}, {"启动 SnowLuma", "start"},
        {"自动识别并切换 SnowLuma", "switch"}, {"SnowLuma 管理页", "webui"}
    };
    for (int i = 0; i < snowActions.size(); ++i) {
        const auto action = snowActions[i];
        auto *button = new QPushButton(action.first, gatewayCard);
        button->setObjectName("homeSnowLuma_" + action.second);
        snowButtons->addWidget(button, i / 2, i % 2);
        connect(button, &QPushButton::clicked, this, [this, action] { emit snowLumaActionRequested(action.second); });
    }
    gatewayLayout->addWidget(m_gatewaySnowActions);
    m_gatewayMessage = new QLabel(QStringLiteral("正在加载接入配置…"), gatewayCard);
    m_gatewayMessage->setObjectName("homeGatewayMessage");
    m_gatewayMessage->setWordWrap(true);
    m_gatewayMessage->setTextFormat(Qt::PlainText);
    gatewayLayout->addWidget(m_gatewayMessage);
    layout->addWidget(gatewayCard);
    gatewayCard->setEnabled(false);
    connect(m_gatewayProvider, &QComboBox::currentIndexChanged, this, [this] {
        const QString provider = m_gatewayProvider->currentData().toString();
        const bool same = provider == m_gatewayConfig.value("onebot.provider").toString();
        m_gatewayWs->setText(same ? m_gatewayConfig.value("onebot.ws_url").toString() : "ws://127.0.0.1:3001");
        m_gatewayTokenEnv->setText(same ? m_gatewayConfig.value("onebot.access_token_env").toString()
            : provider == "snowluma" ? "SNOWLUMA_ONEBOT_TOKEN" : "ONEBOT_ACCESS_TOKEN");
        m_gatewayWebui->setText(same ? m_gatewayConfig.value("onebot.webui_url").toString()
            : provider == "snowluma" ? "http://127.0.0.1:5099/"
            : provider == "napcat" ? "http://127.0.0.1:6099/" : "");
        m_gatewayManaged->setChecked(same ? m_gatewayConfig.value("onebot.manage_process").toBool() : provider == "napcat");
        m_gatewayInstalled->setChecked(same && m_gatewayConfig.value("onebot.start_installed_runtime").toBool());
        updateGatewayFields();
        m_gatewayDetails->setVisible(provider != "qqofficial");
        m_gatewayDetailsToggle->setText(QStringLiteral("收起参数"));
    });
    connect(gatewaySwitch, &QPushButton::clicked, this, [this] {
        QJsonObject patch = m_gatewayConfig;
        const QString provider = m_gatewayProvider->currentData().toString();
        patch.insert("onebot.provider", provider);
        patch.insert("onebot.protocol", provider == "qqofficial" ? "qqofficial" : "onebot11");
        if (provider != "qqofficial") {
            patch.insert("onebot.ws_url", m_gatewayWs->text().trimmed());
            patch.insert("onebot.access_token_env", m_gatewayTokenEnv->text().trimmed());
            patch.insert("onebot.webui_url", m_gatewayWebui->text().trimmed());
        }
        patch.insert("onebot.manage_process", provider == "napcat" && m_gatewayManaged->isChecked());
        patch.insert("onebot.start_installed_runtime", provider == "snowluma" && m_gatewayInstalled->isChecked());
        emit gatewaySwitchRequested(patch);
    });
    connect(gatewayRestore, &QPushButton::clicked, this, &OverviewPage::gatewayRestoreRequested);
    updateGatewayFields();

    // Counts get a row of their own; activity timestamps have wider two-line cards.
    auto *stats = new QGridLayout;
    m_countsLayout = stats;
    stats->setHorizontalSpacing(12);
    stats->setVerticalSpacing(12);
    m_countCards = {
        makeStatCard(&m_statImages, Strings::zh("statImages"), m_body),
        makeStatCard(&m_statLinks, Strings::zh("statLinks"), m_body),
        makeStatCard(&m_statQueue, QStringLiteral("图片队列"), m_body),
        makeStatCard(&m_statRecall, QStringLiteral("撤回记录"), m_body)
    };
    for (int i = 0; i < m_countCards.size(); ++i) stats->addWidget(m_countCards[i], 0, i);
    layout->addLayout(stats);
    auto *activity = new QGridLayout;
    activity->setHorizontalSpacing(12);
    activity->addWidget(makeStatCard(&m_statReport, Strings::zh("statLastReport"), m_body, true), 0, 0);
    activity->addWidget(makeStatCard(&m_statViewSync, QStringLiteral("视图同步"), m_body, true), 0, 1);
    activity->addWidget(makeStatCard(&m_statBackup, QStringLiteral("最近备份"), m_body, true), 0, 2);
    for (int i = 0; i < 3; ++i) activity->setColumnStretch(i, 1);
    layout->addLayout(activity);
    setActivity(m_statReport, {}, "暂无日报");
    setActivity(m_statViewSync, {}, "尚未同步");
    setActivity(m_statBackup, {}, "暂无备份");
    m_statImages->setProperty("metric", "images");
    m_statLinks->setProperty("metric", "links");
    m_statQueue->setProperty("metric", "queue");
    m_statRecall->setProperty("metric", "recall");
    m_statReport->setProperty("metric", "report");
    m_statViewSync->setProperty("metric", "sync");
    m_statBackup->setProperty("metric", "backup");

    // 快捷操作卡：服务控制 + 数据入口分组，按钮网格对齐
    auto *actionsCard = new QFrame(this);
    actionsCard->setObjectName("card");
    auto *actionsLayout = new QVBoxLayout(actionsCard);
    actionsLayout->setContentsMargins(18, 14, 18, 14);
    actionsLayout->setSpacing(8);

    auto *serviceTitle = new QLabel(Strings::zh("groupService"), actionsCard);
    serviceTitle->setObjectName("sectionTitle");
    actionsLayout->addWidget(serviceTitle);
    auto *serviceGrid = new QGridLayout;
    m_serviceActionsLayout = serviceGrid;
    serviceGrid->setHorizontalSpacing(10);
    serviceGrid->setVerticalSpacing(8);
    auto *start = new QPushButton(Strings::zh("start"), actionsCard);
    start->setObjectName("primary");
    auto *stop = new QPushButton(Strings::zh("stop"), actionsCard);
    stop->setObjectName("danger");
    auto *restart = new QPushButton(Strings::zh("restart"), actionsCard);
    auto *refresh = new QPushButton(Strings::zh("refresh"), actionsCard);
    m_collection = new QPushButton(Strings::zh("collectionOn"), actionsCard);
    m_collection->setCheckable(true);
    serviceGrid->addWidget(start, 0, 0);
    serviceGrid->addWidget(stop, 0, 1);
    serviceGrid->addWidget(restart, 0, 2);
    serviceGrid->addWidget(refresh, 0, 3);
    serviceGrid->addWidget(m_collection, 0, 4);
    m_serviceButtons = {start, stop, restart, refresh, m_collection};
    actionsLayout->addLayout(serviceGrid);

    auto *dataTitle = new QLabel(Strings::zh("groupData"), actionsCard);
    dataTitle->setObjectName("sectionTitle");
    actionsLayout->addWidget(dataTitle);
    auto *dataGrid = new QGridLayout;
    m_dataActionsLayout = dataGrid;
    dataGrid->setHorizontalSpacing(10);
    dataGrid->setVerticalSpacing(8);
    auto *logs = new QPushButton(Strings::zh("openLogs"), actionsCard);
    auto *reports = new QPushButton(Strings::zh("openReports"), actionsCard);
    auto *config = new QPushButton(Strings::zh("openConfig"), actionsCard);
    auto *history = new QPushButton(Strings::zh("importHistory"), actionsCard);
    auto *napcat = new QPushButton(Strings::zh("openNapcat"), actionsCard);
    dataGrid->addWidget(logs, 0, 0);
    dataGrid->addWidget(reports, 0, 1);
    dataGrid->addWidget(config, 0, 2);
    dataGrid->addWidget(history, 0, 3);
    dataGrid->addWidget(napcat, 0, 4);
    m_dataButtons = {logs, reports, config, history, napcat};
    actionsLayout->addLayout(dataGrid);
    layout->addWidget(actionsCard);

    // 运行信息：自动重启状态 + 异常提示条（仅异常时出现）
    m_autoRestart = new QLabel(this);
    m_autoRestart->setObjectName("infoLine");
    layout->addWidget(m_autoRestart);
    m_hint = new QLabel(this);
    m_hint->setObjectName("hintBar");
    m_hint->setWordWrap(true);
    m_hint->hide();
    layout->addWidget(m_hint);
    layout->addStretch(1);
    updateResponsiveLayout();

    connect(start, &QPushButton::clicked, this, [this] { emit actionRequested("start"); });
    connect(stop, &QPushButton::clicked, this, [this] { emit actionRequested("stop"); });
    connect(restart, &QPushButton::clicked, this, [this] { emit actionRequested("restart"); });
    connect(refresh, &QPushButton::clicked, this, [this] { emit actionRequested("refresh"); });
    connect(logs, &QPushButton::clicked, this, [this] { emit actionRequested("logs"); });
    connect(reports, &QPushButton::clicked, this, [this] { emit actionRequested("reports"); });
    connect(config, &QPushButton::clicked, this, [this] { emit actionRequested("config"); });
    connect(history, &QPushButton::clicked, this, [this] { emit actionRequested("history"); });
    connect(napcat, &QPushButton::clicked, this, [this] { emit actionRequested("napcat-webui"); });
    connect(m_collection, &QPushButton::clicked, this, [this] {
        setCollectionPaused(m_collection->isChecked());  // 点击后立即更新按钮显示
        emit actionRequested("collection-toggle");
    });
}

void OverviewPage::setStatus(const StatusSnapshot &s) {
    m_lastStatus = s;
    if (!s.valid) {
        m_hint->setText(m_backendFault.isEmpty() ? Strings::zh("staleHint") : m_backendFault);
        m_hint->show();
        m_napcat->setValue("未知", false);
        m_onebot->setValue("未知", false);
        m_bot->setValue(m_backendFault.isEmpty() ? "未知" : "已停止", false);
        m_qq->setValue("未知", false);
        return;
    }
    if (m_backendFault.isEmpty()) m_hint->hide();
    else setHint(m_backendFault);
    if (!s.gatewayError.isEmpty()) setHint(s.gatewayError);
    m_napcat->setTitle(s.gatewayName);
    const bool gatewayRunning = s.gatewayRunning || (s.gatewayProvider == "napcat" && s.napcat);
    m_napcat->setValue(gatewayRunning ? Strings::zh("running") : Strings::zh("stopped"), gatewayRunning,
                     s.gatewayManaged ? "本项目管理" : "外部运行");
    m_onebot->setValue(s.onebot ? Strings::zh("running") : Strings::zh("stopped"), s.onebot);
    m_onebot->setTitle(s.gatewayProvider == "qqofficial" ? "官方网关" : "OneBot");
    const bool botRunning = s.bot && m_backendFault.isEmpty();
    m_bot->setValue(botRunning ? Strings::zh("running") : Strings::zh("stopped"), botRunning);
    const QString account = !s.qqStatusKnown ? "登录状态未确认"
        : (!s.qqLoggedIn ? "未登录" : (s.qqNickname.isEmpty() ? Strings::zh("running") : s.qqNickname));
    const QString idLabel = s.gatewayProvider == "qqofficial" ? "AppID " : "QQ ";
    const QString identity = s.qqNumber.isEmpty() ? QString()
        : (s.qqLoggedIn ? idLabel : (s.qqNickname.isEmpty() ? idLabel : s.qqNickname + " · " + idLabel)) + s.qqNumber;
    m_qq->setValue(account, s.qqStatusKnown && s.qqLoggedIn, identity);
    // 采集健康度：队列积压 / 撤回记录 / 最近视图同步（随 30s 状态心跳更新）
    m_statQueue->setText(QString::number(s.imageQueue));
    m_statQueue->setToolTip(s.imageQueue > 0 ? QStringLiteral("等待处理：%1 张图片").arg(s.imageQueue)
                                           : QStringLiteral("当前没有等待处理的图片"));
    m_statRecall->setText(QString::number(s.recallCount));
    setActivity(m_statViewSync, s.lastViewSync, "尚未同步");
    setActivity(m_statBackup, s.lastBackup, "暂无备份", !s.lastBackup.isEmpty() && !s.backupOk);
    updateResponsiveLayout();
    if (s.gatewayProvider != "qqofficial" && !s.qqNumber.isEmpty() && s.qqNumber != m_avatarQQ) {
        m_avatarQQ = s.qqNumber;  // 每个账号只拉一次（含磁盘缓存）
        AvatarCache::instance().fetch("user", s.qqNumber, [this](const QPixmap &pm) {
            m_qq->setIconPixmap(pm);
        });
    }
}

void OverviewPage::setBackendFault(const QString &reason) {
    m_backendFault = reason;
    setStatus(m_lastStatus);
}

void OverviewPage::clearBackendFault() {
    m_backendFault.clear();
    m_lastStatus.bot = true; // The runtime has accepted an exact live backend.
    setStatus(m_lastStatus);
}

void OverviewPage::setStatNumbers(int images, int links, const QString &lastReport) {
    m_statImages->setText(QString::number(images));
    m_statLinks->setText(QString::number(links));
    m_statImages->setToolTip(m_statImages->text());
    m_statLinks->setToolTip(m_statLinks->text());
    setActivity(m_statReport, lastReport, "暂无日报");
    updateResponsiveLayout();
}

void OverviewPage::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);
    updateResponsiveLayout();
}

void OverviewPage::updateResponsiveLayout() {
    if (!m_body || !m_servicesLayout || !m_countsLayout || !m_dataActionsLayout) return;
    const int available = width() - 52; // page margins plus the possible vertical scrollbar
    const int serviceColumns = available >= 760 ? 4 : 2;
    int metricWidth = 0;
    for (const auto *label : {m_statImages, m_statLinks, m_statQueue, m_statRecall})
        metricWidth = qMax(metricWidth, label->fontMetrics().horizontalAdvance(label->text()) + 32);
    const int countColumns = available >= 760 && available >= metricWidth * 4 + 36 ? 4 : 2;
    const int actionColumns = available >= 760 ? 5 : 3;
    if (serviceColumns != m_serviceColumns) {
        reflow(m_servicesLayout, m_serviceCards, serviceColumns);
        m_serviceColumns = serviceColumns;
    }
    if (countColumns != m_countColumns) {
        reflow(m_countsLayout, m_countCards, countColumns);
        m_countColumns = countColumns;
    }
    if (actionColumns != m_actionColumns) {
        reflow(m_serviceActionsLayout, m_serviceButtons, actionColumns);
        reflow(m_dataActionsLayout, m_dataButtons, actionColumns);
        m_actionColumns = actionColumns;
    }
}

void OverviewPage::setHint(const QString &text) {
    m_hint->setText(text);
    m_hint->setVisible(!text.isEmpty());
}
void OverviewPage::setAutoRestartText(const QString &text) { m_autoRestart->setText(text); }
void OverviewPage::setCollectionPaused(bool paused) {
    m_collectionPaused = paused;
    if (!m_collection) return;
    m_collection->setChecked(paused);
    m_collection->setText(paused ? Strings::zh("collectionOff") : Strings::zh("collectionOn"));
    m_collection->setProperty("class", paused ? "danger" : "primary");
    m_collection->style()->unpolish(m_collection);
    m_collection->style()->polish(m_collection);
}

bool OverviewPage::collectionChecked() const {
    return m_collection ? m_collection->isChecked() : m_collectionPaused;
}

void OverviewPage::setGatewaySchema(const QVariant &schema) {
    m_gatewayConfig = {};
    for (const auto &entry : QJsonDocument::fromVariant(schema).array()) {
        const auto field = entry.toObject();
        const QString key = field.value("key").toString();
        if (key.startsWith("onebot.")) m_gatewayConfig.insert(key, field.value("default"));
    }
    m_gatewayLoaded = m_gatewayConfig.contains("onebot.provider");
    const QSignalBlocker blocker(m_gatewayProvider);
    m_gatewayProvider->setCurrentIndex(m_gatewayProvider->findData(m_gatewayConfig.value("onebot.provider").toString()));
    m_gatewayPanel->findChild<QLabel *>("homeGatewayCurrent")->setText(
        QStringLiteral("当前配置：%1").arg(m_gatewayProvider->currentText()));
    m_gatewayWs->setText(m_gatewayConfig.value("onebot.ws_url").toString());
    m_gatewayTokenEnv->setText(m_gatewayConfig.value("onebot.access_token_env").toString());
    m_gatewayWebui->setText(m_gatewayConfig.value("onebot.webui_url").toString());
    m_gatewayManaged->setChecked(m_gatewayConfig.value("onebot.manage_process").toBool());
    m_gatewayInstalled->setChecked(m_gatewayConfig.value("onebot.start_installed_runtime").toBool());
    m_gatewayPanel->setEnabled(m_gatewayLoaded && !m_gatewayBusy);
    updateGatewayFields();
    m_gatewayDetails->hide();
    m_gatewayDetailsToggle->setText(QStringLiteral("连接参数"));
    if (m_gatewayMessage->text() == QStringLiteral("正在加载接入配置…"))
        setGatewayResult(QStringLiteral("先启动目标框架并完成登录，再检查切换。切换会暂停机器人，成功后点击首页“启动”。"));
}

void OverviewPage::updateGatewayFields() {
    const QString provider = m_gatewayProvider->currentData().toString();
    const bool onebot = provider != "qqofficial";
    m_gatewayWs->setEnabled(onebot);
    m_gatewayTokenEnv->setEnabled(onebot);
    m_gatewayWebui->setEnabled(onebot);
    m_gatewayManaged->setVisible(provider == "napcat");
    m_gatewayInstalled->setVisible(provider == "snowluma");
    m_gatewaySnowActions->setVisible(provider == "snowluma");
    m_gatewayDetailsToggle->setVisible(onebot);
    m_gatewayProvider->setToolTip(provider == "qqofficial"
        ? QStringLiteral("请先在设置页绑定官方机器人；检查切换使用已保存的官方凭据。") : QString());
}

void OverviewPage::setGatewayBusy(bool busy) {
    m_gatewayBusy = busy;
    m_gatewayPanel->setEnabled(m_gatewayLoaded && !busy);
}

void OverviewPage::setGatewayResult(const QString &text) { m_gatewayMessage->setText(text); }
