#include "OverviewPage.h"
#include "../widgets/StatusCard.h"
#include "../Strings.h"
#include <QGridLayout>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QPushButton>
#include <QLabel>

OverviewPage::OverviewPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 24, 24, 24);
    layout->setSpacing(16);

    auto *cards = new QGridLayout;
    cards->setSpacing(12);
    m_napcat = new StatusCard("NapCat", this);
    m_onebot = new StatusCard("OneBot", this);
    m_bot = new StatusCard("Bot", this);
    m_qq = new StatusCard("QQ", this);
    cards->addWidget(m_napcat, 0, 0);
    cards->addWidget(m_onebot, 0, 1);
    cards->addWidget(m_bot, 1, 0);
    cards->addWidget(m_qq, 1, 1);
    layout->addLayout(cards);

    m_hint = new QLabel(this);
    m_hint->setObjectName("muted");
    m_hint->setWordWrap(true);
    layout->addWidget(m_hint);

    m_autoRestart = new QLabel(this);
    m_autoRestart->setObjectName("muted");
    layout->addWidget(m_autoRestart);

    m_stats = new QLabel(this);
    m_stats->setObjectName("muted");
    layout->addWidget(m_stats);

    auto *buttons = new QHBoxLayout;
    buttons->setSpacing(10);
    auto *start = new QPushButton(Strings::zh("start"), this);
    start->setObjectName("primary");
    auto *stop = new QPushButton(Strings::zh("stop"), this);
    stop->setObjectName("danger");
    auto *restart = new QPushButton(Strings::zh("restart"), this);
    auto *refresh = new QPushButton(Strings::zh("refresh"), this);
    auto *logs = new QPushButton(Strings::zh("openLogs"), this);
    auto *reports = new QPushButton(Strings::zh("openReports"), this);
    auto *config = new QPushButton(Strings::zh("openConfig"), this);
    auto *history = new QPushButton(Strings::zh("importHistory"), this);
    auto *napcat = new QPushButton(Strings::zh("openNapcat"), this);
    for (QPushButton *b : {start, stop, restart, refresh, logs, reports, config, history, napcat})
        buttons->addWidget(b);
    buttons->addStretch();
    layout->addLayout(buttons);
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
}

void OverviewPage::setStatus(const StatusSnapshot &s) {
    if (!s.valid) {
        m_hint->setText(Strings::zh("staleHint"));
        m_napcat->setValue("未知", false);
        m_onebot->setValue("未知", false);
        m_bot->setValue("未知", false);
        m_qq->setValue("未知", false);
        return;
    }
    m_hint->clear();
    m_napcat->setValue(s.napcat ? Strings::zh("running") : Strings::zh("stopped"), s.napcat);
    m_onebot->setValue(s.onebot ? Strings::zh("running") : Strings::zh("stopped"), s.onebot);
    m_bot->setValue(s.bot ? Strings::zh("running") : Strings::zh("stopped"), s.bot);
    const QString account = s.qqNumber.isEmpty()
        ? (s.qqLoggedIn ? Strings::zh("running") : "未登录")
        : (s.qqNickname + " (" + s.qqNumber + ")");
    m_qq->setValue(account, s.qqLoggedIn);
}

void OverviewPage::setStats(const QString &text) { m_stats->setText(text); }
void OverviewPage::setHint(const QString &text) { m_hint->setText(text); }
void OverviewPage::setAutoRestartText(const QString &text) { m_autoRestart->setText(text); }
