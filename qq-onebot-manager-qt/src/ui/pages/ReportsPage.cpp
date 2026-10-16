#include "ReportsPage.h"
#include "../Strings.h"
#include <QJsonObject>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QPushButton>
#include <QLabel>
#include <QPlainTextEdit>
#include <QListWidget>
#include <QListWidgetItem>
#include <QGroupBox>
#include <QToolBox>
#include <QScrollArea>

ReportsPage::ReportsPage(QWidget *parent) : QWidget(parent) {
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    auto *scroll = new QScrollArea(this);
    scroll->setObjectName(QStringLiteral("reportsScroll"));
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto *content = new QWidget(scroll);
    auto *layout = new QVBoxLayout(content);
    scroll->setWidget(content);
    outer->addWidget(scroll);
    layout->setContentsMargins(24, 20, 24, 24);
    layout->setSpacing(14);

    auto *title = new QLabel(QStringLiteral("资料中心"), this);
    title->setStyleSheet(QStringLiteral("font-size: 20px; font-weight: 600;"));
    layout->addWidget(title);
    auto *description = new QLabel(QStringLiteral("浏览群知识、术语和精选资料；图片与采集文件可在下方打开。"), this);
    description->setObjectName("muted");
    description->setWordWrap(true);
    layout->addWidget(description);

    auto *primary = new QGridLayout;
    primary->setHorizontalSpacing(10);
    primary->setVerticalSpacing(10);
    const QList<QPair<QString, QString>> mainPages = {
        {QStringLiteral("群知识"), QStringLiteral("data/view/knowledge.html")},
        {QStringLiteral("待跟进"), QStringLiteral("data/view/knowledge.html#followup")},
        {QStringLiteral("术语"), QStringLiteral("data/view/glossary.html")},
        {QStringLiteral("群总结"), QStringLiteral("data/view/knowledge-summary.html")},
        {QStringLiteral("保留文件 · 精选"), QStringLiteral("data/view/knowledge-files.html")},
    };
    for (int i = 0; i < mainPages.size(); ++i) {
        const auto entry = mainPages.at(i);
        auto *button = new QPushButton(entry.first, this);
        button->setMinimumHeight(48);
        button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
        if (i == 0) button->setObjectName("primary");
        connect(button, &QPushButton::clicked, this, [this, path = entry.second] { emit openRequested(path); });
        primary->addWidget(button, i / 2, i % 2);
    }
    layout->addLayout(primary);

    auto *secondaryLabel = new QLabel(QStringLiteral("其他资料"), this);
    secondaryLabel->setObjectName("muted");
    layout->addWidget(secondaryLabel);
    auto *secondary = new QHBoxLayout;
    const QList<QPair<QString, QString>> otherPages = {
        {QStringLiteral("图片总览"), QStringLiteral("data/view/index.html")},
        {QStringLiteral("群文件 · 全部采集"), QStringLiteral("data/view/files.html")},
        {QStringLiteral("资源链接"), QStringLiteral("data/view/resources.html")},
    };
    for (const auto &entry : otherPages) {
        auto *button = new QPushButton(entry.first, this);
        connect(button, &QPushButton::clicked, this, [this, path = entry.second] { emit openRequested(path); });
        secondary->addWidget(button);
    }
    layout->addLayout(secondary);

    auto *tools = new QToolBox(this);
    tools->setObjectName(QStringLiteral("secondaryTools"));
    auto *gallery = new QWidget(tools);
    auto *galleryLayout = new QVBoxLayout(gallery);
    galleryLayout->setContentsMargins(8, 8, 8, 8);
    auto *galleryHint = new QLabel(QStringLiteral("按分类浏览图片；群文件页面包含全部采集文件，保留文件页面只展示精选资料。"), gallery);
    galleryHint->setObjectName("muted");
    galleryHint->setWordWrap(true);
    galleryLayout->addWidget(galleryHint);
    m_categories = new QListWidget(gallery);
    galleryLayout->addWidget(m_categories);
    connect(m_categories, &QListWidget::itemActivated, this, [this](QListWidgetItem *item) {
        const QString url = item->data(Qt::UserRole).toString();
        if (!url.isEmpty()) emit openRequested("data/view/" + url);
    });
    tools->addItem(gallery, QStringLiteral("图片分类"));

    auto *maintenance = new QWidget(tools);
    auto *maintenanceLayout = new QVBoxLayout(maintenance);
    auto *maintenanceActions = new QHBoxLayout;
    m_rebuild = new QPushButton(QStringLiteral("更新资料页面"), maintenance);
    m_backup = new QPushButton(QStringLiteral("立即备份"), maintenance);
    maintenanceActions->addWidget(m_rebuild);
    maintenanceActions->addWidget(m_backup);
    maintenanceActions->addStretch();
    maintenanceLayout->addLayout(maintenanceActions);
    auto *status = new QHBoxLayout;
    m_viewStatus = new QLabel(maintenance);
    m_viewStatus->setObjectName("muted");
    status->addWidget(m_viewStatus);
    m_backupStatus = new QLabel(maintenance);
    m_backupStatus->setObjectName("muted");
    status->addWidget(m_backupStatus);
    status->addStretch();
    maintenanceLayout->addLayout(status);
    connect(m_rebuild, &QPushButton::clicked, this, &ReportsPage::viewRequested);
    connect(m_backup, &QPushButton::clicked, this, &ReportsPage::backupRequested);
    tools->addItem(maintenance, QStringLiteral("更新资料与备份"));

    auto *report = new QWidget(tools);
    auto *reportLayout = new QVBoxLayout(report);
    m_nextTime = new QLabel(report);
    m_nextTime->setObjectName("muted");
    m_nextTime->setWordWrap(true);
    reportLayout->addWidget(m_nextTime);
    m_preview = new QPlainTextEdit(report);
    m_preview->setReadOnly(true);
    m_preview->setMaximumBlockCount(500);
    m_preview->setMinimumHeight(100);
    reportLayout->addWidget(m_preview, 1);
    auto *actions = new QHBoxLayout;
    auto *preview = new QPushButton(Strings::zh("preview"), report);
    auto *send = new QPushButton(Strings::zh("sendTest"), report);
    send->setObjectName("primary");
    actions->addWidget(preview);
    actions->addWidget(send);
    actions->addStretch();
    reportLayout->addLayout(actions);
    connect(preview, &QPushButton::clicked, this, &ReportsPage::previewRequested);
    connect(send, &QPushButton::clicked, this, &ReportsPage::sendRequested);
    tools->addItem(report, Strings::zh("dailyReport"));
    layout->addWidget(tools, 1);
}

