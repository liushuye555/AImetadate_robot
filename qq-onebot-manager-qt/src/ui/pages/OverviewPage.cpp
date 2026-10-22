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
    m_napcat = new StatusCard("NapCat", ":/icons/card-napcat.png", this);
    m_onebot = new StatusCard("OneBot", ":/icons/card-onebot.png", this);
    m_bot = new StatusCard("Bot", ":/icons/card-bot.png", this);
    m_qq = new StatusCard("QQ", ":/icons/card-qq.png", this);
    cards->addWidget(m_napcat, 0, 0);
    cards->addWidget(m_onebot, 0, 1);
    cards->addWidget(m_bot, 0, 2);
    cards->addWidget(m_qq, 0, 3);
    m_serviceCards = {m_napcat, m_onebot, m_bot, m_qq};
    layout->addLayout(cards);

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
    m_napcat->setValue(s.napcat ? Strings::zh("running") : Strings::zh("stopped"), s.napcat);
    m_onebot->setValue(s.onebot ? Strings::zh("running") : Strings::zh("stopped"), s.onebot);
    const bool botRunning = s.bot && m_backendFault.isEmpty();
    m_bot->setValue(botRunning ? Strings::zh("running") : Strings::zh("stopped"), botRunning);
    const QString account = s.qqNumber.isEmpty()
        ? (s.qqLoggedIn ? Strings::zh("running") : "未登录")
        : (s.qqNickname.isEmpty() ? "QQ 账号" : s.qqNickname);
    m_qq->setValue(account, s.qqLoggedIn, s.qqNumber.isEmpty() ? QString() : "QQ " + s.qqNumber);
    // 采集健康度：队列积压 / 撤回记录 / 最近视图同步（随 30s 状态心跳更新）
    m_statQueue->setText(QString::number(s.imageQueue));
    m_statQueue->setToolTip(s.imageQueue > 0 ? QStringLiteral("等待处理：%1 张图片").arg(s.imageQueue)
                                           : QStringLiteral("当前没有等待处理的图片"));
    m_statRecall->setText(QString::number(s.recallCount));
    setActivity(m_statViewSync, s.lastViewSync, "尚未同步");
    setActivity(m_statBackup, s.lastBackup, "暂无备份", !s.lastBackup.isEmpty() && !s.backupOk);
    updateResponsiveLayout();
    if (!s.qqNumber.isEmpty() && s.qqNumber != m_avatarQQ) {
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
