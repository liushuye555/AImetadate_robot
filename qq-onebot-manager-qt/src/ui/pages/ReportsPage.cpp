#include "ReportsPage.h"
#include "../Strings.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QPlainTextEdit>

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
