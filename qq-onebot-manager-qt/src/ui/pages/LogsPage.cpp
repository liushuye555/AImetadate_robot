#include "LogsPage.h"
#include "../Strings.h"
#include "core/LogReader.h"
#include "core/Paths.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QComboBox>
#include <QPlainTextEdit>
#include <QCheckBox>
#include <QLineEdit>
#include <QPushButton>
#include <QScrollBar>
#include <QTextCharFormat>
#include <QDesktopServices>
#include <QUrl>

LogsPage::LogsPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 20, 24, 24);
    layout->setSpacing(12);
    auto *top = new QHBoxLayout;
    top->setSpacing(10);
    m_selector = new QComboBox(this);
    m_selector->addItem("bot.log");
    m_selector->addItem("napcat.log");
    m_filter = new QLineEdit(this);
    m_filter->setPlaceholderText(Strings::zh("search"));
    m_autoScroll = new QCheckBox(Strings::zh("autoScroll"), this);
    m_autoScroll->setChecked(true);
    m_onlyErrors = new QCheckBox(Strings::zh("onlyErrors"), this);
    auto *openDir = new QPushButton(Strings::zh("openLogs"), this);
    top->addWidget(m_selector);
    top->addWidget(m_filter, 1);
    top->addWidget(m_autoScroll);
    top->addWidget(m_onlyErrors);
    top->addWidget(openDir);
    layout->addLayout(top);

    m_view = new QPlainTextEdit(this);
    m_view->setReadOnly(true);
    m_view->setMaximumBlockCount(2000);
    layout->addWidget(m_view, 1);

    m_reader = new LogReader({Paths::repoRoot() + "/logs/bot.log",
                              Paths::repoRoot() + "/logs/napcat.log"}, this);
    connect(m_selector, &QComboBox::currentIndexChanged, m_reader, &LogReader::setActive);
    connect(m_reader, &LogReader::newChunk, this, &LogsPage::appendChunk);
    connect(openDir, &QPushButton::clicked, this, [] {
        QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
    });
    m_reader->setActive(0);
}

void LogsPage::appendChunk(const QString &text) {
    const bool hasError = text.contains("WARN") || text.contains("ERROR") || text.contains("失败");
    if (m_onlyErrors->isChecked() && !hasError) return;
    if (!m_filter->text().isEmpty() && !text.contains(m_filter->text())) return;
    if (hasError) {
        QTextCharFormat errorFormat;
        errorFormat.setForeground(QColor("#d64550"));
        m_view->setCurrentCharFormat(errorFormat);
    }
    m_view->appendPlainText(text.trimmed());
    if (m_autoScroll->isChecked())
        m_view->verticalScrollBar()->setValue(m_view->verticalScrollBar()->maximum());
}
