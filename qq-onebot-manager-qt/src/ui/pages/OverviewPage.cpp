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

namespace {
// NapCat 式统计卡：大数字 + 底部小标签，居中
QFrame *makeStatCard(QLabel **valueLabel, const QString &caption, QWidget *parent) {
    auto *card = new QFrame(parent);
    card->setObjectName("card");
    card->setMinimumHeight(86);
    auto *layout = new QVBoxLayout(card);
    layout->setContentsMargins(12, 14, 12, 12);
    layout->setSpacing(2);
    layout->addStretch();
    auto *value = new QLabel("—", card);
    value->setObjectName("statValue");
    value->setAlignment(Qt::AlignCenter);
    auto *captionLabel = new QLabel(caption, card);
    captionLabel->setObjectName("statCaption");
    captionLabel->setAlignment(Qt::AlignCenter);
    layout->addWidget(value);
    layout->addWidget(captionLabel);
    layout->addStretch();
    *valueLabel = value;
    return card;
}
}  // namespace

OverviewPage::OverviewPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 20, 24, 24);
    layout->setSpacing(14);

    // 服务状态卡行
    auto *cards = new QGridLayout;
    cards->setHorizontalSpacing(12);
    cards->setVerticalSpacing(12);
    m_napcat = new StatusCard("NapCat", ":/icons/card-napcat.svg", this);
    m_onebot = new StatusCard("OneBot", ":/icons/card-onebot.svg", this);
    m_bot = new StatusCard("Bot", ":/icons/card-bot.svg", this);
    m_qq = new StatusCard("QQ", ":/icons/card-qq.svg", this);
    cards->addWidget(m_napcat, 0, 0);
    cards->addWidget(m_onebot, 0, 1);
    cards->addWidget(m_bot, 0, 2);
    cards->addWidget(m_qq, 0, 3);
    layout->addLayout(cards);

    // 数据统计卡行（大数字 + 标签）
    auto *stats = new QGridLayout;
    stats->setHorizontalSpacing(12);
    stats->addWidget(makeStatCard(&m_statImages, Strings::zh("statImages"), this), 0, 0);
    stats->addWidget(makeStatCard(&m_statLinks, Strings::zh("statLinks"), this), 0, 1);
    stats->addWidget(makeStatCard(&m_statReport, Strings::zh("statLastReport"), this), 0, 2);
    layout->addLayout(stats);

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
    serviceGrid->setColumnStretch(5, 1);
    actionsLayout->addLayout(serviceGrid);

    auto *dataTitle = new QLabel(Strings::zh("groupData"), actionsCard);
    dataTitle->setObjectName("sectionTitle");
    actionsLayout->addWidget(dataTitle);
    auto *dataGrid = new QGridLayout;
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
    dataGrid->setColumnStretch(5, 1);
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
    layout->addStretch();

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
    if (!s.valid) {
        m_hint->setText(Strings::zh("staleHint"));
        m_hint->show();
        m_napcat->setValue("未知", false);
        m_onebot->setValue("未知", false);
        m_bot->setValue("未知", false);
        m_qq->setValue("未知", false);
        return;
    }
    m_hint->hide();
    m_napcat->setValue(s.napcat ? Strings::zh("running") : Strings::zh("stopped"), s.napcat);
    m_onebot->setValue(s.onebot ? Strings::zh("running") : Strings::zh("stopped"), s.onebot);
    m_bot->setValue(s.bot ? Strings::zh("running") : Strings::zh("stopped"), s.bot);
    const QString account = s.qqNumber.isEmpty()
        ? (s.qqLoggedIn ? Strings::zh("running") : "未登录")
        : (s.qqNickname + " (" + s.qqNumber + ")");
    m_qq->setValue(account, s.qqLoggedIn);
    if (!s.qqNumber.isEmpty() && s.qqNumber != m_avatarQQ) {
        m_avatarQQ = s.qqNumber;  // 每个账号只拉一次（含磁盘缓存）
        AvatarCache::instance().fetch("user", s.qqNumber, [this](const QPixmap &pm) {
            m_qq->setIconPixmap(pm);
        });
    }
}

void OverviewPage::setStatNumbers(int images, int links, const QString &lastReport) {
    m_statImages->setText(QString::number(images));
    m_statLinks->setText(QString::number(links));
    m_statReport->setText(lastReport.isEmpty() ? QStringLiteral("—") : lastReport);
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
