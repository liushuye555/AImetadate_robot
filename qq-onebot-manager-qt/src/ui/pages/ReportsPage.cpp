#include "ReportsPage.h"
#include "../Strings.h"
#include <QJsonObject>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QPlainTextEdit>
#include <QListWidget>
#include <QListWidgetItem>
#include <QGroupBox>

ReportsPage::ReportsPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 24, 24, 24);

    auto *entries = new QHBoxLayout;
    const QStringList pages = {"data/view/index.html", "data/view/files.html", "data/view/resources.html"};
    for (const QString &page : pages) {
        auto *button = new QPushButton(page.mid(page.lastIndexOf('/') + 1), this);
        connect(button, &QPushButton::clicked, this, [this, page] { emit openRequested(page); });
        entries->addWidget(button);
    }
    entries->addStretch();
    layout->addLayout(entries);

    auto *galleryGroup = new QGroupBox(Strings::zh("gallery"), this);
    auto *galleryLayout = new QVBoxLayout(galleryGroup);
    m_categories = new QListWidget(galleryGroup);
    galleryLayout->addWidget(m_categories);
    connect(m_categories, &QListWidget::itemActivated, this, [this](QListWidgetItem *item) {
        const QString url = item->data(Qt::UserRole).toString();
        if (!url.isEmpty()) emit openRequested("data/view/" + url);
    });
    auto *galleryButtons = new QHBoxLayout;
    auto *openGallery = new QPushButton(Strings::zh("openGallery"), galleryGroup);
    auto *rebuild = new QPushButton(Strings::zh("rebuildView"), galleryGroup);
    galleryButtons->addWidget(openGallery);
    galleryButtons->addWidget(rebuild);
    galleryButtons->addStretch();
    galleryLayout->addLayout(galleryButtons);
    layout->addWidget(galleryGroup);
    connect(openGallery, &QPushButton::clicked, this, [this] { emit openRequested("data/view/index.html"); });
    connect(rebuild, &QPushButton::clicked, this, [this] { emit viewRequested(); });

    m_nextTime = new QLabel(this);
    m_nextTime->setObjectName("muted");
    layout->addWidget(m_nextTime);

    m_preview = new QPlainTextEdit(this);
    m_preview->setReadOnly(true);
    m_preview->setMaximumBlockCount(500);
    layout->addWidget(m_preview, 1);

    auto *actions = new QHBoxLayout;
    auto *preview = new QPushButton(Strings::zh("preview"), this);
    auto *send = new QPushButton(Strings::zh("sendTest"), this);
    send->setObjectName("primary");
    actions->addWidget(preview);
    actions->addWidget(send);
    actions->addStretch();
    layout->addLayout(actions);

    connect(preview, &QPushButton::clicked, this, &ReportsPage::previewRequested);
    connect(send, &QPushButton::clicked, this, &ReportsPage::sendRequested);
}

void ReportsPage::setPreview(const QString &text) { m_preview->setPlainText(text); }
void ReportsPage::setNextTime(const QString &text) { m_nextTime->setText(text); }

void ReportsPage::setCategories(const QVariantList &categories) {
    m_categories->clear();
    for (const QVariant &category : categories) {
        const QJsonObject obj = category.toJsonObject();
        const QString name = obj.value("name").toString();
        const int count = obj.value("count").toInt();
        const QString url = obj.value("url").toString();
        auto *item = new QListWidgetItem(QString("%1  ·  %2 张").arg(name).arg(count), m_categories);
        item->setData(Qt::UserRole, url);
        m_categories->addItem(item);
    }
}