void ReportsPage::setPreview(const QString &text) { m_preview->setPlainText(text); }
void ReportsPage::setNextTime(const QString &text) { m_nextTime->setText(text); }

void ReportsPage::setViewStatus(const QString &text) {
    m_viewStatus->setText(text == QStringLiteral("视图重建中…") ? QStringLiteral("正在更新资料页面…") : text);
    if (m_rebuild) m_rebuild->setEnabled(text != QStringLiteral("视图重建中…"));
}

void ReportsPage::setBackupStatus(const QString &text) {
    m_backupStatus->setText(text);
    if (m_backup) m_backup->setEnabled(text != QStringLiteral("备份中…"));
}

void ReportsPage::setCategories(const QVariantList &categories) {
    if (m_rebuild) m_rebuild->setEnabled(true);
    m_viewStatus->setText(QStringLiteral("资料页面已更新"));
    m_categories->clear();
    for (const QVariant &category : categories) {
        const QJsonObject obj = category.toJsonObject();
        const QString name = obj.value("name").toString();
        const int count = obj.value("count").toInt();
        const QString url = obj.value("url").toString();
        auto *item = new QListWidgetItem(QString("%1  ·  %2 张").arg(name).arg(count));
        item->setData(Qt::UserRole, url);
        m_categories->addItem(item);
    }
}
